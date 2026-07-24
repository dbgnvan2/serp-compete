# SC-7-YT — YouTube Share-of-Attention (phase 1 of SC-7)

**Status:** SPEC — awaiting owner approval. **No code until approved** (per `~/.claude/CLAUDE.md`
planning rules). Supersedes the YouTube portion of `compete-spec.md#C5` (Off-Platform
Share-of-Attention Tracker), which remains DEFERRED for all other platforms.

**Spec ID:** `SC-7-YT` (phase 1 of the proposed `SC-7`). Sub-criteria `SC-7-YT.1 … SC-7-YT.13`.
**Companion docs:** `compete-spec.md#C5` (original deferred design), `RECONCILIATION_CHANGES.md`
(why draft names were corrected), `suite_enhancement_spec_SERPCOMPETE_v1.md` (shipped SC-1…SC-8).

---

## 1. Why this is being un-deferred (YouTube only)

C5 was deferred on 2026-07-22 with this reasoning:

> "The blocker is data access, not effort: this is the only feature needing sources beyond the
> three confirmed (SERP/rank, GSC, LLM APIs), and **each platform is a paid/rate-limited
> provider** — low ROI for one nonprofit."

**Half that premise is now disproven for YouTube.** The `ptd` app (Podcast Tracker Dashboard,
`/Volumes/davemini/ProjectsMini1/ptd`) already performs YouTube discovery and transcript
retrieval in production, and the code was inspected directly:

- **No paid provider, no API key, no quota.** Verified: zero references to `googleapis`,
  `googleapiclient`, `YOUTUBE_API_KEY`, or `youtube/v3` anywhere in the app. All access is the
  free `yt-dlp` binary via `subprocess`.
- **Rate limiting is real and remains the only constraint** — HTTP 429 with IP-wide cooldowns
  lasting minutes to hours. `ptd` already absorbs this (`overnight_pipeline.py` retry loop,
  per-call backoff).

**Scope discipline:** only YouTube's blocker dissolved. **TikTok, Instagram, Reddit and podcasts
stay DEFERRED** under the original C5 reasoning — they genuinely require paid providers. Any
proposal to add them is out of scope for SC-7-YT.

---

## 2. Architecture decision — CONSUME an export, do not scrape from serp-compete

**Decided approach:** `ptd` produces a YouTube attention export; serp-compete **consumes** it.
serp-compete itself never calls YouTube.

This mirrors the already-shipped C1/SC-3 pattern exactly (serp-compete consumes serp-discover's
AI-visibility export via `sov_analyzer.find_av_export` / `load_av_export`, degrading honestly with
`data_available: false`). Three concrete reasons:

1. **429 cooldowns must not stall an audit.** Cooldowns run minutes-to-hours. `run_audit()` is a
   batch job the user watches; blocking it on YouTube rate limits is unacceptable. `ptd` already
   has the patient offline runner for this.
2. **serp-compete gains NO new runtime dependency.** No `yt-dlp` binary, no `curl_cffi`, no API
   key. It reads a JSON file — nothing more. (Contrast: porting the fetchers would add all three.)
3. **The ToS question stays contained.** yt-dlp scraping is against YouTube's Terms of Service;
   the official Data API is not. Under this design that exposure lives entirely in `ptd`, which
   the owner already operates for their own research — serp-compete, which is client-facing,
   never scrapes anything. **This is an owner decision to ratify (§10, D1), not an assumption.**

> **Rejected alternative (recorded for traceability, per the C1 precedent):** porting
> `search_youtube` / `fetch_channel_videos` / `get_video_details` / `fetch_transcripts.py` into
> `Serp-compete/src/`. Rejected because it duplicates `ptd`'s most-built part, drags 429 latency
> into `run_audit()`, and adds three runtime deps. Revisit only if `ptd` is retired.

### What `ptd` already provides (inspected, not assumed)

| `ptd` asset | Role in SC-7-YT |
|---|---|
| `fetch_channel_videos(handle_or_url, n)` — scans `/videos` + `/streams` + `/podcasts` | Per-competitor channel harvesting |
| `get_video_details(id)` — full per-video metadata | views / likes / comments / duration |
| `search_youtube(query, n)` — `ytsearch` topic discovery | Topic corpus for mention-SoV |
| `fetch_transcripts.py` — VTT → clean text + timestamped segments | Brand-mention detection |
| `channels` table (`channel_id`, `channel_name`, `handle`, `channel_url`) | Channel identity |

These already meet this repo's standards: every yt-dlp call carries timeout + retry + 429 backoff
(**P5**), and `BLOCKED_MARKERS` separates retryable `error` from terminal `not_available` (**P1** —
the code cites "LEARNINGS P1"). `dedup_rolling` handles YouTube's rolling-caption duplication.
**No quality downgrade is introduced by reusing them.**

---

