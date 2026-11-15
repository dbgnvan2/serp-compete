"""End-to-end `run_audit` test for the audit universe (C-M-01, C-M-02, C-C-13, C-M-03).

Why end to end: the headline finding is that main.py grouped the handoff targets by
domain and then never read `group_targets` — the wiring, not any single function, was
the bug (P21: grep the call site AND assert it in a test). Every external call is
faked; nothing here touches DataForSEO, Moz, OpenAI, GSC or the repo's database.

Promotes the C-M-01 trace and probes/compete_method/p02 §B to behaviour:
  * the handoff's url / primary_keyword_for_url is what gets audited;
  * a DataForSEO enrichment keyword survives only if it is in the handoff set or
    carries a clinical term, and never if it carries the competitor's brand token;
  * only a page that clears the medical floor, ranks well and has a relevant keyword
    becomes a magnet / vacuum / reframe target;
  * the client's branded-demand query comes from the handoff's client_brand_names.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.database import DatabaseManager
from src.reporting import ReportGenerator
from src.velocity_module import VelocityTracker

COMPETITOR = "www.jerichocounselling.com"
HANDOFF_URL = f"https://{COMPETITOR}/couples-counselling"
HANDOFF_KEYWORD = "couples counselling north vancouver"

CONFIG = {
    "client": {"domain": "livingsystems.ca", "da": 35, "name": "Config Fallback Name"},
    "technical": {"database_path": "test_audit.db", "max_audit_pages_per_domain": 3,
                  "vacuum_min_medical": 10, "magnet_max_position": 10},
    "clinical": {"tier_1_medical": ["therapy", "anxiety"],
                 "tier_2_systems": ["differentiation"], "tier_3_bowen": []},
    "brand": {"name_suffixes": ["counselling", "therapy"]},
    "branded_demand": {"branded_modifiers": ["reviews"], "generic_brand_prune": [],
                       "growth_window_months": 3, "ambiguous_brand_ratio": 10},
    "serp_overlap": {"top_n": 10, "commodity_high_overlap": 3},
    "positioning": {"authority_threshold": 50, "focus_threshold": 50,
                    "authority_weights": {"moz_da": 0.7, "top10": 0.3},
                    "top10_saturation": 10, "min_signal_rankings": 2},
    "risk_signals": {"cliff_drop_pct": 0.3},
    "sov": {}, "youtube_presence": {}, "filtering": {},
}


def _handoff():
    return {
        "schema_version": "1.1",
        "source_run_id": "run_20261114_1200",
        "source_run_timestamp": "2026-11-14T12:00:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems Counselling"],
        "targets": [{
            "url": HANDOFF_URL, "domain": COMPETITOR, "rank": 4,
            "entity_type": "practice", "content_type": "service",
            "title": "Couples Counselling North Vancouver",
            "source_keyword": "How much is couples counselling in North Vancouver?",
            "primary_keyword_for_url": HANDOFF_KEYWORD,
        }],
        "exclusions": {"client_urls_excluded": 0, "omit_list_excluded": 0,
                       "omit_list_used": []},
    }


def _dfs_item(path, keyword, rank_absolute, etv):
    url = f"https://{COMPETITOR}{path}"
    return {"ranked_serp_element": {"serp_item": {"url": url,
                                                  "rank_absolute": rank_absolute,
                                                  "etv": etv}},
            "keyword_data": {"keyword": keyword}}


# The four shapes a real ranked_keywords response mixes: an off-topic navigational
# query, the competitor's own brand query, a genuinely clinical keyword, and the
# handoff target's own keyword.
DFS_ITEMS = [
    _dfs_item("/about", "555 homer street", 58, 900.0),
    _dfs_item("/fees", "jericho counselling fees", 3, 400.0),
    _dfs_item("/anxiety", "anxiety therapy north vancouver", 5, 300.0),
    _dfs_item("/couples-counselling", HANDOFF_KEYWORD, 57, 500.0),
]

SCORES = {
    HANDOFF_URL: {"medical_score": 20, "systems_score": 0.0,
                  "systemic_label": "Standard", "t2_count": 0, "t3_count": 0},
    f"https://{COMPETITOR}/anxiety": {"medical_score": 2, "systems_score": 0.0,
                                      "systemic_label": "Standard", "t2_count": 0,
                                      "t3_count": 0},
}


class _FakeAuditor:
    def scrape_content(self, url):
        return SimpleNamespace(url=url, extraction_status="complete", outline=[],
                               first_500_words="counselling copy", metadata={})

    def analyze_text(self, content):
        return dict(SCORES[content.url])


class _FakeDfs:
    def __init__(self):
        self.volume_queries = []

    def get_relevant_pages(self, domain):
        return list(DFS_ITEMS)

    def get_search_volume(self, keywords):
        self.volume_queries.append(list(keywords))
        return {str(k).lower(): {"search_volume": 100, "monthly_searches": []}
                for k in keywords}


class _FakeMoz:
    def get_url_metrics(self, urls):
        return [{"url": u, "page_authority": 30} for u in urls]


class _FakeGsc:
    def analyze_gaps(self):
        return pd.DataFrame(), pd.DataFrame(), []

    def get_query_position_map(self):
        return {}


class _FakeReframeEngine:
    def __init__(self, *a, **kw):
        self.calls = []

    def generate_bowen_reframe(self, keyword, url, medical_score, paa_questions=None):
        self.calls.append({"keyword": keyword, "url": url,
                           "medical_score": medical_score})
        return {"reframe": "Draft blueprint.", "usage": {"prompt_tokens": 1,
                                                         "completion_tokens": 1,
                                                         "total_tokens": 2}}


@pytest.fixture
def audited(tmp_path, monkeypatch):
    """Run the real `run_audit` against fakes; yield (db, report_markdown, fakes)."""
    monkeypatch.chdir(tmp_path)                     # report files land in tmp
    config_path = tmp_path / "shared_config.json"
    config_path.write_text(json.dumps(CONFIG))
    db_path = str(tmp_path / "test_audit.db")
    handoff_path = tmp_path / "competitor_handoff_test_20261114_1200.json"
    handoff_path.write_text(json.dumps(_handoff()))

    import src.main as main

    dfs, reframe = _FakeDfs(), _FakeReframeEngine()
    captured = {}

    class _Reporter(ReportGenerator):
        def __init__(self, *a, **kw):
            super().__init__(db_path)

        def generate_summary(self, *a, **kw):
            captured["markdown"] = super().generate_summary(*a, **kw)
            return captured["markdown"]

    with patch.object(main, "pre_flight_check", return_value=_FakeGsc()), \
         patch.object(main, "load_shared_config", return_value=CONFIG), \
         patch.object(main, "find_latest_handoff_file", return_value=str(handoff_path)), \
         patch.object(main, "DatabaseManager", lambda *a, **kw: DatabaseManager(db_path)), \
         patch.object(main, "VelocityTracker",
                      lambda *a, **kw: VelocityTracker(str(config_path))), \
         patch.object(main, "DataForSEOClient", lambda *a, **kw: dfs), \
         patch.object(main, "MozClient", lambda *a, **kw: _FakeMoz()), \
         patch.object(main, "SemanticAuditor", lambda *a, **kw: _FakeAuditor()), \
         patch.object(main, "ReframeEngine", lambda *a, **kw: reframe), \
         patch.object(main, "GeoProfiler", MagicMock()), \
         patch.object(main, "EEATScorer", MagicMock()), \
         patch.object(main, "ClusterDetector", MagicMock()), \
         patch.object(main, "ReportGenerator", _Reporter):
        main.run_audit()

    db = DatabaseManager(db_path)
    return db, captured.get("markdown", ""), {"dfs": dfs, "reframe": reframe}


def _rows(db, sql, params=()):
    with db._get_connection() as conn:
        return conn.execute(sql, params).fetchall()


# ── C-M-01: the handoff is the audit universe ────────────────────────────────

def test_the_handoff_target_is_audited(audited):
    db, _, _ = audited
    run_id = db.get_latest_run_id()
    audited_urls = {r[0] for r in _rows(
        db, "SELECT url FROM traffic_magnets WHERE run_id=?", (run_id,))}
    assert HANDOFF_URL in audited_urls


def test_the_handoff_keyword_is_recorded_as_a_handoff_fact(audited):
    db, _, _ = audited
    run_id = db.get_latest_run_id()
    rows = _rows(db, "SELECT primary_keyword, keyword_source, rank, est_traffic "
                     "FROM traffic_magnets WHERE run_id=? AND url=?",
                 (run_id, HANDOFF_URL))
    assert rows == [(HANDOFF_KEYWORD, "handoff", 4, 500.0)]
    # rank 4 is Tool 1's, not DataForSEO's 57 for the same url+keyword; the ETV is
    # taken because it is the only traffic estimate that exists.


def test_off_topic_and_brand_enrichment_keywords_never_enter_the_run(audited):
    """The run_11 signature: 'archdiocese of vancouver', '555 homer street',
    'airport heights medical clinic' — and a rival's own brand query."""
    db, markdown, _ = audited
    run_id = db.get_latest_run_id()
    keywords = {r[0] for r in _rows(
        db, "SELECT keyword FROM competitor_metrics WHERE run_id=?", (run_id,))}
    assert "555 homer street" not in keywords
    assert "jericho counselling fees" not in keywords
    assert "555 homer street" not in markdown
    assert "jericho counselling fees" not in markdown


