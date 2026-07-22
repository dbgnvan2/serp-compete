"""Verifies the wire-up fix: EEATScorer and ClusterDetector persist to their
tables (previously built but never called from the run path)."""

import json
from types import SimpleNamespace

import pytest

from src.database import DatabaseManager
from src.eeat_scorer import EEATScorer
from src.cluster_detector import ClusterDetector
from src.geo_profiler import GeoProfiler

CONFIG = {
    "credential_list": ["PhD", "RCC"],
    "eeat_weights": {
        "experience": {"has_author_byline": 0.5, "has_publish_date": 0.5},
        "expertise": {"has_credentials_in_byline": 1.0},
        "authoritativeness": {"external_link_count_normalised": 1.0},
        "trustworthiness": {"is_https": 1.0},
    },
    "credential_list_dummy": [],
    "cluster_thresholds": {"hub_in_degree_threshold": 2, "min_pages_for_signal": 3},
}


def _page(url, links=None, byline=None, status="complete"):
    meta = {
        "author_byline": byline, "publish_date": "2026-01-01", "update_date": None,
        "schema_types": [], "image_hosts": [], "image_count": 0,
        "external_link_count": 3, "internal_link_count": len(links or []),
        "internal_links": links or [], "is_https": url.startswith("https"),
        "has_contact_link": True, "has_privacy_link": True,
    }
    return SimpleNamespace(
        url=url, extraction_status=status, outline=[],
        first_500_words="we tested our approach with clients", metadata=meta,
    )


def test_eeat_persists_to_eeat_scores_table(tmp_path):
    db = DatabaseManager(str(tmp_path / "w.db"))
    run_id = db.create_run("c.com")
    scorer = EEATScorer(CONFIG)
    score = scorer.score_page(_page("https://comp.com/a", byline="Jane, PhD"), domain_authority=40)
    scorer.save_to_database(db, run_id, score)  # the never-before-run path
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT url, has_credentials_in_byline FROM eeat_scores WHERE run_id=?",
            (run_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "https://comp.com/a"


def test_cluster_persists_to_cluster_results_table(tmp_path):
    db = DatabaseManager(str(tmp_path / "w.db"))
    run_id = db.create_run("c.com")
    det = ClusterDetector(CONFIG)
    # 3 pages, two linking to page A → A is a hub (in_degree 2 >= threshold)
    pages = [
        _page("https://comp.com/a", links=[]),
        _page("https://comp.com/b", links=["https://comp.com/a"]),
        _page("https://comp.com/c", links=["https://comp.com/a"]),
    ]
    result = det.analyze_domain("comp.com", pages)
    det.save_to_database(db, run_id, result)  # the never-before-run path
    assert result.cluster_signal == "clustered"
    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT domain, cluster_signal, max_in_degree FROM cluster_results WHERE run_id=?",
            (run_id,)).fetchone()
    assert row is not None
    assert row[1] == "clustered"
    assert row[2] == 2


def test_cluster_insufficient_data_below_min_pages(tmp_path):
    db = DatabaseManager(str(tmp_path / "w.db"))
    run_id = db.create_run("c.com")
    det = ClusterDetector(CONFIG)
    result = det.analyze_domain("comp.com", [_page("https://comp.com/a")])
    det.save_to_database(db, run_id, result)
    assert result.cluster_signal == "insufficient_data"


# ── Finding 1 (P8 dirty-state): carry-forward on a cached re-run ──────────────
# Without carry-forward, a re-run within the 7-day semantic cache re-scrapes
# nothing, so EEAT/GEO/cluster write zero rows for the new run_id and the report
# sections silently vanish — the exact "empty sections" bug the wire-up fixes.
# These tests pre-populate a PRIOR run (dirty state) and assert the new run is
# still populated by carry_forward_profile.

def test_geo_carry_forward_populates_new_run_on_cache_hit(tmp_path):
    db = DatabaseManager(str(tmp_path / "cf.db"))
    run1 = db.create_run("c.com")
    prof = GeoProfiler(CONFIG).profile_page(_page("https://comp.com/p"))
    db.save_geo_profile(run1, prof)  # prior run's profile
    # Second run: the URL cache-hits, no fresh profile is written — carry forward.
    run2 = db.create_run("c.com")
    assert db.carry_forward_profile("geo_profiles", "url", "https://comp.com/p", run2) is True
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT url FROM geo_profiles WHERE run_id=?", (run2,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == "https://comp.com/p"


def test_eeat_carry_forward_populates_new_run_on_cache_hit(tmp_path):
    db = DatabaseManager(str(tmp_path / "cf2.db"))
    run1 = db.create_run("c.com")
    scorer = EEATScorer(CONFIG)
    scorer.save_to_database(
        db, run1, scorer.score_page(_page("https://comp.com/a", byline="Jane, PhD"),
                                    domain_authority=40))
    run2 = db.create_run("c.com")
    assert db.carry_forward_profile("eeat_scores", "url", "https://comp.com/a", run2) is True
    with db._get_connection() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM eeat_scores WHERE run_id=?", (run2,)).fetchone()[0]
    assert n == 1


def test_cluster_carry_forward_populates_new_run_on_cache_hit(tmp_path):
    db = DatabaseManager(str(tmp_path / "cf3.db"))
    run1 = db.create_run("c.com")
    det = ClusterDetector(CONFIG)
    pages = [
        _page("https://comp.com/a", links=[]),
        _page("https://comp.com/b", links=["https://comp.com/a"]),
        _page("https://comp.com/c", links=["https://comp.com/a"]),
    ]
    det.save_to_database(db, run1, det.analyze_domain("comp.com", pages))
    run2 = db.create_run("c.com")
    assert db.carry_forward_profile("cluster_results", "domain", "comp.com", run2) is True
    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT cluster_signal, max_in_degree FROM cluster_results WHERE run_id=?",
            (run2,)).fetchone()
    assert row is not None
    assert row[0] == "clustered"  # provenance preserved, not fabricated
    assert row[1] == 2


def test_carry_forward_returns_false_when_no_prior(tmp_path):
    """Cache hit with no prior profile (e.g. first run after this feature shipped)
    must return False so the caller counts it, never fabricates a row."""
    db = DatabaseManager(str(tmp_path / "cf4.db"))
    run = db.create_run("c.com")
    assert db.carry_forward_profile("geo_profiles", "url", "https://none.com/x", run) is False
    with db._get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM geo_profiles").fetchone()[0]
    assert n == 0


def test_carry_forward_rejects_unlisted_table(tmp_path):
    """Only allowlisted structural-profile tables may be carried forward — the
    dynamic-SQL identifier is never taken from an arbitrary caller."""
    db = DatabaseManager(str(tmp_path / "cf5.db"))
    run = db.create_run("c.com")
    with pytest.raises(ValueError):
        db.carry_forward_profile("semantic_audits", "url", "x", run)


def test_carry_forward_does_not_pull_from_same_run(tmp_path):
    """A carry-forward must copy a PRIOR run's row, never the current run's own —
    otherwise a re-run could duplicate a fresh row it just wrote."""
    db = DatabaseManager(str(tmp_path / "cf6.db"))
    run1 = db.create_run("c.com")
    prof = GeoProfiler(CONFIG).profile_page(_page("https://comp.com/only"))
    db.save_geo_profile(run1, prof)
    # No other run exists; asking run1 to carry forward finds no OTHER run → False.
    assert db.carry_forward_profile("geo_profiles", "url", "https://comp.com/only", run1) is False