## 3. Producer/consumer contract (P19 — the highest-risk seam)

The export is a **format contract between two repos**. P19 (producer/consumer drift that fails
silent) is the dominant risk: a `ptd`-side change could make serp-compete parse zero rows and
report success. The contract is therefore versioned, validated, and round-trip tested against a
**real** artifact — never a synthetic ideal-shape fixture.

**File:** `youtube_attention_export_<profile>_<YYYYMMDDHHMM>.json`
**Location:** serp-compete repo root or a path set in `shared_config.json → youtube_attention.export_path`.
**Selection contract:** newest `data_available: true` by `source_run_ts` — identical semantics to
`find_av_export`, and implemented by reusing that logic rather than a second copy (P19/DRY).

```jsonc
{
  "schema_version": "1.0",
  "data_available": true,              // false = an honest stub; consumer skips the feature
  "source_run_ts": "2026-07-23T09:00:00Z",
  "profile": "seo-geo",
  "window_days": 90,                   // the observation window these metrics cover
  "channels": [                        // one row per tracked channel
    { "channel_id": "UC…", "handle": "@example", "channel_url": "https://…",
      "channel_name": "Example Counselling", "subscriber_count": 12500,  // null if unavailable
      "verified": true }
  ],
  "channel_metrics": [                 // aggregate per channel over window_days
    { "channel_id": "UC…", "video_count": 14, "total_views": 82000,
      "avg_views_per_video": 5857.1, "avg_views_per_day": 911.1,
      "engagement_rate": 0.031 }       // (likes+comments)/views; null if unavailable
  ],
  "brand_mentions": [                  // from TRANSCRIPTS (the capability upside)
    { "brand": "Example Counselling", "mention_videos": 6, "mention_count": 11 }
  ],
  "corpus": { "videos_scanned": 210, "videos_with_transcript": 173 }  // coverage, for honesty
}
```

