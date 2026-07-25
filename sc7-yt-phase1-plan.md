# SC-7-YT Phase 1 — Implementation Plan (YouTube Presence Check)

**Spec (source of truth):** [`sc7-yt-spec.md`](sc7-yt-spec.md) §3, §5, §6 (P1.1–P1.10), §7 (steps 1–6).
**Status:** PLAN — awaiting owner approval. **No implementation code until approved** (global
planning rules). Phase 2 (ptd transcript dive) is **out of scope** this session.

This plan was written **against the real code** (signatures verified, not assumed). Every
acceptance criterion `P1.x` maps to a specific `file::test_name`. Build is tests-first.

---

## 0. Decisions I need you to confirm (flagged before any code)

### D-A — HTTP library: `requests`, not `urllib` (RECOMMENDATION — please confirm)
The spec §2 and the kickoff say "via `urllib`", **but the real siblings contradict that**:
`Serp-compete/src/api_clients.py` `DataForSEOClient` / `MozClient` **all use `requests`**
(imported at module top; `get_search_volume` is the already-hardened model — `for attempt in
range(3)`, status check, `time.sleep(1.5*(attempt+1))` backoff, `except requests.RequestException`).
`compete-spec.md#C5` itself says "a sanctioned … HTTPS call **like the existing DataForSEO/Moz
clients**."

- **Recommendation: use `requests`.** It is already a declared dependency, it is *literally* how
  the existing clients work, and **P5 (sibling-consistency of hardening)** is cleanest when the new
  call mirrors `get_search_volume`'s idiom. `urllib` would introduce a *second* HTTP idiom that
  contradicts "like the existing clients", for zero benefit (requests is already present).
- The rest of this plan assumes `requests`. **If you want `urllib`, say so and I'll swap the
  transport** — the hardening/retry/quota logic is identical either way.

### D-B — Two new modules, matching the repo's separation of concerns
- `src/youtube_client.py` — the hardened **external-API** surface (`YouTubeDataClient`), sibling to
  `api_clients.py`. **Integration-only against the live API** (flagged untested by design, P10);
  its *hardening/branching logic* is unit-tested with a mocked transport.
- `src/youtube_presence.py` — **pure compute** (`compute_presence`), fully unit-tested, mirroring how
  `sov_analyzer.py` keeps its pure `compute_sov` separate from I/O. Returns the honest-state contract
  `{data_available, rows, stats}` (same shape family as `compute_sov`).

Spec §7 step 2 explicitly allows "`api_clients.py` sibling, **or** `src/youtube_client.py`". I pick
the separate module so the integration-only surface is isolated from the tested pure logic.

### D-C — One row per competitor per run (not one row per candidate)
Spec §3.7 renders **one line per competitor**. So `save_yt_presence` persists **one row per
`(run_id, domain)`**: the single best-matched channel, or the `none_found`/`error` state.
`channel_id` is coerced to `""` when there is no channel so the PK `(run_id, domain, channel_id)`
stays stable, and the save uses `INSERT OR REPLACE` for **within-run idempotency** (P8). Storing
every candidate is unnecessary for Phase 1's report and for seeding `channel_map`.

### D-D — `has_channel` tri-state semantics (per the spec table comment)
`confirmed`/`candidate` → `has_channel = True` (a channel exists; identity certain vs. uncertain).
`none_found` → `False`. `error` → `NULL` (unknown — retryable, **never** written as `False`; P1).

---

## 1. Scope & non-goals

**In scope (Phase 1 only):** per competitor **and the client**, use the official YouTube **Data
API** to determine channel existence + vitals (subscribers / last-upload / recent-activity /
match-confidence), persist it (domain-keyed), and render a "YouTube Presence" report section +
Excel sheet. Ships on its own value (the retired-D2 answer: "who's on YouTube").

**Explicitly NOT in scope:** Phase 2 (ptd transcript dive / mention-SoV / `attention_index`); any
`yt-dlp` or binary dependency; any change to `ptd`; a live API run (key not provisioned — unit
tests use **mocked** Data API JSON; the live path is flagged integration-only, P10).

---

