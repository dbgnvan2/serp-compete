"""SC-7-YT Phase 1 — YouTube Presence Check.

Acceptance criteria P1.1–P1.10 (spec: sc7-yt-spec.md#6). The live YouTube Data API is
integration-only and flagged untested-by-design (P10): every test here uses MOCKED API
JSON (a fake client or a monkeypatched requests.get) — never a real network call.
"""
import json
import os
import sqlite3
import sys

import pytest

from src.database import DatabaseManager

SHARED_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))


# ---------------------------------------------------------------------------
# P1.8 — Dirty-state / second-run (P8)
# ---------------------------------------------------------------------------

def _presence_row(domain, **kw):
    row = {"domain": domain, "checked_at": "2026-07-24", "has_channel": True,
           "channel_id": "UC_" + domain, "handle": "@" + domain, "channel_title": domain,
           "channel_url": "https://youtube.com/@" + domain, "subscriber_count": 1000,
           "video_count": 20, "last_upload_date": "2026-07-01", "uploads_recent": 3,
           "match_confidence": "high", "match_basis": "domain_in_about",
           "check_status": "confirmed", "estimation_basis": "data_api_discovery"}
    row.update(kw)
    return row


def _count(db, run_id):
    with db._get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM yt_channel_presence WHERE run_id=?",
                            (run_id,)).fetchone()[0]


def test_p1_8_second_run_clean(tmp_path):
    """P8: a second run against a DB holding prior presence rows is correct — run 2 is
    scoped to run 2, run 1 is untouched, and a re-save of the SAME run does not double-count
    (INSERT OR REPLACE keeps it idempotent)."""
    db = DatabaseManager(str(tmp_path / "yt.db"))
    run1 = db.create_run("livingsystems.ca")
    db.save_yt_presence(run1, [_presence_row("comp.com"), _presence_row("livingsystems.ca")])
    assert _count(db, run1) == 2

    # Re-saving the SAME run's rows must not double-count (P8 within-run idempotency).
    db.save_yt_presence(run1, [_presence_row("comp.com"), _presence_row("livingsystems.ca")])
    assert _count(db, run1) == 2, "re-save of same run double-counted — INSERT OR REPLACE lost"

    # A second run is isolated by its own run_id; run 1 stays put.
    run2 = db.create_run("livingsystems.ca")
    db.save_yt_presence(run2, [_presence_row("comp.com", subscriber_count=2000)])
    assert _count(db, run1) == 2 and _count(db, run2) == 1
    with db._get_connection() as conn:
        subs = conn.execute("SELECT subscriber_count FROM yt_channel_presence "
                            "WHERE run_id=? AND domain='comp.com'", (run2,)).fetchone()[0]
    assert subs == 2000  # run 2 reads its own value, not run 1's stale 1000

    # A none_found/error row keeps has_channel honest (False vs NULL, never coerced).
    run3 = db.create_run("livingsystems.ca")
    db.save_yt_presence(run3, [
        _presence_row("none.com", has_channel=False, channel_id="", check_status="none_found",
                      match_confidence="low", match_basis="none", estimation_basis="none_found"),
        _presence_row("err.com", has_channel=None, channel_id="", check_status="error",
                      match_confidence="low", match_basis="none", estimation_basis="transient_error"),
    ])
    with db._get_connection() as conn:
        got = dict(conn.execute("SELECT domain, has_channel FROM yt_channel_presence "
                                "WHERE run_id=?", (run3,)).fetchall())
    assert got["none.com"] == 0        # False → stored 0
    assert got["err.com"] is None      # error → stored NULL (unknown), NOT False

    # Status-flip re-save within the SAME run must not leave a stale duplicate: comp starts
    # as an error (channel_id '') then a retry confirms it (channel_id 'UC…'). Exactly one
    # row for that domain must remain (a bare INSERT OR REPLACE would leave both).
    run4 = db.create_run("livingsystems.ca")
    db.save_yt_presence(run4, [_presence_row("flip.com", has_channel=None, channel_id="",
                                             check_status="error",
                                             estimation_basis="transient_error")])
    db.save_yt_presence(run4, [_presence_row("flip.com", has_channel=True,
                                             channel_id="UC_flip", check_status="confirmed")])
    with db._get_connection() as conn:
        flip = conn.execute("SELECT check_status, channel_id FROM yt_channel_presence "
                            "WHERE run_id=? AND domain='flip.com'", (run4,)).fetchall()
    assert len(flip) == 1                          # no stale '' row left behind
    assert flip[0] == ("confirmed", "UC_flip")     # the re-save won


