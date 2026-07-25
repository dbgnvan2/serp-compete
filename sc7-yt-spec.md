# SC-7-YT — YouTube Competitive Attention (phase 1 of SC-7)

**Status:** SPEC — awaiting approval to plan/build. **No implementation code until approved**
(per `~/.claude/CLAUDE.md` planning rules). Supersedes the YouTube portion of `compete-spec.md#C5`
(Off-Platform Share-of-Attention Tracker); all other platforms there remain DEFERRED.

**Owner decision (2026-07-23):** two-tier design — a cheap **Presence Check** inside serp-compete
via the **official YouTube Data API**, then a heavier **Attention Dive** in `ptd` (yt-dlp), gated on
the check. This **retires D2** (whether competitors run channels): the tool now *discovers* that
instead of asking the owner.

**Spec ID:** `SC-7-YT` (phase 1 of the proposed `SC-7`). Sub-criteria `SC-7-YT.P1.x` (Phase 1)
and `SC-7-YT.P2.x` (Phase 2).
**Companion docs:** `compete-spec.md#C5` (original deferred design), `RECONCILIATION_CHANGES.md`
(why draft names were corrected), `suite_enhancement_spec_SERPCOMPETE_v1.md` (shipped SC-1…SC-8),
`TODO.md` (backlog + resume path).

---

## 1. Why this is being un-deferred (YouTube only)

C5 was deferred on 2026-07-22: *"each platform is a paid/rate-limited provider — low ROI for one
nonprofit."* **Both halves of that are answerable for YouTube:**

- **Paid?** No. The `ptd` app (Podcast Tracker Dashboard, `/Volumes/davemini/ProjectsMini1/ptd`)
  already does YouTube discovery + transcript retrieval with the **free `yt-dlp` binary** — verified:
  zero `googleapis` / `googleapiclient` / `youtube/v3` references in it. And the *check* half (below)
  uses the official Data API's **free daily quota** (10,000 units/day at time of writing — treat as a
  current default to confirm, not a guarantee).
- **Rate-limited?** Only the *scraping* path (yt-dlp) hits HTTP 429 with minutes-to-hours IP
  cooldowns. The Data API is quota-bounded, not cooldown-bounded — a handful of competitor lookups is
  a rounding error against the daily quota.

**Scope discipline:** only YouTube's blocker dissolved. **TikTok, Instagram, Reddit, podcasts stay
DEFERRED** under the original C5 reasoning (real paid providers). Out of scope for SC-7-YT.

---

## 2. Architecture — split the cheap *check* from the heavy *dive*; each gets the right tool

The core decision: **serp-compete never runs the *scraper*, but it may make bounded, sanctioned
*API* calls.** The two jobs want different tools, and the tools' strengths map onto the jobs:

| | **Phase 1 — Presence Check** | **Phase 2 — Attention Dive** |
|---|---|---|
| Question | Does competitor X have a channel? how big/active? | What's said in the niche; who's mentioned? |
| Tool | **YouTube Data API** (HTTPS via `urllib`) | **yt-dlp** (transcripts) |
| Where | **serp-compete** (`src/`), inline in `run_audit` | **`ptd`**, consumed as a JSON export |
| Cost | ~1–102 quota units per competitor; bounded | Heavy; 429 IP-cooldowns (min–hours) |
| ToS | Sanctioned official API | Grey — confined to the owner's research tool |

**Why the Data API can live in serp-compete when yt-dlp cannot** — it neutralises all three reasons
the scraper was kept out:
1. **No IP cooldowns.** Quota, not 429 cooldowns; can't stall `run_audit()`.
2. **No binary dependency.** A plain HTTPS call via `urllib` — exactly how `api_clients.py` already
   talks to DataForSEO / Moz, and `analyze_transcripts`-style LLM calls talk to OpenAI. Only a key is
   added (env-only; §6).
3. **ToS-clean.** The official API is sanctioned; no scraping in client-facing code.

