"""Tests for C4 / SC-6 — SERP Overlap & Differentiation Gap (src/serp_overlap.py).

Covers SC-6.1 (deterministic cell classification), SC-6.2 (exclusive_self requires
zero competitors), SC-6.3 (volume rollups match member volumes), SC-6.4
(AnalysisEngine.find_keyword_intersection wired + covered beyond test_analysis.py),
plus a top-N-symmetry adversarial case and the DB round-trip / reader methods.
"""
import json

import pytest

from src.database import DatabaseManager
from src.serp_overlap import (
    classify_cell, build_overlap_rows, rollup_by_cell, analyze_serp_overlap,
    feasibility_by_competitor,
    CELL_SHARED_COMMODITY, CELL_SHARED_DEFENSIBLE, CELL_EXCLUSIVE_SELF,
    CELL_EXCLUSIVE_COMPETITOR, CELL_ABSENT, CELL_SELF_UNKNOWN,
)

CONFIG = {"top_n": 10, "commodity_high_overlap": 3}


# ── SC-6.1 deterministic cell classification ──────────────────────────────────

@pytest.mark.parametrize("self_present,n_comp,commodity_high,expected", [
    (True,  0, False, CELL_EXCLUSIVE_SELF),
    (True,  1, False, CELL_SHARED_DEFENSIBLE),
    (True,  2, False, CELL_SHARED_DEFENSIBLE),   # 2 rivals but NOT high commodity
    (True,  2, True,  CELL_SHARED_COMMODITY),
    (True,  5, True,  CELL_SHARED_COMMODITY),
    (False, 1, False, CELL_EXCLUSIVE_COMPETITOR),
    (False, 4, True,  CELL_EXCLUSIVE_COMPETITOR),
    (False, 0, False, CELL_ABSENT),
])
def test_sc61_classify_cell_all_quadrants(self_present, n_comp, commodity_high, expected):
    assert classify_cell(self_present, n_comp, commodity_high) == expected


def test_sc61_build_rows_is_deterministic():
    comp = {"couples therapy": {"a.com": 2, "b.com": 5, "c.com": 9},
            "grief counselling": {"a.com": 1}}
    client = {"couples therapy": 4}
    once = build_overlap_rows(comp, client, CONFIG, "2026-07-22")
    twice = build_overlap_rows(comp, client, CONFIG, "2026-07-22")
    assert once == twice
    by_kw = {r["keyword"]: r for r in once}
    # 3 rivals + client, high commodity (>=3) → shared_commodity
    assert by_kw["couples therapy"]["cell"] == CELL_SHARED_COMMODITY
    assert by_kw["couples therapy"]["overlap_count"] == 3
    # 1 rival, client absent → exclusive_competitor
    assert by_kw["grief counselling"]["cell"] == CELL_EXCLUSIVE_COMPETITOR


# ── SC-6.2 exclusive_self requires zero competitors in top-N ──────────────────

def test_sc62_exclusive_self_requires_zero_competitors():
    assert classify_cell(True, 0, False) == CELL_EXCLUSIVE_SELF
    # any competitor in top-N must move it OUT of exclusive_self
    for n in (1, 2, 5):
        assert classify_cell(True, n, False) != CELL_EXCLUSIVE_SELF
        assert classify_cell(True, n, True) != CELL_EXCLUSIVE_SELF
    # via build_overlap_rows: client ranks + 1 rival in top-N → not exclusive_self
    rows = build_overlap_rows({"kw": {"r.com": 3}}, {"kw": 2}, CONFIG, "d")
    assert rows[0]["cell"] == CELL_SHARED_DEFENSIBLE


# ── SC-6.3 volume rollups match member keyword volumes ────────────────────────

def test_sc63_rollup_matches_member_volumes():
    comp = {
        "kw_commodity": {"a.com": 1, "b.com": 2, "c.com": 3},  # +client → shared_commodity
        "kw_excl_comp": {"a.com": 4},                          # client absent → exclusive_competitor
        "kw_excl_self": {},                                    # only client → exclusive_self
    }
    client = {"kw_commodity": 5, "kw_excl_self": 2}
    volumes = {"kw_commodity": 1000.0, "kw_excl_comp": 400.0, "kw_excl_self": 50.0}
    rows = build_overlap_rows(comp, client, CONFIG, "d", keyword_volumes=volumes)
    rollup = rollup_by_cell(rows)
    assert rollup[CELL_SHARED_COMMODITY] == 1000.0
    assert rollup[CELL_EXCLUSIVE_COMPETITOR] == 400.0
    assert rollup[CELL_EXCLUSIVE_SELF] == 50.0
    # invariant: sum of cell rollups == sum of all member volumes (no drop/double-count)
    assert sum(rollup.values()) == sum(volumes.values())
    # keyword_volume is carried on each row (surfaced, not discarded)
    assert all("keyword_volume" in r for r in rows)


