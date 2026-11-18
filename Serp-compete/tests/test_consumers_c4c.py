"""The consumers: overlap, GSC, SoV, YouTube (C4c — C-M-11, C-C-17, C-M-16, C-M-17).

Promotes probes/compete_method/p04 §A / §D / §E to behaviour tests. Each case is the
probe's own input, asserted against what the owner would now read.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.audit_universe import build_domain_universe, clinical_term_set
from src.database import DatabaseManager
from src.reporting import ReportGenerator
from src.serp_overlap import analyze_serp_overlap, build_overlap_rows
from src.sov_analyzer import compute_sov

OVERLAP_CONFIG = {"top_n": 10, "commodity_high_overlap": 3}


# ── C-C-17: the top-N test uses the ORGANIC rank ─────────────────────────────

def test_cc17_rank_group_is_preferred_over_rank_absolute():
    """A competitor organically at #8 below three SERP features has rank_absolute 11
    and used to drop out of a `<= 10` test — while the client's side of that same test
    is a GSC position computed on a different element model."""
    item = {"keyword_data": {"keyword": "couples counselling"},
            "ranked_serp_element": {"serp_item": {
                "url": "https://comp.com/a", "rank_group": 8, "rank_absolute": 11,
                "etv": 100.0}}}
    rows = build_domain_universe([], [item], {"couples counselling"},
                                 clinical_term_set({"tier_1_medical": ["counselling"]}),
                                 "comp")
    assert rows[0]["position"] == 8


def test_cc17_rank_absolute_is_the_fallback_when_rank_group_is_absent():
    item = {"keyword_data": {"keyword": "couples counselling"},
            "ranked_serp_element": {"serp_item": {
                "url": "https://comp.com/a", "rank_absolute": 11, "etv": 0}}}
    rows = build_domain_universe([], [item], {"couples counselling"},
                                 clinical_term_set({"tier_1_medical": ["counselling"]}),
                                 "comp")
    assert rows[0]["position"] == 11


# ── C-C-17 / C-M-11: GSC is paginated and market-matched ─────────────────────

class _FakeGscService:
    """Returns `pages` of rows, recording every request body it was given."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def searchanalytics(self):
        return self

    def query(self, siteUrl=None, body=None):
        self.requests.append(body)
        index = len(self.requests) - 1
        rows = self.pages[index] if index < len(self.pages) else []
        return SimpleNamespace(execute=lambda: {"rows": rows})


def _gsc_manager(service, config=None):
    from src.gsc_performance import GSCManager
    manager = GSCManager.__new__(GSCManager)
    manager.config = config or {"auth": {"gsc_property_url": "https://livingsystems.ca/"},
                                "gsc_settings": {"country": "can", "date_range_days": 90},
                                "clinical": {"tier_1_medical": ["symptom"],
                                             "tier_2_systems": ["relationship"]}}
    manager.service = service
    manager._cached_sites = None
    return manager


def _row(query, position=5.0):
    return {"keys": [query, "https://livingsystems.ca/p"], "clicks": 1,
            "impressions": 10, "ctr": 0.1, "position": position}


def test_cc17_gsc_is_paginated_past_the_first_5000_rows():
    """GSC returns rows by clicks descending, so everything past row 5000 — the
    zero-click long tail, most of a real property — was missing, and serp_overlap read
    every missing query as "the client is absent"."""
    first_page = [_row(f"kw{i}") for i in range(5000)]
    second_page = [_row("the five thousand and first query")]
    service = _FakeGscService([first_page, second_page])
    rows = _gsc_manager(service).fetch_performance_data()

    assert len(rows) == 5001
    assert service.requests[0]["startRow"] == 0
    assert service.requests[1]["startRow"] == 5000
    assert rows[-1]["keys"][0] == "the five thousand and first query"


def test_cm11_gsc_is_filtered_to_the_same_market_as_the_serp_snapshot():
    """The DataForSEO side is a Canada snapshot (location_code 2124); the client's
    positions were a global average, and the overlap matrix compares them."""
    service = _FakeGscService([[_row("kw")]])
    _gsc_manager(service).fetch_performance_data()
    filters = service.requests[0]["dimensionFilterGroups"][0]["filters"][0]
    assert filters == {"dimension": "country", "operator": "equals",
                       "expression": "can"}


