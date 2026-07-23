# serp-compete — Suite Enhancement Spec (v1, self-contained)

Origin: split from the cross-tool master `suite_enhancement_spec_v1.md` (in the
serp-discover repo), derived from `three_tool_audit_review_20260721.md`.
**This file is self-contained** — serp-compete's item is inlined in full below.
The master is referenced only for cross-tool context.

Commits MUST carry `Spec: suite_enhancement_spec_v1.md#<item>`.

## Decisions applied (2026-07-21, from the owner)

- **Apps stay independent.** No forced shared client profile; the pre-existing
  `shared_config.json` (already read by serp-compete and serp-discover) stays as
  it is. The suite-orchestration item (X-1) is **dropped** as a shared feature.
- **Phase 1 is the go here: SC-1** (plus the X-4 doc note).

## Build status (2026-07-21)

- **SC-1 — ✅ SHIPPED & tested.** New `src/geo_profiler.py` (`GeoProfiler` /
  `GeoProfile`) computes a per-page GEO/extractability profile from the
  already-scraped `ScrapedPage` (schema types, credentialed authorship,
  question-shaped headings, freshness) plus a plain-language "why cited"
  rationale. Wired into `src/main.py`: the fresh-scrape branch computes the profile,
  and a cached re-run carries the URL's latest prior profile forward (see
  "Review-driven fixes" below); persisted via a new `geo_profiles` table +
  `db.save_geo_profile` in `src/database.py`; rendered as a "GEO / Extractability —
  Why Competitors Get Cited" section + Excel sheet in `src/reporting.py`; editorial
  `geo_signals` block added to `shared_config.json`. Tests:
  `tests/test_geo_profiler.py` (11, incl. a P7 adversarial case) +
  `tests/test_wiring.py` (9, incl. 6 cache-hit carry-forward cases). Full suite:
  **54 passing locally** (see "Verification").
  - **Decoupled from spaCy on purpose:** `GeoProfiler` is duck-typed (needs only
    `url`/`extraction_status`/`outline`/`metadata`), so it doesn't import
    `src.semantic`.
  - **Honest scope:** answer-first placement and FAQ-answers-in-raw-HTML from the
    SC-1 spec need DOM-position / JS-render analysis the scraper doesn't do; they
    are reported in `GeoProfile.not_measured`, never faked.

### Bug fixes shipped 2026-07-21 (found while implementing SC-1)

1. **EEAT / Cluster wired into the run path — ✅ FIXED.** `EEATScorer`
   (`src/eeat_scorer.py`) and `ClusterDetector` (`src/cluster_detector.py`) were
   fully built with `save_to_database` methods and documented "integrated" in
   `SPEC_COVERAGE_REPORT_v3.md`, but **neither was imported or called anywhere** —
   so the report's EEAT and Cluster sections were always empty on real runs.
   `main.py` now instantiates both, scores each freshly-scraped page (EEAT, with
   Moz PA as the DA proxy) and runs per-domain cluster detection over the retained
   scraped pages, persisting to the existing `eeat_scores` / `cluster_results`
   tables. Both `save_to_database` paths are now covered by
   `tests/test_wiring.py` (they had never executed against the real schema before).

2. **Dead 429 circuit-breaker — ✅ FIXED.** `main.py` branched on
   `content == "BLOCK"` / `elif content:`, assuming the pre-`ScrapedPage` scraper
   contract. The current `scrape_content` always returns a `ScrapedPage`, so the
   breaker never fired and blocked/errored fetches were saved as **zero-score
   traffic magnets** — polluting the "systemic vacuum" list (systems_score == 0)
   with pages that merely failed to load. It now branches on
   `extraction_status`: `blocked` fires the domain circuit-breaker, `error` skips
   the page, and only `complete`/`partial` pages are scored and saved.

**Behaviour change to note:** blocked/errored competitor pages are no longer
written to `traffic_magnets` / `semantic_audits`, so those tables (and the vacuum
list) will be cleaner and slightly smaller than before on sites that rate-limit.