# ── SC-6.4 AnalysisEngine wired (find_keyword_intersection + check_feasibility) ─

def test_sc64_analysis_engine_intersection_gap_wired():
    # kw1 is ranked by BOTH competitors and NOT by the client → an all-competitor gap
    competitor_keywords = {"a.com": {"kw1", "kw2"}, "b.com": {"kw1", "kw3"}}
    client_keywords = {"kw2"}
    result = analyze_serp_overlap(
        competitor_positions={"kw1": {"a.com": 3, "b.com": 5}},
        client_positions={"kw2": 4},
        competitor_keywords=competitor_keywords,
        client_keywords=client_keywords,
        client_domain="livingsystems.ca", client_da=35, competitor_das={},
        config=CONFIG, snapshot_date="2026-07-22",
    )
    # only AnalysisEngine.find_keyword_intersection produces this set → it is wired
    assert result["gap_keywords"] == ["kw1"]
    kw1 = next(r for r in result["rows"] if r["keyword"] == "kw1")
    assert kw1["all_competitor_gap"] is True
    assert kw1["cell"] == CELL_EXCLUSIVE_COMPETITOR


def test_sc64_feasibility_wired():
    feas = feasibility_by_competitor("livingsystems.ca", client_da=35,
                                     competitor_das={"weak.com": 40, "strong.com": 60})
    assert feas["weak.com"]["feasible"] is True          # (35+5) >= 40
    assert feas["weak.com"]["suggestion"] == "Proceed"
    assert feas["strong.com"]["feasible"] is False        # (35+5) < 60
    assert feas["strong.com"]["suggestion"] == "Hyper-Local Pivot"


# ── adversarial: top-N symmetry (a page-2 client is NOT "present") ────────────

def test_adversarial_client_page2_is_not_shared():
    """Looks like it could be 'shared' (client ranks + many rivals), but the client
    is on page 2 (pos 15 > top_n=10), so it must be exclusive_competitor, not shared —
    self-presence is symmetric with competitor top-N presence."""
    rows = build_overlap_rows(
        {"kw": {"a.com": 1, "b.com": 2, "c.com": 3, "d.com": 4}},
        {"kw": 15},  # client ranks, but page 2
        CONFIG, "d")
    row = rows[0]
    assert row["cell"] == CELL_EXCLUSIVE_COMPETITOR
    assert row["self_position"] == 15   # raw GSC position retained for transparency


# ── DB round-trip + reader methods ───────────────────────────────────────────

def test_sc6_save_and_read_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "o.db"))
    run_id = db.create_run("livingsystems.ca")
    rows = build_overlap_rows({"kw": {"a.com": 2, "b.com": 3}}, {"kw": 4}, CONFIG, "2026-07-22")
    db.save_serp_overlap(run_id, rows)
    with db._get_connection() as conn:
        got = conn.execute(
            "SELECT keyword, cell, self_position, overlap_count, competitors_ranking_json "
            "FROM serp_overlap WHERE run_id=?", (run_id,)).fetchall()
    assert len(got) == 1
    kw, cell, self_pos, overlap, comp_json = got[0]
    assert kw == "kw" and self_pos == 4 and overlap == 2
    assert json.loads(comp_json) == {"a.com": 2, "b.com": 3}


def test_get_competitor_positions_best_per_domain(tmp_path):
    db = DatabaseManager(str(tmp_path / "p.db"))
    run_id = db.create_run("c.com")
    db.save_competitor_metrics([
        {"domain": "a.com", "url": "u1", "keyword": "kw", "position": 8, "traffic": 100},
        {"domain": "a.com", "url": "u2", "keyword": "kw", "position": 3, "traffic": 50},  # better
        {"domain": "b.com", "url": "u3", "keyword": "kw", "position": 6, "traffic": 70},
    ], run_id)
    pos = db.get_competitor_positions(run_id)
    assert pos == {"kw": {"a.com": 3, "b.com": 6}}  # best (lowest) per domain


