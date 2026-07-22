"""Unit tests for the extracted run_audit enrichment wiring (src/enrichment.py).

Closes Finding 2 (P10): the fresh-vs-cache-hit decision and the per-domain cluster
gate were previously only reachable through the live run_audit() integration path.
They now live in importable helpers and are exercised here with a real DB + real
engines + duck-typed pages, no network/model stack required.

Also proves the Finding 1 mixed-domain fix: a domain with SOME cache-served pages
carries the last complete cluster result forward instead of under-counting hubs on
the partial fresh subset.
"""

from types import SimpleNamespace

import pytest

from src.database import DatabaseManager
from src.eeat_scorer import EEATScorer
from src.cluster_detector import ClusterDetector
from src.geo_profiler import GeoProfiler
from src.enrichment import (
    new_enrichment_stats, enrich_scraped_page,
    carry_forward_cached_page, finalize_domain_cluster,
)

CONFIG = {
    "credential_list": ["PhD", "RCC"],
    "eeat_weights": {
        "experience": {"has_author_byline": 0.5, "has_publish_date": 0.5},
        "expertise": {"has_credentials_in_byline": 1.0},
        "authoritativeness": {"external_link_count_normalised": 1.0},
        "trustworthiness": {"is_https": 1.0},
    },
    "cluster_thresholds": {"hub_in_degree_threshold": 2, "min_pages_for_signal": 3},
    "geo_signals": {"interrogatives": ["how", "what", "why", "can", "is"],
                    "strong_tier_min_signals": 3, "moderate_tier_min_signals": 1},
}


def _page(url, links=None, byline="Jane, PhD", status="complete"):
    meta = {
        "author_byline": byline, "publish_date": "2026-01-01", "update_date": None,
        "schema_types": [], "image_hosts": [], "image_count": 0,
        "external_link_count": 3, "internal_link_count": len(links or []),
        "internal_links": links or [], "is_https": url.startswith("https"),
        "has_contact_link": True, "has_privacy_link": True,
    }
    return SimpleNamespace(url=url, extraction_status=status, outline=[],
                           first_500_words="we tested our approach with clients",
                           metadata=meta)


# ── enrich_scraped_page (fresh path) ──────────────────────────────────────────

def test_enrich_scraped_page_persists_eeat_and_geo(tmp_path):
    db = DatabaseManager(str(tmp_path / "e.db"))
    run_id = db.create_run("c.com")
    stats = new_enrichment_stats()
    enrich_scraped_page(db, run_id, _page("https://comp.com/a"), 40,
                        EEATScorer(CONFIG), GeoProfiler(CONFIG), stats)
    assert stats["eeat_fresh"] == 1 and stats["geo_fresh"] == 1
    assert stats["eeat_failed"] == 0 and stats["geo_failed"] == 0
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM eeat_scores WHERE run_id=?",
                            (run_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM geo_profiles WHERE run_id=?",
                            (run_id,)).fetchone()[0] == 1


def test_enrich_scraped_page_counts_failure_not_silent(tmp_path):
    """P2: a systematic engine failure is counted + surfaced, not swallowed into an
    empty section. A broken EEAT scorer must not stop GEO from persisting."""
    db = DatabaseManager(str(tmp_path / "e2.db"))
    run_id = db.create_run("c.com")
    stats = new_enrichment_stats()

    class BrokenEEAT:
        def score_page(self, *a, **k):
            raise RuntimeError("boom")

    enrich_scraped_page(db, run_id, _page("https://comp.com/a"), 40,
                        BrokenEEAT(), GeoProfiler(CONFIG), stats)
    assert stats["eeat_failed"] == 1 and stats["eeat_fresh"] == 0
    assert stats["geo_fresh"] == 1  # GEO still ran despite the EEAT failure


# ── carry_forward_cached_page (cache-hit path) ────────────────────────────────

def test_carry_forward_cached_page_populates_from_prior_run(tmp_path):
    db = DatabaseManager(str(tmp_path / "e3.db"))
    run1 = db.create_run("c.com")
    enrich_scraped_page(db, run1, _page("https://comp.com/a"), 40,
                        EEATScorer(CONFIG), GeoProfiler(CONFIG), new_enrichment_stats())
    run2 = db.create_run("c.com")
    stats = new_enrichment_stats()
    carry_forward_cached_page(db, run2, "https://comp.com/a", stats)
    assert stats["eeat_carried"] == 1 and stats["geo_carried"] == 1
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM eeat_scores WHERE run_id=?",
                            (run2,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM geo_profiles WHERE run_id=?",
                            (run2,)).fetchone()[0] == 1


def test_carry_forward_cached_page_counts_no_prior(tmp_path):
    db = DatabaseManager(str(tmp_path / "e4.db"))
    run = db.create_run("c.com")
    stats = new_enrichment_stats()
    carry_forward_cached_page(db, run, "https://none.com/x", stats)
    assert stats["eeat_no_prior"] == 1 and stats["geo_no_prior"] == 1
    assert stats["eeat_carried"] == 0 and stats["geo_carried"] == 0