def test_a_relevant_enrichment_keyword_is_kept_and_labelled(audited):
    db, _, _ = audited
    run_id = db.get_latest_run_id()
    rows = _rows(db, "SELECT keyword, keyword_source FROM competitor_metrics "
                     "WHERE run_id=? AND keyword=?",
                 (run_id, "anxiety therapy north vancouver"))
    assert rows == [("anxiety therapy north vancouver", "ranked_keywords")]


def test_the_report_states_keyword_provenance(audited):
    _, markdown, _ = audited
    assert "**Keyword provenance:**" in markdown
    assert "handoff: 1" in markdown and "ranked_keywords: 1" in markdown


# ── C-M-02 / C-M-15: the magnet, vacuum and reframe gate ─────────────────────

def test_only_the_page_clearing_the_floor_is_a_magnet(audited):
    db, markdown, _ = audited
    run_id = db.get_latest_run_id()
    assert db.count_audited_pages(run_id) == 2        # both pages audited…
    magnets = _rows(db, "SELECT url FROM traffic_magnets WHERE run_id=? AND "
                        "keyword_relevant=1 AND medical_score>=10 AND rank<=10",
                    (run_id,))
    assert [r[0] for r in magnets] == [HANDOFF_URL]   # …one qualifies
    assert "1 of 2 audited page(s) meet the magnet definition" in markdown


