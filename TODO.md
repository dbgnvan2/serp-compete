# serp-compete — TODO / Backlog

Running capture list for deferred and in-flight work (the **Capture** step of
Capture → Spec → Plan → Build). Canonical designs live in the `*-spec.md` files; this file
records **decisions and what's next**, newest first. Not user-facing — that's `docs/FEATURE_GUIDE.md`.

---

## SC-7-YT — YouTube Competitive Attention (phase 1 of SC-7)

**Spec:** [`sc7-yt-spec.md`](sc7-yt-spec.md) · **Origin:** un-defers the YouTube part of `compete-spec.md#C5`.

### Decision (2026-07-23): two-tier design — a cheap Presence Check in serp-compete, then a heavier Dive in ptd. D2 RETIRED (auto-discovered).

The tool now *discovers* whether competitors have channels instead of asking the owner — so the old
"on hold pending D2" gate is gone. Phase 1 is **built first** (self-contained in serp-compete).

- **Phase 1 — YouTube Presence Check (serp-compete, official YouTube Data API). ✅ BUILT & SHIPPED
  (2026-07-24).** Per competitor: has a channel? subscribers, last-upload, activity, match
  confidence. Cheap (quota-bounded, not 429-cooldown-bound), ToS-clean, no yt-dlp/binary dep — an
  HTTPS `requests` call like the existing DataForSEO/Moz clients + an env-only API key.
  Self-contained and shippable on its own ("who in the competitive set is on YouTube") — the D2
  answer. Criteria P1.1–P1.10 all `done` (`Serp-compete/tests/test_youtube_presence.py`, 15 tests;
  `src/youtube_client.py` + `src/youtube_presence.py`, `yt_channel_presence` table, wired in
  `run_comparison_features`, "YouTube Presence" report section + Excel sheet). Plan of record:
  [`sc7-yt-phase1-plan.md`](sc7-yt-phase1-plan.md).
  **Residual owner action:** provision a free `YOUTUBE_API_KEY` into env/`.env` for the first *live*
  run (integration-only; unit tests use mocked API JSON). Without a key the feature skips honestly.
- **Phase 2 — YouTube Attention Dive (ptd export, consumed; gated on Phase 1).** The heavy
  transcript + brand-mention-SoV work, in `ptd` via yt-dlp, consumed by serp-compete like the C1
  AV export. Runs **only** for channels Phase 1 confirmed. → spec §4, build order §7 Phase-2 steps 7–9.
- **Owner decisions:**
  - **D1 (ToS) — RESOLVED** by "approach A": serp-compete uses only the sanctioned Data API; scraping
    (yt-dlp) stays confined to ptd. **Prereq:** provision a free YouTube Data API key into env/`.env`
    (needed for a *live* Phase-1 run, not for code or mocked tests).
  - **D2 — RETIRED.** Auto-discovered by Phase 1. Residual: owner confirms `candidate`
    (medium-confidence) channel hits — a short checklist, not research from scratch.
  - **D3 (mention corpus) — OPEN, Phase 2 only.** Needs a counselling/therapy `ptd` profile
    (`seo-geo` is the wrong topic). Does **not** block Phase 1.
- **Resume path.** Phase 1 is done. Next: provision the free `YOUTUBE_API_KEY` and do one *live*
  run; confirm any `candidate` channels (see `docs/TEST_RUN_CHECKLIST.md` §6) and seed
  `youtube_presence.channel_map`. **Then decide Phase 2 on the evidence:** if the live run finds
  competitor channels worth diving, build Phase 2 (ptd export + consumer, spec §4 / §7 steps 7–9);
  if it finds none, stop — Phase 1 is a valid endpoint.

---

## SC-7 — other platforms · still DEFERRED

TikTok, Instagram, Reddit, and podcasts remain deferred per `compete-spec.md#C5`: their data sources
really are paid/rate-limited providers. Only **YouTube's** "paid provider" blocker dissolved (ptd already
scrapes it for free via the `yt-dlp` binary — no API key, no quota). Revisit the rest only if the owner
wants cross-platform tracking **and** a provider budget is approved.

---

## Pre-existing "not yet built" (from the shipped suite)

- **Cron/launchd automation** — a scheduled weekly audit run. Today it's manual / dashboard-triggered.
  (Mirrors the same gap noted in ptd's `CLAUDE.md`.)
- **D2 branded export (serp-discover)** — would supply the GSC-anchored own-brand figure that C3's
  Branded-Demand benchmark currently leaves `NULL` (see `docs/TEST_RUN_CHECKLIST.md` §7).
- **D4 commodity export (serp-discover)** — would upgrade C4's local "commodity" overlap proxy to a real
  signal (`docs/TEST_RUN_CHECKLIST.md` §7).

## SC-8.4 anchor-text spam — deferred and adjacent items (2026-08-28)

Raised by the pre-push sweeps and deliberately **not** fixed in that batch, with the reason.

**Deferred (sweep findings, below the fix bar):**
- **Coverage counts are not persisted.** `anchor_coverage` reaches the console and the report,
  but no `risk_signal`-adjacent column stores it, so a past run's coverage cannot be recovered.
  Needs a schema change; the report caveat covers the case that matters now.
- **Stale cached anchors are stamped with today's date.** The Moz block is read from a second,
  schema-unvalidated read of the handoff, `moz.generated_at` is discarded, and a signal is added
  for any domain in the block whether or not it is in this run's target set. Producer caches with
  a 30-day TTL, so weeks-old anchor data can be attributed to a domain no longer ranking. Fix:
  pass the already-loaded handoff, carry `generated_at` into the evidence, and intersect with the
  run's competitor set.
- **Anchor text is interpolated into markdown unescaped** (`reporting.py`, pre-existing for the
  neighbouring rows). Third-party-authored text; worth `json.dumps`-escaping or code-fencing.
- **An anchor matching a term but below `min_domains` is dropped with no counter** — the same
  silent-drop class the `unmeasured` counter was added for. Unreachable at the default of 1, live
  if anyone raises it.
- **`anchor_coverage` labels every domain in `moz.domains` a "competitor".** True today because
  Tool 1 excludes the client, but that is an assumption about the producer, not a fact from the data.

**Known gap — the own-site path is unreachable:**
- Tool 1 excludes the client's own domain from `moz.domains`, so client anchors never arrive and
  the own-site branch of the detector — the case that would surface negative SEO *against the
  client* — cannot fire. The radar's `is_own_site` tagging is correct and tested for when that
  changes. Fixing it means a producer-side change in serp-discover (add the client to the block,
  or a `moz.client.anchor_texts` entry) plus another handoff-schema sync.

**Adjacent, pre-existing, not caused by this work:**
- **`DEFAULT_COMMERCIAL_TERMS` has drifted from `shared_config.json`** exactly as the anchor term
  list had (`"insurance"` and `"buy"` are in code, absent from config). The new parity test covers
  only the anchor keys; extend it to the commercial terms and resync.
- **The two test suites cannot run in one pytest invocation.** `pytest tests Serp-compete/tests`
  fails collection with duplicate module basenames, on unmodified `main` as well. They must be run
  separately.
- **`Serp-compete/tests/` cannot be fully collected in the current venv** — `pandas`, `spacy` and
  `requests_mock` are missing, giving 7 pre-existing collection errors. Individual files run.
  `reporting.py` is unimportable without pandas, which is why the anchor caveat logic lives behind
  a pandas-free seam in `risk_radar.py`.