# ── finalize_domain_cluster (per-domain gate + mixed-domain fix) ──────────────

def _clustered_pages():
    return [
        _page("https://comp.com/a", links=[]),
        _page("https://comp.com/b", links=["https://comp.com/a"]),
        _page("https://comp.com/c", links=["https://comp.com/a"]),
    ]


def test_finalize_cluster_all_fresh_computes(tmp_path):
    db = DatabaseManager(str(tmp_path / "e5.db"))
    run = db.create_run("c.com")
    stats = new_enrichment_stats()
    finalize_domain_cluster(db, run, "comp.com", _clustered_pages(),
                            had_cache_hit=False, cluster_detector=ClusterDetector(CONFIG),
                            stats=stats)
    assert stats["cluster_fresh"] == 1 and stats["cluster_carried"] == 0
    with db._get_connection() as conn:
        row = conn.execute("SELECT cluster_signal, max_in_degree FROM cluster_results "
                           "WHERE run_id=?", (run,)).fetchone()
    assert row == ("clustered", 2)


def test_finalize_cluster_all_cached_carries_forward(tmp_path):
    db = DatabaseManager(str(tmp_path / "e6.db"))
    det = ClusterDetector(CONFIG)
    run1 = db.create_run("c.com")
    finalize_domain_cluster(db, run1, "comp.com", _clustered_pages(),
                            had_cache_hit=False, cluster_detector=det,
                            stats=new_enrichment_stats())
    run2 = db.create_run("c.com")
    stats = new_enrichment_stats()
    finalize_domain_cluster(db, run2, "comp.com", [], had_cache_hit=True,
                            cluster_detector=det, stats=stats)
    assert stats["cluster_carried"] == 1 and stats["cluster_fresh"] == 0
    with db._get_connection() as conn:
        row = conn.execute("SELECT cluster_signal FROM cluster_results WHERE run_id=?",
                           (run2,)).fetchone()
    assert row is not None and row[0] == "clustered"


def test_finalize_cluster_mixed_domain_prefers_carry_forward(tmp_path):
    """Finding 1 mixed-domain fix: run 2 sees only ONE fresh page (the other two
    were cache-served). Computing on that partial subset would report
    'insufficient_data' and lose the hub. Instead the complete prior result is
    carried forward, so the hub survives the re-run."""
    db = DatabaseManager(str(tmp_path / "e7.db"))
    det = ClusterDetector(CONFIG)
    run1 = db.create_run("c.com")
    finalize_domain_cluster(db, run1, "comp.com", _clustered_pages(),
                            had_cache_hit=False, cluster_detector=det,
                            stats=new_enrichment_stats())
    # Run 2: mixed — only page /b freshly scraped, /a and /c came from cache.
    run2 = db.create_run("c.com")
    stats = new_enrichment_stats()
    finalize_domain_cluster(db, run2, "comp.com",
                            [_page("https://comp.com/b", links=["https://comp.com/a"])],
                            had_cache_hit=True, cluster_detector=det, stats=stats)
    assert stats["cluster_carried"] == 1  # carried, NOT a partial fresh compute
    assert stats["cluster_fresh"] == 0
    with db._get_connection() as conn:
        row = conn.execute("SELECT cluster_signal, max_in_degree FROM cluster_results "
                           "WHERE run_id=?", (run2,)).fetchone()
    assert row == ("clustered", 2)  # the complete prior, not insufficient_data


def test_finalize_cluster_mixed_no_prior_falls_back_to_partial(tmp_path):
    """Mixed domain but nothing prior to carry (e.g. first run after the feature
    shipped): fall back to a best-effort fresh compute on what we have, counted as
    fresh — better than emitting nothing."""
    db = DatabaseManager(str(tmp_path / "e8.db"))
    run = db.create_run("c.com")
    stats = new_enrichment_stats()
    finalize_domain_cluster(db, run, "comp.com", _clustered_pages(),
                            had_cache_hit=True, cluster_detector=ClusterDetector(CONFIG),
                            stats=stats)
    assert stats["cluster_fresh"] == 1 and stats["cluster_carried"] == 0
    with db._get_connection() as conn:
        row = conn.execute("SELECT cluster_signal FROM cluster_results WHERE run_id=?",
                           (run,)).fetchone()
    assert row is not None and row[0] == "clustered"


def test_finalize_cluster_no_pages_no_cache_is_noop(tmp_path):
    db = DatabaseManager(str(tmp_path / "e9.db"))
    run = db.create_run("c.com")
    stats = new_enrichment_stats()
    finalize_domain_cluster(db, run, "comp.com", [], had_cache_hit=False,
                            cluster_detector=ClusterDetector(CONFIG), stats=stats)
    assert all(v == 0 for v in stats.values())
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cluster_results WHERE run_id=?",
                           (run,)).fetchone()[0] == 0
