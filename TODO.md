# serp-compete — TODO / Backlog

Running capture list for deferred and in-flight work (the **Capture** step of
Capture → Spec → Plan → Build). Canonical designs live in the `*-spec.md` files; this file
records **decisions and what's next**, newest first. Not user-facing — that's `docs/FEATURE_GUIDE.md`.

---

## SC-7-YT — YouTube Share-of-Attention (phase 1 of SC-7)

**Spec:** [`sc7-yt-spec.md`](sc7-yt-spec.md) · **Origin:** un-defers the YouTube part of `compete-spec.md#C5`.

### Decision (2026-07-23): build the `ptd` export ONLY for now; the serp-compete consumer is ON HOLD pending D2.

- **Why on hold.** D2 — *do the tracked counselling competitors actually run YouTube channels?* — is
  unresolved (owner unsure). If they don't, the **channel-metrics half** of the feature renders empty
  forever, so the serp-compete section (spec §9 steps 2–8) is not worth building yet. The transcript
  **brand-mention** half could stand alone, but shipping half a section on an unknown isn't worth it.
- **Proceeds now (low-regret).** Spec §9 **step 1** only — a new `export_youtube_attention.py` in the
  **`ptd` repo** (`/Volumes/davemini/ProjectsMini1/ptd`), emitting the spec §3 export schema from ptd's
  existing `videos` / `channels` / `transcripts` tables. It is needed **regardless** of D2's outcome,
  touches serp-compete not at all, and must follow ptd's own conventions (stdlib-only, one-DB-per-profile)
  and its own plan/approval step. **NOT yet written** — no code exists for it.
- **Still open — do NOT build the serp-compete side until resolved:**
  - **D2 (gating):** owner checks whether any tracked competitor maintains a YouTube channel.
  - **D1:** ToS posture — keep yt-dlp confined to ptd (serp-compete only reads the JSON export), or move
    ptd to the official YouTube Data API (has a free daily quota — check the current limit, don't assume).
  - **D3:** which ptd profile defines the mention-SoV corpus (needs a counselling/therapy profile, not `seo-geo`).
- **Resume path.** Answer **D2**. **Yes →** build the serp-compete consumer per spec §9 steps 2–8
  (config+schema → loader → compute → persist → wire inside its guard → report). **No →** keep only the
  ptd export; do not build the serp-compete section.

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