## 2. Files to create / modify (verified signatures)

| File | Change | Spec step |
|---|---|---|
| `shared_config.json` (repo root) | **Add** `youtube_presence` block (§5). Key is a *pointer* (`api_key_env`), never a secret. | 1 |
| `Serp-compete/src/database.py` | **Add** `CREATE TABLE yt_channel_presence`; **add** ALTER migration(s) in the existing migrations block (~L208–227); **add** `save_yt_presence(run_id, rows)`. | 1, 4 |
| `Serp-compete/src/youtube_client.py` | **New.** `YouTubeDataClient` (hardened `requests`), `.available`, `search_channels`, `get_channels`, `get_recent_uploads`; `YouTubeTransientError`. | 2 |
| `Serp-compete/src/youtube_presence.py` | **New.** `compute_presence(...)` pure compute + matching/confidence helpers; honest states; quota accounting. | 3 |
| `Serp-compete/src/comparison_features.py` | **Add** one guarded block in `run_comparison_features` (P13 pattern), after the C6 block. | 5 |
| `Serp-compete/src/reporting.py` | **Add** `df_yt` read + "## YouTube Presence" section + `'YouTube Presence'` Excel sheet in `generate_summary`. | 6 |
| `Serp-compete/tests/test_youtube_presence.py` | **New.** P1.1–P1.10. | all |

**Verified call site (no `main.py` change needed):** `src/main.py:484` already calls
`run_comparison_features(db, run_id, shared_config, client_domain, competitor_keywords, gsc,
dfs_client, PROJECT_ROOT)`. Wiring lives entirely inside that function. `derive_brand_name` is
already imported at the top of `comparison_features.py`.

---

## 3. Data model + migration (P1.9)

New table (domain-keyed; **no `competitor_id`** — `competitors` is `domain TEXT PRIMARY KEY`):

```sql
CREATE TABLE IF NOT EXISTS yt_channel_presence (
    run_id INTEGER NOT NULL, domain TEXT NOT NULL, checked_at TEXT,
    has_channel BOOLEAN,                       -- True | False | NULL (unknown/error)
    channel_id TEXT DEFAULT '', handle TEXT, channel_title TEXT, channel_url TEXT,
    subscriber_count INTEGER, video_count INTEGER,
    last_upload_date TEXT, uploads_recent INTEGER,
    match_confidence TEXT,                     -- high | medium | low
    match_basis TEXT,                          -- domain_in_about | handle | name_exact | none
    check_status TEXT,                         -- confirmed | candidate | none_found | error
    estimation_basis TEXT,
    PRIMARY KEY (run_id, domain, channel_id),
    FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_yt_presence_run ON yt_channel_presence(run_id);
```

**Migration discipline (the F1/P8 lesson).** The *table* is new, so `CREATE TABLE IF NOT EXISTS`
reaches existing DBs (it runs on every `DatabaseManager()` init). To honor P1.9's "**via the
migrations block**" literally *and* guard the real F1 regression (a column added later reaching an
existing DB), I mirror the shipped `cited_gap` precedent (`database.py:225`): the activity column
`uploads_recent` is **also** added via `ALTER TABLE yt_channel_presence ADD COLUMN` in the
migrations block, wrapped in `try/except sqlite3.OperationalError`. `test_p1_9` proves it by
building a DB whose `yt_channel_presence` **predates** that column, re-opening it, and asserting the
column now exists + a save succeeds.

`save_yt_presence` follows the `save_sov` executemany idiom (`INSERT OR REPLACE`, `int(bool(...))`
for booleans, `None`-safe `.get`), coercing `channel_id` to `""` when absent.

---

## 4. Config block (§5) — added to root `shared_config.json`

```jsonc
"youtube_presence": {
  "api_key_env": "YOUTUBE_API_KEY",     // env pointer ONLY — never a secret value
  "channel_map": {},                    // seeded by owner-confirmed Phase-1 hits: {"ex.com":["@ex"]}
  "max_candidates_per_competitor": 3,
  "active_recency_days": 180,           // "active" = uploaded within this window
  "min_subscribers_notable": 100,
  "daily_quota_budget": 5000            // stop + announce when exceeded (P9), never silent
}
```
All thresholds read from here (P4). No literals in Python. No secret in config or code (P1.3).

