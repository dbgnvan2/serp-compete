# Test-Run Review Checklist

What to check when you do a **real end-to-end audit run** — the things unit tests can't
cover (live APIs, the assembled report, and the judgement calls). Tick as you go.

Run: `cd Serp-compete && PYTHONPATH=. python3 src/main.py`  (or `./run_audit.sh`).
Outputs: `strategic_briefing_run_N.md` + `audit_results_run_N.xlsx`.

---

## 1. Before the run
- [ ] **GSC OAuth valid** — the pre-flight check passes (it hard-fails the CLI otherwise).
- [ ] **DataForSEO + Moz creds** set in `.env` (`DATAFORSEO_LOGIN/PASSWORD`, `MOZ_TOKEN`).
- [ ] **AV export present for C1 (optional):** an `ai_visibility_export_*.json` sits in the
  repo root or `../serp-discover/output/`. If absent, AI Share-of-Voice will *skip* (expected,
  not an error) — to test it, run serp-discover's `export_ai_visibility.py` first.

## 2. Console output — watch the coverage lines
- [ ] `📊 Enrichment coverage (fresh / carried-forward / cache-hit-no-prior / failed)` — a
  non-zero **failed** count means a systematic EEAT/GEO/cluster problem, investigate.
- [ ] `🗺️ SERP overlap: N keywords classified …`
- [ ] `🧭 Positioning: <quadrant counts>`
- [ ] `📣 AI Share-of-Voice: …`  **or**  `ℹ️ … no export found — skipped`
- [ ] `💷 Branded demand: N brands benchmarked.`
- [ ] `🚨 Reputation risk: N signals (M own-site).`
- [ ] `▶️ YouTube presence: checked N, confirmed C, candidates K, none D, errors E, skipped S,
  quota units U`  **or**  `ℹ️ … no API key in env — skipped`. If it shows `⚠️ quota budget hit`,
  the run stopped early on purpose (the skipped domains are retryable `error`, not "no channel").
- [ ] **Any `⚠️ … skipped` line = that feature errored.** Should be rare now — investigate the
  message (an import/signature/data problem hides here rather than crashing the audit).

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
