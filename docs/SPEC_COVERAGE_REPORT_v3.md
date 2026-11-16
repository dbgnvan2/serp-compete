# Spec Coverage Report — Tool 2 v3

**Date:** 2026-05-02
**Spec Version:** 3.0
**Implementation Status:** v3 scope delivered, with two of the three
"technical debt" items corrected below — see the verification note.

> **Verification note, 2026-11-16.** The claims in this report were checked
> against the code. Three corrections, all in Part 3:
>
> - **Debt 2 (legacy tables) was wrong in a way that would break the tool if
>   acted on.** It lists `competitor_metrics` and `semantic_audits` as
>   "Deprecated — retained for backwards compat", with a plan to remove them in
>   v4. Both are **live**: `semantic_audits` is the 7-day scoring cache every run
>   reads and writes, and `competitor_metrics` carries the per-run ranking rows
>   that the visibility series and the barbell's top-10 counts are computed from.
>   Chunks C1, C3 and C4 all added columns to them. Removing them on that plan
>   would delete the audit's own working tables.
> - **Debt 3 (step DAG) claims a remediation that never took effect.** Its
>   "After" column describes the orchestrator executing a topologically sorted
>   DAG. `src/step_dag.py` exists and is correct, but it is imported by nothing
>   except its own test, the orchestrator still sequences its steps directly,
>   and the `step_dag` config section it reads was deleted in November 2026 as a
>   documented key with no reader (C-C-14).
> - **The test counts were stale.** They are now, by exit code:
>   `pytest tests` → **162**, `pytest Serp-compete/tests` → **539**, both
>   suites in one run (`pytest -q`, which `pytest.ini` configures) → **701**.
>
> **Line-number references in this report are as of 2026-05-02 and are not
> maintained.** Four review chunks have edited these files since. Use the
> function and class names, which are stable; where a line number and a name
> disagree, the name is right.

---

## Executive Summary

The v3 specification requirements were implemented and tested. Corrected
2026-11-16 where the original claims did not match the code:

- ✅ **5/5 Gap Refinements** (improved from v2)
- ✅ **3/3 Feature Authorizations** (new features approved and integrated)
- ⚠️ **1/3 Technical Debt Remediation** — hardcoded editorial content **was**
  moved to config (verified: 20 `clinical_pivots` entries read at
  `reframe_engine.py:58`, with a `DEFAULT_CLINICAL_PIVOTS` fallback). The
  "legacy tables" item describes live tables as deprecated, and the step-DAG
  item describes an execution model the orchestrator does not use. See Part 3.
- ⚠️ **4/4 Third-Party Integration Skeleton** (Ahrefs, Moz placeholders) — the
  skeleton exists as intended, but it is imported by nothing and has **no
  tests**, despite `IMPLEMENTATION_PLAN_v3.md` having named a
  `test_third_party_crawlers.py` that does not exist (corrected 2026-11-16).
- ✅ **Tests passing** — 701 by exit code, 2026-11-16 (was "158/158" in 2026-05)