---

## 5. `youtube_client.py` — hardened Data API surface (P1.4)

- `__init__(self, cfg)` reads `os.getenv(cfg.get("api_key_env","YOUTUBE_API_KEY"))`; `self.available
  = bool(key)`. Absent key ⇒ `available=False` (no crash, no call — feeds P1.3 honest skip).
- Private `_get(endpoint, params)`: `requests.get(BASE+endpoint, params={**params,"key":key},
  timeout=30)`, **retry ×3 with `time.sleep(1.5*(attempt+1))` backoff** (mirrors `get_search_volume`).
  - **Transient (retryable):** HTTP 429, 5xx, or a 403 whose JSON error reason is `quotaExceeded`
    / `rateLimitExceeded` / `backendError`. After retries exhausted ⇒ raise `YouTubeTransientError`.
  - **Terminal:** HTTP 200 with empty `items` ⇒ normal empty result (a real "no channel").
- Public methods (each returns plain dicts/lists; each is one accounted call):
  `search_channels(query, max_results)` (search.list, ~100 units) ·
  `get_channels(id=…|handle=…)` (channels.list part=snippet,statistics,contentDetails, 1 unit) ·
  `get_recent_uploads(uploads_playlist_id, max_results)` (playlistItems.list, 1 unit).
- **Live API = integration-only, flagged untested by design (P10).** Tests mock `requests.get` and
  `time.sleep` to exercise the retry/backoff/transient-vs-terminal branching without network.

## 6. `youtube_presence.py` — pure compute (honest states, matching, quota)

`compute_presence(client, competitor_domains, client_domain, brand_by_domain, cfg, snapshot_date,
client_brand=None) -> {data_available, rows, stats}`

- **Client not available** (no key) ⇒ `{"data_available": False, "rows": [], "stats": {...}}` — the
  `sov` `data_available:false` honest-degradation pattern (P1.3).
- **Per domain (client always included, is_client marked — P1.6):**
  1. **channel_map short-circuit** (§3.2): if `cfg.channel_map[domain]` names a handle/id ⇒
     `get_channels` (1 unit), `match_basis="handle"`, `confidence="high"`, `check_status="confirmed"`
     (owner-confirmed steady state).
  2. else **discover**: `search_channels` (~100) → up to `max_candidates_per_competitor`; `get_channels`
     (+1) for stats + uploads playlist; `get_recent_uploads` (+1) for `last_upload_date` and
     `uploads_recent` (count within `active_recency_days`).
  3. **Matching & confidence (adversarial, P7):** `domain_in_about` = competitor domain appears in the
     channel description/customUrl; `handle` = customUrl/handle match; `name_exact` = normalised
     brand/domain-stem == normalised channel title. **`high` iff (domain_in_about OR handle)** →
     `confirmed`; **`name_exact` only ⇒ `medium` → `candidate`** (owner-confirmable), **never
     auto-`confirmed`**; else `low`. No candidate at all ⇒ `none_found`.
  4. **Transient failure** (`YouTubeTransientError` from any call) ⇒ `check_status="error"`,
     `has_channel=None` (retryable) — **distinct from `none_found`** (P1.1/P1.2 boundary).
- **Quota budget (P9):** track `units_used`; before a competitor's *discovery* cost would exceed
  `daily_quota_budget`, **stop**, mark the remaining domains `check_status="error"`
  (`estimation_basis="quota_budget_skipped"`, retryable — not `none_found`), and record
  `stats={checked, confirmed, candidates, none_found, errors, skipped, units_used}`. The wiring layer
  **announces** it (P9) — never a silent cap.
- Every row carries `estimation_basis` (P4/P1.10): e.g. `channel_map_confirmed`,
  `data_api_discovery`, `none_found`, `transient_error`, `quota_budget_skipped`.

## 7. Wiring — `run_comparison_features` guarded block (P1.7 / P13 / P21)