# ---------------------------------------------------------------------------
# P1.9 — Migration reaches an EXISTING DB via the migrations block (P8/F1)
# ---------------------------------------------------------------------------

def test_p1_9_migrates_on_existing_db(tmp_path):
    """P8/F1: a DB that predates the `uploads_recent` column must have it added via the
    ALTER TABLE migrations block on re-open — not only via CREATE TABLE (which no-ops when
    the table already exists). Simulate the prior schema, then open DatabaseManager."""
    db_path = str(tmp_path / "old.db")
    # A realistic prior-version DB: the runs table + a yt_channel_presence table that has
    # every column EXCEPT uploads_recent, plus a real row (data that must survive).
    conn = sqlite3.connect(db_path)
    conn.executescript('''
        CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, client_domain TEXT,
                           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO runs (client_domain) VALUES ('livingsystems.ca');
        CREATE TABLE yt_channel_presence (
            run_id INTEGER NOT NULL, domain TEXT NOT NULL, checked_at TEXT,
            has_channel BOOLEAN, channel_id TEXT DEFAULT '', handle TEXT,
            channel_title TEXT, channel_url TEXT, subscriber_count INTEGER,
            video_count INTEGER, last_upload_date TEXT,
            match_confidence TEXT, match_basis TEXT, check_status TEXT, estimation_basis TEXT,
            PRIMARY KEY (run_id, domain, channel_id));
        INSERT INTO yt_channel_presence (run_id, domain, channel_id, has_channel, check_status)
            VALUES (1, 'prior.com', 'UC_prior', 1, 'confirmed');
    ''')
    conn.commit()
    conn.close()

    cols_before = {r[1] for r in sqlite3.connect(db_path)
                   .execute("PRAGMA table_info(yt_channel_presence)").fetchall()}
    assert "uploads_recent" not in cols_before  # precondition: the old DB lacks it

    # Opening DatabaseManager runs _create_tables → the migrations block ALTERs the column in.
    db = DatabaseManager(db_path)
    cols_after = {r[1] for r in sqlite3.connect(db_path)
                  .execute("PRAGMA table_info(yt_channel_presence)").fetchall()}
    assert "uploads_recent" in cols_after, "migration did not add uploads_recent to existing DB"

    # Prior data survived, and a save touching the new column now works end-to-end.
    with db._get_connection() as conn2:
        assert conn2.execute("SELECT COUNT(*) FROM yt_channel_presence "
                             "WHERE domain='prior.com'").fetchone()[0] == 1
    db.save_yt_presence(1, [_presence_row("new.com", uploads_recent=5)])
    with db._get_connection() as conn2:
        got = conn2.execute("SELECT uploads_recent FROM yt_channel_presence "
                            "WHERE run_id=1 AND domain='new.com'").fetchone()[0]
    assert got == 5


# ---------------------------------------------------------------------------
# P1.10 (config half) — the shipped config block, no secret in it (also feeds P1.3)
# ---------------------------------------------------------------------------

def test_p1_10_config_block_present_and_secretless():
    """P4/P1.3: shared_config.json ships a youtube_presence block whose thresholds drive the
    feature, and it holds only an env POINTER (api_key_env) — never a literal key/secret."""
    with open(SHARED_CONFIG_PATH) as f:
        cfg = json.load(f)
    yt = cfg.get("youtube_presence")
    assert yt is not None, "youtube_presence config block missing"
    for key in ("api_key_env", "channel_map", "max_candidates_per_competitor",
                "active_recency_days", "min_subscribers_notable", "daily_quota_budget"):
        assert key in yt, f"youtube_presence.{key} missing"
    assert yt["api_key_env"] == "YOUTUBE_API_KEY"          # a NAME, not a value
    assert "api_key" not in yt and "key" not in yt          # no literal secret field
    # The pointer's value must not itself look like a Google API key (AIza… , 39 chars).
    assert not yt["api_key_env"].startswith("AIza")


# ---------------------------------------------------------------------------
# P1.4 — Data API client hardened; transient vs terminal distinguished (P5/P1)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _seq_get(responses, calls):
    """A fake requests.get that yields queued responses and records call kwargs."""
    def _get(url, params=None, timeout=None, **kw):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return responses.pop(0)
    return _get


