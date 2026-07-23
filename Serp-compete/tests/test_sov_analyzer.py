"""Tests for C1 / SC-3 — AI Answer Share-of-Voice (src/sov_analyzer.py).

Covers SC-3.1 (shares sum ~100% per engine, unlisted → other), SC-3.2 (one engine
failing doesn't block others), SC-3.3 (adding a competitor recomputes from the stored
export, no re-probe), SC-3.4 (per-competitor sentiment uses only that competitor's
rows), the data_available guard, the export selection contract, and DB persistence.
"""
import json

import pytest

from src.database import DatabaseManager
from src.sov_analyzer import compute_sov, find_av_export, load_av_export

EXPORT = {
    "schema_version": "1.0", "data_available": True,
    "source_run_ts": "2026-07-22T10:00:00Z", "client_name": "Living Systems",
    "engines": ["gemini", "openai"],
    "brand_mentions": [
        {"engine": "gemini", "brand": "Living Systems", "mention_count": 3, "questions_total": 4, "is_client": True, "source": "gazetteer"},
        {"engine": "gemini", "brand": "Theravive", "mention_count": 1, "questions_total": 4, "is_client": False, "source": "gazetteer"},
        {"engine": "gemini", "brand": "RandomCo", "mention_count": 1, "questions_total": 4, "is_client": False, "source": "gazetteer"},
        {"engine": "openai", "brand": "Theravive", "mention_count": 2, "questions_total": 3, "is_client": False, "source": "gazetteer"},
    ],
    "ai_citations": [
        {"engine": "gemini", "url": "https://theravive.com/x", "domain": "theravive.com", "category": "directory", "brand": "Theravive", "is_client": False, "cite_count": 2},
        {"engine": "gemini", "url": "https://livingsystems.ca/y", "domain": "livingsystems.ca", "category": "practitioner", "brand": "Living Systems", "is_client": True, "cite_count": 1},
        {"engine": "openai", "url": "https://theravive.com/z", "domain": "theravive.com", "category": "directory", "brand": "Theravive", "is_client": False, "cite_count": 1},
    ],
    "answer_sentiment": [
        {"engine": "gemini", "brand": "Living Systems", "polarity": "positive"},
        {"engine": "gemini", "brand": "Theravive", "polarity": "negative"},
        {"engine": "gemini", "brand": "Theravive", "polarity": "neutral"},
    ],
}
COMPETITORS = ["theravive.com"]   # RandomCo is NOT tracked → "other"


# ── SC-3.1 shares sum to ~100% per engine (unlisted → other) ──────────────────

def test_sc31_mention_shares_sum_to_100_per_engine():
    res = compute_sov(EXPORT, COMPETITORS, "2026-07-22")
    for engine in ("gemini", "openai"):
        shares = [r["mention_share"] for r in res["rows"]
                  if r["engine"] == engine and r["entity_type"] == "brand"]
        assert abs(sum(shares) - 100.0) < 0.5
    randomco = next(r for r in res["rows"] if r["entity"] == "RandomCo")
    assert randomco["category"] == "other"          # unlisted, but still in the share base


def test_sc31_citation_shares_and_cited_but_not_gap():
    res = compute_sov(EXPORT, COMPETITORS, "d")
    gem = [r["citation_share"] for r in res["rows"]
           if r["engine"] == "gemini" and r["entity_type"] == "domain"]
    assert abs(sum(gem) - 100.0) < 0.5
    # openai cites theravive but NOT the client → a gap; gemini cites the client → no gap
    assert any(g["engine"] == "openai" and g["domain"] == "theravive.com" for g in res["gaps"])
    assert not any(g["engine"] == "gemini" for g in res["gaps"])


# ── SC-3.2 one engine failing doesn't block others ────────────────────────────

def test_sc32_missing_engine_does_not_block_others():
    export = {**EXPORT, "engines": ["gemini", "perplexity"]}  # perplexity has no rows
    res = compute_sov(export, COMPETITORS, "d")
    engines_present = {r["engine"] for r in res["rows"]}
    assert "gemini" in engines_present       # computed despite perplexity being empty
    assert "perplexity" not in engines_present   # no rows, no crash


# ── SC-3.3 recompute on added competitor, no re-probe ─────────────────────────

def test_sc33_recompute_on_added_competitor_no_reprobe():
    before = compute_sov(EXPORT, [], "d")                 # no competitors → theravive "other"
    after = compute_sov(EXPORT, ["theravive.com"], "d")   # add theravive
    th_before = next(r for r in before["rows"]
                     if r["entity"] == "theravive.com" and r["entity_type"] == "domain")
    th_after = next(r for r in after["rows"]
                    if r["entity"] == "theravive.com" and r["entity_type"] == "domain")
    assert th_before["category"] == "other"
    assert th_after["category"] == "competitor"   # recomputed from the SAME export