Verified in a sandbox: **18 tests pass** (3 wiring + 10 geo + 3 database + 2
config); `main.py` compiles. The spaCy/Google/OpenAI-dependent suites and the live
`run_audit` path were not run in-sandbox (need the full model + API stack).

### Review-driven fixes (2026-07-22, pre-push failure-pattern sweep)

A `learning-qa` sweep of the uncommitted change (before push) surfaced four
findings; the substantive one changed the design.

- **Finding 1 — cache-path silently re-empties the new sections (P8 dirty-state) —
  ✅ FIXED.** The EEAT/GEO/cluster wire-up sat inside `main.py`'s cache-**miss**
  branch, and `was_audited_recently` is not `run_id`-scoped — so any re-run within
  the 7-day semantic-audit cache over already-audited URLs wrote **zero** rows for
  the new `run_id` and the report sections silently vanished (the very bug the
  wire-up fixes, back on the *common* re-run path). Fixed with
  `db.carry_forward_profile(table, match_col, match_val, run_id)` (allowlisted
  tables only): on a cache hit the URL's latest prior EEAT/GEO row — and, for an
  all-cached domain, the domain's latest prior cluster row — is re-associated with
  the current run. Honest: it reuses a real earlier scrape (original timestamps
  preserved), exactly as the semantic-score cache reuses prior scores; a cache hit
  with **no** prior profile returns `False` and is counted, never fabricated.
- **Finding 3 — question-heading proxy over-triggered (P7) — ✅ FIXED.**
  `_count_question_headings` counted any heading whose first word was an
  interrogative *or* that ended in `?`, so declaratives ("How We Help", "Why
  differentiation matters") inflated the extractability tier. Now requires a
  trailing `?` **and** an interrogative/auxiliary opener. Adversarial test added;
  the test that had enshrined the loose behaviour was corrected.
- **Finding 4 — silent enrichment failures (P2) — ✅ FIXED.** The per-page
  `try/except` around EEAT/GEO/cluster now feeds a run-level coverage counter,
  printed as an "Enrichment coverage (fresh / carried-forward / cache-hit-no-prior
  / failed)" summary — a systematic failure or a fully cache-served run is now
  provable, not an indistinguishable empty section.
- **Finding 2 — the wiring itself is not unit-tested (P10) — ✅ FIXED.** The
  fresh-scrape / cache-hit / cluster-gate decision logic was extracted from the
  monolithic `run_audit()` into a new importable module `src/enrichment.py`
  (`new_enrichment_stats`, `enrich_scraped_page`, `carry_forward_cached_page`,
  `finalize_domain_cluster`); `main.py` now delegates to it. The wiring is now
  unit-tested directly with a real DB + real engines + duck-typed pages, no
  network/model stack (`tests/test_enrichment.py`, 9 tests). Only the outer SERP
  loop (which pages get audited) remains integration-only.

**Finding 1 mixed-domain fix — ✅ FIXED.** A *mixed* domain on a re-run (some URLs
cache-served, some freshly scraped) previously computed cluster detection over only
the fresh subset and could under-count hubs. `finalize_domain_cluster` now computes
fresh **only** when the whole domain was freshly scraped; if any page was
cache-served it carries the latest **complete** prior cluster result forward instead
(falling back to a best-effort partial compute only when no prior exists). Proven by
`tests/test_enrichment.py::test_finalize_cluster_mixed_domain_prefers_carry_forward`.

**Known limitation (residual, accepted).** A domain that keeps ≥1 cache hit on every
run inside the 7-day audit window will always take the carry-forward branch and never
*recompute* its cluster result, so `max_in_degree` / hub counts can go stale until the
whole domain is next re-scraped. This is the deliberate, honest trade against the
under-count bug, and matches the per-URL EEAT/GEO carry-forward semantics (same
staleness). A future fix persists per-page internal-link structure so a mixed set can
be fully recomputed.

## Verification