def test_p1_4_api_client_hardened(monkeypatch):
    import src.youtube_client as yc

    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    sleeps = []
    monkeypatch.setattr(yc.time, "sleep", lambda s: sleeps.append(s))
    client = yc.YouTubeDataClient({"api_key_env": "YOUTUBE_API_KEY"})
    assert client.available is True

    # (a) 429 twice then 200 → retried with backoff, timeout passed, succeeds.
    calls = []
    ok = {"items": [{"id": {"channelId": "UC1"}, "snippet": {"title": "X", "description": ""}}]}
    monkeypatch.setattr(yc.requests, "get", _seq_get(
        [_FakeResp(429, {}), _FakeResp(429, {}), _FakeResp(200, ok)], calls))
    out = client.search_channels("living systems", 3)
    assert out and out[0]["channel_id"] == "UC1"
    assert len(calls) == 3                       # retried past the two 429s
    assert len(sleeps) == 2 and all(s > 0 for s in sleeps)  # backoff between retries
    assert all(c["timeout"] for c in calls)      # every call carried a timeout (P5)
    assert all("key" in c["params"] for c in calls)  # key attached to the request

    # (b) persistent 429 → YouTubeTransientError (retryable), NOT a silent empty.
    monkeypatch.setattr(yc.requests, "get", _seq_get(
        [_FakeResp(429, {}), _FakeResp(429, {}), _FakeResp(429, {})], []))
    with pytest.raises(yc.YouTubeTransientError):
        client.get_channels(channel_id="UC1")

    # (c) 403 quotaExceeded is TRANSIENT (retryable), distinct from a terminal 4xx.
    quota = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    monkeypatch.setattr(yc.requests, "get", _seq_get(
        [_FakeResp(403, quota), _FakeResp(403, quota), _FakeResp(403, quota)], []))
    with pytest.raises(yc.YouTubeTransientError):
        client.search_channels("x", 3)

    # (d) 200 with empty items is TERMINAL "no results" — a normal empty, never an error.
    monkeypatch.setattr(yc.requests, "get", _seq_get([_FakeResp(200, {"items": []})], []))
    assert client.search_channels("nobody", 3) == []


def test_p1_4b_absent_key_makes_client_unavailable(monkeypatch):
    """P1.3 support: no env key → available=False and no network call is attempted."""
    import src.youtube_client as yc
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    def _boom(*a, **k):
        raise AssertionError("no HTTP call may be made without a key")

    monkeypatch.setattr(yc.requests, "get", _boom)
    client = yc.YouTubeDataClient({"api_key_env": "YOUTUBE_API_KEY"})
    assert client.available is False


# ---------------------------------------------------------------------------
# Fake client for the pure-compute tests (no network, no key needed)
# ---------------------------------------------------------------------------

from src.youtube_client import YouTubeTransientError
from src.youtube_presence import compute_presence

CFG = {"max_candidates_per_competitor": 3, "active_recency_days": 180,
       "min_subscribers_notable": 100, "daily_quota_budget": 5000, "channel_map": {}}


class FakeClient:
    """Programmable stand-in for YouTubeDataClient. `by_query` maps a search term to a list
    of candidate dicts; `by_id`/`by_handle` map to a channel dict; `uploads` maps a playlist
    id to ISO date strings. `raise_for` forces a transient error on any domain whose search
    term is listed. Every call increments a per-endpoint counter."""

    def __init__(self, by_query=None, by_id=None, by_handle=None, uploads=None, raise_for=()):
        self.available = True
        self.by_query = by_query or {}
        self.by_id = by_id or {}
        self.by_handle = by_handle or {}
        self.uploads = uploads or {}
        self.raise_for = set(raise_for)
        self.calls = {"search": 0, "channels": 0, "playlist": 0}

    def search_channels(self, query, max_results):
        self.calls["search"] += 1
        if query in self.raise_for:
            raise YouTubeTransientError("forced transient")
        return list(self.by_query.get(query, []))[:max_results]

    def get_channels(self, channel_id=None, handle=None):
        self.calls["channels"] += 1
        if handle is not None:
            return self.by_handle.get(handle.lstrip("@"))
        return self.by_id.get(channel_id)

    def get_recent_uploads(self, uploads_playlist_id, max_results=10):
        self.calls["playlist"] += 1
        return list(self.uploads.get(uploads_playlist_id, []))


