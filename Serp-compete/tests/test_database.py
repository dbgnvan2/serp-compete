import pytest
import os
from src.database import DatabaseManager

@pytest.fixture
def db():
    db_path = "test_competitor_history.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    manager = DatabaseManager(db_path)
    yield manager
    if os.path.exists(db_path):
        os.remove(db_path)

def test_run_creation(db):
    run_id1 = db.create_run("client.com")
    run_id2 = db.create_run("client.com")
    assert run_id2 == run_id1 + 1
    assert db.get_latest_run_id() == run_id2

def test_volatility_logic(db):
    run_id1 = db.create_run("client.com")
    run_id2 = db.create_run("client.com")
    
    # Run 1: Competitor at Pos 10
    db.save_competitor_metrics([
        {"domain": "comp.com", "url": "url1", "keyword": "anxiety", "position": 10, "traffic": 100}
    ], run_id=run_id1)
    
    # Run 2: Competitor drops to Pos 5 (Shift of 5)
    db.save_competitor_metrics([
        {"domain": "comp.com", "url": "url1", "keyword": "anxiety", "position": 5, "traffic": 100}
    ], run_id=run_id2)
    
    alerts = db.get_volatility_alerts(run_id2)
    assert len(alerts) == 1
    assert alerts[0]['domain'] == "comp.com"
    assert alerts[0]['shift'] == -5.0 # Average position improved (decreased) by 5

# ── C-M-02 / owner decision 2 (2026-11-14): the vacuum gate ──────────────────
# Promotes docs/review_2026-11-04/probes/compete_method/p02_reporting_db.py §B, where
# `rcav.org` (medical 0, systems 0) came back as the first reframe target because the
# only conditions were "systems_score = 0 OR Surface-Level", ordered by est_traffic.

def _magnet(db, run_id, url, keyword, medical, systems, traffic=500.0, rank=3,
            relevant=True, source="handoff", label="Standard"):
    db.save_traffic_magnet(run_id, "comp.com", url, keyword, traffic, medical, systems,
                           label=label, keyword_source=source,
                           keyword_relevant=relevant, rank=rank)


def test_strategic_openings(db):
    run_id = db.create_run("client.com")

    # Case 1: clears the medical floor, ranks well, relevant keyword, no systems score
    _magnet(db, run_id, "url1", "anxiety counselling", medical=10, systems=0)

    # Case 2: same but with real systems language (not an opening)
    _magnet(db, run_id, "url2", "depression counselling", medical=10, systems=5)

    openings = db.identify_strategic_openings(run_id, min_medical=10, max_position=10)
    assert len(openings) == 1
    assert openings[0]['keyword'] == "anxiety counselling"
    assert openings[0]['medical_score'] == 10
    assert openings[0]['keyword_source'] == "handoff"


def test_a_page_with_no_medical_vocabulary_is_never_an_opening(db):
    """The Archdiocese of Vancouver case: medical 0, systems 0, highest est_traffic —
    previously the top 'primary target for content reframing' and a gpt-4o spend."""
    run_id = db.create_run("client.com")
    _magnet(db, run_id, "https://rcav.org/", "archdiocese of vancouver",
            medical=0, systems=0, traffic=1094.4)
    _magnet(db, run_id, "url2", "anxiety counselling", medical=12, systems=0, traffic=10.0)

    openings = db.identify_strategic_openings(run_id, min_medical=10, max_position=10)
    assert [o['url'] for o in openings] == ["url2"]


def test_an_irrelevant_keyword_is_never_an_opening(db):
    """'555 homer street' on a page full of medical words is still not a content gap."""
    run_id = db.create_run("client.com")
    _magnet(db, run_id, "url1", "555 homer street", medical=30, systems=0,
            relevant=False, source="ranked_keywords")
    assert db.identify_strategic_openings(run_id, min_medical=10, max_position=10) == []


def test_a_page_outside_the_top_10_is_never_an_opening(db):
    """'Ranks well' is the handoff rank; run_11's avg_pos of 58-65 was not ranking well."""
    run_id = db.create_run("client.com")
    _magnet(db, run_id, "url1", "anxiety counselling", medical=20, systems=0, rank=58)
    assert db.identify_strategic_openings(run_id, min_medical=10, max_position=10) == []


def test_an_unlabelled_legacy_row_is_never_an_opening(db):
    """A row written before provenance existed cannot have its relevance
    reconstructed, so it is reported but never claimed as a target."""
    run_id = db.create_run("client.com")
    db.save_traffic_magnet(run_id, "comp.com", "url1", "anxiety", 500.0, 20, 0)
    assert db.identify_strategic_openings(run_id, min_medical=10, max_position=10) == []
    assert db.count_audited_pages(run_id) == 1          # still audited, still counted


def test_the_openings_gate_defaults_to_config(db):
    """No explicit thresholds → shared_config technical.* (not a hard-coded number)."""
    from src.database import magnet_thresholds
    floor, max_pos = magnet_thresholds()
    run_id = db.create_run("client.com")
    _magnet(db, run_id, "url_pass", "anxiety counselling", medical=floor, systems=0,
            rank=max_pos)
    _magnet(db, run_id, "url_fail", "grief counselling", medical=floor - 1, systems=0,
            rank=max_pos)
    assert [o['url'] for o in db.identify_strategic_openings(run_id)] == ["url_pass"]


def test_keyword_source_counts_separate_handoff_from_enrichment(db):
    run_id = db.create_run("client.com")
    db.save_competitor_metrics([
        {"domain": "comp.com", "url": "u1", "keyword": "couples therapy",
         "position": 2, "traffic": 1, "keyword_source": "handoff"},
        {"domain": "comp.com", "url": "u2", "keyword": "family therapy",
         "position": 4, "traffic": 1, "keyword_source": "ranked_keywords"},
        {"domain": "comp.com", "url": "u3", "keyword": "legacy kw", "position": 4,
         "traffic": 1},
    ], run_id=run_id)
    assert db.keyword_source_counts(run_id) == {
        "handoff": 1, "ranked_keywords": 1, "unlabelled": 1}


def test_a_db_predating_the_provenance_columns_is_repaired(tmp_path):
    """ALTER beside CREATE (the fourth occurrence of this class in database.py): a DB
    written before keyword_source / keyword_relevant / rank existed must be repaired on
    construction, not break save_traffic_magnet and the magnet query."""
    import sqlite3
    db_path = str(tmp_path / "old.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE traffic_magnets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, domain TEXT, url TEXT,
            primary_keyword TEXT, est_traffic REAL, medical_score INTEGER,
            systems_score INTEGER, systemic_label TEXT)""")
        conn.execute("""CREATE TABLE competitor_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, domain TEXT NOT NULL,
            url TEXT NOT NULL, keyword TEXT, position INTEGER, traffic REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("INSERT INTO traffic_magnets (run_id, domain, url, primary_keyword,"
                     " est_traffic, medical_score, systems_score, systemic_label) "
                     "VALUES (99, 'old.com', 'u', 'kw', 1.0, 30, 0, 'Standard')")
        conn.commit()

    db = DatabaseManager(db_path)           # must migrate, not raise
    run_id = db.create_run("client.com")
    _magnet(db, run_id, "new_url", "anxiety counselling", medical=20, systems=0)
    assert [o['url'] for o in db.identify_strategic_openings(
        run_id, min_medical=10, max_position=10)] == ["new_url"]
    # the pre-existing row survives, unlabelled, and is never claimed as a target
    assert db.identify_strategic_openings(99, min_medical=10, max_position=10) == []
    assert db.count_audited_pages(99) == 1