Full local suite: **139 passing** (`cd Serp-compete && PYTHONPATH=. pytest tests/ -q`)
— geo profiler, wire-up + cache-hit carry-forward, the extracted enrichment wiring, the
**SC-6 SERP-overlap matrix**, **SC-4 barbell positioning**, **SC-3 AI share-of-voice**,
**SC-5 branded-demand benchmark**, and **SC-8 reputation-risk radar** all covered; modules
byte-compile. The root v3 suite (`PYTHONPATH=Serp-compete pytest tests/ -q`) stays at
**158 passing**. The comparison-layer **assembly** is now unit-tested too — the five features
were extracted into `src/comparison_features.py::run_comparison_features` with a smoke test
(`tests/test_comparison_features.py`) that fails if any `save_*` wiring is removed. Only the
live DataForSEO / serp-discover-export **inputs** remain integration-only. A run-through
checklist for a real audit lives in `docs/TEST_RUN_CHECKLIST.md`.

**Post-batch review-driven fixes.** F7: extracting the assembly (above) and its smoke test
**caught a real bug** — `src/competitor_mining.py` uses bare `from api_clients import` /
`from reframe_engine import` (should be `from src.…`), so it's un-importable as a submodule,
which was silently disabling C1/C3 via their guarded `try/except`. Worked around by inlining
`_derive_brand_name` in `comparison_features.py`; **the competitor_mining import bug is flagged
as an adjacent issue, not swept**. F8: the SoV "cited-but-you're-not" gap is now a single
persisted `cited_gap` flag (computed once in `compute_sov`, read by the report) instead of two
implementations that could drift.

A **second sweep** on the F7/F8 diff caught two more (both fixed + regression-tested, hence
139): **F1 (P8, HIGH)** — `cited_gap` was added only to `CREATE TABLE IF NOT EXISTS sov_daily`,
so a DB that already had `sov_daily` (from the C1 commit) never got the column; the next real
run would silently disable C1 on save **and** crash the unguarded report `SELECT cited_gap`. Now
migrated via `ALTER TABLE … ADD COLUMN` in the migrations block, locked by a dirty-state test.
**F2 (P12, MED)** — the extraction unified all DA reads to a `0` default, but C2 authority must
receive `None` for a missing client DA (compute_authority *excludes* it, never scores it as 0);
restored the `None` default for C2 only (C4 still uses `0`), with a regression test.

## Read first (this repo)

`README.md`; `shared_config.json` (config authority — new editorial tokens/
thresholds go here, not in Python); `docs/SPEC_COVERAGE_REPORT_v3.md`; the v3
EEAT / page-structure extraction / handoff-ingestion modules.

---

## SC-1 — Competitor GEO / extractability comparison  · Phase 1 · no new dependency

**Problem.** serp-compete scores competitor pages for *language* (medical vs.
systems) and EEAT, but not for the **structural** reasons AI engines cite them. It
already fetches and extracts competitor page structure (v3), so the signals are in
reach.

**Required change.**
1. On the competitor pages already scraped, compute a compact **extractability /
   GEO profile** per page: schema types present (esp. FAQPage / Article /
   Organization / Person), author byline + credential presence, FAQ-answers-in-
   HTML, answer-first structure (lead paragraph directly under an H2), and
   question-shaped headings.
2. Reuse TalkingToad's AI-readiness heuristics. **Decision point for the
   implementer:** whether TalkingToad's checker can be **imported/shared** or must
   be **re-expressed** here. If re-expressed, all token/threshold lists live in
   `shared_config.json` (editorial-content-in-config rule) — no hardcoded
   editorial content in Python. *(verify in code — importability across repos.)*