# ── SC-3.4 per-competitor sentiment uses only that competitor's rows ──────────

def test_sc34_sentiment_is_scoped_per_competitor():
    res = compute_sov(EXPORT, COMPETITORS, "d")
    ls = next(r for r in res["rows"]
              if r["entity"] == "Living Systems" and r["engine"] == "gemini")
    th = next(r for r in res["rows"] if r["entity"] == "Theravive"
              and r["engine"] == "gemini" and r["entity_type"] == "brand")
    assert ls["avg_sentiment"] == 1.0                  # only LS's positive row
    assert th["avg_sentiment"] == round((-1 + 0) / 2, 3)  # only Theravive's neg + neutral


# ── data_available guard ──────────────────────────────────────────────────────

def test_sov_data_unavailable_when_export_absent():
    assert compute_sov(None, COMPETITORS, "d")["data_available"] is False
    assert compute_sov({"data_available": False}, COMPETITORS, "d")["data_available"] is False


# ── export selection contract (newest data_available by source_run_ts) ────────

def test_find_av_export_prefers_data_available_over_stub(tmp_path):
    (tmp_path / "ai_visibility_export_x_00000000.json").write_text(
        json.dumps({"data_available": False, "source_run_ts": None}))
    real = tmp_path / "ai_visibility_export_x_202601010000.json"
    real.write_text(json.dumps({"data_available": True, "source_run_ts": "2026-01-01T00:00:00Z"}))
    assert find_av_export(str(tmp_path), {}) == str(real)


def test_find_av_export_none_when_absent(tmp_path):
    assert find_av_export(str(tmp_path), {}) is None


# ── DB persistence ────────────────────────────────────────────────────────────

def test_f8_cited_gap_flag_is_single_source():
    """Sweep F8: the persisted `cited_gap` flag is the one source of the gap list — it
    matches `gaps` exactly, so the report can read it instead of re-deriving (no drift)."""
    res = compute_sov(EXPORT, COMPETITORS, "d")
    flagged = {(r["engine"], r["entity"]) for r in res["rows"] if r.get("cited_gap")}
    from_gaps = {(g["engine"], g["domain"]) for g in res["gaps"]}
    assert flagged == from_gaps
    assert ("openai", "theravive.com") in flagged   # openai cites theravive, not the client


def test_mentioned_but_not_cited_competitor_matched_by_brand():
    """Sweep F5: a competitor mentioned but never cited is still classified 'competitor'
    (matched by brand name), not silently dropped into the 'other' bucket."""
    export = {"data_available": True, "engines": ["gemini"], "answer_sentiment": [],
              "brand_mentions": [{"engine": "gemini", "brand": "BetterHelp", "mention_count": 2,
                                  "questions_total": 3, "is_client": False, "source": "gazetteer"}],
              "ai_citations": []}
    res = compute_sov(export, competitor_domains=["betterhelp.com"], snapshot_date="d",
                      competitor_brands=["BetterHelp"])
    bh = next(r for r in res["rows"] if r["entity"] == "BetterHelp")
    assert bh["category"] == "competitor"   # matched by brand name despite no citation


def test_f1_cited_gap_migrates_on_existing_db(tmp_path):
    """Sweep F1 (P8 dirty-state): a DB whose sov_daily predates the cited_gap column (as
    the C1 commit created it) must be ALTER-migrated, so the next run's save_sov + the
    report's `SELECT cited_gap` don't break. Fresh-DB tests miss this."""
    import sqlite3
    dbfile = str(tmp_path / "old.db")
    with sqlite3.connect(dbfile) as conn:   # the pre-cited_gap schema
        conn.execute("""CREATE TABLE sov_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, engine TEXT,
            snapshot_date TEXT, entity TEXT, entity_type TEXT, is_client BOOLEAN,
            category TEXT, mention_share REAL, citation_share REAL, presence_rate REAL,
            avg_sentiment REAL)""")
        conn.commit()
    db = DatabaseManager(dbfile)             # init runs the ALTER migration
    with db._get_connection() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sov_daily)")}
    assert "cited_gap" in cols
    run_id = db.create_run("c.com")
    db.save_sov(run_id, compute_sov(EXPORT, COMPETITORS, "d")["rows"])   # must not raise


def test_save_sov_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "sov.db"))
    run_id = db.create_run("c.com")
    res = compute_sov(EXPORT, COMPETITORS, "2026-07-22")
    db.save_sov(run_id, res["rows"])
    with db._get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM sov_daily WHERE run_id=?", (run_id,)).fetchone()[0]
    assert n == len(res["rows"])