def test_the_reframe_target_is_the_vacuum_and_carries_its_score(audited):
    db, markdown, fakes = audited
    calls = fakes["reframe"].calls
    assert [(c["url"], c["medical_score"]) for c in calls] == [(HANDOFF_URL, 20)]
    assert "### ⚡ Strategic Targets: Systemic Vacuums" in markdown
    assert f"({HANDOFF_KEYWORD} — handoff, rank 4)" in markdown


def test_a_page_below_the_floor_is_reported_but_not_a_target(audited):
    db, markdown, fakes = audited
    run_id = db.get_latest_run_id()
    low = _rows(db, "SELECT medical_score FROM traffic_magnets WHERE run_id=? AND url=?",
                (run_id, f"https://{COMPETITOR}/anxiety"))
    assert low == [(2,)]                                    # persisted, auditable
    assert all("anxiety" not in c["url"] for c in fakes["reframe"].calls)


# ── C-C-13 / C-M-03: brand identity ──────────────────────────────────────────

def test_the_clients_brand_comes_from_the_handoff_not_the_stem(audited):
    db, _, _ = audited
    run_id = db.get_latest_run_id()
    rows = _rows(db, "SELECT brand FROM brand_demand_bench WHERE run_id=? AND domain=?",
                 (run_id, "livingsystems.ca"))
    assert rows == [("Living Systems Counselling",)]         # handoff client_brand_names
    assert rows != [("livingsystems",)]                      # the pre-fix bare stem