3. Attach the profile to each competitor page record and surface it in the
   **strategic briefing**: for every "traffic magnet", state *why* it is likely
   cited (e.g. "ranks #2, AI-cited; carries FAQPage schema + credentialed author +
   answer-first structure") and contrast with the client's equivalent page when
   known.
4. Do **not** add competitor performance/CWV (that is SC-2, declined).

**Acceptance criteria.**
- SC-1.1 Each audited competitor page record gains a GEO-profile block with the
  listed fields; unit tests for a schema-rich page, a bare page, and a
  credentialed-author page.
- SC-1.2 The briefing renders at least one "why cited" structural rationale per
  traffic magnet when the data supports it, and says so honestly when it does not.
- SC-1.3 All editorial token/threshold lists used by the ported heuristics live in
  `shared_config.json`; no new hardcoded editorial content in Python.
- SC-1.4 Existing serp-compete suites stay green; new logic covered per the v3 test
  conventions.

---

## SC-4 — Barbell Positioning Diagnostic  · **✅ SHIPPED** · reuse-heavy

**Problem.** Winners are large-and-authoritative or small-and-niche; the undifferentiated
middle loses. The discrete `tag_competitor_position` labels existed, but not the
continuous authority×focus 2×2 quadrant.

**What shipped.** `src/positioning.py` — an **authority** axis (0-100) × a **focus** axis
(0-100) 2×2:
- **authority** = a config-weighted composite of **Moz DA + top-10 ranking count**, the
  SAME formula for competitors and the client (commensurability). Competitor DA is
  persisted per run by `save_competitor_summary` (newly wired into `run_audit`); the
  client's DA is `client.da`; top-10 counts come from GSC (client) / competitor_metrics.
- **focus** = `1 - normalized_entropy([medical, systems])` — tier-identity concentration
  from the traffic_magnets tier scores (the client: classify its GSC queries into tiers).
- **quadrant** ∈ authoritative / niche_owner / middle / emerging / insufficient_data.
  Thin or un-scoreable domains are emerging / insufficient_data, never silently `middle`;
  the client is always plotted. New `positioning` table (`db.save_positioning`); report
  "Barbell Positioning Diagnostic" section + Excel sheet. Config:
  `shared_config.json → positioning`.

**Acceptance criteria.**
- SC-4.1 client always plotted — `tests/test_positioning.py::test_sc41_client_always_plotted`
  (+ `::test_sc41_client_plotted_even_with_no_data`).
- SC-4.2 thresholds from config — `::test_sc42_thresholds_read_from_config`.
- SC-4.3 quadrant assignment at the corners — `::test_sc43_quadrant_corners` +
  `::test_sc43_via_positioning_row`.
- SC-4.4 rationale carries the numbers — `::test_sc44_rationale_has_numbers`.
- Guards (never silently middle) — `::test_thin_domain_is_emerging_not_middle`,
  `::test_no_tier_signal_is_insufficient_not_middle`.

**Review-driven fixes (pre-push sweep).** (1) The authority axis was **incommensurable**:
`competitors.avg_da` was never populated (its writer `save_competitor_summary` had no
caller), so competitors used {EEAT, top-10} while the client used {DA, top-10} — two
different formulas on one plot — and EEAT double-embeds DA. Fixed by wiring
`save_competitor_summary(domain, avg_pa)` on the run path and using **{Moz DA, top-10} for
both sides** (EEAT dropped from the axis; it stays in its own report section). **The same
wiring also repairs C4 feasibility, which was latent-empty for the same missing-DA
reason.** (2) The `emerging` gate now requires thin evidence **and** low authority, so an
established high-DA rival that just doesn't rank in the niche isn't mislabelled emerging.
(3) The report/config caption now matches the actual formula and notes that avg-PA > 50
rivals are filtered upstream (an empty `authoritative` quadrant ≠ none exist).

**Known limitation.** "Focus" is tier-identity concentration (medical vs. systems), not
topic-count breadth. The client's axes come from GSC (not a page audit), so a GSC-less run
leaves the client `insufficient_data` (still plotted). Genuinely authoritative rivals
(avg PA > 50) are filtered upstream and won't appear.

---

## SC-6 — SERP Overlap & Differentiation Gap  · **✅ SHIPPED** · reuse-heavy (the tool's spine)

**Problem.** Where do you and competitors collide on commoditized SERPs (shared
AI-absorption risk), and where are you uniquely present (defensible)? The
differentiation gap (Systemic Vacuum) was wired, but the who-ranks-where keyword
matrix and the `AnalysisEngine` keyword-intersection gap were scattered/unwired.

**What shipped.** A single, wired who-ranks-where matrix:
- `src/serp_overlap.py` — pure, deterministic `classify_cell` / `build_overlap_rows`
  / `rollup_by_cell` + `analyze_serp_overlap`, which also wires the previously-unwired
  `analysis.py::AnalysisEngine.find_keyword_intersection` (keywords ALL competitors
  rank for but the client doesn't) and `check_feasibility` (client DA vs each
  competitor DA).
- Competitor positions from `competitor_metrics` (`db.get_competitor_positions`); the
  client's own positions from first-party GSC (`GSCManager.get_query_position_map` →
  `self_position`) since the handoff is competitor-only. "Ranks top-N" is symmetric
  for client and competitors (a page-2 client is not "present").
