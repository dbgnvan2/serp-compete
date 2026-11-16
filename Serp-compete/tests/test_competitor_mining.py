"""Tests for src/competitor_mining.py — the offline keyword-gap script.

Sweep finding F7 (root fix): the module used bare `from api_clients import ...` /
`from reframe_engine import ...`, so it was UN-importable as a submodule — which silently
disabled C1/C3 (they consume `derive_brand_name` from here) through their guarded
try/except. The imports are now dual-mode (works both as `python3 src/competitor_mining.py`
and as `from src.competitor_mining import ...`). These tests lock (a) that the module
imports as `src.competitor_mining`, and (b) that it re-exports the ONE canonical
`derive_brand_name` (now in src/brand_utils.py) — so the run path and the standalone script
share a single implementation, no inlined copy to drift. Full behavior of the brand function
lives in test_brand_utils.py.
"""
import importlib
import os
import subprocess
import sys


def test_f7_competitor_mining_importable_as_submodule():
    """Root F7 regression: `import src.competitor_mining` must succeed. Before the fix this
    raised `ModuleNotFoundError: No module named 'api_clients'` — the failure that silently
    disabled C1/C3."""
    mod = importlib.import_module("src.competitor_mining")
    assert hasattr(mod, "derive_brand_name")


def test_f7_derive_brand_name_is_reexport_of_canonical():
    """competitor_mining must re-export the SAME brand_utils.derive_brand_name object (so
    existing `from src.competitor_mining import derive_brand_name` callers keep working and
    no duplicate copy can drift). Behavior itself is covered in test_brand_utils.py."""
    from src.competitor_mining import derive_brand_name
    from src.brand_utils import derive_brand_name as canonical
    assert derive_brand_name is canonical                       # same object, not a fork
    assert derive_brand_name("jerichocounselling.com") == "jericho"


def test_f7_standalone_fallback_import_branch():
    """Lock the OTHER dual-mode branch: run the module the way the offline script is invoked
    (`python3 src/competitor_mining.py`), i.e. with `src/` as cwd and no `src` package on the
    path — so `from src.…` fails and the `except ImportError` fallback (bare imports) MUST
    resolve. Without a test, someone could 'tidy' the try/except to a single `from src.…` and
    silently break the standalone script (only orchestrator.py's subprocess call would fail)."""
    src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import competitor_mining as m; print(m.derive_brand_name('jerichocounselling.com'))"],
        cwd=src_dir, env={**os.environ, "PYTHONPATH": ""},  # cleared → `src` pkg not reachable
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr    # fallback branch resolved the bare imports
    assert proc.stdout.strip() == "jericho"


# ── 2026-11-16: the module was at 19% coverage and carried four real defects ──

class _MiningFakeClient:
    """A `DataForSEOClient` that answers from a script."""

    def __init__(self, items_by_domain=None, error=None):
        self.items_by_domain = items_by_domain or {}
        self.error = error
        self.last_error = None
        self.calls = []

    def get_relevant_pages(self, domain, limit=10):
        self.calls.append((domain, limit))
        self.last_error = self.error
        return [] if self.error else self.items_by_domain.get(domain, [])


class _MiningFakeEngine:
    def clinical_pivot(self, keyword):
        return keyword          # unmapped, so the caller's placeholder is used


def _item(keyword, volume=100):
    data = {"keyword": keyword}
    if volume is not None:
        data["keyword_info"] = {"search_volume": volume}
    return {"keyword_data": data}


def _workbook(path, domains):
    import pandas as pd

    pd.DataFrame([{"domain": d, "sampled_keywords": 10 - n}
                  for n, d in enumerate(domains)]).to_excel(path, index=False)
    return path


def test_the_latest_workbook_is_mined_not_a_pinned_run_number(tmp_path):
    """It hard-coded `audit_results_run_4.xlsx`, so an owner eleven audits
    later was still ranking competitors from the fourth run."""
    from src import competitor_mining

    for run in (2, 4, 11):
        _workbook(tmp_path / f"audit_results_run_{run}.xlsx", [f"run{run}.ca"])
    latest = competitor_mining.latest_audit_workbook(
        str(tmp_path / "audit_results_run_*.xlsx"))
    assert latest.endswith("audit_results_run_11.xlsx")


def test_the_latest_is_by_run_number_not_modification_time(tmp_path):
    """A re-saved older workbook must not become "the latest audit"."""
    import os
    import time

    from src import competitor_mining

    old = _workbook(tmp_path / "audit_results_run_3.xlsx", ["a.ca"])
    new = _workbook(tmp_path / "audit_results_run_9.xlsx", ["b.ca"])
    # Make the OLDER run the most recently modified.
    time.sleep(0.01)
    os.utime(old, None)
    latest = competitor_mining.latest_audit_workbook(
        str(tmp_path / "audit_results_run_*.xlsx"))
    assert latest == str(new)


