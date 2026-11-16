# Test-Run Review Checklist

What to check when you do a **real end-to-end audit run** — the things unit tests can't
cover (live APIs, the assembled report, and the judgement calls). Tick as you go.

Run: `cd Serp-compete && PYTHONPATH=. python3 src/main.py [--handoff <path>]`
(or `./run_audit.sh`, which passes the flag for you).
Outputs: `strategic_briefing_run_N.md` + `audit_results_run_N.xlsx`, in
`orchestrator.reports_dir` when that is set, else the working directory.

---

## 1. Before the run
- [ ] **GSC OAuth valid** — the pre-flight check passes (it hard-fails the CLI otherwise).
- [ ] **DataForSEO + Moz creds** set in `.env` (`DATAFORSEO_LOGIN/PASSWORD`, `MOZ_TOKEN`).
- [ ] **AV export present for C1 (optional):** an `ai_visibility_export_*.json` sits in the
  repo root or `../serp-discover/output/`. If absent, AI Share-of-Voice will *skip* (expected,
  not an error) — to test it, run serp-discover's `export_ai_visibility.py` first.

## 1b. Moz — CONFIRM THE ENDPOINT AND THE RESPONSE KEY (C-C-04, still open)
- [ ] Watch the per-domain line `Moz returned N metrics for M URL(s).` **N must not be 0
  while M is non-zero.** 0-of-M on every domain means the response shape or the endpoint
  is not what this tool assumes, and every Page Authority will be NULL (unknown) — the
  report will say so under *Run coverage* rather than reporting authority 0.
- [ ] Why this needs a live run: Moz's url-metrics objects identify the target as `page`
  (scheme-less), not `url`, and serp-discover has already migrated to JSON-RPC
  `api.moz.com/jsonrpc` while this tool still calls `api.moz.com/v2/url_metrics`.
  `api_clients.page_authority_map` accepts either key and matches scheme-insensitively,
  but only a real call can confirm which endpoint answers and in what shape. Record the
  answer here, then align the client with serp-discover's.
- [ ] If the call fails outright, expect `⚠️ Moz metrics failed: … — Page Authority is
  UNKNOWN for <domain> this run (stored NULL, not 0)` and no `competitors` row for that
  domain. A *Fragile Magnet* alert must NOT appear for it.

## 2. Console output — watch the coverage lines
- [ ] `🎯 Audit universe: N keyword(s) handed over by Tool 1 across M target URL(s)` — the
  audit works from the handoff (C-M-01). N of 0 means the handoff was empty.
- [ ] `🎯 Keyword universe: handoff targets N (…); enrichment keywords kept N, dropped N
  brand-token + N off-topic` — a large off-topic drop count is the fix working, not an
  error.
- [ ] `📋 Run coverage: audited N of M handoff domain(s); … Page Authority measured for N
  of M audited URL(s)` — compare with the *Run coverage* block in the briefing; they
  should agree.
- [ ] `📊 Enrichment coverage (fresh / carried-forward / cache-hit-no-prior / failed)` — a
  non-zero **failed** count means a systematic EEAT/GEO/cluster problem, investigate.
- [ ] `🗺️ SERP overlap: N keywords classified …`
- [ ] `🧭 Positioning: <quadrant counts>`
- [ ] `📣 AI Share-of-Voice: …`  **or**  `ℹ️ … no export found — skipped`
- [ ] `💷 Branded demand: N brands benchmarked.`
- [ ] `🚨 Reputation risk: N signals (M own-site).` — and, when it appears,
  `Visibility cliff: not measured for N of M domain(s) …`, which is the expected answer
  while a run samples fewer than `risk_signals.cliff_min_sample` keywords per domain.
- [ ] `▶️ YouTube presence: checked N, confirmed C, candidates K, none D, errors E, skipped S,
  quota units U`  **or**  `ℹ️ … no API key in env — skipped`. If it shows `⚠️ quota budget hit`,
  the run stopped early on purpose (the skipped domains are retryable `error`, not "no channel").
- [ ] **Any `⚠️ … skipped` line = that feature errored.** Should be rare now — investigate the
  message (an import/signature/data problem hides here rather than crashing the audit).

## 2b. Report header and coverage (C-C-16, C-M-20)
- [ ] **`**Handoff:**` in the header names the file you selected** — not "not recorded",
  and not a different timestamp. This is the check that the GUI's selection took effect.