- Cells: `shared_commodity` / `shared_defensible` / `exclusive_self` /
  `exclusive_competitor` / `absent`. `commodity_score` is a LOCAL overlap-density
  proxy (`estimation_basis="local_overlap_density"` — a framing, not a measured index;
  upgrade to the serp-discover D4 commodity export when it exists).
- Persisted to a new `serp_overlap` table (`db.save_serp_overlap`); rendered as a
  "SERP Overlap & Differentiation Gap" report section + Excel sheet with
  `exclusive_competitor` and `shared_commodity` action queues; folds in the Systemic
  Vacuum list (not duplicated). Wired into `run_audit()` after `save_competitor_metrics`
  (guarded). Config: `shared_config.json → serp_overlap` (`top_n` 10,
  `commodity_high_overlap` 3, `framework_caption`).

**Acceptance criteria.**
- SC-6.1 cell classification deterministic given snapshot + commodity + config top-N —
  `tests/test_serp_overlap.py::test_sc61_classify_cell_all_quadrants` +
  `::test_sc61_build_rows_is_deterministic`.
- SC-6.2 `exclusive_self` requires zero competitors in top-N —
  `::test_sc62_exclusive_self_requires_zero_competitors`.
- SC-6.3 volume rollups match member keyword volumes — `::test_sc63_rollup_matches_member_volumes`.
- SC-6.4 `AnalysisEngine.find_keyword_intersection` wired into `run_audit()` + covered
  beyond `test_analysis.py` — `::test_sc64_analysis_engine_intersection_gap_wired`
  (+ `::test_sc64_feasibility_wired`). Plus the top-N-symmetry adversarial case
  `::test_adversarial_client_page2_is_not_shared`.

**Review-driven fixes (pre-push sweep).** (1) A GSC-unavailable run (empty client
map) no longer classifies every keyword as `exclusive_competitor` — self-presence is
UNKNOWN (`self_unknown` cell), the exclusive queues are withheld, and the report
prints a loud caveat (never a false "you're absent"). (2) The join key is normalized
(lower/trim) on both sides, so a competitor `"Couples Therapy"` and GSC
`"couples therapy"` are one keyword, not a false exclusive-competitor/exclusive-self
split. (3) The SC-6.3 volume rollup and the `check_feasibility` half are surfaced, not
discarded: `keyword_volume` per row + a "Volume by cell" line, and a new
`competitor_feasibility` table rendered as a "Competitor Feasibility" section + Excel
sheet.

**Known limitation.** A page-2 client (GSC position > `top_n`) is treated as absent
from the top-N battle for cell purposes (raw `self_position` retained for
transparency). The keyword universe is "who ranked" (competitors' + the client's GSC
keywords), so the `absent` cell only becomes reachable if a full target-keyword list
is later plumbed in. `commodity_score` is a local overlap-density proxy until the
serp-discover D4 commodity export exists (soft dependency, plan §12.4).

---

## SC-3 — AI Answer Share-of-Voice  · **✅ SHIPPED** · consume, don't re-probe

