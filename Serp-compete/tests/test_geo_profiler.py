"""Tests for SC-1 GEO / extractability profiler (src/geo_profiler.py)."""

import json
import os
from types import SimpleNamespace

import pytest

from src.geo_profiler import GeoProfiler, GeoProfile, NOT_MEASURED

CONFIG = {
    "credential_list": ["MD", "PhD", "RCC", "MSW", "RP"],
    "geo_signals": {
        "interrogatives": ["how", "what", "why", "when", "where", "who",
                           "which", "can", "does", "do", "is", "are"],
        "strong_tier_min_signals": 3,
        "moderate_tier_min_signals": 1,
    },
}


def _page(url="https://ex.com/p", status="complete", outline=None, metadata=None):
    """Build a duck-typed ScrapedPage-like object."""
    base_meta = {
        "schema_types": [], "has_faq_schema": False, "has_article_schema": False,
        "has_localbusiness_schema": False, "author_byline": None,
        "publish_date": None, "update_date": None,
    }
    if metadata:
        base_meta.update(metadata)
    return SimpleNamespace(
        url=url, extraction_status=status,
        outline=outline or [], metadata=base_meta,
    )


def test_schema_rich_credentialed_fresh_page_is_strong():
    page = _page(
        outline=[
            {"level": "h1", "text": "Grief Counselling", "order": 0},
            {"level": "h2", "text": "What is grief counselling?", "order": 1},
            {"level": "h2", "text": "How long does it take?", "order": 2},
        ],
        metadata={
            "schema_types": ["FAQPage", "Person"], "has_faq_schema": True,
            "author_byline": "Jane Doe, RCC", "publish_date": "2026-01-01",
        },
    )
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert prof.extractability_tier == "Strong"
    assert prof.signals["has_faq_schema"] is True
    assert prof.signals["has_person_schema"] is True
    assert prof.signals["matched_credentials"] == ["RCC"]
    assert prof.signals["question_heading_count"] == 2
    # 3+ present signals: schema, credentialed author, question headings, fresh
    assert len(prof.present_signals) >= 3
    assert "RCC" in prof.why_cited


def test_bare_page_is_weak_with_no_signals():
    page = _page(
        outline=[{"level": "h1", "text": "Home", "order": 0},
                 {"level": "h2", "text": "Our Services", "order": 1}],
        metadata={},
    )
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert prof.extractability_tier == "Weak"
    assert prof.present_signals == []
    assert prof.signals["question_heading_count"] == 0
    assert "little structural advantage" in prof.why_cited


def test_credentialed_author_detected_from_byline():
    page = _page(metadata={"author_byline": "Dr. Alex Smith, PhD, RP"})
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert set(prof.signals["matched_credentials"]) == {"PhD", "RP"}
    assert any("credentialed author" in s for s in prof.present_signals)


def test_question_headings_ratio_only_counts_subheads():
    page = _page(outline=[
        {"level": "h1", "text": "Is this a question?", "order": 0},  # h1 ignored
        {"level": "h2", "text": "Why differentiation matters", "order": 1},  # P7: declarative → NOT counted
        {"level": "h2", "text": "Our approach", "order": 2},
        {"level": "h3", "text": "Can therapy help?", "order": 3},  # real question ✓
    ])
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert prof.signals["subheading_count"] == 3
    # P7: only the genuine question ("Can therapy help?") counts — the interrogative-
    # opener-but-declarative "Why differentiation matters" does not.
    assert prof.signals["question_heading_count"] == 1
    assert prof.signals["question_heading_ratio"] == round(1 / 3, 3)


def test_declarative_interrogative_opener_is_not_a_question_heading():
    """P7 adversarial: headings that *look* question-shaped (start with an
    interrogative word) but are declarative must NOT count toward extractability
    or inflate the tier. Only a real, '?'-terminated question counts."""
    page = _page(outline=[
        {"level": "h2", "text": "How We Help", "order": 0},              # declarative
        {"level": "h2", "text": "Why differentiation matters", "order": 1},  # declarative
        {"level": "h2", "text": "What Sets Us Apart", "order": 2},        # declarative
        {"level": "h2", "text": "How long does therapy take?", "order": 3},  # real question
    ])
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert prof.signals["subheading_count"] == 4
    assert prof.signals["question_heading_count"] == 1  # only the real question
    # The rationale must report exactly one question-shaped heading, not four.
    assert "1 question-shaped heading" in " ".join(prof.present_signals)


def test_blocked_page_is_unknown_and_does_not_crash():
    page = _page(status="blocked", metadata={})
    prof = GeoProfiler(CONFIG).profile_page(page)
    assert prof.extractability_tier == "Unknown"
    assert prof.present_signals == []
    assert "could not be fully retrieved" in prof.why_cited


def test_not_measured_signals_are_declared():
    prof = GeoProfiler(CONFIG).profile_page(_page())
    assert prof.not_measured == NOT_MEASURED
    d = prof.to_dict()
    assert "answer_first_placement" in d["not_measured"]
    assert d["caveat"]


def test_empty_config_falls_back_to_defaults():
    # No geo_signals / credential_list → safe defaults, still runs.
    prof = GeoProfiler({}).profile_page(
        _page(outline=[{"level": "h2", "text": "How does it work?", "order": 0}])
    )
    assert prof.signals["question_heading_count"] == 1


def test_save_and_read_geo_profile_roundtrip(tmp_path):
    """SC-1: geo_profiles table is created and a profile persists + reads back."""
    from src.database import DatabaseManager
    db = DatabaseManager(str(tmp_path / "geo_test.db"))
    run_id = db.create_run("client.com")
    page = _page(
        url="https://comp.com/faq",
        outline=[{"level": "h2", "text": "What is it?", "order": 0}],
        metadata={"schema_types": ["FAQPage"], "has_faq_schema": True,
                  "author_byline": "Dr. X, PhD"},
    )
    prof = GeoProfiler(CONFIG).profile_page(page)
    db.save_geo_profile(run_id, prof)
    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT url, extractability_tier, credential_count, why_cited "
            "FROM geo_profiles WHERE run_id=?", (run_id,)).fetchone()
    assert row is not None
    assert row[0] == "https://comp.com/faq"
    assert row[2] == 1  # one credential (PhD)


def test_geo_signals_present_in_shared_config():
    path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "shared_config.json"))
    with open(path) as f:
        cfg = json.load(f)
    assert "geo_signals" in cfg, "geo_signals block missing from shared_config.json"
    assert cfg["geo_signals"].get("interrogatives"), "interrogatives list is empty"
