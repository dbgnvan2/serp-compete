"""Tests for C2 / SC-4 — Barbell Positioning Diagnostic (src/positioning.py).

Covers SC-4.1 (client always plotted), SC-4.2 (thresholds from config), SC-4.3
(quadrant assignment at the corners), SC-4.4 (rationale carries the numbers), plus
the emerging / insufficient_data guards (never silently middle), the entropy/axis
math, the client GSC-query tier classifier, and the DB reader/writer.
"""
import json

import pytest

from src.database import DatabaseManager
from src.positioning import (
    normalized_entropy, compute_authority, compute_focus, classify_quadrant,
    classify_query_tiers, positioning_row, compute_positioning,
    QUAD_AUTHORITATIVE, QUAD_NICHE_OWNER, QUAD_MIDDLE, QUAD_EMERGING, QUAD_INSUFFICIENT,
)

CONFIG = {
    "authority_threshold": 50, "focus_threshold": 50,
    "authority_weights": {"moz_da": 0.7, "top10": 0.3},
    "top10_saturation": 10, "min_signal_rankings": 2,
}


# ── axis math ─────────────────────────────────────────────────────────────────

def test_normalized_entropy():
    assert normalized_entropy([1, 0]) == 0.0        # fully concentrated
    assert normalized_entropy([5]) == 0.0           # single bucket
    assert normalized_entropy([]) == 0.0
    assert normalized_entropy([1, 1]) == pytest.approx(1.0)  # uniform over 2


def test_compute_authority_renormalizes_over_present_components():
    # both present: (60*0.7 + 50*0.3) / 1.0 = 57  (top10=5 → 50)
    assert compute_authority(60, 5, CONFIG) == pytest.approx(57.0)
    # missing DA → renormalize over top10 alone (never counted as 0)
    assert compute_authority(None, 5, CONFIG) == pytest.approx(50.0)
    # nothing available → None (DA missing, top10 == 0 excluded)
    assert compute_authority(None, 0, CONFIG) is None


def test_compute_focus_concentration():
    assert compute_focus(10, 0) == 100.0            # pure medical → maximally focused
    assert compute_focus(0, 10) == 100.0            # pure systems → maximally focused
    assert compute_focus(5, 5) == 0.0               # even split → broad
    assert compute_focus(0, 0) is None              # no tier signal → unplaceable


# ── SC-4.2 thresholds from config ─────────────────────────────────────────────

def test_sc42_thresholds_read_from_config():
    strict = {**CONFIG, "authority_threshold": 60}
    assert classify_quadrant(55, 10, CONFIG) == QUAD_AUTHORITATIVE      # 55 ≥ 50
    assert classify_quadrant(55, 10, strict) == QUAD_MIDDLE             # 55 < 60


# ── SC-4.3 quadrant assignment at the corners ─────────────────────────────────

@pytest.mark.parametrize("authority,focus,expected", [
    (70, 10, QUAD_AUTHORITATIVE),   # broad + high authority
    (30, 80, QUAD_NICHE_OWNER),     # concentrated + low authority
    (30, 20, QUAD_MIDDLE),          # low / low (undifferentiated middle)
    (70, 80, QUAD_AUTHORITATIVE),   # concentrated + high authority → authority wins
])
def test_sc43_quadrant_corners(authority, focus, expected):
    assert classify_quadrant(authority, focus, CONFIG) == expected


def test_sc43_via_positioning_row():
    # broad + high authority (moz 80, top10 5 → authority 70; even tiers → focus 0)
    row = positioning_row("a.com", {"moz_da": 80, "top10_count": 5,
                                    "medical_total": 5, "systems_total": 5}, False, CONFIG)
    assert row["quadrant"] == QUAD_AUTHORITATIVE
    # concentrated + low authority
    row = positioning_row("b.com", {"moz_da": 10, "top10_count": 2,
                                    "medical_total": 10, "systems_total": 0}, False, CONFIG)
    assert row["quadrant"] == QUAD_NICHE_OWNER


# ── SC-4.4 rationale carries the driving numbers ──────────────────────────────

def test_sc44_rationale_has_numbers():
    row = positioning_row("a.com", {"moz_da": 55, "top10_count": 4,
                                    "medical_total": 8, "systems_total": 2}, False, CONFIG)
    r = row["rationale"]
    for key in ("moz_da", "top10_count", "medical_total", "systems_total",
                "authority_score", "focus_score", "authority_threshold", "focus_threshold"):
        assert key in r
    assert r["moz_da"] == 55 and r["top10_count"] == 4
    assert r["authority_score"] == row["authority_score"]


# ── emerging / insufficient_data (never silently middle) ──────────────────────

def test_thin_domain_is_emerging_not_middle():
    # computable but only 1 top-10 ranking (< min_signal 2) → emerging
    row = positioning_row("new.com", {"moz_da": 20, "top10_count": 1,
                                      "medical_total": 5, "systems_total": 5}, False, CONFIG)
    assert row["quadrant"] == QUAD_EMERGING