- [ ] **Run coverage** in the Executive Summary: audited N of M handoff domains, the
  skipped ones with reasons, any blocked (429) or cache-served domains, and "Page
  Authority measured for N of M audited URL(s)". Compare with the console's
  `📋 Run coverage` line.
- [ ] Each long section that was capped says "Showing the first N of M" — and the Excel
  sheet for it has **all M rows** (C-C-07). Spot-check one: *GEO Extractability*.

## 0. Before a live run — read a rendered briefing for free

```bash
python3 tools/render_sample_briefing.py full -o sample_briefings
```

Renders a complete briefing from fabricated data: no API keys, no GSC property,
no Moz token, no handoff. **The numbers are invented — read the wording, the
caveats and the N-of-M lines, not the figures.** `--list` describes the five
scenarios. Two are worth knowing about: **`deep`** uses the real
`SemanticAuditor`, `GeoProfiler`, `EEATScorer` and `ClusterDetector` over
fabricated HTML, so the EEAT, Extractability and Cluster sections actually
render — the other scenarios mock those three away, which is why their tables
had never been seen. **`total-outage`** has every provider down, so nothing in
the briefing may read as a clean bill of health.

This is not §4 of the review protocol (which diffs a real regenerated briefing
against the previous one, and needs the artifacts only a developer machine
has). It is the cheap version, and in one evening it caught `nan` printed where
a value had been deliberately withheld, a timestamp printed among the failure
counts, `–` in the owner's report, and two caveats describing behaviour the
code no longer had. Run it after any change to `reporting.py`,
`comparison_features.py` or a caveat string, and skim the output.

## 2c. Handoff contract (chunk X) — the cross-tool checks
- [ ] **One site, one competitor.** If the handoff carries both `www.x.com` and `x.com`
  for one site (grep the targets), the briefing must list that domain **once** and the
  console's `📋 Run coverage` must count it as one handoff domain. Two rows for one site
  means the canonical grouping regressed.
- [ ] **The page-relative rank warning is present** while serp-discover's chunk D1 is
  unshipped: the coverage block should carry *"Handoff ranks are page-relative"* naming the
  schema version. If D1 **has** shipped, the warning must be **gone** — and if it is still
  there, add the new version to `handoff.absolute_rank_versions` rather than editing code.
- [ ] **AI Share-of-Voice names any unmeasured engine** ("Not measured this run: …") rather
  than showing it at 0%. Cross-check the console's `Not measured (0 answers in the export)`
  line. An engine that was asked and found nothing should still appear in the shares.
- [ ] **Anchor coverage distinguishes cached errors.** If the caveat reports errored
  domains, check for the follow-on clause saying how many came from Tool 1's cache. All of
  them cached means one old outage, not a provider problem to chase today.
- [ ] **The GSC section states its pull** — "last N days, country `can`, all devices". If
  you are comparing a figure with a serp-discover report, confirm that report states the
  same window and filter; they are otherwise not comparable.