Appended after the C6 block, self-contained in its **own** `try/except` (so a YouTube failure or an
import failure degrades **only** this feature — P13). Instantiates `YouTubeDataClient(yt_cfg)`; if
`.available`, calls `compute_presence(...)`, and on `data_available` calls
`db.save_yt_presence(run_id, presence["rows"])`, sets `summary["yt_presence_rows"]`, and prints the
**announced** counts line ("checked N, confirmed C, candidates K, none D, errors E, quota units U").
If the key is absent it prints the honest skip line. The client search term for the client row is
`client.brand_names[0]` if present else `client.name` (mirrors the C3 client-brand precedent).

## 8. Reporting — `generate_summary` (P1.3 render / P1.6)

Inside the existing report-body connection block (after the Reputation-Risk section), add
`df_yt = pd.read_sql_query("SELECT domain,is_client,has_channel,handle,channel_title,
subscriber_count,last_upload_date,uploads_recent,match_confidence,check_status FROM
yt_channel_presence WHERE run_id=?", conn, params=(run_id,))`. `if not df_yt.empty:` append
"## YouTube Presence" (client row prefixed ⭐; a note that `candidate` rows await owner confirmation).
Add `if not df_yt.empty: df_yt.to_excel(writer, sheet_name='YouTube Presence', index=False)` in the
ExcelWriter block. Absent key ⇒ no rows ⇒ **section absent** (not a table of zeros).

---

## 9. Acceptance criteria → tests (verbatim IDs; all in `Serp-compete/tests/test_youtube_presence.py`)

| ID | Criterion (from spec §6) | Test | Verifies |
|---|---|---|---|
| **P1.1** | Records `has_channel` + `check_status`; **`none_found` distinct from `error`** — a quota/5xx failure is never written as "no channel" | `test_p1_1_none_found_distinct_from_error` | compute: no-candidates→`none_found`/`False`; transient→`error`/`None`; asserts the two differ |
| **P1.2** | **Adversarial (P7):** same-name-but-unrelated channel is at most `candidate`, never `confirmed`; `high` needs domain-in-about or handle | `test_p1_2_samename_not_autoconfirmed` | name-only match ⇒ `medium`/`candidate`; domain-in-about ⇒ `high`/`confirmed` |
| **P1.3** | API key from env only; absent key ⇒ honest skip (`data_available:false`), no crash, **no secret in config/code** | `test_p1_3_key_from_env_absent_skips` | `monkeypatch.delenv` ⇒ `available=False` + `data_available:False`; config block has `api_key_env` pointer, no key value |
| **P1.4** | Data API client hardened (timeout+retry+backoff); transient (429/5xx/quotaExceeded) vs terminal distinguished | `test_p1_4_api_client_hardened` | mocked `requests.get`: 429→retry→200; `timeout` kwarg asserted; persistent 429/quotaExceeded ⇒ `YouTubeTransientError`; 200+empty ⇒ terminal empty |
| **P1.5** | `daily_quota_budget` stop is **announced**, never a silent cap (P9) | `test_p1_5_quota_budget_surfaced` | tiny budget ⇒ remaining domains `error`/`quota_budget_skipped`; `stats` reports skipped+units; `capsys` sees the announced line |
| **P1.6** | The client is always present in the presence report | `test_p1_6_client_always_present` | client row present with `is_client=True` even when its own channel is `none_found` |
| **P1.7** | **Wired (P21):** `run_comparison_features` calls it **inside its own guard**; removing the call fails a test | `test_p1_7_wired_in_comparison_features` | seed DB + monkeypatched `YouTubeDataClient` (fake JSON) ⇒ `yt_channel_presence` rows > 0; also asserts a forced `youtube_presence` import failure degrades ONLY this feature (others still persist) |
| **P1.8** | **Dirty-state (P8):** a second run against a DB holding prior presence rows is correct (no double-count/stale) | `test_p1_8_second_run_clean` | run 1 rows persist; run 2 scoped to run 2; re-save same run ⇒ count stable (`INSERT OR REPLACE`) |
| **P1.9** | **Migration (P8/F1):** the new table reaches an EXISTING DB via the migrations block, not only `CREATE TABLE` | `test_p1_9_migrates_on_existing_db` | pre-build a DB with `yt_channel_presence` missing `uploads_recent` (+ other tables/rows); re-open ⇒ column present via ALTER; `save_yt_presence` works |
| **P1.10** | Thresholds/weights from config; no magic numbers; every row carries `estimation_basis` | `test_p1_10_config_driven` | `active_recency_days` 1 vs 9999 flips `uploads_recent` classification; every row has non-empty `estimation_basis`; shipped config block has required keys |

