"""Tests for C3 / SC-5 — Branded-Demand Competitive Benchmark (src/brand_demand.py).

Covers SC-5.1 (own GSC-anchored figure distinct from volume-estimated competitors),
SC-5.2 (branded query expansion inspectable/editable via config), SC-5.3 (growth over
equal-length periods), SC-5.4 (generic brand names pruned), plus share math and DB.
"""
import pytest

from src.database import DatabaseManager
from src.brand_demand import (
    expand_branded_queries, compute_growth, compute_branded_demand,
)

CONFIG = {"branded_modifiers": ["reviews", "pricing"],
          "generic_brand_prune": ["therapy"], "growth_window_months": 2}


def _provider(vol=100, monthly=None):
    monthly = monthly if monthly is not None else []
    def provider(queries):
        return {q.lower(): {"search_volume": vol, "monthly_searches": monthly} for q in queries}
    return provider


# ── SC-5.2 branded query expansion inspectable / editable ─────────────────────

def test_sc52_expand_uses_config_modifiers():
    assert expand_branded_queries("Theravive", ["reviews", "pricing"]) == \
        ["Theravive", "Theravive reviews", "Theravive pricing"]


def test_sc52_expansion_flows_through_provider():
    seen = []
    def provider(queries):
        seen.extend(queries)
        return {q.lower(): {"search_volume": 10} for q in queries}
    compute_branded_demand({"a.com": "Acme"}, provider, CONFIG, period="2026-07")
    assert "Acme reviews" in seen and "Acme pricing" in seen   # config modifiers applied


# ── SC-5.3 growth over equal-length periods ───────────────────────────────────

def test_sc53_growth_equal_windows():
    # window=2: recent [30,40]=70 vs prior [10,20]=30 → 40/30
    assert compute_growth([10, 20, 30, 40], window=2) == round(40 / 30, 3)
    assert compute_growth([10, 20], window=2) is None          # not enough history
    assert compute_growth([0, 0, 30, 40], window=2) is None    # prior window zero → no divide


# ── SC-5.1 own (GSC-anchored) vs estimated competitor figures ─────────────────

def test_sc51_own_vs_estimated_labeling():
    rows = compute_branded_demand(
        {"a.com": "Acme", "livingsystems.ca": "Living Systems"}, _provider(100),
        CONFIG, period="2026-07", own_domain="livingsystems.ca", own_anchor=0.4)
    by_domain = {r["domain"]: r for r in rows}
    assert by_domain["livingsystems.ca"]["estimation_basis"] == "gsc_anchored"
    assert by_domain["livingsystems.ca"]["est_branded_click_share"] == 0.4
    assert by_domain["a.com"]["estimation_basis"] == "volume_estimated"
    assert by_domain["a.com"]["est_branded_click_share"] is None


# ── SC-5.4 generic brand names → pruning ──────────────────────────────────────

def test_sc54_generic_brand_pruned():
    rows = compute_branded_demand({"t.com": "therapy"}, _provider(100), CONFIG, period="2026-07")
    assert rows[0]["estimation_basis"] == "pruned_generic_brand"
    assert rows[0]["branded_search_volume"] is None            # never guessed


# ── share math + DB ───────────────────────────────────────────────────────────

def test_shares_sum_to_100():
    rows = compute_branded_demand({"a.com": "Acme", "b.com": "Bcorp"}, _provider(100),
                                  CONFIG, period="p")
    assert abs(sum(r["branded_volume_share"] for r in rows) - 100.0) < 0.5


def test_volume_unavailable_when_all_zero():
    """Sweep F2: all-zero volume (a DataForSEO outage) is labelled 'volume_unavailable',
    not rendered as genuine zero demand."""
    def zero_provider(queries):
        return {q.lower(): {"search_volume": 0} for q in queries}
    rows = compute_branded_demand({"a.com": "Acme"}, zero_provider, CONFIG, period="p")
    assert rows[0]["estimation_basis"] == "volume_unavailable"


def test_save_brand_demand_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "bd.db"))
    run_id = db.create_run("c.com")
    rows = compute_branded_demand({"a.com": "Acme"}, _provider(100), CONFIG, period="2026-07")
    db.save_brand_demand(run_id, rows)
    with db._get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM brand_demand_bench WHERE run_id=?",
                         (run_id,)).fetchone()[0]
    assert n == 1


# ── C-M-03: display brand, not the bare stem; and the ambiguous-brand gate ────
# Promotes docs/review_2026-11-04/probes/compete/probe_brand_demand.py and
# probes/compete_method/p04_overlap_positioning_brand.py §C: the query set sent for
# Google Ads volume was ['lavender', 'lavender reviews', ...] — demand for a plant —
# and every `www.` domain sent the identical set ['www', 'www reviews', ...].