def _chan(cid, title, desc="", custom_url="", subs=500, videos=10, uploads_pl=None):
    return {"channel_id": cid, "title": title, "description": desc, "custom_url": custom_url,
            "subscriber_count": subs, "video_count": videos,
            "uploads_playlist_id": uploads_pl or ("UU_" + cid), "hidden_subscriber_count": False}


def _rows_by_domain(result):
    return {r["domain"]: r for r in result["rows"]}


# ---------------------------------------------------------------------------
# P1.1 — none_found is DISTINCT from error (P1/P2)
# ---------------------------------------------------------------------------

def test_p1_1_none_found_distinct_from_error():
    # jericho: search returns nothing → none_found (a real "no channel", has_channel False).
    # err.com: the client raises a transient error → error (has_channel None, retryable).
    client = FakeClient(by_query={"jerichocounselling": []}, raise_for={"errcorp"})
    result = compute_presence(
        client, competitor_domains=["jerichocounselling.com", "errcorp.com"],
        client_domain="livingsystems.ca", brand_by_domain={
            "jerichocounselling.com": "jericho", "errcorp.com": "errcorp",
            "livingsystems.ca": "livingsystems"},
        cfg=CFG, snapshot_date="2026-07-24", client_brand="Living Systems Counselling")
    rows = _rows_by_domain(result)

    none_row = rows["jerichocounselling.com"]
    assert none_row["check_status"] == "none_found"
    assert none_row["has_channel"] is False        # a real negative

    err_row = rows["errcorp.com"]
    assert err_row["check_status"] == "error"
    assert err_row["has_channel"] is None          # unknown — NEVER written as False
    assert err_row["check_status"] != none_row["check_status"]  # the two are distinct


# ---------------------------------------------------------------------------
# P1.2 — Adversarial (P7): same-name channel is at most candidate, never confirmed
# ---------------------------------------------------------------------------

def test_p1_2_samename_not_autoconfirmed():
    # An UNRELATED vlog that merely shares the name "Living Systems" — no domain in About,
    # no handle match. Must be a `candidate` (medium), NEVER auto-`confirmed`.
    unrelated = _chan("UCvlog", "Living Systems", desc="general systems theory videos",
                      custom_url="@systemsvlog", subs=9000)
    client = FakeClient(
        by_query={"Living Systems Counselling": [unrelated]},
        by_id={"UCvlog": unrelated})
    result = compute_presence(
        client, competitor_domains=[], client_domain="livingsystems.ca",
        brand_by_domain={"livingsystems.ca": "livingsystems"}, cfg=CFG,
        snapshot_date="2026-07-24", client_brand="Living Systems Counselling")
    row = _rows_by_domain(result)["livingsystems.ca"]
    assert row["check_status"] == "candidate"
    assert row["match_confidence"] == "medium"
    assert row["match_basis"] == "name_exact"
    assert row["has_channel"] is True              # a channel exists; identity uncertain

    # The SAME name but WITH the domain in the About → high confidence, confirmed.
    real = _chan("UCreal", "Living Systems Counselling",
                 desc="Official channel — livingsystems.ca", custom_url="@lscounselling",
                 subs=300, uploads_pl="UU_real")
    client2 = FakeClient(by_query={"Living Systems Counselling": [real]},
                         by_id={"UCreal": real}, uploads={"UU_real": ["2026-07-01T10:00:00Z"]})
    row2 = _rows_by_domain(compute_presence(
        client2, [], "livingsystems.ca", {"livingsystems.ca": "livingsystems"}, CFG,
        "2026-07-24", client_brand="Living Systems Counselling"))["livingsystems.ca"]
    assert row2["check_status"] == "confirmed"
    assert row2["match_confidence"] == "high"
    assert row2["match_basis"] == "domain_in_about"


