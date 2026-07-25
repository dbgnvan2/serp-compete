# serp-compete — TODO / Backlog

Running capture list for deferred and in-flight work (the **Capture** step of
Capture → Spec → Plan → Build). Canonical designs live in the `*-spec.md` files; this file
records **decisions and what's next**, newest first. Not user-facing — that's `docs/FEATURE_GUIDE.md`.

---

## SC-7-YT — YouTube Competitive Attention (phase 1 of SC-7)

**Spec:** [`sc7-yt-spec.md`](sc7-yt-spec.md) · **Origin:** un-defers the YouTube part of `compete-spec.md#C5`.

### Decision (2026-07-23): two-tier design — a cheap Presence Check in serp-compete, then a heavier Dive in ptd. D2 RETIRED (auto-discovered).

The tool now *discovers* whether competitors have channels instead of asking the owner — so the old
"on hold pending D2" gate is gone. Build **Phase 1 first** (self-contained in serp-compete).

- **Phase 1 — YouTube Presence Check (serp-compete, official YouTube Data API).** Per competitor:
  has a channel? subscribers, last-upload, activity, match confidence. Cheap (quota-bounded, not
  429-cooldown-bound), ToS-clean, no yt-dlp/binary dep — just an HTTPS call like the existing
  DataForSEO/Moz clients + an env-only API key. **Self-contained, no cross-repo dependency, and
  shippable on its own** ("who in the competitive set is on YouTube"). This IS the D2 answer.
  → spec §3, build order §7 Phase-1 steps 1–6. **Not yet built** (planning; awaiting build approval).
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
- **Resume path.** Approve building Phase 1 → implement spec §7 Phase-1 steps 1–6 (config+schema →
  hardened Data API client → presence compute → persist → wire inside its guard → report). Then, if
  Phase 1 finds competitor channels worth diving, do Phase 2 (ptd export + consumer). If it finds
  none, stop — Phase 1 is a valid endpoint.

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