**Fix→test priority (P10):** the highest-stakes, most-regression-prone units are the **matching/
confidence adversarial guard (P1.2)** and the **transient-vs-terminal + quota honesty (P1.1/P1.4/
P1.5)** — I write those tests **first**, then wiring (P1.7), migration (P1.9), dirty-state (P1.8),
config (P1.10), client-always (P1.6), key-absent (P1.3).

### Concerns that CANNOT be code-tested (flagged per planning rules → `docs/TEST_RUN_CHECKLIST.md`)
| Concern | Why | Human review |
|---|---|---|
| Channel identity for `candidate` (medium-confidence) hits | No programmatic ground truth; same-name channels exist | Owner ticks/unticks Phase-1 candidates; confirmed ones seed `channel_map`. Checklist item (much lighter than retired D2) |
| Live Data API behaviour (real key, real quota) | Integration-only | Untested by design (P10); a real run exercises it once the key is provisioned. Unit tests use mocked JSON |

---

## 10. Build order (dependencies) — spec §7 steps 1–6

1. **Config block + schema/migration + `save_yt_presence`** (`shared_config.json`, `database.py`).
   → unblocks P1.9, P1.10, P1.8. *(no deps)*
2. **`youtube_client.py`** (hardened transport). → P1.4. *(no deps)*
3. **`youtube_presence.py`** (compute: lookup, matching, honest states, quota). → P1.1, P1.2, P1.5,
   P1.6. *(deps: 2 for the client interface; `derive_brand_name`)*
4. **Persistence tests** against `save_yt_presence`. → P1.8. *(deps: 1)*
5. **Wire into `run_comparison_features`** inside its own guard. → P1.7. *(deps: 1,2,3)*
6. **Report section + Excel sheet.** → P1.3 (render side), P1.6 (render side). *(deps: 1,5)*

**Tests-first within each step** (write the failing test, then the code). Both suites must be green
before finishing:
- core: `cd Serp-compete && PYTHONPATH=. pytest tests/ -q`
- root: `PYTHONPATH=Serp-compete pytest tests/ -q`

## 11. Finish (after code is approved & green) — `csdp`
Verify `client_secret_*.json` is gitignored (confirmed: `.gitignore:8`); stage **explicit paths**
only (never `git add .`); commit via heredoc ending `Co-Authored-By: Claude Opus 4.8
<noreply@anthropic.com>`. `learning-qa` sweep over the diff; fix findings. Update
`docs/FEATURE_GUIDE.md`, `docs/TEST_RUN_CHECKLIST.md` (Phase-1 human-review: confirming
medium-confidence candidates), and mark Phase-1 status in `sc7-yt-spec.md` + `TODO.md`. **Do NOT
stage** the pre-existing do-not-commit files (strategic_briefing_run_*, docs/DATA_PERSISTENCE_MAP_v3,
docs/USER_MANUAL, competitor_handoff_*, docs/DOC_AUDIT_FINDINGS_2026-06-17, docs/strategic_briefing_run_9).

## 12. P1–P22 coverage self-check
P1 transient→retryable (`error`, never `none_found`) ✔ · P2 counts surfaced in `stats`/announce ✔ ·
P4 all thresholds in config ✔ · P5 hardened like `get_search_volume`, transient/terminal split ✔ ·
P7 name-only ⇒ `candidate`, never auto-confirmed ✔ · P8 dirty-state + migration tests ✔ ·
P9 quota stop announced ✔ · P10 live API flagged integration-only; adversarial test written first ✔ ·
P13 own guard ✔ · P21 wiring test fails if caller removed ✔. Secret env-only, gitignore verified ✔.