def test_no_tier_signal_is_insufficient_not_middle():
    row = positioning_row("x.com", {"moz_da": 20, "top10_count": 5,
                                    "medical_total": 0, "systems_total": 0}, False, CONFIG)
    assert row["quadrant"] == QUAD_INSUFFICIENT


# ── SC-4.1 client always plotted ──────────────────────────────────────────────

def test_sc41_client_always_plotted():
    rows = compute_positioning(
        {"comp.com": {"moz_da": 50, "top10_count": 5, "medical_total": 10, "systems_total": 2}},
        "livingsystems.ca",
        {"moz_da": 35, "top10_count": 3, "medical_total": 1, "systems_total": 4}, CONFIG)
    client = [r for r in rows if r["is_client"]]
    assert len(client) == 1 and client[0]["domain"] == "livingsystems.ca"
    assert client[0]["estimation_basis"] == "first_party_gsc"


def test_sc41_client_plotted_even_with_no_data():
    rows = compute_positioning({}, "livingsystems.ca", {}, CONFIG)
    client = next(r for r in rows if r["is_client"])
    assert client["domain"] == "livingsystems.ca"
    assert client["quadrant"] == QUAD_INSUFFICIENT  # no data → insufficient, but STILL plotted


# ── client GSC-query tier classifier ──────────────────────────────────────────

def test_classify_query_tiers():
    vocab = {"tier_1_medical": ["symptom", "diagnosis"],
             "tier_2_systems": ["differentiation"], "tier_3_bowen": ["emotional fusion"]}
    med, sys = classify_query_tiers(
        ["anxiety symptom", "differentiation of self", "emotional fusion in couples",
         "north vancouver therapy"], vocab)
    assert med == 1        # "anxiety symptom"
    assert sys == 2        # "differentiation..." + "emotional fusion..."


# ── DB reader + writer ────────────────────────────────────────────────────────

def test_get_positioning_inputs(tmp_path):
    db = DatabaseManager(str(tmp_path / "p.db"))
    run_id = db.create_run("c.com")
    db.save_traffic_magnet(run_id, "a.com", "https://a.com/1", "kw1", 100, 10, 2, label="Standard")
    db.save_traffic_magnet(run_id, "a.com", "https://a.com/2", "kw2", 50, 5, 8, label="Standard")
    db.save_competitor_metrics([
        {"domain": "a.com", "url": "https://a.com/1", "keyword": "kw1", "position": 3, "traffic": 100},
        {"domain": "a.com", "url": "https://a.com/2", "keyword": "kw2", "position": 15, "traffic": 50},
    ], run_id)
    db.save_competitor_summary("a.com", 42)        # the run-path DA persistence
    db.save_competitor_summary("other.com", 60)    # a domain NOT audited this run
    inputs = db.get_positioning_inputs(run_id)
    assert inputs["a.com"]["medical_total"] == 15.0   # 10 + 5
    assert inputs["a.com"]["systems_total"] == 10.0   # 2 + 8
    assert inputs["a.com"]["top10_count"] == 1        # only kw1 (pos 3 ≤ 10)
    assert inputs["a.com"]["moz_da"] == 42            # DA merged from the competitors table
    assert "other.com" not in inputs                 # not audited this run → excluded


def test_high_authority_thin_domain_is_not_emerging():
    """Sweep Finding 3: a high-DA rival with few top-10 rankings in the tracked set is
    still authoritative, not mislabelled 'emerging' (which connotes new/thin)."""
    row = positioning_row("bigsite.com", {"moz_da": 90, "top10_count": 1,
                                          "medical_total": 5, "systems_total": 5}, False, CONFIG)
    assert row["quadrant"] == QUAD_AUTHORITATIVE


def test_save_competitor_summary_feeds_get_competitor_das(tmp_path):
    """Sweep Finding 1: the run-path DA persistence must actually populate the
    competitors table so BOTH positioning and C4 feasibility get competitor DA."""
    db = DatabaseManager(str(tmp_path / "da.db"))
    db.save_competitor_summary("a.com", 42)
    assert db.get_competitor_das() == {"a.com": 42}


def test_save_positioning_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "s.db"))
    run_id = db.create_run("c.com")
    rows = compute_positioning(
        {"a.com": {"moz_da": 80, "top10_count": 5, "medical_total": 5, "systems_total": 5}},
        "livingsystems.ca",
        {"moz_da": 35, "top10_count": 3, "medical_total": 8, "systems_total": 1}, CONFIG)
    db.save_positioning(run_id, rows, computed_at="2026-07-22")
    with db._get_connection() as conn:
        got = conn.execute(
            "SELECT domain, is_client, quadrant, rationale_json FROM positioning "
            "WHERE run_id=? ORDER BY is_client", (run_id,)).fetchall()
    assert len(got) == 2
    client = [r for r in got if r[1] == 1][0]
    assert client[0] == "livingsystems.ca"
    assert json.loads(client[3])["moz_da"] == 35   # rationale persisted with numbers