**Why the split is natural, not redundant:** the Data API is good at exactly what the check needs
(existence, subscriber count, upload cadence) and **cannot** readily deliver transcripts; yt-dlp is
the reverse. So Phase 1 (metadata) → Data API, Phase 2 (transcripts) → yt-dlp. They do different
jobs, not two versions of one.

**Phase 2 still CONSUMES a `ptd` export — never scrapes from serp-compete** (the shipped C1/SC-3
pattern: `sov_analyzer.find_av_export` / `load_av_export`, `data_available:false` honest
degradation). This keeps 429 latency out of the audit and confines yt-dlp's ToS exposure to `ptd`.

> **Rejected alternative (recorded for traceability, per the C1 precedent):** porting `ptd`'s yt-dlp
> fetchers (`search_youtube` / `fetch_channel_videos` / `fetch_transcripts.py`) into
> `Serp-compete/src/`. Rejected — duplicates `ptd`'s most-built part, drags 429 latency into
> `run_audit()`, adds a binary+`curl_cffi` dep, and puts scraping in client-facing code. The Data
> API in serp-compete is **not** this — it is a sanctioned metadata call, not the scraper.

### The two phases gate each other

Phase 1 **auto-discovers** which competitors have channels and produces candidate channel IDs.
That output (owner-confirmed for ambiguous cases) **seeds Phase 2's channel list** — so Phase 2
dives only channels worth diving, and the owner never hand-builds a channel map from scratch.
**Phase 1 is self-contained in serp-compete and ships on its own value** ("who in your competitive
set is on YouTube, and how active") even if Phase 2 is never built.

### What `ptd` already provides for Phase 2 (inspected, not assumed)

| `ptd` asset | Role |
|---|---|
| `fetch_channel_videos(handle_or_url, n)` — scans `/videos`+`/streams`+`/podcasts` | Per-channel video harvest |
| `get_video_details(id)` | views / likes / comments / duration |
| `search_youtube(query, n)` | Topic corpus for mention-SoV |
| `fetch_transcripts.py` → clean text + timestamped segments; `dedup_rolling` | Brand-mention detection |

These already meet this repo's bar: every yt-dlp call has timeout+retry+429 backoff (**P5**);
`BLOCKED_MARKERS` separates retryable `error` from terminal `not_available` (**P1**, cited in-code).
No quality downgrade from reuse.

---

## 3. Phase 1 — YouTube Presence Check (serp-compete, Data API)

**Goal:** for each competitor (and the client), determine channel existence and basic vitals, and
report it. This is the D2 answer, produced in-audit.

**3.1 Inputs.** The competitor set is already in scope at audit time — domains + `client_brand_names`
from the ingested handoff / `competitors` table. No new source.

**3.2 Lookup (quota-aware).**
- If `youtube_presence.channel_map` already names a channel/handle for a domain → `channels.list`
  by handle/id (**1 unit** — cheap, deterministic). This is the steady-state path once channels are
  confirmed.
- Else auto-discover: `search.list?type=channel&q=<brand>` (**~100 units**) → top
  `max_candidates_per_competitor`. Then `channels.list` (statistics + uploads playlist, **1 unit**)
  and `playlistItems.list` on the uploads playlist (**1 unit**) for `last_upload_date` and a recent-
  upload count. ~102 units/competitor discovering; ~2 units/competitor once mapped.

**3.3 Matching & confidence (P7 — a same-name channel is NOT a confirmed match).** Score each
candidate: exact/normalised brand↔title match, the competitor's **domain appearing in the channel's
About/links** (strong signal), handle match. Emit `match_confidence` (high/medium/low) and
`match_basis`. **`high` only for domain-in-about or an exact handle match**; a bare name match is at
most `medium` (a `candidate`, owner-confirmable), never auto-`confirmed`. This is the adversarial
guard: "Living Systems" the practice must not be confirmed as "Living Systems" some unrelated vlog.

**3.4 Honest states (P1/P2 — "no channel" ≠ "couldn't check").** `check_status ∈
{confirmed, candidate, none_found, error}`. A quota exhaustion / 5xx / network failure is `error`
(retryable), **never** silently recorded as `none_found`. Counts are logged ("checked N, confirmed
C, candidates K, none D, errors E, quota units used U").

**3.5 Hardening (P5).** The Data API client is hardened exactly like its `api_clients.py` siblings —
timeout + retry + backoff, transient (429/5xx/quotaExceeded) vs terminal distinguished. A
`daily_quota_budget` cap stops and **announces** what it skipped (P9), never silently truncates.

**3.6 Key handling.** The API key is read from env / `.env` only (`youtube_presence.api_key_env`,
default `YOUTUBE_API_KEY`) — **never** committed to config or code (the repo's `client_secret_*`
gitignore discipline). Absent key → Phase 1 skips honestly (`data_available:false`, no rows, section
absent, console says so), never a crash.

**3.7 Output.** A "YouTube Presence" report section + Excel sheet: per competitor — has-channel?,
handle, subscribers, last-upload, recent-activity, confidence; the client marked (⭐). This section
alone answers "who's on YouTube."

### Phase 1 data model (domain-keyed)

```
yt_channel_presence (run_id INT, domain TEXT, checked_at TEXT,
                     has_channel BOOLEAN,          -- true | false | NULL(unknown/error)
                     channel_id TEXT, handle TEXT, channel_title TEXT, channel_url TEXT,
                     subscriber_count INT, video_count INT,
                     last_upload_date TEXT, uploads_recent INT,   -- activity in active_recency_days
                     match_confidence TEXT,        -- high | medium | low
                     match_basis TEXT,             -- domain_in_about | handle | name_exact | none
                     check_status TEXT,            -- confirmed | candidate | none_found | error
                     estimation_basis TEXT,
                     PRIMARY KEY (run_id, domain, channel_id))
```
`competitor_id` is deliberately absent — the real `competitors` table is `domain TEXT PRIMARY KEY`
(verified; the same correction `RECONCILIATION_CHANGES.md` records). New table via
`CREATE TABLE IF NOT EXISTS`; any later column via the `ALTER TABLE … ADD COLUMN` migrations block
(the F1/P8 lesson).

---

## 4. Phase 2 — YouTube Attention Dive (ptd export, consumed; gated on Phase 1)

Runs only for competitors Phase 1 confirmed. Adds the transcript-derived depth the Data API can't
give.

**4.1 Producer/consumer contract (P19 — highest-risk seam).** `ptd` writes
`youtube_attention_export_<profile>_<YYYYMMDDHHMM>.json`; serp-compete consumes it, selecting the
newest `data_available:true` by `source_run_ts` — **reusing** `find_av_export`'s logic, not a second
copy. Versioned + round-trip tested against a **real** artifact (never a synthetic ideal shape).

```jsonc
{
  "schema_version": "1.0", "data_available": true,
  "source_run_ts": "2026-07-23T09:00:00Z", "profile": "counselling", "window_days": 90,
  "channels": [ { "channel_id": "UC…", "handle": "@ex", "channel_name": "Example Counselling",
                  "domain": "example.com" } ],       // domain carried from Phase 1's confirmed map
  "channel_metrics": [ { "channel_id": "UC…", "video_count": 14, "total_views": 82000,
                         "avg_views_per_video": 5857.1, "avg_views_per_day": 911.1,
                         "engagement_rate": 0.031 } ],
  "brand_mentions": [ { "brand": "Example Counselling", "mention_videos": 6, "mention_count": 11 } ],
  "corpus": { "videos_scanned": 210, "videos_with_transcript": 173 }
}
```

**4.2 Brand-mention SoV (the depth beyond the check).** Competitor brands via the canonical
`brand_utils.derive_brand_name` (config vocab, case-insensitive) — no second implementation.
Mention = **word-boundary / brand-term match, never substring** (the C1 rule). `mention_share` over
all tracked entities; untracked → `other` so shares sum ~100% (mirrors SC-3.1).

**4.3 `attention_index`.** Weighted mean of normalised 0–100 sub-scores (subscribers, avg views,
engagement, mention share), weights in config. **A missing component is EXCLUDED and weights
renormalised — never scored 0** (the C2 `compute_authority` rule; the exact F2/P12 defect fixed
2026-07-23). `coverage_pct` reports how many components had data (P2).

**4.4 Honest degradation.** No export → `data_available:false`, no rows, section absent (not a table
of zeros). Partial data → partial index + `coverage_pct`, never a hard failure.

### Phase 2 data model (domain-keyed)

```
yt_attention_metric (run_id INT, domain TEXT, channel_id TEXT, snapshot_date TEXT,
                     subscriber_count INT, video_count INT, total_views INT,
                     avg_views_per_video REAL, avg_views_per_day REAL, engagement_rate REAL,
                     window_days INT, estimation_basis TEXT, data_available BOOLEAN)

yt_mention_sov     (run_id INT, snapshot_date TEXT, entity TEXT, domain TEXT, is_client BOOLEAN,
                    category TEXT,          -- client | competitor | other
                    mention_videos INT, mention_count INT, mention_share REAL,
                    videos_scanned INT, videos_with_transcript INT, estimation_basis TEXT)

yt_attention_rollup (run_id INT, snapshot_date TEXT, domain TEXT, is_client BOOLEAN,
                     has_presence BOOLEAN, attention_index REAL, coverage_pct REAL, estimation_basis TEXT)
```

---

## 5. Config (`shared_config.json`)

All editorial content / thresholds here, never in Python (rule #9 / P4). Secrets in env only.

```jsonc
"youtube_presence": {                    // Phase 1
  "api_key_env": "YOUTUBE_API_KEY",      // key from env/.env — NEVER inline
  "channel_map": { "example.com": ["@examplecounselling"] },  // seeded by confirmed Phase-1 hits
  "max_candidates_per_competitor": 3,
  "active_recency_days": 180,            // "active" = uploaded within this window
  "min_subscribers_notable": 100,
  "daily_quota_budget": 5000             // stop + log when exceeded (P9), never silent
},
"youtube_attention": {                   // Phase 2
  "export_path": null,                   // null = search repo root, like sov.export_path
  "weights": { "subscribers": 0.30, "avg_views": 0.30, "engagement": 0.20, "mention_share": 0.20 },
  "min_videos_for_index": 3,             // below → insufficient_data, not a low score
  "window_days": 90
}
```

---

## 6. Acceptance criteria → tests

Criteria are tests, not assertions. Tests in `Serp-compete/tests/test_youtube_presence.py` (P1) and
`test_youtube_attention.py` (P2). API/export calls are mocked; the live paths are flagged
integration-only (§8), never implied-covered by a mock (P10).

### Phase 1 — Presence Check

| ID | Criterion | Test |
|---|---|---|
| **P1.1** | Per competitor, records `has_channel` + `check_status`; **`none_found` is distinct from `error`** (P1/P2) — a quota/5xx failure is never written as "no channel" | `test_p1_1_none_found_distinct_from_error` |
| **P1.2** | **Adversarial (P7):** a same-name-but-unrelated channel is at most `candidate`, never `confirmed`; `high` confidence requires domain-in-about or handle match | `test_p1_2_samename_not_autoconfirmed` |
| **P1.3** | API key read from env only; absent key → honest skip (`data_available:false`), no crash, **no secret in config/code** | `test_p1_3_key_from_env_absent_skips` |
| **P1.4** | Data API client hardened (timeout+retry+backoff); transient (429/5xx/quotaExceeded) vs terminal distinguished (P5/P1) | `test_p1_4_api_client_hardened` |
| **P1.5** | `daily_quota_budget` stop is **announced** ("checked N, skipped M, units U"), never a silent cap (P9) | `test_p1_5_quota_budget_surfaced` |
| **P1.6** | The client is always present in the presence report | `test_p1_6_client_always_present` |
| **P1.7** | **Wired (P21):** `run_comparison_features` calls it **inside its own guard**; removing the call fails a test | `test_p1_7_wired_in_comparison_features` |
| **P1.8** | **Dirty-state (P8):** a second run against a DB holding prior presence rows is correct (no double-count/stale confusion) | `test_p1_8_second_run_clean` |
| **P1.9** | **Migration (P8/F1):** the new table reaches an EXISTING DB via the migrations block, not only `CREATE TABLE` | `test_p1_9_migrates_on_existing_db` |
| **P1.10** | Thresholds/weights from config; no magic numbers; every row carries `estimation_basis` (P4) | `test_p1_10_config_driven` |

### Phase 2 — Attention Dive (consumed)

| ID | Criterion | Test |
|---|---|---|
| **P2.1** | Export selection picks newest `data_available:true` by `source_run_ts`; stubs ignored (reuses `find_av_export`) | `test_p2_1_export_selection` |
| **P2.2** | No export → `data_available:false`, zero rows, no section, no crash | `test_p2_2_absent_export_degrades` |
| **P2.3** | **Adversarial (P7):** a brand only appearing as a substring of an unrelated word is NOT a mention | `test_p2_3_mention_not_substring` |
| **P2.4** | Mention shares sum ~100% per snapshot; untracked → `other` | `test_p2_4_shares_sum_100` |
| **P2.5** | A missing index component (e.g. `null` engagement) is EXCLUDED and weights renormalised — never scored 0 (F2/P12) | `test_p2_5_missing_component_excluded` |
| **P2.6** | `coverage_pct` reflects availability; partial data degrades, never hard-fails | `test_p2_6_partial_coverage` |
| **P2.7** | **P19 round-trip on a REAL `ptd` export** (not synthetic): parsed counts == artifact's; **zero-from-non-empty is a loud warning**, not a clean pass | `test_p2_7_real_export_roundtrip` |
| **P2.8** | **Dirty-state (P8)** + **migration (P8/F1)** for the Phase-2 tables | `test_p2_8_second_run_and_migration` |
| **P2.9** | **Wired (P21)** inside its own guard; only runs for Phase-1-confirmed channels | `test_p2_9_wired_and_gated` |

### Concerns that CANNOT be code-tested (flagged per planning rules)

| Concern | Why | Human review |
|---|---|---|
| **Channel identity for `candidate` (medium-confidence) hits** | No programmatic ground truth; same-name channels exist | Owner ticks/unticks Phase-1 candidates; confirmed ones seed `channel_map`. `docs/TEST_RUN_CHECKLIST.md` item. **Much lighter than the retired D2** — a short list to confirm, not research from scratch |
| **Mention context** — is "Living Systems" the practice or a generic phrase? | Semantic judgement | Sample-review N mentions on first real run; tune brand terms. Checklist item |
| **Live Data API behaviour (Phase 1)** | Integration-only (real key, real quota) | Untested-by-design; a real run exercises it. Unit tests use mocked API JSON |
| **Live `ptd`→export behaviour (Phase 2)** | Integration-only (real YouTube, real 429s) | Untested-by-design; the round-trip test (P2.7) uses a real *saved* artifact |

---

## 7. Implementation order (Phase 1 ships independently; Phase 2 is gated)

**Prereq (owner):** provision a free YouTube Data API key (a Google Cloud project) into the env /
`.env`. Needed for a *live* Phase-1 run; **not** needed to write code or run the mocked unit tests.

**Phase 1 — serp-compete, self-contained (no cross-repo dependency):**
1. Config block + `yt_channel_presence` schema/migration (§3, §5). → P1.9, P1.10
2. Hardened YouTube Data API client (`api_clients.py` sibling, or `src/youtube_client.py`). → P1.4
3. Presence compute: lookup, matching+confidence, honest states, quota accounting. → P1.1, P1.2, P1.5
4. Persistence (`save_*` in `database.py`). → P1.8
5. Wire into `run_comparison_features` **inside its own guard** (the P13 pattern). → P1.7
6. Report section + Excel sheet ("YouTube Presence"). → P1.3, P1.6
   → **Phase 1 done = the D2 answer + a shippable competitive signal.**

**Phase 2 — ptd export + consumer (gated on Phase-1 confirmations):**
7. `ptd`: `export_youtube_attention.py` — dive **only** Phase-1-confirmed channels; emit §4.1 schema
   from `videos`/`channels`/`transcripts`; `data_available:false` stub when empty. (ptd-repo task;
   follows ptd conventions + its own plan step.) *Blocks P2.7 — the round-trip needs a real export.*
8. compete: consumer (reuse `find_av_export`), mention-SoV, `attention_index`, coverage, persistence,
   wiring (gated), report. → P2.1–P2.9
9. Docs: `docs/FEATURE_GUIDE.md`, `docs/TEST_RUN_CHECKLIST.md` (the human-review items),
   `docs/SPEC_COVERAGE_REPORT_v3.md`, and the SC-7 status in `compete-spec.md#C5` + `TODO.md`.

---

## 8. Owner decisions

| # | Decision | Status |
|---|---|---|
| **D1 — ToS posture** | serp-compete uses **only** the sanctioned Data API (Phase 1); scraping (yt-dlp) stays confined to `ptd` (Phase 2, consumed as an export). | **RESOLVED** by the 2026-07-23 "approach A" decision. Requires provisioning a free Data API key (prereq above). |
| **D2 — do competitors run channels?** | ~~Owner researches which competitors have channels.~~ | **RETIRED** — Phase 1 auto-discovers this. Residual: owner confirms `candidate` (medium-confidence) hits — a short checklist, not research. |
| **D3 — mention-SoV corpus** | Which `ptd` profile defines "the niche" whose videos are scanned for mentions (`seo-geo` is wrong — needs a counselling/therapy profile). | **OPEN, Phase 2 only.** Does not block Phase 1. |

---

## 9. Risks

- **Name→channel false positives (Phase 1).** Mitigated by the confidence tiers (P1.2): `high` needs
  domain-in-about/handle; name-only stays `candidate` for owner confirmation. The check *narrows*
  the identity judgment, it doesn't claim to eliminate it.
- **Quota (Phase 1).** Bounded by `daily_quota_budget` with a surfaced stop (P9); the `channel_map`
  short-circuits search (100→1 unit) once channels are confirmed.
- **P19 producer/consumer drift (Phase 2, highest for that phase).** `schema_version` + real-artifact
  round-trip (P2.7) + loud zero-from-non-empty.
- **429 / IP cooldown.** Confined to `ptd` (Phase 2 consume architecture); serp-compete is immune.
- **Small-N noise (Phase 2).** `min_videos_for_index` → `insufficient_data`, not a misleading score.
- **Feature earns its keep.** Now *measured* by Phase 1 rather than guessed: if Phase 1 finds no
  competitor channels, stop — don't build Phase 2. This is the point of the two-tier split.

---

## 10. Definition of done

Per phase, each criterion `done` with its proving test named (Completion Standard); the untestable
concerns carried into `docs/TEST_RUN_CHECKLIST.md`; a `learning-qa` sweep clean; a **grep-proven
caller on the run path** (P21), not merely a module that exists; and — Phase 2 — the gate on
Phase-1 confirmations verified by test (P2.9). Phase 1 is a valid stopping point: it can be `done`
and shipped without Phase 2.