def test_get_keyword_volumes_max_per_keyword(tmp_path):
    db = DatabaseManager(str(tmp_path / "v.db"))
    run_id = db.create_run("c.com")
    db.save_competitor_metrics([
        {"domain": "a.com", "url": "u1", "keyword": "kw", "position": 2, "traffic": 100},
        {"domain": "b.com", "url": "u2", "keyword": "kw", "position": 5, "traffic": 300},  # max
    ], run_id)
    assert db.get_keyword_volumes(run_id) == {"kw": 300.0}


def test_get_competitor_das_from_competitors_table(tmp_path):
    db = DatabaseManager(str(tmp_path / "d.db"))
    with db._get_connection() as conn:
        conn.execute("INSERT INTO competitors (domain, avg_da) VALUES ('a.com', 42)")
        conn.execute("INSERT INTO competitors (domain, avg_da) VALUES ('b.com', NULL)")
        conn.commit()
    das = db.get_competitor_das()
    assert das == {"a.com": 42}  # NULL avg_da excluded


# ── sweep-fix regression tests ───────────────────────────────────────────────

def test_finding1_classify_cell_unknown_self():
    assert classify_cell(None, 2, True) == CELL_SELF_UNKNOWN
    assert classify_cell(None, 0, False) == CELL_ABSENT


def test_finding1_gsc_absent_is_self_unknown_not_absent():
    """Finding 1: an empty client map (GSC failed / no session) must NOT classify
    every keyword as exclusive_competitor — self-presence is UNKNOWN, and the false
    'you're absent' action queue is withheld."""
    result = analyze_serp_overlap(
        competitor_positions={"kw": {"a.com": 2, "b.com": 3}},
        client_positions={},  # GSC unavailable this run
        competitor_keywords={"a.com": {"kw"}, "b.com": {"kw"}}, client_keywords=set(),
        client_domain="livingsystems.ca", client_da=35, competitor_das={},
        config=CONFIG, snapshot_date="d",
    )
    assert result["client_positions_available"] is False
    assert result["rows"][0]["cell"] == CELL_SELF_UNKNOWN
    assert result["action_exclusive_competitor"] == []


def test_finding2_case_insensitive_join_no_false_split():
    """Finding 2: a competitor 'Couples Therapy' and GSC 'couples therapy' are the
    SAME keyword — one shared row, not a false exclusive_competitor + exclusive_self."""
    rows = build_overlap_rows(
        {"Couples Therapy": {"a.com": 2}}, {"couples therapy": 4}, CONFIG, "d")
    assert len(rows) == 1
    assert rows[0]["keyword"] == "couples therapy"
    assert rows[0]["cell"] == CELL_SHARED_DEFENSIBLE  # client present + 1 rival


def test_finding2_gap_is_case_insensitive():
    """The all-competitor gap must not falsely flag a keyword the client ranks for
    under different casing."""
    result = analyze_serp_overlap(
        competitor_positions={"EMDR": {"a.com": 3, "b.com": 4}},
        client_positions={"emdr": 5},
        competitor_keywords={"a.com": {"EMDR"}, "b.com": {"EMDR"}}, client_keywords={"emdr"},
        client_domain="c.com", client_da=35, competitor_das={},
        config=CONFIG, snapshot_date="d",
    )
    assert result["gap_keywords"] == []  # client DOES rank emdr → not a gap
    assert result["rows"][0]["all_competitor_gap"] is False


def test_finding3_feasibility_includes_competitor_da():
    feas = feasibility_by_competitor("c.com", 35, {"x.com": 40})
    assert feas["x.com"]["competitor_da"] == 40
    assert feas["x.com"]["feasible"] is True


def test_finding3_save_competitor_feasibility_roundtrip(tmp_path):
    """Feasibility (the check_feasibility half of SC-6.4) is persisted, not discarded."""
    db = DatabaseManager(str(tmp_path / "f.db"))
    run_id = db.create_run("c.com")
    feas = feasibility_by_competitor("c.com", 35, {"weak.com": 40, "strong.com": 60})
    db.save_competitor_feasibility(run_id, 35, feas)
    with db._get_connection() as conn:
        rows = dict(conn.execute(
            "SELECT domain, feasible FROM competitor_feasibility WHERE run_id=?",
            (run_id,)).fetchall())
    assert rows == {"weak.com": 1, "strong.com": 0}
