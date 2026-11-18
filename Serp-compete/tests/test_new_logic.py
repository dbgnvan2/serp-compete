import pytest
import os
import sqlite3
from src.database import DatabaseManager

@pytest.fixture
def temp_db():
    db_path = "test_competitor_history.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = DatabaseManager(db_path)
    yield db
    if os.path.exists(db_path):
        os.remove(db_path)

def test_competitor_tagging(temp_db):
    # Volume Scaler: Traffic > 1000, Medical > 15
    temp_db.tag_competitor_position("volumescaler.com", medical_score=20, systems_t2=5, systems_t3=0, traffic=1500)
    meta = temp_db.get_competitor_metadata("volumescaler.com")
    assert meta['market_position'] == "Volume Scaler"
    
    # Direct Systemic: T3 > 0
    temp_db.tag_competitor_position("systemic.com", medical_score=5, systems_t2=5, systems_t3=2, traffic=100)
    meta = temp_db.get_competitor_metadata("systemic.com")
    assert meta['market_position'] == "Direct Systemic"
    
    # Generalist: T2 > 10
    temp_db.tag_competitor_position("generalist.com", medical_score=5, systems_t2=15, systems_t3=0, traffic=100)
    meta = temp_db.get_competitor_metadata("generalist.com")
    assert meta['market_position'] == "Generalist"

# ── C-C-03 / C-C-05: PA 0 is not PA unknown, and there is now ONE drift detector ──
# Promotes docs/review_2026-11-04/probes/compete/probe_pa_zero_fragile.py. The second
# detector (`database.get_feasibility_drift`, drift < -2) is gone: it rendered under its
# own heading for the same event, with its own threshold, off the same bad input.

def test_drift_is_computed_from_two_measured_page_authorities(temp_db):
    run_id1 = temp_db.create_run("client.com")
    url = "https://competitor.com/page"
    temp_db.save_competitor_history(run_id1, url, position=1, pa=30, traffic=500)

    run_id2 = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run_id2, url, position=1, pa=25, traffic=500)

    with temp_db.connection() as conn:
        drift = conn.execute("SELECT drift FROM competitor_history WHERE run_id=?",
                             (run_id2,)).fetchone()[0]
    assert drift == -5


def test_an_unknown_page_authority_is_stored_null_and_drifts_nowhere(temp_db):
    """A Moz 401/429/5xx used to arrive here as pa=0, so every page of every affected
    domain showed a -35 authority collapse and the next working run showed +35."""
    run_id1 = temp_db.create_run("client.com")
    url = "https://competitor.com/page"
    temp_db.save_competitor_history(run_id1, url, position=1, pa=35, traffic=500)

    run_id2 = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run_id2, url, position=1, pa=None, traffic=500)

    with temp_db.connection() as conn:
        pa, drift = conn.execute(
            "SELECT pa, drift FROM competitor_history WHERE run_id=?",
            (run_id2,)).fetchone()
    assert pa is None            # not 0.0
    assert drift is None         # not -35.0


def test_the_run_after_an_outage_does_not_report_a_rebound(temp_db):
    """The mirror image of the same bug: 0 -> 35 used to read as +35 of real growth."""
    url = "https://competitor.com/page"
    run1 = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run1, url, position=1, pa=35, traffic=500)
    run2 = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run2, url, position=1, pa=None, traffic=500)
    run3 = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run3, url, position=1, pa=35, traffic=500)

    with temp_db.connection() as conn:
        drift = conn.execute("SELECT drift FROM competitor_history WHERE run_id=?",
                             (run3,)).fetchone()[0]
    assert drift == 0            # compared with the last MEASURED PA, not with NULL


def test_pa_coverage_counts_measured_against_attempted(temp_db):
    """"N of M URLs had PA" is persisted as the NULL-vs-value distinction, so an old
    run can still say whether its authority figures were measured."""
    run_id = temp_db.create_run("client.com")
    temp_db.save_competitor_history(run_id, "u1", position=1, pa=30, traffic=1)
    temp_db.save_competitor_history(run_id, "u2", position=2, pa=None, traffic=1)
    temp_db.save_competitor_history(run_id, "u3", position=3, pa=None, traffic=1)
    assert temp_db.get_pa_coverage(run_id) == (1, 3)


def test_the_second_fragile_magnet_detector_is_gone(temp_db):
    """C-M-06: two detectors with different thresholds rendered under two headings for
    the same event. `velocity_module.get_market_alerts` is the only one left."""
    assert not hasattr(temp_db, "get_feasibility_drift")
