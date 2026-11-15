"""End-to-end `run_audit` coverage reporting (C-C-03, C-C-12, C-C-06).

The chunk's failure modes are all about what the ARTEFACT says when something did not
work: a competitor dropped by a DataForSEO 429 left no trace in the briefing (the
"Missing Data Alert" compared the set of domains that produced pages with itself, so it
could never fire for one), a Moz outage was rendered as an authority of 0, and an
errored scrape silently shrank the visibility series. Every external call is faked.

Promotes probes/compete/probe_dfs_abort.py and probe_pa_zero_fragile.py to behaviour.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.database import DatabaseManager
from src.reporting import ReportGenerator
from src.velocity_module import VelocityTracker

ENRICHED = "enriched.ca"          # DataForSEO answers, Moz answers
NO_ENRICHMENT = "noenrich.ca"     # DataForSEO 429s for this one
NO_MOZ = "nomoz.ca"               # Moz has no record for its URLs
OMITTED = "psychologytoday.com"   # on the omit list

CONFIG = {
    "client": {"domain": "livingsystems.ca", "da": 35, "name": "Living Systems Counselling"},
    "technical": {"database_path": "coverage.db", "max_audit_pages_per_domain": 3,
                  "vacuum_min_medical": 10, "magnet_max_position": 10},
    "clinical": {"tier_1_medical": ["therapy", "counselling"],
                 "tier_2_systems": ["differentiation"], "tier_3_bowen": []},
    "brand": {"name_suffixes": ["counselling", "therapy"]},
    "branded_demand": {"branded_modifiers": [], "generic_brand_prune": [],
                       "growth_window_months": 3},
    "serp_overlap": {"top_n": 10, "commodity_high_overlap": 3},
    "positioning": {"authority_threshold": 50, "focus_threshold": 50,
                    "authority_weights": {"moz_da": 0.7, "top10": 0.3},
                    "top10_saturation": 10, "min_signal_rankings": 2},
    "risk_signals": {"cliff_drop_pct": 0.3, "cliff_min_sample": 10, "pa_drop_min": 3},
    "sov": {}, "youtube_presence": {}, "filtering": {},
}


def _target(domain, path="/couples", keyword="couples counselling north vancouver",
            rank=4):
    return {"url": f"https://{domain}{path}", "domain": domain, "rank": rank,
            "entity_type": "practice", "content_type": "service",
            "title": "Couples Counselling", "source_keyword": keyword,
            "primary_keyword_for_url": keyword}


def _handoff():
    return {
        "schema_version": "1.1", "source_run_id": "run_x",
        "source_run_timestamp": "2026-11-14T12:00:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems Counselling"],
        "targets": [_target(ENRICHED), _target(NO_ENRICHMENT), _target(NO_MOZ),
                    _target(OMITTED)],
        "exclusions": {"client_urls_excluded": 0, "omit_list_excluded": 0,
                       "omit_list_used": []},
    }


class _FakeAuditor:
    """Every page reads fine except the one that is meant to error."""

    def __init__(self, error_urls=()):
        self.error_urls = set(error_urls)

    def scrape_content(self, url):
        status = "error" if url in self.error_urls else "complete"
        return SimpleNamespace(url=url, extraction_status=status, outline=[],
                               first_500_words="counselling copy", metadata={})

    def analyze_text(self, content):
        return {"medical_score": 20, "systems_score": 0.0,
                "systemic_label": "Standard", "t2_count": 0, "t3_count": 0}


class _FakeDfs:
    """DataForSEO: a 429 for NO_ENRICHMENT (empty list + last_error), else nothing
    extra — the handoff target is the universe either way."""

    def __init__(self):
        self.last_error = None

    def get_relevant_pages(self, domain):
        if domain == NO_ENRICHMENT:
            self.last_error = "HTTP 429"
            return []
        self.last_error = None
        return []

    def get_search_volume(self, keywords):
        return {str(k).lower(): {"search_volume": 10, "monthly_searches": []}
                for k in keywords}


class _FakeMoz:
    def get_url_metrics(self, urls):
        if any(NO_MOZ in u for u in urls):
            return []            # Moz has no record for this domain's URLs
        return [{"page_authority": 30, "page": u.removeprefix("https://")}
                for u in urls]


class _FakeGsc:
    def analyze_gaps(self):
        return pd.DataFrame(), pd.DataFrame(), []

    def get_query_position_map(self):
        return {}


class _FakeReframe:
    def generate_bowen_reframe(self, keyword, url, medical_score, paa_questions=None):
        return {"reframe": "Draft.", "usage": {}}


@pytest.fixture
def audited(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "shared_config.json"
    config_path.write_text(json.dumps(CONFIG))
    omit_path = tmp_path / "omitted_domains.txt"
    omit_path.write_text(f"{OMITTED}\n")
    config = dict(CONFIG)
    config["filtering"] = {"omitted_domains_path": str(omit_path)}
    db_path = str(tmp_path / "coverage.db")
    handoff_path = tmp_path / "competitor_handoff_cov_20261115_1200.json"
    handoff_path.write_text(json.dumps(_handoff()))

    import src.main as main

    captured = {}

    class _Reporter(ReportGenerator):
        def __init__(self, *a, **kw):
            super().__init__(db_path)

        def generate_summary(self, *a, **kw):
            captured["markdown"] = super().generate_summary(*a, **kw)
            return captured["markdown"]

    auditor = _FakeAuditor(error_urls={f"https://{NO_MOZ}/couples"})
    with patch.object(main, "pre_flight_check", return_value=_FakeGsc()), \
         patch.object(main, "load_shared_config", return_value=config), \
         patch.object(main, "PROJECT_ROOT", str(tmp_path)), \
         patch.object(main, "find_latest_handoff_file", return_value=str(handoff_path)), \
         patch.object(main, "DatabaseManager", lambda *a, **kw: DatabaseManager(db_path)), \
         patch.object(main, "VelocityTracker",
                      lambda *a, **kw: VelocityTracker(str(config_path))), \
         patch.object(main, "DataForSEOClient", lambda *a, **kw: _FakeDfs()), \
         patch.object(main, "MozClient", lambda *a, **kw: _FakeMoz()), \
         patch.object(main, "SemanticAuditor", lambda *a, **kw: auditor), \
         patch.object(main, "ReframeEngine", lambda *a, **kw: _FakeReframe()), \
         patch.object(main, "GeoProfiler", MagicMock()), \
         patch.object(main, "EEATScorer", MagicMock()), \
         patch.object(main, "ClusterDetector", MagicMock()), \
         patch.object(main, "ReportGenerator", _Reporter):
        main.run_audit()

    return DatabaseManager(db_path), captured.get("markdown", ""), str(tmp_path)


def _rows(db, sql, params=()):
    with db._get_connection() as conn:
        return conn.execute(sql, params).fetchall()


# ── C-C-12: a domain that drops out leaves a trace in the ARTEFACT ───────────

def test_the_briefing_states_run_coverage(audited):
    _db, markdown, _tmp = audited
    assert "**Run coverage:** audited 3 of 4 handoff domain(s)" in markdown


def test_an_omitted_domain_is_named_with_its_reason(audited):
    _db, markdown, _tmp = audited
    assert "**Skipped domains:**" in markdown
    assert f"{OMITTED} — on the omit list" in markdown


def test_a_domain_whose_enrichment_failed_is_named(audited):
    """A DataForSEO 429 used to drop the competitor entirely, with the console line as
    its only trace. It is now audited on its handoff target and the failure is stated."""
    db, markdown, _tmp = audited
    assert "Keyword enrichment was unavailable" in markdown
    assert f"{NO_ENRICHMENT} (HTTP 429)" in markdown
    audited_domains = {r[0] for r in _rows(
        db, "SELECT DISTINCT domain FROM competitor_metrics WHERE run_id=?",
        (db.get_latest_run_id(),))}
    assert NO_ENRICHMENT in audited_domains


# ── C-C-03: unknown Page Authority is NULL, and says so ──────────────────────

def test_an_unmeasured_page_authority_is_null_not_zero(audited):
    db, markdown, _tmp = audited
    run_id = db.get_latest_run_id()
    rows = _rows(db, "SELECT url, pa FROM competitor_history WHERE run_id=? "
                     "AND url LIKE ?", (run_id, f"https://{NO_MOZ}%"))
    assert rows and all(pa is None for _url, pa in rows)
    assert "**Page Authority was unmeasured**" in markdown
    assert NO_MOZ in markdown


def test_no_competitors_row_is_written_without_a_measured_authority(audited):
    """`avg_pa = 0` used to be stored as this domain's Domain Authority, which then
    fed positioning and feasibility as a measured figure."""
    db, _markdown, _tmp = audited
    stored = {r[0] for r in _rows(db, "SELECT domain FROM competitors")}
    assert NO_MOZ not in stored
    assert ENRICHED in stored


def test_pa_coverage_is_reported_as_n_of_m(audited):
    db, markdown, _tmp = audited
    measured, total = db.get_pa_coverage(db.get_latest_run_id())
    assert total > measured > 0
    assert f"Page Authority measured for {measured} of {total} audited URL(s)" in markdown


def test_no_fragile_magnet_is_claimed_on_a_single_run(audited):
    """There is nothing to compare a first run with — silence, not a -30 collapse."""
    _db, markdown, _tmp = audited
    assert "Fragile Magnets" not in markdown


# ── C-C-06: an errored scrape is recorded, not omitted ───────────────────────

def test_an_errored_scrape_leaves_a_null_rank_snapshot(audited):
    db, _markdown, _tmp = audited
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT url, rank FROM market_history WHERE url LIKE ?",
            (f"https://{NO_MOZ}%",)).fetchall()
    assert rows == [(f"https://{NO_MOZ}/couples", None)]


def test_an_errored_page_is_not_persisted_as_a_zero_score_magnet(audited):
    db, _markdown, _tmp = audited
    run_id = db.get_latest_run_id()
    magnet_urls = {r[0] for r in _rows(
        db, "SELECT url FROM traffic_magnets WHERE run_id=?", (run_id,))}
    assert f"https://{NO_MOZ}/couples" not in magnet_urls
