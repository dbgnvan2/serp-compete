"""Tests for C6 / SC-8 — Reputation-Risk Radar (src/risk_radar.py).

Covers SC-8.1 (a synthetic ~60% visibility drop → visibility_cliff high with the drop %
in evidence), SC-8.2 (parasite needs topical mismatch AND commercial intent, not the
subfolder name alone), SC-8.3 (own-site signals separated from competitor signals),
plus the DB reader/writer.
"""
import json

import pytest

from src.database import DatabaseManager
from src.risk_radar import (
    detect_visibility_cliff, detect_parasite, compute_risk_signals,
)

CONFIG = {"cliff_drop_pct": 0.5, "volatility_high_shift": 6,
          "commercial_terms": ["casino", "loan", "cheap", "bonus"]}


# ── SC-8.1 visibility cliff ───────────────────────────────────────────────────

def test_sc81_visibility_cliff_high_with_drop_pct():
    sig = detect_visibility_cliff([100, 90, 80, 40], CONFIG)   # peak 100, latest 40 → 60%
    assert sig["signal_type"] == "visibility_cliff"
    assert sig["severity"] == "high"
    assert sig["evidence"]["drop_pct"] == 60.0


def test_no_cliff_when_stable():
    assert detect_visibility_cliff([100, 98, 99], CONFIG) is None
    assert detect_visibility_cliff([100], CONFIG) is None      # too little history


def test_sc81_cliff_medium_severity_reachable():
    """Sweep F4: with cliff_drop_pct 0.3 the medium/low tiers are live (not always high)."""
    sig = detect_visibility_cliff([100, 65], {"cliff_drop_pct": 0.3, "cliff_lookback": 6})
    assert sig["severity"] == "medium"     # 35% drop → medium


def test_cliff_historical_drop_scrolls_out_of_window():
    """Sweep F4: a collapse that happened long ago (outside cliff_lookback) and has been
    flat-low since must STOP re-flagging on every future run."""
    cfg = {"cliff_drop_pct": 0.3, "cliff_lookback": 3}
    assert detect_visibility_cliff([100, 40, 40, 40, 40], cfg) is None   # last 3 are flat


# ── SC-8.2 parasite requires mismatch AND commercial intent ───────────────────

def test_sc82_parasite_requires_mismatch_and_commercial():
    core = ["therapy", "counselling"]
    assert detect_parasite("/deals", ["cheap casino bonus"], core, CONFIG["commercial_terms"]) is not None
    assert detect_parasite("/blog", ["gardening tips"], core, CONFIG["commercial_terms"]) is None      # mismatch, no commercial
    assert detect_parasite("/x", ["therapy cheap"], core, CONFIG["commercial_terms"]) is None          # on-topic (overlap) + commercial


def test_sc82_word_boundary_no_false_positive_on_substring():
    """Sweep F3: 'dealing'/'promoting' must NOT match the commercial words 'deal'/'promo'
    (word-boundary, not substring) — legitimate therapy content isn't flagged."""
    core = ["mindfulness", "coaching"]   # /grief keywords are a topical mismatch vs core
    assert detect_parasite("/grief", ["dealing with grief", "promoting healing"],
                           core, ["deal", "promo", "casino"]) is None


def test_sc82_subfolder_name_alone_does_not_flag():
    # subfolder literally "/casino" but its keywords are on-topic → NOT a parasite
    assert detect_parasite("/casino", ["therapy for anxiety"], ["therapy"],
                           CONFIG["commercial_terms"]) is None


# ── SC-8.3 own-site signals separated from competitor signals ─────────────────

def test_sc83_own_and_competitor_signals_separated():
    rows = compute_risk_signals(
        volatility_alerts=[{"domain": "rival.com", "shift": 8}],
        series_by_domain={"livingsystems.ca": [100, 30]},   # own-site cliff
        parasite_candidates=[], own_domain="livingsystems.ca", config=CONFIG)
    own = [r for r in rows if r["is_own_site"]]
    comp = [r for r in rows if not r["is_own_site"]]
    assert any(r["domain"] == "livingsystems.ca" and r["signal_type"] == "visibility_cliff" for r in own)
    assert any(r["domain"] == "rival.com" and r["signal_type"] == "ranking_volatility" for r in comp)


# ── DB reader + writer ────────────────────────────────────────────────────────

def test_save_risk_signals_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "r.db"))
    run_id = db.create_run("c.com")
    rows = compute_risk_signals([], {"a.com": [100, 20]}, [], "livingsystems.ca", CONFIG)
    db.save_risk_signals(run_id, rows, detected_at="2026-07-22")
    with db._get_connection() as conn:
        got = conn.execute("SELECT signal_type, evidence_json FROM risk_signal WHERE run_id=?",
                           (run_id,)).fetchall()
    assert len(got) == 1 and got[0][0] == "visibility_cliff"
    assert json.loads(got[0][1])["drop_pct"] == 80.0


def test_get_parasite_candidates_core_from_other_subfolders(tmp_path):
    db = DatabaseManager(str(tmp_path / "p.db"))
    run_id = db.create_run("c.com")
    db.save_competitor_metrics([
        {"domain": "big.com", "url": "https://big.com/therapy/anxiety", "keyword": "therapy anxiety", "position": 3, "traffic": 10},
        {"domain": "big.com", "url": "https://big.com/therapy/grief", "keyword": "grief counselling", "position": 5, "traffic": 5},
        {"domain": "big.com", "url": "https://big.com/casino/slots", "keyword": "best casino bonus", "position": 2, "traffic": 100},
    ], run_id)
    cands = db.get_parasite_candidates(run_id)
    casino = next(c for c in cands if c["subfolder"] == "/casino")
    assert "best casino bonus" in casino["keywords"]
    # core comes from the OTHER subfolders (/therapy), enabling the mismatch judgement
    core_text = " ".join(casino["core_terms"]).lower()
    assert "therapy" in core_text or "grief" in core_text


def test_get_visibility_series_graceful_and_with_data(tmp_path):
    db = DatabaseManager(str(tmp_path / "v.db"))
    assert db.get_visibility_series("x.com") == []   # market_history absent → graceful, no crash
    with db._get_connection() as conn:
        conn.execute("""CREATE TABLE market_history (id INTEGER PRIMARY KEY, domain TEXT,
            url TEXT, keyword TEXT, rank INTEGER, da INTEGER, systems_score REAL,
            medical_score REAL, timestamp DATETIME)""")
        conn.execute("INSERT INTO market_history (domain, rank, timestamp) VALUES ('x.com', 3, '2026-01-01')")
        conn.execute("INSERT INTO market_history (domain, rank, timestamp) VALUES ('x.com', 15, '2026-01-02')")
        conn.commit()
    assert db.get_visibility_series("x.com") == [1.0, 0.0]   # day1 rank3→top10=1; day2 rank15→0