def test_p1_2b_domain_substring_not_confirmed():
    """P7: a channel whose About mentions a DIFFERENT domain that merely CONTAINS the
    competitor domain as a substring (`notcomp.com`, `comp.company`) must NOT be confirmed
    via domain_in_about — a bare substring is not a domain match. Name still matches → the
    honest result is `candidate`, not `confirmed`."""
    trap = _chan("UCtrap", "Comp", desc="visit notcomp.com and comp.company today",
                 custom_url="@compfan", subs=4000, uploads_pl="UU_trap")
    client = FakeClient(by_query={"comp": [trap]}, by_id={"UCtrap": trap},
                        uploads={"UU_trap": ["2026-07-10T00:00:00Z"]})
    row = _rows_by_domain(compute_presence(
        client, competitor_domains=["comp.com"], client_domain="livingsystems.ca",
        brand_by_domain={"comp.com": "comp", "livingsystems.ca": "living"}, cfg=CFG,
        snapshot_date="2026-07-24", client_brand="Living Systems"))["comp.com"]
    assert row["match_basis"] != "domain_in_about"   # substring must not count as the domain
    assert row["check_status"] == "candidate"        # name-only → candidate, never confirmed
    assert row["match_confidence"] == "medium"

    # A genuine subdomain form (www.comp.com) in the About IS a real domain match → confirmed.
    real = _chan("UCreal2", "Comp", desc="official — https://www.comp.com/about",
                 custom_url="@comp_official", uploads_pl="UU_r2")
    client2 = FakeClient(by_query={"comp": [real]}, by_id={"UCreal2": real},
                         uploads={"UU_r2": ["2026-07-10T00:00:00Z"]})
    row2 = _rows_by_domain(compute_presence(
        client2, ["comp.com"], "livingsystems.ca",
        {"comp.com": "comp", "livingsystems.ca": "living"}, CFG, "2026-07-24",
        client_brand="Living Systems"))["comp.com"]
    assert row2["check_status"] == "confirmed"
    assert row2["match_basis"] == "domain_in_about"


# ---------------------------------------------------------------------------
# P1.3 — absent key → honest skip (data_available False), no crash
# ---------------------------------------------------------------------------

def test_p1_3_key_from_env_absent_skips():
    class _Unavailable:
        available = False

        def search_channels(self, *a, **k):
            raise AssertionError("must not call the API when unavailable")

    result = compute_presence(_Unavailable(), ["comp.com"], "livingsystems.ca",
                              {"comp.com": "comp", "livingsystems.ca": "living"}, CFG,
                              "2026-07-24")
    assert result["data_available"] is False
    assert result["rows"] == []


# ---------------------------------------------------------------------------
# P1.5 — quota budget stop is ANNOUNCED, never silent (P9)
# ---------------------------------------------------------------------------

def test_p1_5_quota_budget_surfaced(capsys):
    # Budget only affords the client + one competitor (~102 units each). The rest must be
    # SKIPPED as retryable error/quota_budget_skipped, surfaced in stats, never none_found.
    def cand(d):
        return [_chan("UC_" + d, d, desc="x", custom_url="@" + d)]
    client = FakeClient(by_query={"Living Systems": cand("living"),
                                  "compa": cand("compa"), "compb": cand("compb")},
                        by_id={"UC_living": _chan("UC_living", "living"),
                               "UC_compa": _chan("UC_compa", "compa"),
                               "UC_compb": _chan("UC_compb", "compb")})
    cfg = {**CFG, "daily_quota_budget": 150}
    result = compute_presence(
        client, competitor_domains=["compa.com", "compb.com"],
        client_domain="livingsystems.ca",
        brand_by_domain={"compa.com": "compa", "compb.com": "compb",
                         "livingsystems.ca": "living"},
        cfg=cfg, snapshot_date="2026-07-24", client_brand="Living Systems")
    stats = result["stats"]
    assert stats["skipped"] >= 1
    assert stats["units_used"] <= 150               # budget respected
    rows = _rows_by_domain(result)
    skipped_rows = [r for r in result["rows"] if r["estimation_basis"] == "quota_budget_skipped"]
    assert skipped_rows, "no domain was marked quota_budget_skipped"
    for r in skipped_rows:
        assert r["check_status"] == "error"         # retryable, NOT none_found (P1)
        assert r["has_channel"] is None
    # Compute surfaces the budget stop to the caller (stats carry it; the caller announces).
    assert stats.get("budget_hit") is True


# ---------------------------------------------------------------------------
# P1.6 — the client is ALWAYS present in the presence report
# ---------------------------------------------------------------------------

