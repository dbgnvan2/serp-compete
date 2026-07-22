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

Full local suite: **63 passing** (`cd Serp-compete && PYTHONPATH=. pytest tests/ -q`)
— geo profiler, wire-up persistence, cache-hit carry-forward, and the extracted
enrichment wiring (fresh / cache-hit / mixed-domain cluster gate) all covered;
`main.py` + `src/enrichment.py` byte-compile. The root v3 suite (`PYTHONPATH=Serp-compete
pytest tests/ -q`) stays at **158 passing**. Only the outer SERP loop of `run_audit`
(DataForSEO / Moz / spaCy / OpenAI) remains integration-only.

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
