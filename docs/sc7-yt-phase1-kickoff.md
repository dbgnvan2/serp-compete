# SC-7-YT Phase 1 — next-session kickoff prompt

Paste the block below into a **fresh** session to start building **SC-7-YT Phase 1
(YouTube Presence Check)**. It is self-contained (points at the approved `sc7-yt-spec.md`
as source of truth), pins this session's hard-won constraints, and honors the planning
rules (plan → approval → code). Approved by the owner on 2026-07-23.

> Companion docs the new session will also have: `sc7-yt-spec.md` (the spec), `TODO.md`
> (backlog + resume path), `compete-spec.md#C5` (origin), and the auto-loaded memory index.

---

```text
Build SC-7-YT Phase 1 — YouTube Presence Check — in serp-compete
(/Users/davemini2/ProjectsLocal/serp-compete). The spec and approach are approved.

START BY READING (source of truth):
- sc7-yt-spec.md — focus on §3 (Phase 1), §5 (config), §6 Phase-1 criteria P1.1–P1.10,
  §7 Phase-1 build order (steps 1–6). Also skim compete-spec.md#C5 and
  RECONCILIATION_CHANGES.md for background.
- CLAUDE.md (this repo) and ~/.claude/standards/learnings.md (P1–P22) per the repo rules.

SCOPE — Phase 1 ONLY:
- Phase 1 is the "YouTube Presence Check": per competitor (and the client), use the
  official YouTube Data API to determine channel existence + subscribers / last-upload /
  activity / match-confidence, persist it, and render a "YouTube Presence" report section.
  It auto-answers "which competitors are on YouTube" and ships on its own.
- Do NOT build Phase 2 (the ptd transcript dive) — it's gated on Phase 1's results and
  lives in the separate ptd repo. Do NOT touch ptd this session.
- Do NOT add yt-dlp or any binary to serp-compete. Phase 1 is a sanctioned HTTPS Data API
  call via urllib, like the existing DataForSEO/Moz clients in src/api_clients.py.

KEY IS NOT PROVISIONED YET:
- The YouTube Data API key is env-only (YOUTUBE_API_KEY, per youtube_presence.api_key_env)
  and does NOT exist yet. Build and unit-test against MOCKED Data API JSON. Flag the live
  API path as integration-only — never imply coverage with a mock (P10). A live run is
  deferred until the owner provisions a free key.

WHAT TO DO (follow the global planning rules — plan before code):
1. FIRST produce a Phase-1 implementation plan: map each criterion P1.1–P1.10 to the exact
   test (file::name) that verifies it; list the precise files/functions to create or modify
   (config block in shared_config.json; yt_channel_presence table + migration in
   src/database.py; a hardened Data API client; a presence-compute module; save_* in
   database.py; wiring into src/comparison_features.py::run_comparison_features INSIDE its
   own try-guard; a report section in src/reporting.py); give the build order + deps. Verify
   all of this against the REAL code — don't assume signatures. Commit the plan and STOP for
   my approval before writing any implementation code.
2. After approval, build tests-first.

HARD CONSTRAINTS (repo + global standards):
- Domain-keyed tables: competitors is `domain TEXT PRIMARY KEY` — there is NO competitor_id.
- New columns must reach EXISTING DBs via the `ALTER TABLE … ADD COLUMN` migrations block in
  database.py, not only CREATE TABLE (the F1/P8 lesson).
- Harden the Data API call: timeout + retry + backoff; distinguish transient
  (429/5xx/quotaExceeded → retryable "error") from terminal (no channel → "none_found")
  (P5/P1). A same-name channel is at most "candidate", never auto-"confirmed" — "high"
  confidence requires domain-in-About or a handle match (P7). Any quota-budget stop must be
  announced, never silent (P9). The API key comes from env only, never committed.
- Wire the feature INSIDE its own guard in run_comparison_features (P13), with a test that
  fails if the caller is removed (P21).
- Both suites must be green before finishing:
  core: `cd Serp-compete && PYTHONPATH=. pytest tests/ -q`
  root: `PYTHONPATH=Serp-compete pytest tests/ -q`

FINISH with the csdp skill (commit → learning-qa sweep → docs → push):
- Verify client_secret_*.json is gitignored before any commit; never `git add .` — stage
  explicit paths; commit via heredoc ending with:
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
- Update docs/FEATURE_GUIDE.md, docs/TEST_RUN_CHECKLIST.md (Phase-1 human-review items:
  confirming medium-confidence candidate channels), and mark Phase-1 status in
  sc7-yt-spec.md + TODO.md.
- Do NOT stage the pre-existing do-not-commit files (strategic_briefing_run_*,
  docs/DATA_PERSISTENCE_MAP_v3.md, docs/USER_MANUAL.md, competitor_handoff_*,
  docs/DOC_AUDIT_FINDINGS_2026-06-17.md, docs/strategic_briefing_run_9.md).

First action: read sc7-yt-spec.md and produce the Phase-1 implementation plan for my approval.
```