def test_cc14_the_gsc_window_comes_from_config():
    """`gsc_settings.date_range_days` was documented with no reader (hard-coded 90)."""
    service = _FakeGscService([[_row("kw")]])
    config = {"auth": {"gsc_property_url": "https://livingsystems.ca/"},
              "gsc_settings": {"date_range_days": 7}}
    _gsc_manager(service, config).fetch_performance_data()
    body = service.requests[0]
    import datetime
    span = (datetime.date.fromisoformat(body["endDate"])
            - datetime.date.fromisoformat(body["startDate"])).days
    assert span == 7


def test_a_mid_pagination_failure_returns_what_was_read_and_says_so(capsys):
    class _Failing(_FakeGscService):
        def query(self, siteUrl=None, body=None):
            self.requests.append(body)
            if len(self.requests) == 1:
                return SimpleNamespace(
                    execute=lambda: {"rows": [_row(f"kw{i}") for i in range(5000)]})
            raise RuntimeError("GSC 503")

    rows = _gsc_manager(_Failing([])).fetch_performance_data()
    assert len(rows) == 5000
    assert "UNREAD, not empty" in capsys.readouterr().out


# ── C-M-11: a rival's own brand query is not a content gap ───────────────────

def test_cm11_rival_brand_keywords_are_excluded_from_the_matrix():
    """p04 §A: "jericho counselling" landed in `exclusive_competitor` — "rivals rank,
    you're absent — your clearest content gaps to fill", the top action queue."""
    competitor_positions = {"jericho counselling": {"jerichocounselling.com": 1},
                            "couples counselling north vancouver": {"rival.ca": 4}}
    rows = build_overlap_rows(competitor_positions, {}, OVERLAP_CONFIG, "2026-11-15",
                              excluded_keywords={"jericho counselling"})
    assert [r["keyword"] for r in rows] == ["couples counselling north vancouver"]


def test_cm11_the_exclusion_is_wired_into_the_run_path(tmp_path):
    """P21: the filter has to be applied by the caller that builds the matrix."""
    from src.comparison_features import run_comparison_features

    db = DatabaseManager(str(tmp_path / "overlap.db"))
    run_id = db.create_run("livingsystems.ca")
    db.save_competitor_metrics([
        {"domain": "jerichocounselling.com", "url": "https://jerichocounselling.com/a",
         "keyword": "jericho counselling", "position": 1, "traffic": 1.0,
         "keyword_source": "ranked_keywords"},
        {"domain": "jerichocounselling.com", "url": "https://jerichocounselling.com/b",
         "keyword": "couples counselling north vancouver", "position": 4,
         "traffic": 1.0, "keyword_source": "handoff"},
    ], run_id)

    class _Gsc:
        def get_query_position_map(self):
            return {}

    class _Dfs:
        def get_search_volume(self, keywords):
            return {}

    config = {"client": {"domain": "livingsystems.ca", "da": 35},
              "clinical": {"tier_1_medical": ["counselling"], "tier_2_systems": [],
                           "tier_3_bowen": []},
              "serp_overlap": OVERLAP_CONFIG, "positioning": {}, "branded_demand": {},
              "risk_signals": {}, "sov": {}, "youtube_presence": {},
              "brand": {"name_suffixes": ["counselling"]}}
    run_comparison_features(db, run_id, config, "livingsystems.ca",
                            {"jerichocounselling.com": {"jericho counselling"}},
                            _Gsc(), _Dfs(), str(tmp_path))
    with db.connection() as conn:
        keywords = {r[0] for r in conn.execute(
            "SELECT keyword FROM serp_overlap WHERE run_id=?", (run_id,)).fetchall()}
    assert "jericho counselling" not in keywords
    assert "couples counselling north vancouver" in keywords


# ── C-M-17: SoV counts a mentioned-but-uncited rival as a rival ──────────────

