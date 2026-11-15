"""Standing guard: every threshold in shared_config.json carries its provenance.

Owner decision 7 (2026-11-15) accepted "editorial, uncalibrated, <date>" labels
instead of scheduling a calibration, and asked for a guard test: "a guard test that
walks the config for threshold keys and fails when one has no provenance sibling is
the only thing that will keep this from rotting."

A threshold key is a numeric key whose name looks like a knob (`*_min`, `*_max`,
`*_threshold`, `*_pct`, …) or one listed in THRESHOLD_KEYS below. Its provenance is a
sibling `_<key>_source` / `_<key>_comment`, or a block-level `_source` / `_comment`
that covers the whole group (weights, for instance, are documented once).

This test is about documentation, not about the values: it never asserts a number.
"""
import json
import os
import re

import pytest

CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))

# Numeric keys that are thresholds despite not matching the name patterns.
THRESHOLD_KEYS = {
    "cliff_drop_pct", "cliff_lookback", "pa_drop_min", "cliff_min_sample",
    "vacuum_min_medical", "magnet_max_position", "scoring_window_words",
    "ambiguous_brand_ratio", "growth_window_months", "markdown_row_cap",
    "magnet_markdown_row_cap", "systems_depth_min_t2", "feasibility_threshold",
    "high_authority_max_pa", "volatility_min_shift", "volatility_high_shift",
    "min_focus_tokens", "min_signal_rankings", "top10_saturation",
    "hub_in_degree_threshold", "min_pages_for_signal", "commodity_high_overlap",
    "top_n", "strong_tier_min_signals", "moderate_tier_min_signals",
    "tier_1_max", "tier_1_max_density_per_1000", "tier_1_min_hits",
    "tier_2_penalty_multiplier", "max_audit_pages_per_domain",
}
NAME_PATTERNS = (r"_min$", r"_max$", r"_threshold$", r"_pct$", r"_ratio$",
                 r"_min_[a-z0-9_]+$", r"_max_[a-z0-9_]+$")

# Keys that are plumbing, not judgement calls: a path, a credential, an id, a window
# the API itself defines. These need no editorial provenance.
EXEMPT_KEYS = {
    "da",                       # the client's own DA — decision 6 owns it
    "date_range_days", "ctr_threshold", "position_target_max",  # documented in gsc_settings._comment
    "daily_quota_budget", "max_candidates_per_competitor", "active_recency_days",
    "min_subscribers_notable",  # youtube_presence block, documented as a group
    "anchor_spam_min_domains", "anchor_spam_high_share", "anchor_spam_min_anchor_reach",
}


def _load():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _is_threshold(key: str, value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if key in EXEMPT_KEYS:
        return False
    if key in THRESHOLD_KEYS:
        return True
    return any(re.search(pattern, key) for pattern in NAME_PATTERNS)


def _walk(node, path=""):
    """Yield (dotted path, key, value, siblings) for every numeric leaf."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                yield from _walk(value, child)
            else:
                yield child, key, value, node


def _has_provenance(key: str, siblings: dict) -> bool:
    for marker in (f"_{key}_source", f"_{key}_comment", f"_{key}_basis"):
        if siblings.get(marker):
            return True
    # A block-level note covers the whole group (e.g. a weights block).
    for marker in ("_source", "_comment", "_tier_comment", "_tier_source"):
        if siblings.get(marker):
            return True
    return False


def test_every_threshold_has_a_provenance_note():
    """Decision 7: a threshold added without provenance is a defect, not a style lapse."""
    missing = [
        path for path, key, value, siblings in _walk(_load())
        if _is_threshold(key, value) and not _has_provenance(key, siblings)
    ]
    assert not missing, (
        "These thresholds have no `_<key>_source` / `_<key>_comment` sibling and no "
        "block-level note (owner decision 7, 2026-11-15): " + ", ".join(sorted(missing)))


def test_the_guard_can_actually_fail():
    """A guard that cannot fail is worse than none (the repo's own rule)."""
    assert _is_threshold("some_new_min", 5) is True
    assert _has_provenance("some_new_min", {"some_new_min": 5}) is False
    assert _has_provenance("some_new_min",
                           {"_some_new_min_source": "editorial, 2026-11-15"}) is True


def test_the_recalibrated_thresholds_say_they_are_uncalibrated():
    """Decision 7 accepts the label; it requires the label to be there."""
    technical = _load()["technical"]
    for key in ("vacuum_min_medical", "magnet_max_position", "scoring_window_words"):
        note = technical.get(f"_{key}_source", "")
        assert "editorial" in note and "uncalibrated" in note, (key, note)
        assert re.search(r"20\d\d-\d\d-\d\d", note), f"{key} has no date: {note}"


def test_the_removed_dead_keys_are_actually_gone():
    """C-C-14: a documented key with no reader implies the owner can tune something."""
    config = _load()
    technical = config["technical"]
    assert "score_normaliser" not in technical
    assert "moderate_feasibility_max_gap" not in technical
    assert "pseudo_systems_threshold" not in technical["penalty_thresholds"]
    assert "step_dag" not in config
    assert "minimum_version" not in config["handoff"]
    assert "legacy_fallback_enabled" not in config["handoff"]
    for key in ("step_timeout_seconds", "log_level"):
        assert key not in config.get("orchestrator", {})
    # …and the removal is recorded rather than silent.
    assert "C-C-14" in config.get("_removed_2026_11_15", "")


@pytest.mark.parametrize("dotted,module_name,attribute", [
    ("technical.feasibility_threshold", "analysis", "AnalysisEngine.check_feasibility"),
    ("technical.high_authority_max_pa", "main", "run_audit"),
    ("risk_signals.volatility_min_shift", "database",
     "DatabaseManager.get_volatility_alerts"),
    ("handoff.supported_versions", "main", "_unsupported_handoff_version"),
])
def test_the_keys_that_were_dead_now_have_a_live_reader(dotted, module_name, attribute):
    """C-M-18 / C-C-14: these were documented knobs whose real value was a literal in
    Python. The key must be in the config AND its reader must still exist."""
    import importlib

    node = _load()
    for part in dotted.split("."):
        assert part in node, f"{dotted} is missing from shared_config.json"
        node = node[part]

    target = importlib.import_module(f"src.{module_name}")
    for part in attribute.split("."):
        assert hasattr(target, part), f"{module_name}.{attribute} no longer exists"
        target = getattr(target, part)


def test_feasibility_threshold_is_read_from_config():
    from src.analysis import AnalysisEngine, feasibility_threshold

    configured = feasibility_threshold()
    assert configured == _load()["technical"]["feasibility_threshold"]
    engine = AnalysisEngine("livingsystems.ca")
    # client 35 + threshold vs competitor: the boundary moves with the config value.
    assert engine.check_feasibility(35, int(35 + configured))["feasible"] is True
    assert engine.check_feasibility(35, int(35 + configured) + 1)["feasible"] is False