def test_p1_6_client_always_present():
    # The client's own channel is not found — it must STILL appear as a row, is_client True.
    client = FakeClient(by_query={"Living Systems Counselling": []})
    result = compute_presence(
        client, competitor_domains=["comp.com"], client_domain="livingsystems.ca",
        brand_by_domain={"comp.com": "comp", "livingsystems.ca": "livingsystems"},
        cfg=CFG, snapshot_date="2026-07-24", client_brand="Living Systems Counselling")
    rows = _rows_by_domain(result)
    assert "livingsystems.ca" in rows
    assert rows["livingsystems.ca"]["is_client"] is True
    assert rows["livingsystems.ca"]["check_status"] == "none_found"
    # Competitor rows are not is_client.
    assert rows["comp.com"]["is_client"] is False


# ---------------------------------------------------------------------------
# P1.10 (behavioural half) — thresholds are config-driven; every row has estimation_basis
# ---------------------------------------------------------------------------

def test_p1_10_config_driven():
    # A single confirmed channel with one upload ~100 days before the snapshot. Whether it
    # counts as a RECENT upload depends ONLY on active_recency_days from config.
    chan = _chan("UCx", "Comp Counselling", desc="see comp.com", custom_url="@comp",
                 uploads_pl="UU_x")
    uploads = {"UU_x": ["2026-04-15T10:00:00Z"]}  # ~100 days before 2026-07-24

    def run(active_days):
        client = FakeClient(by_query={"compcounselling": [chan]}, by_id={"UCx": chan},
                            uploads=uploads)
        cfg = {**CFG, "active_recency_days": active_days}
        return _rows_by_domain(compute_presence(
            client, ["compcounselling.com"], "livingsystems.ca",
            {"compcounselling.com": "comp", "livingsystems.ca": "living"}, cfg,
            "2026-07-24", client_brand="Living Systems"))["compcounselling.com"]

    narrow = run(1)       # 1-day window → the 100-day-old upload is NOT recent
    wide = run(9999)      # huge window → it IS recent
    assert narrow["uploads_recent"] == 0
    assert wide["uploads_recent"] == 1
    assert narrow["last_upload_date"] == "2026-04-15"   # last-upload date is reported either way

    # Every persisted row carries a non-empty estimation_basis (P4).
    for r in [narrow, wide]:
        assert r["estimation_basis"]


def test_p1_10b_notable_threshold_is_live_config():
    """P4/P21: min_subscribers_notable is a REAL consumer, not dead config — the notable
    count in stats responds to the configured floor."""
    chan = _chan("UCn", "Comp Counselling", desc="see compcounselling.com",
                 custom_url="@x", subs=500, uploads_pl="UU_n")

    def notable_count(threshold):
        client = FakeClient(by_query={"compcounselling": [chan]}, by_id={"UCn": chan},
                            uploads={"UU_n": []})
        cfg = {**CFG, "min_subscribers_notable": threshold}
        return compute_presence(
            client, ["compcounselling.com"], "livingsystems.ca",
            {"compcounselling.com": "comp", "livingsystems.ca": "living"}, cfg,
            "2026-07-24", client_brand="LS")["stats"]["notable"]

    assert notable_count(100) == 1       # 500 subs clears a 100 floor
    assert notable_count(10000) == 0     # ...but not a 10000 floor


# ---------------------------------------------------------------------------
# P1.7 — Wired (P21) inside its own guard; removing the call fails a test
# ---------------------------------------------------------------------------

class _WiredYT:
    """Stands in for YouTubeDataClient in the wiring test: available, and returns a channel
    per candidate whose handle == the query token (→ a confirmed/candidate match)."""

    def __init__(self, cfg=None, **kw):
        self.available = True

    def search_channels(self, query, max_results):
        return [{"channel_id": "UCq::" + query, "title": query, "description": ""}]

    def get_channels(self, channel_id=None, handle=None):
        q = (channel_id.split("::", 1)[-1] if channel_id and "::" in channel_id
             else (handle or channel_id or ""))
        return {"channel_id": channel_id or ("UC_" + q), "title": q, "description": "",
                "custom_url": "@" + q.replace(" ", "").lower(), "subscriber_count": 123,
                "video_count": 4, "uploads_playlist_id": "UU", "hidden_subscriber_count": False}

    def get_recent_uploads(self, uploads_playlist_id, max_results=10):
        return ["2026-07-01T00:00:00Z"]


class _FakeGsc2:
    def get_query_position_map(self):
        return {}


class _FakeDfs2:
    def get_search_volume(self, queries):
        return {}