def _export(**overrides):
    export = {
        "schema_version": "1.0", "data_available": True,
        "source_run_ts": "2026-11-15T10:00:00Z", "client_name": "Living Systems",
        "engines": ["gemini"],
        "brand_mentions": [
            {"engine": "gemini", "brand": "Living Systems", "mention_count": 2,
             "questions_total": 5, "is_client": True, "source": "gazetteer"},
            {"engine": "gemini", "brand": "Jericho Counselling", "mention_count": 6,
             "questions_total": 5, "is_client": False, "source": "gazetteer"},
        ],
        "ai_citations": [], "answer_sentiment": [],
    }
    export.update(overrides)
    return export


def test_cm17_a_mentioned_but_never_cited_rival_is_a_competitor_not_other():
    """p04 §D: the export carries display names ("Jericho Counselling") and the tool
    compared them with derived tokens ("jericho"), so the rival fell into `other` —
    which the report filters out, printing "Living Systems (you) 25%" with no visible
    75%."""
    sov = compute_sov(_export(), competitor_domains=["jerichocounselling.com"],
                      snapshot_date="2026-11-15", competitor_brands=["jericho"])
    by_entity = {r["entity"]: r for r in sov["rows"] if r["entity_type"] == "brand"}
    assert by_entity["Jericho Counselling"]["category"] == "competitor"
    assert by_entity["Living Systems"]["category"] == "client"


def test_cm17_presence_rate_is_computed_per_answer():
    sov = compute_sov(_export(), competitor_domains=["jerichocounselling.com"],
                      snapshot_date="2026-11-15", competitor_brands=["jericho"])
    client = next(r for r in sov["rows"] if r["is_client"])
    assert client["presence_rate"] == pytest.approx(2 / 5)


def test_cm17_the_report_prints_presence_and_the_other_remainder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "sov.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    rg.db.save_sov(run_id, [
        {"engine": "gemini", "snapshot_date": "2026-11-15", "entity": "Living Systems",
         "entity_type": "brand", "is_client": True, "category": "client",
         "mention_share": 25.0, "citation_share": None, "presence_rate": 0.4,
         "avg_sentiment": None, "cited_gap": False},
        {"engine": "gemini", "snapshot_date": "2026-11-15", "entity": "Some Directory",
         "entity_type": "brand", "is_client": False, "category": "other",
         "mention_share": 75.0, "citation_share": None, "presence_rate": 1.2,
         "avg_sentiment": None, "cited_gap": False},
    ])
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "named in 40% of answers" in content
    assert "Other brands" in content and "75%" in content
    assert "Some Directory" in content


# ── C-M-16: YouTube states what it actually found ────────────────────────────

def test_cm16_a_handle_matching_only_the_brand_token_is_not_confirmed():
    """p04 §E: `bachcounselling.com` derives the token "bach", so a channel at `@bach`
    — a composer, a beer, anyone — scored `high` / `confirmed`."""
    from src.youtube_presence import _score

    rank, confidence, basis = _score(
        {"title": "Bach Cantatas", "description": "", "custom_url": "@bach"},
        "bachcounselling.com", stem="bachcounselling", token="bach")
    assert confidence != "high"
    assert basis != "handle"


def test_cm16_a_handle_matching_the_domain_stem_is_confirmed():
    from src.youtube_presence import _score

    rank, confidence, basis = _score(
        {"title": "Bach Counselling", "description": "", "custom_url": "@bachcounselling"},
        "bachcounselling.com", stem="bachcounselling", token="bach")
    assert (confidence, basis) == ("high", "handle")


def test_cm16_none_found_is_not_a_measured_no_channel():
    from src.youtube_presence import _state_row

    row = _state_row("comp.com", False, "2026-11-15", "none_found", "none_found")
    assert row["has_channel"] is None          # was False — a definitive negative
    assert row["check_status"] == "none_found"


def test_cm16_the_report_says_what_none_found_means(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "yt.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    rg.db.save_yt_presence(run_id, [
        {"domain": "comp.com", "checked_at": "2026-11-15", "has_channel": None,
         "channel_id": "", "handle": None, "channel_title": None, "channel_url": None,
         "subscriber_count": None, "video_count": None, "last_upload_date": None,
         "uploads_recent": None, "match_confidence": "low", "match_basis": "none",
         "check_status": "none_found", "estimation_basis": "none_found"}])
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "none matched by a name search of the top 3 results" in content
    assert "not a measured 'no channel'" in content


