import pytest
import os
import sqlite3
from src.velocity_module import VelocityTracker

@pytest.fixture
def temp_tracker(tmp_path):
    # Create a dummy shared_config.json
    config_file = tmp_path / "shared_config.json"
    config_file.write_text('{"technical": {"database_path": "test_velocity.db"}}')
    
    tracker = VelocityTracker(str(config_file))
    yield tracker
    
    # Cleanup
    if os.path.exists(tracker.db_path):
        os.remove(tracker.db_path)

def test_save_and_calculate_velocity(temp_tracker):
    url = "https://competitor.com/page"
    kw = "anxiety"
    
    # Run 1
    temp_tracker.save_market_snapshot("competitor.com", url, kw, rank=10, da=30, systems_score=1.0, medical_score=5.0)
    
    # Run 2 (Dropping Rank and DA)
    temp_tracker.save_market_snapshot("competitor.com", url, kw, rank=12, da=28, systems_score=1.5, medical_score=4.0)
    
    v = temp_tracker.calculate_velocity(url, kw)
    
    assert v["rank_drift"] == -2
    assert v["da_drift"] == -2
    assert v["systems_drift"] == 0.5
    assert v["medical_drift"] == -1.0

# ── C-C-05 / C-M-06: one detector, thresholded, run-scoped ───────────────────
# Promotes docs/review_2026-11-04/probes/compete/probe_pa_zero_fragile.py (run 3) and
# probes/compete_method/p02 §E.


def _snapshot(tracker, run_id, url="https://competitor.com/fragile", kw="trauma",
              rank=5, da=40):
    tracker.save_market_snapshot("competitor.com", url, kw, rank=rank, da=da,
                                 systems_score=0, medical_score=10, run_id=run_id)


def test_fragile_magnet_alert(temp_tracker):
    """A real authority drop (40 -> 35, past pa_drop_min) in the run being reported."""
    _snapshot(temp_tracker, 1, da=40)
    _snapshot(temp_tracker, 2, da=35)

    alerts = temp_tracker.get_market_alerts(run_id=2)
    assert len(alerts) == 1
    assert alerts[0]["type"] == "Fragile Magnet"
    assert alerts[0]["da_drift"] == -5
    assert "Strike this page now" in alerts[0]["advice"]


def test_one_point_of_moz_noise_is_not_a_fragile_magnet(temp_tracker):
    """PA 40 -> 39 with the rank unchanged used to produce "Strike this page now"."""
    _snapshot(temp_tracker, 1, da=40)
    _snapshot(temp_tracker, 2, da=39)
    assert temp_tracker.get_market_alerts(run_id=2) == []


def test_a_rank_slip_alone_is_not_a_fragile_magnet(temp_tracker):
    """Rank 3 -> 5 on a <=10-keyword sample, authority flat: noise, not a collapse.
    The rank move is still reported as evidence when the authority drop qualifies."""
    _snapshot(temp_tracker, 1, rank=3, da=40)
    _snapshot(temp_tracker, 2, rank=5, da=40)
    assert temp_tracker.get_market_alerts(run_id=2) == []


def test_the_threshold_is_live_config(temp_tracker):
    """P4: pa_drop_min is a real consumer, not decorative."""
    _snapshot(temp_tracker, 1, da=40)
    _snapshot(temp_tracker, 2, da=38)
    temp_tracker.config.setdefault("risk_signals", {})["pa_drop_min"] = 5
    assert temp_tracker.get_market_alerts(run_id=2) == []
    temp_tracker.config["risk_signals"]["pa_drop_min"] = 2
    assert len(temp_tracker.get_market_alerts(run_id=2)) == 1


def test_an_unmeasured_page_authority_never_produces_an_alert(temp_tracker):
    """A Moz outage used to store da=0 and so report a -40 authority collapse."""
    _snapshot(temp_tracker, 1, da=40)
    _snapshot(temp_tracker, 2, da=None)
    assert temp_tracker.get_market_alerts(run_id=2) == []
    v = temp_tracker.calculate_velocity("https://competitor.com/fragile", "trauma",
                                        run_id=2)
    assert v["da_drift"] is None        # unknown, not 0


def test_a_url_absent_from_this_run_is_not_re_alerted(temp_tracker):
    """C-C-05: `SELECT DISTINCT url, keyword, domain FROM market_history` had no run
    filter, so a competitor skipped this run (omitted, PA-filtered, DataForSEO 429)
    kept its last recorded drop in every later briefing, indefinitely."""
    _snapshot(temp_tracker, 1, da=40)
    _snapshot(temp_tracker, 2, da=30)          # a genuine drop in run 2
    # Run 3 audited a different page; the fragile URL was not snapshotted at all.
    temp_tracker.save_market_snapshot("other.com", "https://other.com/x", "kw",
                                      rank=4, da=20, systems_score=0, medical_score=0,
                                      run_id=3)
    assert len(temp_tracker.get_market_alerts(run_id=2)) == 1
    assert temp_tracker.get_market_alerts(run_id=3) == []


def test_an_errored_scrape_records_a_null_rank_snapshot(temp_tracker):
    """C-C-06: the attempt is on record, so "we could not read it" stays
    distinguishable from "it was not attempted" — and it drifts nowhere."""
    temp_tracker.save_market_snapshot("competitor.com", "https://competitor.com/e",
                                      "kw", rank=None, da=None, systems_score=None,
                                      medical_score=None, run_id=1)
    with temp_tracker._get_connection() as conn:
        row = conn.execute("SELECT run_id, rank, da FROM market_history").fetchone()
    assert row == (1, None, None)
    assert temp_tracker.get_market_alerts(run_id=1) == []


def test_a_db_predating_run_id_is_repaired(tmp_path):
    """ALTER beside CREATE: market_history is created by this class, so a DB written
    before run_id existed must be migrated, not break every query."""
    import sqlite3
    config_file = tmp_path / "shared_config.json"
    config_file.write_text('{"technical": {"database_path": "old_velocity.db"}}')
    db_path = tmp_path / "old_velocity.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""CREATE TABLE market_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, domain TEXT, url TEXT,
            keyword TEXT, rank INTEGER, da INTEGER, systems_score REAL,
            medical_score REAL)""")
        conn.execute("INSERT INTO market_history (domain, url, keyword, rank, da) "
                     "VALUES ('old.com', 'u', 'kw', 3, 40)")
        conn.commit()

    tracker = VelocityTracker(str(config_file))     # must migrate, not raise
    tracker.save_market_snapshot("old.com", "u", "kw", rank=3, da=30,
                                 systems_score=0, medical_score=0, run_id=7)
    # The legacy row has run_id NULL, so it is not a comparison point and the new
    # snapshot has nothing to drift from — silence, not a fabricated -10.
    assert tracker.get_market_alerts(run_id=7) == []
