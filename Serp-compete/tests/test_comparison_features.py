"""Smoke test for the comparison-layer assembly (src/comparison_features.py).

Sweep finding F7: previously the five comparison blocks lived inline in run_audit() with
no test, so deleting a save() failed nothing. This exercises the ACTUAL assembly with a
seeded DB + fake GSC/DataForSEO clients + a fixture AV export, and asserts every feature
persisted — so removing any wiring now fails a test.
"""
import json

from src.database import DatabaseManager
from src.comparison_features import run_comparison_features

SHARED_CONFIG = {
    "client": {"domain": "livingsystems.ca", "da": 35},
    "clinical": {"tier_1_medical": ["therapy"], "tier_2_systems": ["systemic"], "tier_3_bowen": []},
    "serp_overlap": {"top_n": 10, "commodity_high_overlap": 3},
    "positioning": {"authority_threshold": 50, "focus_threshold": 50,
                    "authority_weights": {"moz_da": 0.7, "top10": 0.3},
                    "top10_saturation": 10, "min_signal_rankings": 2},
    "branded_demand": {"branded_modifiers": ["reviews"], "generic_brand_prune": [], "growth_window_months": 3},
    "risk_signals": {"cliff_drop_pct": 0.3, "commercial_terms": ["casino", "bonus"]},
    "sov": {},
}

AV_EXPORT = {
    "schema_version": "1.0", "data_available": True, "source_run_ts": "2026-07-22T10:00:00Z",
    "client_name": "LS", "engines": ["gemini"],
    "brand_mentions": [{"engine": "gemini", "brand": "Comp", "mention_count": 2,
                        "questions_total": 3, "is_client": False, "source": "gazetteer"}],
    "ai_citations": [{"engine": "gemini", "url": "https://comp.com/x", "domain": "comp.com",
                      "category": "x", "brand": "Comp", "is_client": False, "cite_count": 1}],
    "answer_sentiment": [],
}


class _FakeGsc:
    def get_query_position_map(self):
        return {"couples therapy": 4}   # client ranks → overlap has self-presence


class _FakeDfs:
    def get_search_volume(self, queries):
        return {}   # DataForSEO "down" — C3 still produces rows (volume_unavailable)


def test_f7_run_comparison_features_persists_all_five(tmp_path):
    db = DatabaseManager(str(tmp_path / "c.db"))
    run_id = db.create_run("livingsystems.ca")
    db.save_competitor_metrics([
        {"domain": "comp.com", "url": "https://comp.com/therapy/a", "keyword": "couples therapy", "position": 3, "traffic": 100},
        {"domain": "comp.com", "url": "https://comp.com/casino/b", "keyword": "best casino bonus", "position": 2, "traffic": 50},
    ], run_id)
    db.save_traffic_magnet(run_id, "comp.com", "https://comp.com/therapy/a", "couples therapy", 100, 10, 5, label="Standard")
    db.save_competitor_summary("comp.com", 40)
    (tmp_path / "ai_visibility_export_lsc_20260722.json").write_text(json.dumps(AV_EXPORT))

    competitor_keywords = {"comp.com": {"couples therapy", "best casino bonus"}}
    summary = run_comparison_features(db, run_id, SHARED_CONFIG, "livingsystems.ca",
                                      competitor_keywords, _FakeGsc(), _FakeDfs(), str(tmp_path))

    def count(table):
        with db._get_connection() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id=?",
                                (run_id,)).fetchone()[0]

    assert count("serp_overlap") > 0           # C4 SERP overlap wired + saved
    assert count("positioning") > 0            # C2 barbell positioning wired + saved
    assert count("sov_daily") > 0              # C1 AI share-of-voice consumed + saved
    assert count("brand_demand_bench") > 0     # C3 branded demand wired + saved
    assert count("risk_signal") > 0            # C6 reputation risk (parasite on /casino) wired + saved
    assert summary["sov_available"] is True    # the fixture export was found + consumed


def test_f2_client_moz_da_none_when_da_absent(tmp_path):
    """Sweep F2 (P12): with client.da absent, the client's positioning moz_da must be None
    (compute_authority EXCLUDES a missing DA and renormalizes), NOT 0 — which would count
    a zero score, dragging authority down and possibly flipping the barbell quadrant. The
    extraction must not coerce it to client_da's 0 default (that default is for C4 only)."""
    db = DatabaseManager(str(tmp_path / "c2.db"))
    run_id = db.create_run("livingsystems.ca")
    db.save_competitor_metrics([
        {"domain": "comp.com", "url": "https://comp.com/therapy/a", "keyword": "couples therapy", "position": 3, "traffic": 100},
    ], run_id)
    db.save_traffic_magnet(run_id, "comp.com", "https://comp.com/therapy/a", "couples therapy", 100, 10, 5, label="Standard")
    cfg = {**SHARED_CONFIG, "client": {"domain": "livingsystems.ca"}}  # NO "da" key
    run_comparison_features(db, run_id, cfg, "livingsystems.ca",
                            {"comp.com": {"couples therapy"}}, _FakeGsc(), _FakeDfs(), str(tmp_path))
    with db._get_connection() as conn:
        row = conn.execute("SELECT rationale_json FROM positioning "
                           "WHERE run_id=? AND is_client=1", (run_id,)).fetchone()
    assert row is not None                        # client is always plotted (SC-4.1)
    assert json.loads(row[0])["moz_da"] is None    # excluded, not coerced to 0