def _recording_provider(volumes):
    """volumes: {query_lower: search_volume}; unknown queries return 0."""
    seen = []

    def provider(queries):
        seen.append(list(queries))
        return {q.lower(): {"search_volume": volumes.get(q.lower(), 0),
                            "monthly_searches": []} for q in queries}
    provider.seen = seen
    return provider


def test_cm03_query_set_is_the_display_brand():
    provider = _recording_provider({"lavender counselling": 50})
    compute_branded_demand({"lavendercounselling.com": "Lavender Counselling"}, provider,
                           CONFIG, period="p")
    assert provider.seen[0] == ["Lavender Counselling", "Lavender Counselling reviews",
                                "Lavender Counselling pricing"]


def test_cm03_two_www_domains_never_share_a_query_set():
    """The C-C-01 consequence, asserted at the branded-demand layer: both domains used
    to send ['www', 'www reviews', 'www pricing'] and persist identical volume rows."""
    from src.brand_utils import derive_display_brand
    provider = _recording_provider({})
    brands = {d: derive_display_brand(d) for d in
              ("www.jerichocounselling.com", "www.averytherapy.com")}
    compute_branded_demand(brands, provider, CONFIG, period="p")
    assert provider.seen[0] != provider.seen[1]
    assert not any("www" in q.lower() for call in provider.seen for q in call)


def test_cm03_ambiguous_brand_withholds_share_and_growth():
    """'lavender' alone pulls 10x the practice name → the demand is not the practice's."""
    provider = _recording_provider({"lavender counselling": 50, "lavender": 40000,
                                    "jericho counselling": 100})
    rows = compute_branded_demand(
        {"lavendercounselling.com": "Lavender Counselling",
         "jerichocounselling.com": "Jericho Counselling"},
        provider, dict(CONFIG, ambiguous_brand_ratio=10), period="p",
        ambiguity_token_by_domain={"lavendercounselling.com": "lavender",
                                   "jerichocounselling.com": "jericho"})
    by_domain = {r["domain"]: r for r in rows}
    amb = by_domain["lavendercounselling.com"]
    assert amb["estimation_basis"] == "ambiguous_brand"
    assert amb["branded_volume_share"] is None and amb["branded_growth"] is None
    assert amb["branded_search_volume"] == 50          # the measured display-brand volume
    # The unambiguous rival keeps a real share, computed without the withheld row.
    assert by_domain["jerichocounselling.com"]["estimation_basis"] == "volume_estimated"
    assert by_domain["jerichocounselling.com"]["branded_volume_share"] == 100.0


def test_cm03_specific_brand_is_not_flagged_ambiguous():
    provider = _recording_provider({"jericho counselling": 500, "jericho": 900})
    rows = compute_branded_demand({"jerichocounselling.com": "Jericho Counselling"},
                                  provider, dict(CONFIG, ambiguous_brand_ratio=10),
                                  period="p",
                                  ambiguity_token_by_domain={"jerichocounselling.com": "jericho"})
    assert rows[0]["estimation_basis"] == "volume_estimated"
    assert rows[0]["branded_volume_share"] == 100.0


def test_cm03_ambiguity_probe_volume_never_enters_the_branded_total():
    provider = _recording_provider({"hollyburn": 9999})
    rows = compute_branded_demand({"hollyburn.ca": "Hollyburn"}, provider,
                                  dict(CONFIG, ambiguous_brand_ratio=0), period="p",
                                  ambiguity_token_by_domain={"hollyburn.ca": "hollyburn"})
    # ratio 0 disables the gate; the stem's 9999 must not be counted as branded demand
    # (the display brand "Hollyburn" is the same word, so no probe call is made at all).
    assert rows[0]["branded_search_volume"] == 9999   # queried as the display brand itself
    assert provider.seen == [["Hollyburn", "Hollyburn reviews", "Hollyburn pricing"]]


def test_cm03_query_strings_are_persisted_for_the_excel_sheet(tmp_path):
    db = DatabaseManager(str(tmp_path / "bdq.db"))
    run_id = db.create_run("c.com")
    rows = compute_branded_demand({"a.com": "Acme Counselling"}, _provider(100), CONFIG,
                                  period="2026-07")
    db.save_brand_demand(run_id, rows)
    with db._get_connection() as conn:
        queries = conn.execute("SELECT queries FROM brand_demand_bench WHERE run_id=?",
                               (run_id,)).fetchone()[0]
    assert "Acme Counselling reviews" in queries