> **Post-v3 enhancements** (tracked in `suite_enhancement_spec_SERPCOMPETE_v1.md`, not
> counted in the v3 totals above): **SC-1** — competitor GEO / extractability (shipped);
> **SC-6** — SERP Overlap & Differentiation Gap (shipped: the wired who-ranks-where
> matrix + the previously-unwired `AnalysisEngine.find_keyword_intersection`/
> `check_feasibility`, new `serp_overlap` + `competitor_feasibility` tables); **SC-4** —
> Barbell Positioning Diagnostic (shipped: authority×focus 2×2, new `positioning` table;
> also wires competitor-DA persistence, which repairs C4 feasibility); **SC-3** — AI Answer
> Share-of-Voice (consumes serp-discover's AI-visibility export; `sov_daily`); **SC-5** —
> Branded-Demand Benchmark (`brand_demand_bench`); **SC-8** — Reputation-Risk Radar
> (`risk_signal`); **SC-7-YT Phase 1** — YouTube presence check
> (`yt_channel_presence`). Suite sizes as of 2026-11-16: the suite beside the
> source is **539 passing**, the root `tests/` suite **162**, and `pytest -q`
> runs both for **701**. (This note previously said 135 and 158.)
>
> Since then, the 2026-11-04 review's chunks C1–C4 and the compete half of chunk
> X have landed — see `docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md` §6
> for the per-finding status, and `docs/handoff_contract.md` for the cross-tool
> contract. Several behaviours this report describes were corrected by them;
> `docs/FEATURE_GUIDE.md` §9 is the authoritative list of what each number means
> and what it cannot support.

---

## Part 1: Gap Refinements

### Gap 1: Competitor Handoff Ingestion ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| Load competitor_handoff_*.json | src/main.py:98–135 (get_latest_market_data) | ✅ Done |
| Validate against handoff_schema.json | src/main.py:109–128 (jsonschema validation) | ✅ Done |
| Fallback to legacy market_analysis_*.json | src/main.py:136–151 (DeprecationWarning) | ✅ Done |
| Fallback to manual_targets.json | src/main.py:153–164 (developer override) | ✅ Done |
| Pass PAA questions to reframe engine | src/main.py:427–433 (paa_map integration) | ✅ Done |

**Test:** tests/test_handoff_ingestion.py (14 tests, 100% pass)  
**Files Modified:** src/main.py  
**Backwards Compat:** Maintained (legacy fallbacks preserved)

---

### Gap 2: Page Structure Extraction ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| ScrapedPage dataclass | src/semantic.py:13–38 | ✅ Done |
| Extract outline (h1, h2, h3) | src/semantic.py:185–199 (_extract_outline) | ✅ Done |
| Extract metadata (title, dates, schema) | src/semantic.py:201–307 (_extract_metadata) | ✅ Done |
| Extract internal links | src/semantic.py:282–305 (link detection) | ✅ Done |
| Preserve first_500_words backwards compat | src/semantic.py:127–140 | ✅ Done |
| Detect original images (not stock) | src/semantic.py:268–277 (likely_original_images_count) | ✅ Done |
| Detect case study signals | src/semantic.py:311–316 (case_study_signal) | ✅ Done |

**Test:** tests/test_page_structure.py (18 tests, 100% pass)  
**Files Modified:** src/semantic.py  
**Backwards Compat:** Maintains first_500_words field for vocabulary scoring

---

### Gap 3: EEAT Heuristic Scoring ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| EEATScore dataclass | src/eeat_scorer.py:22–47 | ✅ Done |
| Experience dimension (author, dates, images) | src/eeat_scorer.py:133–162 | ✅ Done |
| Expertise dimension (credentials, schema) | src/eeat_scorer.py:163–186 | ✅ Done |
| Authoritativeness dimension (DA, links, schema) | src/eeat_scorer.py:187–199 | ✅ Done |
| Trustworthiness dimension (HTTPS, contacts) | src/eeat_scorer.py:200–205 | ✅ Done |
| Weighted scoring per dimension | src/eeat_scorer.py:207–243 | ✅ Done |
| Caveat messaging for heuristic nature | src/eeat_scorer.py:33 | ✅ Done |
| Persistence to database | src/eeat_scorer.py:340–383 (save_to_database) | ✅ Done |

**Test:** tests/test_eeat_scorer.py (54 tests, 100% pass)  
**Files Modified:** src/eeat_scorer.py  
**Database:** eeat_scores table (26 columns, indexed on url + run_id)

---

### Gap 4: Internal Linking Cluster Detection ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| ClusterResult dataclass | src/cluster_detector.py:28–46 | ✅ Done |
| Build internal link graph | src/cluster_detector.py:89–94 | ✅ Done |
| Detect hub candidates | src/cluster_detector.py:112–115 | ✅ Done |
| Classify cluster signal (isolated/linked/clustered) | src/cluster_detector.py:117–123 | ✅ Done |
| Caveat for limited scope (N≤3 pages) | src/cluster_detector.py:20–25, 131 | ✅ Done |
| Persistence to database | src/cluster_detector.py:140–183 (save_to_database) | ✅ Done |

**Test:** Integration tested via Task 7 verification  
**Files Modified:** src/cluster_detector.py  
**Database:** cluster_results table (13 columns, indexed on domain + run_id)

---

### Gap 5: Strategic Briefing Generation ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| Executive summary | src/reporting.py:21–26 | ✅ Done |
| GSC performance gaps | src/reporting.py:29–49 | ✅ Done |
| EEAT competitive analysis | src/reporting.py:69–87 (NEW) | ✅ Done |
| Internal linking cluster analysis | src/reporting.py:89–102 (NEW) | ✅ Done |
| Volatility alerts | src/reporting.py:58–63 | ✅ Done |
| Feasibility drift alerts | src/reporting.py:65–72 | ✅ Done |
| Market velocity alerts | src/reporting.py:74–82 | ✅ Done |
| Competitor ranking summary | src/reporting.py:118–134 | ✅ Done |
| Traffic magnets with systemic labels | src/reporting.py:144–147 | ✅ Done |
| Strategic targets (systemic vacuums) | src/reporting.py:148–155 | ✅ Done |
| Automated Bowen reframes | src/reporting.py:191–200 | ✅ Done |
| Markdown + Excel export | src/reporting.py:206–226 | ✅ Done |

**Test:** Integration tested via Task 8 verification  
**Files Modified:** src/reporting.py  
**Output:** strategic_briefing_run_N.md + audit_results_run_N.xlsx

---

## Part 2: Feature Authorization

### Feature 1: Competitor Keyword Mining ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| competitor_mining.py module | Serp-compete/src/competitor_mining.py (161 lines) | ✅ Done |
| Integrate into main.py | src/main.py:99 | ✅ Done |
| Add to step_dag as step_1_mining | shared_config.json step_dag | ✅ Done |
| Optional step (can skip) | shared_config.json: optional=true | ✅ Done |

**Authorized:** Yes, core to workflow  
**Status:** Complete and integrated

---

### Feature 2: Orchestrator Streamlit UI ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| orchestrator.py module | Serp-compete/src/orchestrator.py (169 lines) | ✅ Done |
| Step checkboxes | src/orchestrator.py:31–35 | ✅ Done |
| Step dependency note | src/orchestrator.py:37 | ✅ Done |
| Step execution with logging | src/orchestrator.py:42–62 (run_script) | ✅ Done |
| Report generation | src/orchestrator.py:113–140 | ✅ Done |

**Authorized:** Yes, useful for manual workflow  
**Status:** Complete, UI functional

---

### Feature 3: Strike Distance Mapping ✅

| Requirement | Implementation | Status |
|-------------|------------------|--------|
| strike_mapper.py module | `Serp-compete/src/strike_mapper.py` | ✅ Done. Rewritten 2026-11-16 — see below |
| GSC-to-content gaps | `strike_mapper.get_top_gsc_keywords` / `inject_headers` | ⚠️ It **invented** the gaps. `gsc_strike_list.md` holds one row, `\| No data \|`, and the parser silently returned five hard-coded keywords; `inject_headers` wrote them into `pillar_north_shore_draft.md`, where those five headings still are. It was also non-idempotent (every run re-injected them) and kept its reframe vocabulary in Python source, against CLAUDE.md. Fixed 2026-11-16: no data now means no headings unless `--allow-fallback` is passed, which says in the output that the headings are editorial and not Search Console data |
| Integration point | ~~Called from orchestrator.py:111~~ | ❌ Not true as of 2026-11-16: `orchestrator.py` contains no reference to `strike_mapper`. It is a standalone script, run by hand |
| Tests | `Serp-compete/tests/test_strike_mapper.py` (21 cases) | ✅ Written 2026-11-16. `IMPLEMENTATION_PLAN_v3.md` had listed this file as "(existing)" since 2026-05; it did not exist, and the module was at 0% coverage |

**Authorized:** Yes, supports publication planning  
**Status:** Complete

---

## Part 3: Technical Debt Remediation

### Debt 1: Hardcoded Editorial Content ✅

| Item | Before | After | Status |
|------|--------|-------|--------|
| Bowen pivot_map | reframe_engine.py:8–30 (hardcoded dict) | shared_config.json: clinical_pivots (20 entries) + DEFAULT_CLINICAL_PIVOTS fallback | ✅ Done |
| Config pattern | `self.pivot_map = {...}` | `self.pivot_map = config.get("clinical_pivots", DEFAULT_CLINICAL_PIVOTS)` | ✅ Done |
| Implementation | src/reframe_engine.py:8–26, 46–47 | Safe defaults + config override | ✅ Done |

**Benefit:** Non-engineers can now edit reframes without code changes  
**Test:** Verified in Task 4.5 (config defaults validation)

---

### Debt 2: Legacy Database Tables — ❌ **the premise was wrong**

**Corrected 2026-11-16. Do not act on the original plan below.** Neither table
is legacy. Both are read and written on every run, and three review chunks have
added columns to them:

| Table | What it actually is | Written by | Read by |
|---|---|---|---|
| `semantic_audits` | The 7-day scrape/score cache. C3 added `t2_count`, `t3_count`, `scoring_window_words` so a cache-served page no longer has its tiers estimated (C-C-08) | `database.save_semantic_audit` | `database.was_audited_recently`, `gsc_performance` |
| `competitor_metrics` | The per-(run, domain, keyword) ranking rows. C1 added `keyword_source`; the run-keyed visibility series (C-C-06) and the barbell's top-10 counts are computed from it | `database.save_competitor_metrics` | `reporting`, `database.get_visibility_series` |

Removing them "in v4 or 2027-01-01" as the original table proposed would delete
the audit's own working storage. The two tables that genuinely have no writer
are `market_gaps` and `semantic_audit_results` — see
`docs/DATA_PERSISTENCE_MAP_v3.md` §1.4, which also explains how this inversion
arose (a rename that was designed, half-applied, and never reconciled).

**Still open:** nothing here is deprecated, so there is no deprecation to plan.

---

### Debt 3: Step Dependency Management — ⚠️ **built, never wired**

**Corrected 2026-11-16.** `src/step_dag.py` exists, is correct, and is covered
by 13 passing tests. What the original table's "After" column described —
the orchestrator executing a topologically sorted DAG instead of a manual
chain — **did not happen**:

| Requirement | Claimed | Actual |
|---|---|---|
| Hardcoded dependencies | moved to `shared_config.json → step_dag` | the `step_dag` section was **deleted** in Nov 2026 as a documented key with no reader (C-C-14) |
| DAG validation | `src/step_dag.py` (`StepDAG`) | exists and works — imported by nothing but its own test |
| Execution order | `get_execution_order` topological sort | the orchestrator sequences its steps directly; nothing calls this |
| Cycle detection | DFS-based validation | exists, unreached |

So `StepDAG` can now only be fed by a test fixture: the module reads a config
key that no longer exists, and `tests/test_config_provenance.py` asserts the key
stays gone.

**This is a decision, not a cleanup.** Wiring it means deciding that step order
should be owner-configurable — a feature, with a failure mode of its own (a bad
config stops the audit). Deleting it means removing the module, its test and the
mention in `compete-spec.md`. Recorded in `LEARNINGS.md` → "Open risks" and
guarded by `Serp-compete/tests/test_no_new_dead_code.py` so it cannot quietly
grow companions.

**Test:** `tests/test_step_dag.py` (13 tests, passing — against a fixture-supplied config)

---

## Part 4: Third-Party Integration Planning

### Ahrefs API Skeleton ✅

| Method | Implementation | Status |
|--------|-----------------|--------|
| AhrefsClient.__init__ | src/third_party_crawlers.py:33–40 | ✅ Skeleton |
| get_domain_backlinks | src/third_party_crawlers.py:42–60 | ✅ Skeleton + TODO |
| get_internal_links | src/third_party_crawlers.py:62–73 | ✅ Skeleton + TODO |
| track_link_velocity | src/third_party_crawlers.py:75–86 | ✅ Skeleton + TODO |

**Authorization:** Deferred to v4  
**Documentation:** Docstrings with v4 roadmap  
**Files:** src/third_party_crawlers.py

---

### Moz API Skeleton ✅

| Method | Implementation | Status |
|--------|-----------------|--------|
| MozClient.__init__ | src/third_party_crawlers.py:90–96 | ✅ Skeleton |
| batch_domain_metrics | src/third_party_crawlers.py:98–117 | ✅ Skeleton + TODO |
| get_anchor_text | src/third_party_crawlers.py:119–131 | ✅ Skeleton + TODO |
| get_top_linking_pages | src/third_party_crawlers.py:133–146 | ✅ Skeleton + TODO |

**Authorization:** Deferred to v4  
**Documentation:** Docstrings with v4 roadmap  
**Files:** src/third_party_crawlers.py

---

## Part 5: Configuration-Driven Architecture

### shared_config.json Enhancements ✅

| Section | Lines | Purpose | Status |
|---------|-------|---------|--------|
| clinical_pivots | 118–139 | Bowen reframe mappings (20 entries) | ✅ New |
| handoff | 140–145 | Version management + schema location | ✅ New |
| orchestrator | 146–152 | Streamlit theme, timeout, logging | ✅ New |
| step_dag | 153–180 | DAG step definitions with dependencies | ✅ New |
| eeat_client_messaging | 181–189 | Client-facing EEAT positioning + caveat | ✅ New |

**Implementation:** shared_config.json (updated with 5 new sections)  
**Backwards Compat:** All sections have .get() defaults in code  
**Validation:** Verified in Task 4.6 (backwards compatibility audit)

---

## Part 6: Database Schema Evolution

### New Tables Created ✅

| Table | Columns | Purpose | Status |
|-------|---------|---------|--------|
| eeat_scores | 26 | Store EEAT dimension scores per URL | ✅ Done |
| cluster_results | 13 | Store internal link cluster analysis | ✅ Done |
| semantic_audit_results | 14 | Detailed tier scoring (medical vs systems) | ✅ Done |

**Documentation:** docs/DATA_PERSISTENCE_MAP_v3.md  
**Migrations:** database.py:128–198 (Yolo Mode safe)  
**Verification:** All 3 tables verified to create and accept data

---

## Test Coverage Summary

**Rewritten 2026-11-16.** This was a per-file table of test counts dated
2026-05-02. It had rotted twice over (it listed `test_eeat_scorer.py` at 54
tests against 80 today, and mixed the root `tests/` files with the ones beside
the source), and a hand-maintained count is wrong the moment anyone adds a test.
The live numbers, by exit code:

| Suite | Command | Count (2026-11-16) |
|---|---|---|
| Beside the source | `python3 -m pytest Serp-compete/tests -q` | 539 |
| Root (v3-era) | `python3 -m pytest tests -q` | 162 |
| **Both, as configured** | `python3 -m pytest -q` | **701** |

`pytest.ini` runs both suites in one invocation with `--import-mode=importlib`
and `pythonpath = Serp-compete`, so `pytest -q` is the number that matters.
**Judge it by exit code, never by grepping the summary line.**

Standing guard tests, which exist to fail when a document or a config drifts
from the code rather than to cover a feature:

| Guard | What it catches |
|---|---|
| `Serp-compete/tests/test_config_provenance.py` | a threshold added to `shared_config.json` with no `_<key>_source` note (owner decision 7), and a documented key whose reader was deleted |
| `Serp-compete/tests/test_persistence_map.py` | `docs/DATA_PERSISTENCE_MAP_v3.md` disagreeing with the real schema |
| `Serp-compete/tests/test_no_new_dead_code.py` | a function added to `src/` that nothing references |
| `Serp-compete/tests/test_handoff_contract.py` | the handoff semantics in `docs/handoff_contract.md` |

---

## Backwards Compatibility Audit

✅ **All config access patterns use `.get()` with defaults**
- semantic.py: .get() for all config fields
- eeat_scorer.py: .get() for weights, hosts, credentials, triggers
- cluster_detector.py: .get() for thresholds
- main.py: .get() for auth, client, technical config
- reframe_engine.py: .get() for clinical_pivots, client_messaging

✅ **Database migrations safe**
- CREATE TABLE IF NOT EXISTS (idempotent)
- ALTER TABLE wrapped in try/except (Yolo Mode)
- Legacy tables retained for migration path

✅ **ScrapedPage dataclass backwards compatible**
- first_500_words field preserved
- New fields (likely_original_images_count, case_study_signal) optional
- analyze_text() still accepts string OR ScrapedPage

---

## Files Changed

| File | Changes | Lines Added |
|------|---------|-------------|
| shared_config.json | 5 new config sections | +71 |
| src/reframe_engine.py | DEFAULT_CLINICAL_PIVOTS, config param | +26 |
| src/semantic.py | EEAT metadata fields, case study detection | +15 |
| src/eeat_scorer.py | save_to_database() method | +45 |
| src/cluster_detector.py | save_to_database() method | +47 |
| src/reporting.py | EEAT + cluster sections, Excel sheets | +45 |
| src/database.py | 3 new tables + indices | +72 |
| src/step_dag.py | NEW: DAG class | 167 |
| src/third_party_crawlers.py | NEW: Ahrefs + Moz skeletons | 151 |
| src/main.py | config passing to ReframeEngine | +5 |
| tests/test_step_dag.py | NEW: 13 tests | 123 |
| docs/DATA_PERSISTENCE_MAP_v3.md | NEW: schema documentation | 290 |
| docs/SPEC_COVERAGE_REPORT_v3.md | NEW: this report | 456 |

**Total New Code:** ~888 lines (implementation + tests + docs)

---

## Sign-Off

**As signed off 2026-05-02:**

**Specification v3 Implementation:** ✅ COMPLETE
**Test Coverage:** ✅ 158/158 PASSING (100%)
**Backwards Compatibility:** ✅ VERIFIED
**Technical Debt Remediation:** ✅ 3/3 ADDRESSED
**Feature Authorization:** ✅ 3/3 INTEGRATED
**Database Schema:** ✅ 3 NEW TABLES CREATED

**Ready for:** Spec writing session → Implementation by coding agent
**Date Generated:** 2026-05-02

**As verified against the code 2026-11-16:**

| Claim | Verified |
|---|---|
| v3 implementation complete | Yes for the Gap Refinements and Feature Authorizations |
| Test coverage | **701** by exit code (`pytest -q`, both suites), not 158 |
| Technical debt 3/3 addressed | **1/3.** Debt 1 (hardcoded editorial content) is done. Debt 2 describes two live tables as deprecated. Debt 3's DAG is built but unwired, and the config it reads has since been deleted. See Part 3 |
| 3 new tables created | **22 tables exist**, of which 2 (`market_gaps`, `semantic_audit_results`) have no writer. See `docs/DATA_PERSISTENCE_MAP_v3.md` §1 |
| Third-party skeleton 4/4 | The skeleton exists as declared future work, but has no tests and no caller; `IMPLEMENTATION_PLAN_v3.md` had named a test file that does not exist |

Since this sign-off, the 2026-11-04 review's chunks C1–C4 and the compete half
of chunk X have changed behaviour described in Parts 1 and 2. Where this report
and `docs/FEATURE_GUIDE.md` §9 disagree, **the FEATURE_GUIDE is current**.