**What shipped.** `src/sov_analyzer.py` CONSUMES serp-discover's AI-visibility export
(`brand_mentions` + `ai_citations` + `answer_sentiment`, the last added by extending the
Phase-0 export) — no probing here. Per engine it computes mention share, citation share,
per-competitor sentiment (SC-3.4, from that competitor's own rows only), and a
"cited-but-you're-not" gap; shares within an engine sum to ~100% (unlisted → "other"). New
`sov_daily` table + `db.save_sov`; report section + Excel. Absent export →
`data_available:false` (section skipped). Consumer-selection contract honoured (newest
`data_available:true` by `source_run_ts`).

**Acceptance criteria.** SC-3.1 `test_sc31_mention_shares_sum_to_100_per_engine`;
SC-3.2 `test_sc32_missing_engine_does_not_block_others`; SC-3.3
`test_sc33_recompute_on_added_competitor_no_reprobe`; SC-3.4 `test_sc34_sentiment_is_scoped_per_competitor`.
**Review-driven fix.** A competitor *mentioned* but not *cited* was hidden in "other"
(brand→domain came only from citations); `compute_sov` now also matches mentions by
competitor brand name.

---

## SC-5 — Branded-Demand Competitive Benchmark  · **✅ SHIPPED**

**What shipped.** `src/brand_demand.py`: per competitor, expand a branded query set (brand +
config modifiers), sum DataForSEO search volume (new hardened
`DataForSEOClient.get_search_volume`), compute share + equal-window growth. Generic brand
names are pruned (SC-5.4), never guessed. The client's own row is GSC-anchored (serp-discover
D2) when that export exists — a soft dep not yet available, so `est_branded_click_share` is
NULL/labelled and the report identifies the own row by domain. New `brand_demand_bench`
table + `db.save_brand_demand`; report + Excel.

**Acceptance criteria.** SC-5.1 `test_sc51_own_vs_estimated_labeling`; SC-5.2 `test_sc52_*`;
SC-5.3 `test_sc53_growth_equal_windows`; SC-5.4 `test_sc54_generic_brand_pruned`.
**Review-driven fixes.** An all-zero volume (DataForSEO outage) renders as
`estimation_basis='volume_unavailable'` (not "zero demand"); the own row is identifiable by
domain regardless of the anchor. The live search-volume fetch is integration-only (mocked in
tests); the D2 own-anchor is a documented follow-up.

---

## SC-8 — Reputation-Risk Radar  · **✅ SHIPPED** · reuse-heavy

**What shipped.** `src/risk_radar.py`: `visibility_cliff` (a recent-window step-drop),
`parasite_subfolder` (topical mismatch AND commercial intent — never the subfolder name
alone), and `ranking_volatility` (fed from `get_volatility_alerts`), unified into one feed
with own-site signals separated from competitor intel (SC-8.3) and labelled **pattern
detections, not confirmed penalties**. New `risk_signal` table + `db.save_risk_signals` +
`db.get_visibility_series` / `db.get_parasite_candidates`; report + Excel.

**Acceptance criteria.** SC-8.1 `test_sc81_visibility_cliff_high_with_drop_pct`; SC-8.2
`test_sc82_parasite_requires_mismatch_and_commercial` (+ `_word_boundary_no_false_positive`,
`_subfolder_name_alone_does_not_flag`); SC-8.3 `test_sc83_own_and_competitor_signals_separated`.
**Review-driven fixes.** The cliff peak is bounded to a recent lookback (a months-ago
collapse no longer re-flags forever) and the severity tiers are live (`cliff_drop_pct` 0.3);
the parasite commercial-term match is word-boundary (so "dealing" ≠ "deal") with a trimmed vocab.

---

## X-4 — Backlink-exclusion note  · Phase 1 · docs only

Add a short **"Out of scope: backlink graph analysis"** note to `README.md`: the
suite uses Domain Authority as the sole authority proxy; full backlink/toxic-link/
disavow analysis needs a paid link-graph provider and is judged low-ROI for one
nonprofit; revisit only if scale or budget changes.

**Acceptance criteria.** X-4.1 The note exists in `README.md`, wording consistent
across the three repos. No code/test change.

---

## Out of scope (this repo)

- **SC-2** competitor Core Web Vitals — declined (PSI cost scales with
  competitor×page; poor ROI; rarely explanatory in this niche).
- **X-1** suite orchestration — dropped as a shared feature per the keep-apps-
  independent decision.