## 3. Report sections — each new section renders, numbers look sane, caveat present
- [ ] **SERP Overlap & Differentiation Gap** — cell distribution + "Volume by cell" + the two
  action queues (exclusive-competitor, shared-commodity). If GSC was unavailable this run, look
  for the **⚠️ "self_unknown"** caveat (it must NOT claim you're absent everywhere).
- [ ] **Barbell Positioning** — **you are plotted (⭐)**; quadrant distribution present; the
  "avg PA > 50 filtered upstream" note is there (so an empty `authoritative` quadrant reads right).
- [ ] **Competitor Feasibility** — ✅/❌ per competitor (needs competitor DA — see §6).
- [ ] **Competitive AI Share-of-Voice** (if an export was consumed) — per-engine **mention
  shares sum to ~100%**; **you appear** in the leaderboards; the "cited but you're not" list
  looks right; sentiment is per-competitor.
- [ ] **Branded-Demand Benchmark** — **you (⭐) are identifiable**; competitor figures are
  labelled *volume-estimated*; if DataForSEO returned nothing, the **⚠️ "search-volume source
  returned nothing"** caveat shows (NOT a table of zeros presented as real demand).
- [ ] **Reputation-Risk Radar** — **own-site warnings are a separate block** from competitor
  signals; the **"pattern detections, not confirmed Google penalties"** label is present.
- [ ] **YouTube Presence** (if a `YOUTUBE_API_KEY` is set) — **you appear (⭐)**; per-competitor
  has-channel / handle / subscribers / last-upload / confidence / status; the `confirmed` vs
  `candidate` vs `none_found` vs `error` legend reads right; any `candidate` rows carry the
  **"confirm identity before trusting"** note.

## 4. Excel workbook — sheets present
- [ ] `SERP Overlap`, `Feasibility`, `Positioning`, `AI Share-of-Voice`, `Branded Demand`,
  `Reputation Risk`, `YouTube Presence` (alongside the earlier `Competitor Summary` / `Traffic
  Magnets` / `EEAT Scores` / `Cluster Analysis` / `GEO Extractability` / `Automated Reframes` /
  `AI Usage Stats`). A sheet is absent only if that feature produced no data.

## 5. Degradation cases — spot-check the honest-absence behaviour (optional but valuable)
- [ ] **No AV export** → AI Share-of-Voice section absent + console "no export found" (not an error).
- [ ] **Expired GSC token** → SERP-overlap shows `self_unknown` (not a false "you're absent"), and
  positioning marks you `insufficient_data` but **still plots you**.
- [ ] **DataForSEO down** → Branded-Demand shows the "volume unavailable" caveat, not zeros-as-fact.
- [ ] **No `YOUTUBE_API_KEY`** → YouTube Presence section + sheet absent, console says "no API key
  in env — skipped" (a clean skip, not a crash, not a table of zeros).
- [ ] **YouTube quota exhausted mid-run** → the remaining competitors are marked `error`
  (retryable) and the console announces `⚠️ quota budget hit` — they are **not** recorded as
  "no channel".

## 6. Human-judgement items — can't be automated
- [ ] **Reputation-Risk parasite flags:** eyeball each — is it a genuine off-topic *commercial*
  subfolder, or a false positive on legitimate content? Tune `shared_config.json →
  risk_signals.commercial_terms` if noisy.
- [ ] **AI Share-of-Voice stability:** run twice — do shares swing wildly? LLM answers are
  non-deterministic (the tool labels them rolling snapshots); one run is a snapshot, not truth.
- [ ] **Positioning + overlap legibility:** do the quadrant table / who-ranks-where matrix read
  clearly? Any competitor obviously mis-placed vs. your knowledge of them?
- [ ] **Branded-demand brands:** any generic brand that slipped through (add it to
  `branded_demand.generic_brand_prune`), or a real brand wrongly pruned?
- [ ] **Feasibility empties?** If the Competitor Feasibility section is empty, confirm
  `competitors.avg_da` was populated this run (it's written per audited domain).
- [ ] **YouTube `candidate` channels (the key Phase-1 review):** for each row marked `candidate`
  (name-only match), open the channel and confirm it's really that competitor — a same-name
  channel is common. Tick the real ones; for each confirmed, add its handle to
  `shared_config.json → youtube_presence.channel_map` (e.g. `"comp.com": ["@compcounselling"]`)
  so the next run resolves it directly (1 quota unit) instead of re-searching (~100) and can
  never mis-match it again. This is a **short confirm list, not research from scratch** — it
  replaces the retired "which competitors have channels?" question.
- [ ] **YouTube `confirmed` sanity:** spot-check one or two `confirmed` rows — the subscriber /
  last-upload figures should look plausible for that brand (a wildly-off figure hints at a bad
  channel match despite a domain/handle signal).

## 7. Known-absent-by-design — do NOT file these as bugs
- [ ] Your **branded GSC-anchored figure is NULL** — it needs a serp-discover **D2** branded
  export that isn't built yet; your row is still identified by domain.
- [ ] SERP-overlap **"commodity" is a local overlap-density proxy** — it upgrades when a
  serp-discover **D4** commodity export exists.
- [ ] **High-PA (avg > 50) competitors don't appear** in positioning/overlap — they're filtered
  upstream as "too entrenched" (deliberate).
- [ ] `absent` overlap cell is effectively unreachable (the keyword universe is "who ranked").
- [ ] **YouTube Presence absent entirely** when no `YOUTUBE_API_KEY` is provisioned — the free
  key is an owner prerequisite; without it Phase 1 skips honestly (by design, not a bug).

---

*Companion to `docs/FEATURE_GUIDE.md` (what each feature means) and
`suite_enhancement_spec_SERPCOMPETE_v1.md` (spec status). If a feature's behaviour changes,
update this checklist too.*