`subscriber_count` is nullable **by design**: it is not currently captured by `ptd`, and whether
`yt-dlp` exposes it was deliberately **not** verified (that needs a live call which would consume
the owner's YouTube rate limit). Producing it is a `ptd`-side task (§9, step 1); the consumer must
work correctly when it is `null` (SC-7-YT.6).

---

## 4. Data model — domain-keyed (correcting the C5 draft)

> **Correction carried forward from `RECONCILIATION_CHANGES.md`.** C5's draft model used
> `attention_source (competitor_id, …)`. **`competitor_id` does not exist in this repo.** Verified:
> `database.py` defines `CREATE TABLE competitors (domain TEXT PRIMARY KEY, avg_da INTEGER, …)`.
> All SC-7-YT tables are keyed by **`domain`**, consistent with `serp_overlap`, `positioning`,
> `sov_daily`, `brand_demand_bench`, and `risk_signal`.

Added to `database.py::_create_tables()` via `CREATE TABLE IF NOT EXISTS`, with any later column
added through the **`ALTER TABLE … ADD COLUMN` migrations block** (the F1/P8 lesson — a column
added only to `CREATE TABLE` never reaches an existing DB).

```
yt_attention_source (domain TEXT, channel_id TEXT, handle TEXT, channel_url TEXT,
                     channel_name TEXT, is_client BOOLEAN, verified BOOLEAN,
                     match_basis TEXT,          -- config_map | handle_match | unmapped
                     PRIMARY KEY (domain, channel_id))

yt_attention_metric (run_id INT, domain TEXT, channel_id TEXT, snapshot_date TEXT,
                     subscriber_count INT, video_count INT, total_views INT,
                     avg_views_per_video REAL, avg_views_per_day REAL,
                     engagement_rate REAL, window_days INT,
                     estimation_basis TEXT, data_available BOOLEAN)

yt_mention_sov     (run_id INT, snapshot_date TEXT, entity TEXT, domain TEXT,
                    is_client BOOLEAN, category TEXT,       -- client | competitor | other
                    mention_videos INT, mention_count INT, mention_share REAL,
                    videos_scanned INT, videos_with_transcript INT, estimation_basis TEXT)

yt_attention_rollup (run_id INT, snapshot_date TEXT, domain TEXT, is_client BOOLEAN,
                     has_presence BOOLEAN, attention_index REAL, coverage_pct REAL,
                     estimation_basis TEXT)
```

---

## 5. Core logic

**5.1 Channel ↔ competitor mapping.** A channel is tied to a competitor domain by an explicit map
in `shared_config.json → youtube_attention.channel_map` (`{"example.com": ["@handle"]}`). Handle
matching is a *suggestion* only. Channels that cannot be mapped are **counted and logged, never
silently dropped** (P2), and `match_basis` records how each link was made. **Unverified channels
are excluded from `attention_index`** (carried from C5's original acceptance criteria).

**5.2 Brand-mention SoV (the upside beyond C5's spec).** Competitor brands are derived with the
existing canonical `brand_utils.derive_brand_name` (config vocab, case-insensitive) — no second
implementation. Mention detection is **word-boundary / brand-term matching, never substring**,
matching the C1 rule ("mention = brand-term/domain match, not substring"). `mention_share` is
computed over all tracked entities per snapshot; untracked brands roll into `other` so shares sum
to ~100% (mirrors SC-3.1).

**5.3 `attention_index`.** A weighted mean over normalized 0–100 sub-scores — subscribers, avg
views, engagement rate, mention share — with weights in config. **A missing component is EXCLUDED
and the weights renormalized; it is never scored as 0.** This is the C2/`compute_authority` rule
and the exact F2/P12 defect fixed on 2026-07-23 — a missing metric must not drag a competitor down.
`coverage_pct` reports the fraction of components that had data (P2: surface what's absent).

**5.4 Honest degradation.** No export → `data_available: false`, no rows written, report section
absent, console line says so — no crash, no fabricated zeros (the C1/C3 convention). Partial data
degrades to a partial index plus `coverage_pct`, never a hard failure (C5's original AC).

**5.5 `estimation_basis` on every row.** Required by compete-spec's cross-cutting rule: competitor
metrics are third-party-observed, not first-party measured, and must say so in every output.

---

## 6. Config (`shared_config.json → youtube_attention`)

All editorial content and thresholds live here, never in Python (rule #9 / P4):

```jsonc
"youtube_attention": {
  "export_path": null,                  // null = search repo root, like sov.export_path
  "channel_map": { "example.com": ["@examplecounselling"] },
  "weights": { "subscribers": 0.30, "avg_views": 0.30, "engagement": 0.20, "mention_share": 0.20 },
  "min_videos_for_index": 3,            // below this → insufficient_data, not a low score
  "window_days": 90,
  "exclude_unverified": true
}
```

---

## 7. Access surface

- **Report section** (`src/reporting.py`): "YouTube Share-of-Attention" — a leaderboard (client
  vs competitors) with subscribers / avg views / engagement / mention share / `attention_index`,
  the client clearly marked (⭐), a `coverage_pct` column, and the caveat that figures are
  third-party-observed estimates over `window_days`, not click-measured.
- **Excel sheet:** `YouTube Attention`.
- Absent-export case renders **no section at all** (not an empty table of zeros).

---

## 8. Acceptance criteria → tests

Every criterion is verified by a named automated test (planning rule: criteria are tests, not
assertions). Tests live in `Serp-compete/tests/test_youtube_attention.py` unless noted.

| ID | Criterion | Test |
|---|---|---|
| **SC-7-YT.1** | Export selection picks the newest `data_available:true` by `source_run_ts`; stubs ignored | `test_sc7yt1_export_selection_prefers_available` |
| **SC-7-YT.2** | No export → `data_available False`, zero rows, no section, no crash | `test_sc7yt2_absent_export_degrades_honestly` |
| **SC-7-YT.3** | Unmappable channels are counted + logged, never silently dropped (P2) | `test_sc7yt3_unmapped_channels_surfaced` |
| **SC-7-YT.4** | **Adversarial (P7):** a brand appearing only as a substring inside an unrelated word must NOT count as a mention | `test_sc7yt4_mention_is_not_substring` |
| **SC-7-YT.5** | Mention shares sum to ~100% per snapshot; untracked → `other` | `test_sc7yt5_mention_shares_sum_to_100` |
| **SC-7-YT.6** | A missing component (e.g. `subscriber_count: null`) is EXCLUDED and weights renormalized — never scored 0 | `test_sc7yt6_missing_component_excluded_not_zero` |
| **SC-7-YT.7** | `coverage_pct` reflects component availability; partial data degrades, never hard-fails | `test_sc7yt7_partial_coverage_reported` |
| **SC-7-YT.8** | The client is always present in the leaderboard, even with no channel | `test_sc7yt8_client_always_present` |
| **SC-7-YT.9** | **P19 round-trip on a REAL `ptd` export** (not a synthetic ideal): parsed counts equal the artifact's; zero-from-non-empty logs a loud warning, not a clean pass | `test_sc7yt9_real_export_roundtrip` |
| **SC-7-YT.10** | **Wired (P21):** `run_comparison_features` calls it inside its own guard; removing the call fails a test | `test_sc7yt10_wired_in_comparison_features` |
| **SC-7-YT.11** | **Dirty-state (P8):** correct on the SECOND run against a DB that already holds prior-run rows | `test_sc7yt11_second_run_ignores_prior_rows` |
| **SC-7-YT.12** | **Migration (P8/F1):** new tables/columns reach an EXISTING DB via `ALTER`, not only `CREATE TABLE` | `test_sc7yt12_migrates_on_existing_db` |
| **SC-7-YT.13** | Every persisted row carries `estimation_basis`; weights/thresholds come from config, no magic numbers (P4) | `test_sc7yt13_estimation_basis_and_config_driven` |

### Criteria that CANNOT be made code-testable (flagged per planning rules)

| Concern | Why untestable | Proposed human review |
|---|---|---|
| **Channel identity** — does this channel really belong to this competitor? | No programmatic ground truth; same-name channels exist | Owner confirms each entry in `channel_map`; `verified:false` entries excluded from the index. Add to `docs/TEST_RUN_CHECKLIST.md` |
| **Mention context** — is "Living Systems" here the practice or a generic phrase? | Requires semantic judgement | Sample-review N flagged mentions on the first real run; tune brand terms. Checklist item |
| **ToS/legal posture** | A policy decision, not a code property | Owner decision D1 (§10), recorded in this spec |
| **Live `ptd`→export behaviour** | Integration-only (real YouTube, real 429s) | Flagged as untested-by-design; exercised by a real run, per the P10 rule against implying coverage with mocks |

---

## 9. Implementation order (dependencies first)

0. **Owner decisions D1–D3 (§10) resolved.** ← blocks everything
1. **`ptd` side — export writer.** New `export_youtube_attention.py` in `ptd`, emitting §3's schema
   from the existing `videos`/`channels`/`transcripts` tables, plus subscriber capture if `yt-dlp`
   exposes it (verify with one live call). Writes a `data_available:false` stub when it has nothing.
   *Blocks SC-7-YT.9 — the real-artifact round-trip test needs a genuine export.*
2. **compete — config block + schema/migration** (§4, §6). → SC-7-YT.12
3. **compete — consumer**: `src/youtube_attention.py` loader reusing the `find_av_export` selection
   logic. → SC-7-YT.1, .2
4. **compete — compute**: mapping, mention SoV, index, coverage. → SC-7-YT.3–.8, .13
5. **compete — persistence** (`save_*` in `database.py`). → SC-7-YT.11
6. **compete — wiring** into `run_comparison_features`, import **inside** its own try guard (the
   P13 pattern established 2026-07-23). → SC-7-YT.10
7. **compete — reporting** section + Excel sheet (§7).
8. **Docs**: `docs/FEATURE_GUIDE.md`, `docs/TEST_RUN_CHECKLIST.md` (incl. the two human-review
   items), `docs/SPEC_COVERAGE_REPORT_v3.md`, and the SC-7 status in `compete-spec.md#C5`.

**Cross-repo sequencing note:** step 1 must land before steps 3–4 can be verified against a real
artifact — the same producer-before-consumer dependency as D5→C1, and the same P19 risk.

---

## 10. Owner decisions required before implementation

| # | Decision | Why it matters |
|---|---|---|
| **D1** | **Ratify the ToS posture:** yt-dlp scraping stays confined to `ptd` (owner's own research tool); serp-compete only reads a JSON export and never scrapes. Alternative: use the official YouTube Data API in `ptd` instead — it has a free daily quota tier that may well cover a handful of competitor channels (**current limit should be checked**, not assumed). | serp-compete is client-facing work |
| **D2** | **Which competitors have YouTube channels?** SC-7-YT is only meaningful if some do. If none of the tracked counselling competitors maintain channels, the mention-SoV arm still works (are *they* discussed?) but the channel-metrics arm will be mostly empty. | Determines whether the feature earns its keep |
| **D3** | **Mention-SoV corpus:** which `ptd` profile/queries define "the niche" whose videos are scanned? (`seo-geo` is the wrong topic — this needs a counselling/therapy profile.) | Without the right corpus, mention share is meaningless |

---

## 11. Risks

- **P19 producer/consumer drift (highest).** Two repos, one JSON contract. Mitigated by
  `schema_version`, the real-artifact round-trip test (SC-7-YT.9), and loud
  zero-from-non-empty warnings.
- **429 / IP cooldown.** Contained in `ptd` by the consume architecture; serp-compete is immune.
- **Small-N noise.** A handful of videos makes engagement rates volatile — `min_videos_for_index`
  yields `insufficient_data` rather than a misleading score (the C2 `emerging`/`insufficient_data`
  precedent).
- **Transcript coverage.** Not every video has captions; `videos_with_transcript` vs
  `videos_scanned` is reported so mention share is read against real coverage (P2/P9).
- **Feature earns its keep (D2).** If no competitor runs a channel, prefer to stop after step 1
  rather than build a section that renders empty forever.

---

## 12. Definition of done

All 13 criteria `done` with the proving test named, per the Completion Standard; the four
untestable concerns carried into `docs/TEST_RUN_CHECKLIST.md`; a `learning-qa` sweep clean;
`docs/spec_coverage`-style status updated; and — per **P21** — a grep-proven caller on the run
path, not merely a module that exists.