WIRE_CONFIG = {
    "client": {"domain": "livingsystems.ca", "name": "Living Systems Counselling"},
    "brand": {"name_suffixes": ["counselling", "counseling", "therapy"]},
    "youtube_presence": {"max_candidates_per_competitor": 3, "active_recency_days": 180,
                         "daily_quota_budget": 5000, "channel_map": {}},
}


def test_p1_7_wired_in_comparison_features(tmp_path, monkeypatch):
    """P21: run_comparison_features actually calls compute + save_yt_presence. If the wiring
    block or the save() were removed, no rows persist and this test goes red."""
    import src.youtube_client as yc
    from src.comparison_features import run_comparison_features
    monkeypatch.setattr(yc, "YouTubeDataClient", _WiredYT)

    db = DatabaseManager(str(tmp_path / "wire.db"))
    run_id = db.create_run("livingsystems.ca")
    summary = run_comparison_features(db, run_id, WIRE_CONFIG, "livingsystems.ca",
                                      {"comp.com": {"anxiety"}}, _FakeGsc2(), _FakeDfs2(),
                                      str(tmp_path))
    assert _count(db, run_id) >= 2, "no yt_channel_presence rows — wiring/save missing (P21)"
    assert summary.get("yt_presence_rows", 0) >= 2
    with db._get_connection() as conn:
        statuses = dict(conn.execute("SELECT domain, check_status FROM yt_channel_presence "
                                     "WHERE run_id=?", (run_id,)).fetchall())
    assert "livingsystems.ca" in statuses and "comp.com" in statuses
    assert statuses["comp.com"] == "confirmed"   # handle match on the brand token


def test_p1_7b_guard_isolates_failure(tmp_path, monkeypatch):
    """P13: the YouTube block sits in its OWN guard — forcing its compute import to fail
    degrades only this feature (no rows, no summary key) and never raises to the caller."""
    import src.youtube_client as yc
    from src.comparison_features import run_comparison_features
    monkeypatch.setattr(yc, "YouTubeDataClient", _WiredYT)
    monkeypatch.setitem(sys.modules, "src.youtube_presence", None)  # break the import

    db = DatabaseManager(str(tmp_path / "guard.db"))
    run_id = db.create_run("livingsystems.ca")
    summary = run_comparison_features(db, run_id, WIRE_CONFIG, "livingsystems.ca",
                                      {"comp.com": {"anxiety"}}, _FakeGsc2(), _FakeDfs2(),
                                      str(tmp_path))   # must NOT raise
    assert _count(db, run_id) == 0                 # YouTube degraded to nothing
    assert "yt_presence_rows" not in summary        # never reached its summary write


# ---------------------------------------------------------------------------
# Render layer (P11 — trace all layers): the report section appears when rows exist,
# the client is marked, candidates are flagged; and it is ABSENT when there are no rows
# (P1.3 render side — absent key → no rows → no section, not a table of zeros).
# ---------------------------------------------------------------------------

def test_p1_report_section_renders(tmp_path, monkeypatch):
    from src.reporting import ReportGenerator
    monkeypatch.chdir(tmp_path)   # keep the generated .md/.xlsx out of the repo
    rg = ReportGenerator(str(tmp_path / "rep.db"))

    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_yt_presence(run_id, [
        _presence_row("livingsystems.ca", check_status="confirmed"),
        _presence_row("comp.com", check_status="confirmed", subscriber_count=5000),
        _presence_row("samename.com", has_channel=True, check_status="candidate",
                      match_confidence="medium", match_basis="name_exact",
                      estimation_basis="data_api_discovery"),
        _presence_row("nochan.com", has_channel=False, channel_id="",
                      check_status="none_found", estimation_basis="none_found"),
    ])
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "## YouTube Presence" in content
    assert "⭐ livingsystems.ca (you)" in content        # client marked (P1.6 render side)
    assert "candidate channel" in content                # candidate confirmation note

    # A run with NO presence rows → the section must be ABSENT (P1.3 render side). Seed one
    # competitor metric so the run has other content (an all-empty run trips a pre-existing
    # ExcelWriter "need >=1 sheet" quirk unrelated to this feature — see status report).
    run2 = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/x", "keyword": "anxiety",
          "position": 3, "traffic": 100}], run_id=run2)
    content2 = rg.generate_summary("livingsystems.ca", run_id=run2)
    assert "## YouTube Presence" not in content2