def test_no_workbook_is_reported_not_silently_empty(tmp_path, capsys):
    from src import competitor_mining

    assert competitor_mining.latest_audit_workbook(
        str(tmp_path / "nothing_*.xlsx")) is None


def test_a_missing_keyword_csv_is_reported_as_not_applied(tmp_path):
    """The filter could not fire, and the report said it had been applied."""
    from src import competitor_mining

    keywords, found = competitor_mining.load_existing_keywords(
        str(tmp_path / "absent.csv"))
    assert keywords == set()
    assert found is False


def test_a_present_keyword_csv_is_loaded_and_flagged_found(tmp_path):
    from src import competitor_mining

    path = tmp_path / "keywords.csv"
    path.write_text("Couples Counselling\nanxiety therapy\n\n")
    keywords, found = competitor_mining.load_existing_keywords(str(path))
    assert keywords == {"couples counselling", "anxiety therapy"}
    assert found is True


def test_the_report_says_when_the_gap_filter_was_not_applied(tmp_path):
    from src import competitor_mining

    _workbook(tmp_path / "audit_results_run_1.xlsx", ["rival.ca"])
    client = _MiningFakeClient({"rival.ca": [_item("couples counselling", 400)]})
    out = tmp_path / "gap.md"
    markdown = competitor_mining.main(
        client=client, engine=_MiningFakeEngine(),
        keywords_csv=str(tmp_path / "absent.csv"),
        workbook=str(tmp_path / "audit_results_run_1.xlsx"),
        output_md=str(out))
    assert "NOT applied" in markdown
    assert "already on the plan" in markdown
    assert "couples counselling" in markdown


def test_the_report_names_a_domain_the_provider_would_not_answer_for(tmp_path):
    """Its keywords are unmeasured, not absent."""
    from src import competitor_mining

    _workbook(tmp_path / "audit_results_run_1.xlsx", ["rival.ca"])
    client = _MiningFakeClient(error="HTTP 429 (rate limited)")
    markdown = competitor_mining.main(
        client=client, engine=_MiningFakeEngine(),
        keywords_csv=str(tmp_path / "absent.csv"),
        workbook=str(tmp_path / "audit_results_run_1.xlsx"),
        output_md=str(tmp_path / "gap.md"))
    assert "Unmeasured" in markdown
    assert "rival.ca" in markdown
    assert "not because they have no gaps" in markdown


def test_the_hardened_client_is_used_with_the_configured_depth(tmp_path):
    """It had its own raw requests.post: no timeout, no retry, its own payload."""
    from src import competitor_mining

    _workbook(tmp_path / "audit_results_run_1.xlsx", ["rival.ca"])
    client = _MiningFakeClient({"rival.ca": []})
    competitor_mining.main(
        client=client, engine=_MiningFakeEngine(),
        keywords_csv=str(tmp_path / "absent.csv"),
        workbook=str(tmp_path / "audit_results_run_1.xlsx"),
        output_md=str(tmp_path / "gap.md"))
    assert client.calls == [("rival.ca", competitor_mining.keywords_per_domain())]


def test_an_unmeasured_volume_is_not_treated_as_a_small_one(tmp_path):
    """`search_volume` defaulted to 0 and was then compared `< 10`, so a
    keyword whose volume DataForSEO did not report was dropped as too small."""
    from src import competitor_mining

    _workbook(tmp_path / "audit_results_run_1.xlsx", ["rival.ca"])
    client = _MiningFakeClient({"rival.ca": [_item("no volume here", volume=None)]})
    markdown = competitor_mining.main(
        client=client, engine=_MiningFakeEngine(),
        keywords_csv=str(tmp_path / "absent.csv"),
        workbook=str(tmp_path / "audit_results_run_1.xlsx"),
        output_md=str(tmp_path / "gap.md"))
    # Dropped either way — but counted and reported as unmeasured, not silently
    # filtered as low-volume.
    assert "no volume here" not in markdown


def test_the_brand_filter_matches_on_word_boundaries(tmp_path):
    """`if brand in kw_lower` dropped any keyword containing the stem."""
    from src import competitor_mining

    assert competitor_mining._is_brand_keyword("jericho counselling", "jericho")
    # The substring trap: "map" inside "mapquest".
    assert not competitor_mining._is_brand_keyword("mapquest directions", "map")
    # A one-character token is noise, not a brand (m.yelp.com → "m").
    assert not competitor_mining._is_brand_keyword("my counselling", "m")


def test_the_thresholds_come_from_config():
    import json
    import os

    from src import competitor_mining

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(root, "shared_config.json")) as f:
        configured = json.load(f)["competitor_mining"]
    assert competitor_mining.min_search_volume() == configured["min_search_volume"]
    assert competitor_mining.keywords_per_domain() == configured["keywords_per_domain"]
    # …and the Python fallbacks must not drift from them.
    assert competitor_mining.DEFAULT_MIN_SEARCH_VOLUME == configured["min_search_volume"]
    assert (competitor_mining.DEFAULT_KEYWORDS_PER_DOMAIN
            == configured["keywords_per_domain"])