# ── 2026-11-16: the paths the owner meets on a FIRST live GSC run ────────────

def test_the_pagination_cap_warns_that_there_may_be_more(capsys):
    """`GSC_MAX_PAGES` stops the loop. If it stops silently, a truncated window
    reads as the whole property — the same defect C-C-17 fixed for one page,
    one order of magnitude up."""
    from src.gsc_performance import GSCManager

    full = [_row(f"kw{i}") for i in range(GSCManager.GSC_PAGE_SIZE)]
    service = _FakeGscService([full] * (GSCManager.GSC_MAX_PAGES + 2))
    rows = _gsc_manager(service).fetch_performance_data()

    assert len(service.requests) == GSCManager.GSC_MAX_PAGES
    assert len(rows) == GSCManager.GSC_PAGE_SIZE * GSCManager.GSC_MAX_PAGES
    assert "there may be more" in capsys.readouterr().out


def test_a_failure_on_the_very_first_page_returns_nothing_and_says_so(capsys):
    """Zero rows read. The caller must not get a silent empty window."""
    class _FailsImmediately(_FakeGscService):
        def query(self, siteUrl=None, body=None):
            self.requests.append(body)
            raise RuntimeError("GSC 503")

    rows = _gsc_manager(_FailsImmediately([])).fetch_performance_data()
    out = capsys.readouterr().out
    assert rows == []
    assert "GSC Data Fetch Error" in out
    # No "rows read before the error" claim when none were.
    assert "UNREAD, not empty" not in out


def test_list_sites_survives_an_api_failure(capsys):
    class _NoSites:
        def sites(self):
            raise RuntimeError("permission denied")

    manager = _gsc_manager(_FakeGscService([]))
    manager.service = _NoSites()
    assert manager.list_sites() == []
    assert "GSC List Sites Error" in capsys.readouterr().out


class _SitesService(_FakeGscService):
    """A service with a sites() listing as well as searchanalytics()."""

    def __init__(self, site_entries, pages=None):
        super().__init__(pages or [[]])
        self.site_entries = site_entries

    def sites(self):
        return SimpleNamespace(
            list=lambda: SimpleNamespace(
                execute=lambda: {"siteEntry": self.site_entries}))


def test_test_connection_names_the_www_variant_when_the_property_differs():
    """The owner's most likely first-run mistake, and the one the error message
    has to diagnose: GSC holds `https://www.x/` and the config says
    `https://x/`, or the reverse."""
    manager = _gsc_manager(_SitesService(
        [{"siteUrl": "https://www.livingsystems.ca/", "permissionLevel": "siteOwner"}]))
    ok, message = manager.test_connection()
    assert ok is False
    assert "URL Mismatch" in message
    assert "https://www.livingsystems.ca/" in message


def test_test_connection_lists_the_available_sites_when_there_is_no_match():
    manager = _gsc_manager(_SitesService(
        [{"siteUrl": "https://someone-else.ca/", "permissionLevel": "siteOwner"}]))
    ok, message = manager.test_connection()
    assert ok is False
    assert "someone-else.ca" in message


def test_test_connection_reports_insufficient_permissions_distinctly():
    """"Unverified" is not "not found", and the fix is different."""
    for level in ("siteUnverifiedUser", "siteRestrictedUser"):
        manager = _gsc_manager(_SitesService(
            [{"siteUrl": "https://livingsystems.ca/", "permissionLevel": level}]))
        ok, message = manager.test_connection()
        assert ok is False
        assert "Insufficient permissions" in message
        assert level in message


def test_test_connection_succeeds_on_a_verified_property():
    manager = _gsc_manager(_SitesService(
        [{"siteUrl": "https://livingsystems.ca/", "permissionLevel": "siteOwner"}]))
    ok, message = manager.test_connection()
    assert ok is True
    assert "Successfully connected" in message


def test_test_connection_reports_an_empty_account():
    manager = _gsc_manager(_SitesService([]))
    ok, message = manager.test_connection()
    assert ok is False
    assert "No GSC properties" in message