def test_the_competitors_branded_queries_use_the_display_brand(audited):
    db, _, fakes = audited
    sent = [q for call in fakes["dfs"].volume_queries for q in call]
    assert "Jericho Counselling" in sent
    assert not any(q.lower().startswith("www") for q in sent)   # C-C-01
    db_brands = {r[0] for r in _rows(
        db, "SELECT brand FROM brand_demand_bench WHERE run_id=?",
        (db.get_latest_run_id(),))}
    assert "Jericho Counselling" in db_brands


# ── C-C-16: the handoff the caller selects is the handoff that is audited ────

def test_cc16_parse_args_reads_the_handoff_flag():
    from src.main import parse_args
    assert parse_args(["--handoff", "/outputs/h.json"])["handoff"] == "/outputs/h.json"
    assert parse_args(["--handoff=/outputs/h.json"])["handoff"] == "/outputs/h.json"
    assert parse_args([])["handoff"] is None          # unchanged default behaviour


def test_cc16_an_explicit_handoff_beats_the_newest_file(tmp_path, monkeypatch):
    """`find_latest_handoff_file` picks the newest mtime in the project root, so the
    GUI's selection only took effect when "Copy handoff to root" was ticked: with it
    cleared, selecting an OLDER handoff silently audited the newest one."""
    import src.main as main

    older = tmp_path / "competitor_handoff_older_20260101_0000.json"
    newer = tmp_path / "competitor_handoff_newer_20261115_0000.json"
    chosen = _handoff()
    chosen["source_run_id"] = "the-one-i-picked"
    older.write_text(json.dumps(chosen))
    other = _handoff()
    other["source_run_id"] = "the-newest-file"
    newer.write_text(json.dumps(other))
    os.utime(newer, (2_000_000_000, 2_000_000_000))    # definitively newest

    with patch.object(main, "find_latest_handoff_file", return_value=str(newer)):
        _targets, _paa, _brands, used = main.get_latest_market_data(str(older))
    assert used == str(older)

    # …and with no explicit path the newest file is still used, as before.
    with patch.object(main, "find_latest_handoff_file", return_value=str(newer)):
        _targets, _paa, _brands, used_default = main.get_latest_market_data()
    assert used_default == str(newer)


def test_cc16_a_missing_explicit_handoff_fails_loudly(tmp_path):
    import src.main as main
    with pytest.raises(SystemExit):
        main.get_latest_market_data(str(tmp_path / "does_not_exist.json"))


def test_cc16_the_briefing_names_the_handoff_that_was_audited(audited):
    _db, markdown, _fakes = audited
    assert "**Handoff:** competitor_handoff_test_20261114_1200.json" in markdown


def test_cc16_the_orchestrator_passes_the_selected_handoff():
    """The GUI needs streamlit, which this repo deliberately does not install (only
    the optional GUI imports it), so its call site is checked by parsing rather than
    executing — the same approach test_risk_radar.TestMainWiring uses for main.py.
    Matching source TEXT would also match a comment; the AST cannot."""
    import ast
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "src", "orchestrator.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    cmd_lists = [node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", None) == "cmd" for t in node.targets)
                 and isinstance(node.value, ast.List)]
    assert cmd_lists, "orchestrator.py no longer builds a `cmd` list"
    rendered = [ast.unparse(node) for node in cmd_lists]
    assert any("--handoff" in r and "selected_handoff_path" in r for r in rendered), \
        f"orchestrator must pass the selected handoff to main.py; got {rendered}"
