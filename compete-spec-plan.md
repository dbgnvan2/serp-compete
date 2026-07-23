# Implementation Plan — `compete-spec.md` (Competitive AI-Era Visibility)

**Status: AWAITING APPROVAL — no implementation code written yet.**
**Spec:** `compete-spec.md` (+ `RECONCILIATION_CHANGES.md`) · **Date:** 2026-07-22 ·
**Author:** Claude Code (plan phase)

This plan maps every in-scope feature and acceptance criterion (spec IDs verbatim) to
the automated test that will verify it, in a dependency-ordered build sequence. It
honors the two directives given up front: **extend, don't rebuild** (Discover D5 and
Compete SC-1 already ship — build the comparative layer on top), and **the D5 export
lands before C1**.

---

## 1. Scope

| ID | Feature | Spec status | This plan |
|---|---|---|---|
| **AV-EXPORT** (Discover) | Export `brand_mentions`/`ai_citations` for Compete to consume | new sub-item of D5 (extend-only) | **Phase 0 — build (in serp-discover)** |
| **C1 / SC-3** | AI Answer Share-of-Voice vs competitors | new (consume, don't re-probe) | build |
| **C2 / SC-4** | Barbell Positioning Diagnostic | partially-exists | build |
| **C3 / SC-5** | Branded-Demand Competitive Benchmark | new | build |
| **C4 / SC-6** | SERP Overlap & Differentiation Gap | partially-exists (the spine) | build |
| **C6 / SC-8** | Reputation-Risk / Site-Reputation-Abuse Radar | partially-exists | build |
| **C5 / SC-7** | Off-Platform Share-of-Attention | **DEFERRED** | **NOT built** (interface only, already documented) |

**Out of scope / must not touch (already shipped — extend only):** `GeoProfiler`,
`EEATScorer`, `ClusterDetector`, the Systemic-Vacuum core (`semantic.py` +
`scoring_logic.py` + `identify_strategic_openings`), `ReframeEngine`, `enrichment.py`.
Discover's AI-probe runner (`probe_ai_visibility.py` and the probe classes) is
**consumed, never forked**.

---

## 2. Global adaptations (apply to every Compete feature)

These are decided by the "reconcile to the real repo" rule; they correct the spec's
data models against ground truth:

1. **`competitor_id` → `domain`.** The spec's new tables all FK an invented
   `competitor_id`. The real `competitors` table is **`domain TEXT PRIMARY KEY`**
   (database.py:42–46); `competitor_metadata` and `competitor_metrics` also key on
   `domain`. **Every new table below keys competitors by `domain TEXT`**, not
   `competitor_id`. (This mirrors how `traffic_magnets`/`geo_profiles` already store
   `domain`/`url`.)
2. **New tables the existing way.** Add each `CREATE TABLE IF NOT EXISTS` in
   `database.py::_create_tables()` (+ defensive `ALTER TABLE … ADD COLUMN` in
   `try/except sqlite3.OperationalError` for later columns), with a `save_*` method —
   exactly like the SC-1 `geo_profiles` work. No ORM.
3. **Config, not constants.** All new weights/thresholds/vocab go in the repo-root
   `shared_config.json` (new blocks `positioning`, `branded_demand`, `serp_overlap`,
   `risk_signals`, `sov`) read with hardcoded fallbacks, following the
   `scoring_logic.py` pattern. No magic numbers in Python.
4. **`estimation_basis` label on every competitor metric** (own = GSC/first-party;
   competitor = SERP/LLM/volume-estimated) per the cross-cutting requirement.
5. **Themed-statistic labeling.** Barbell / site-reputation-abuse / "search is
   everywhere" render as **framings**, with caption strings stored in config.
6. **Reporting.** Each feature adds one `src/reporting.py` section (markdown) + one
   Excel sheet, gated `if not df.empty`, in the SC-1 style. A missing upstream input
   → `data_available: false`, a stated "not available" line, **never a crash or a
   fabricated row**.
7. **Recompute-from-stored-raw.** Adding/removing a competitor recomputes
   shares/cells/quadrants from stored snapshots — **no new external calls**.
8. **Git hygiene.** Confirm `client_secret_*.json` gitignored before any commit; never
   `git add .`; stage explicit paths only.

---

## 3. Cross-repo structure & dependency graph

Phase 0 is in **serp-discover** (separate repo, own `CLAUDE.md`, own test runner
`python3 -m pytest test_*.py tests/ -q`, business-logic tests must not need tkinter).
Everything else is in **serp-compete** (`PYTHONPATH=. pytest tests/`).

```
                Phase 0: AV-EXPORT (serp-discover)
                        │  (hard dependency)
                        ▼
   C2/SC-4 ──────────► C1/SC-3        C4/SC-6        C3/SC-5
 (positioning)      (AI SoV)      (overlap spine)  (branded)
      │                                  ▲              ▲
      │ (focus/cluster reuse)            │ soft:        │ soft:
      ▼                          D4 commodity    D2 branded anchor
   C6/SC-8                       (else local     (else NULL,
 (risk radar)                     proxy)          labeled)
```

**Hard dependency:** only **C1 requires Phase 0** (Discover's `brand_mentions`/
`ai_citations` export). **Soft dependencies** (spec already specifies a graceful
fallback, so they do NOT block): C4's `commodity_score` (Discover D4 → else local
entity-dominance proxy) and C3's own-site branded anchor (Discover D2 → else NULL,
labeled). C6 reuses C2's focus/cluster math, so **C2 precedes C6**.

**Recommended build order:** `Phase 0 → C4 → C2 → C1 → C3 → C6`
(C4 first: it's the wired-in spine and mostly reuse; C2 before C6; C1 after Phase 0.)

**Delivery:** I propose building **one phase per session**, each ending in its own
`csdp` (commit → learning-qa sweep → docs → push) with a status report, so you review
incrementally rather than one giant PR. Each phase is independently shippable.

---

## 4. Phase 0 — AV-EXPORT (serp-discover): AI-visibility export

**Goal:** give Compete a stable, decoupled JSON contract for Discover's already-computed
`brand_mentions` + `ai_citations` (+ optional `answer_sentiment`, `ai_visibility_index`),
mirroring the existing `handoff_writer.build_competitor_handoff → output/*.json` pattern.
**Extend-only:** reuse the rows the probe run already wrote; run no new probes.

**Design (grounded in the recon):** Discover's 5 AI-visibility tables are keyed by
`run_ts` + `engine` (no `run_id`), created lazily, and may be absent. There is **no**
JSON export today — only the tables + a markdown report. Add:
- New `ai_visibility_export.py`: `build_ai_visibility_export(db_path, run_ts=None) → dict`
  (latest `run_ts` if unspecified) + `write_ai_visibility_export(...) → path` to
  `output/ai_visibility_export_<slug>_<ts>.json`.
- New `ai_visibility_export_schema.json` (draft-07); validate on write, like
  `handoff_schema.json`.
- Invocation: a `--export` flag on `probe_ai_visibility.py::main()` (and/or a 3-line
  `export_ai_visibility.py`) that serializes from the DB (or the in-memory `enrichment`
  dict at `probe_ai_visibility.py:1033` when run inline). **Reads stored rows only.**
- Payload: `{schema_version, source_run_ts, client_name, engines:[…], brand_mentions:[{engine,brand,mention_count,questions_total,is_client,source}], ai_citations:[{engine,url,domain,category,brand,is_client,cite_count}], answer_sentiment?:[…], data_available: true}`.
- Absent/empty tables → `{data_available: false, …}` written cleanly (no crash).

| Criterion | Verifying test (new) |
|---|---|
| **AV-EXPORT.1** serializes brand_mentions + ai_citations for the latest `run_ts`, grouped by engine, schema-valid | `tests/test_ai_visibility_export.py::test_export_shape_and_schema` |
| **AV-EXPORT.2** absent/empty AI-visibility tables → `data_available:false`, clean exit | `::test_absent_tables_data_unavailable` |
| **AV-EXPORT.3** export reuses stored rows only — no probe/LLM/network call | `::test_export_makes_no_network_calls` (monkeypatch probe classes → assert un-called) |
| **AV-EXPORT.4** `is_client`/brand attribution byte-match the source tables (no re-detection) | `::test_is_client_parity_with_tables` |

**Files (serp-discover):** new `ai_visibility_export.py`, `ai_visibility_export_schema.json`,
`tests/test_ai_visibility_export.py`; small edit to `probe_ai_visibility.py` (export flag);
update `docs/spec_coverage.md`. **Commit trailer:** `Spec: discover AV-EXPORT` (Discover's
scheme). Reuse `brand_mentions`/`citation_table` detectors — do not re-implement.

---

## 5. Phase C4 / SC-6 — SERP Overlap & Differentiation Gap (the spine)

**Reuse (don't restart):** wire the **built-but-unwired** `analysis.py::AnalysisEngine`
(`find_keyword_intersection`, `check_feasibility`) into `run_audit()` (today imported,
never instantiated); fold in the live `identify_strategic_openings` systemic-vacuum list
rather than duplicating it; read positions from `competitor_metrics`.

**New:** `src/serp_overlap.py` — build the who-ranks-where matrix + deterministic cell
classification. New table `serp_overlap(run_id, keyword, snapshot_date,
competitors_ranking_json TEXT, self_position INT, overlap_count INT, commodity_score REAL,
cell TEXT, config_ref TEXT)`. `commodity_score` from Discover D4 export **if present, else
a local entity-dominance proxy** (soft dep). Cells: `shared_commodity | shared_defensible
| exclusive_self | exclusive_competitor | absent`. Report: keyword×competitor matrix +
cell filters + action queues (`exclusive_competitor`, `shared_commodity`); Excel sheet.

| Criterion | Verifying test (new) |
|---|---|
| **SC-6.1** cell classification deterministic given snapshot + commodity + config top-N | `tests/test_serp_overlap.py::test_cell_classification_deterministic` |
| **SC-6.2** `exclusive_self` requires zero competitors in top-N | `::test_exclusive_self_requires_zero_competitors` |
| **SC-6.3** volume rollups match member keyword volumes | `::test_volume_rollup_matches_members` |
| **SC-6.4** `AnalysisEngine.find_keyword_intersection` wired into `run_audit()` + covered beyond `test_analysis.py` | `::test_analysis_engine_wired_in_run_audit` (extract the wiring into a testable helper à la `enrichment.py`, assert it's invoked) + keep `test_analysis.py` |

---

## 6. Phase C2 / SC-4 — Barbell Positioning Diagnostic

**Reuse:** `EEATScorer`/`eeat_scores` (authoritativeness axis) + Moz PA + top-10 count
from `competitor_metrics`; `ClusterDetector`/`cluster_results` + tier concentration from
`semantic.py`/`scoring_logic.py` (focus axis); `tag_competitor_position` labels for
cross-checking.

**New:** `src/positioning.py` — `authority_score` (0–100 composite) + `focus_score`
(`1 − normalized_entropy(tier/topic distribution)`) → `quadrant`. New table
`positioning(run_id, domain, computed_at, authority_score REAL, focus_score REAL,
quadrant TEXT, rationale_json TEXT)`. Thresholds in `shared_config.json → positioning`.
Thin/new domains → `emerging`/`insufficient_data`, **never silently `middle`**. Report:
2×2 (x=focus, y=authority) as a markdown quadrant table + per-domain rationale, **client
always plotted**, danger-zone (middle) shaded, framework caption; Excel sheet.

| Criterion | Verifying test (new) |
|---|---|
| **SC-4.1** client always plotted | `tests/test_positioning.py::test_client_always_present` |
| **SC-4.2** thresholds from config | `::test_thresholds_read_from_config` |
| **SC-4.3** concentrated+low-auth→`niche_owner`; broad+high-auth→`authoritative`; low/low→`middle` | `::test_quadrant_assignment` (parametrized 4 corners) |
| **SC-4.4** rationale contains the driving numbers | `::test_rationale_json_has_numbers` |
| (guard) thin/new domain → `emerging`/`insufficient_data`, not `middle` | `::test_thin_domain_not_silently_middle` |

---

## 7. Phase C1 / SC-3 — AI Answer Share-of-Voice  *(requires Phase 0)*

**Consume, don't probe.** New optional input in `shared_config.json → sov.discover_export_path`
(else auto-discover latest `ai_visibility_export_*.json` beside the handoff); absent →
`data_available:false`. New `src/sov_analyzer.py`: map export brands/domains to the run's
competitor set (client via `client_brand_names`), compute per engine:
`mention_share_i = mentions_i / Σ mentions_all` (unlisted → **"other"**), `citation_share_i`
over cited domains, `presence_rate_i`, `rank_in_answer`. New tables (domain-keyed):
`sov_probe_result(run_id, ai_probe_ref, domain, mentioned, mention_count, cited,
cited_urls_json, sentiment, sentiment_score, rank_in_answer)` and `sov_daily(run_id,
engine, date, domain, mention_share, citation_share, avg_sentiment, presence_rate)`. Report:
"Competitive AI Share-of-Voice" — per-engine leaderboard (client vs competitors) +
"cited-but-you're-not" gap list + rolling averages; Excel sheet. **One answer per prompt×engine
evaluated against all competitors** (inherited from Discover's rows — no per-competitor probes).

| Criterion | Verifying test (new) |
|---|---|
| **SC-3.1** shares within an engine sum to ~100% (unlisted → "other") | `tests/test_sov_analyzer.py::test_shares_sum_to_100_with_other` |
| **SC-3.2** one engine failing doesn't block others | `::test_one_engine_absent_others_computed` |
| **SC-3.3** adding a competitor recomputes from stored answers, no re-probe | `::test_recompute_on_added_competitor_no_network` |
| **SC-3.4** per-competitor sentiment uses only that competitor's mention sentences | `::test_sentiment_scoped_per_competitor` |
| (input guard) export absent → `data_available:false`, no crash | `::test_export_absent_data_unavailable` |

---

## 8. Phase C3 / SC-5 — Branded-Demand Competitive Benchmark

**Reuse:** `client_brand_names` (handoff) + `derive_brand_name()`; `search_volume` reads
in `infiltrator.py`/`competitor_mining.py` (DataForSEO). **New:** `src/brand_demand.py` —
per competitor, branded query set = brand + config modifiers (`login/pricing/reviews/vs`,
editable), sum DataForSEO `search_volume` → `branded_search_volume`, share + period-over-
period growth. Own domain only: GSC-anchored branded share from **Discover D2 export if
present, else `NULL`** (labeled). New table `brand_demand_bench(run_id, domain, period,
branded_search_volume INT, branded_volume_share REAL, branded_growth REAL,
est_branded_click_share REAL, estimation_basis TEXT)`. Report: ranked bars + growth column,
competitor figures labeled volume-estimated; Excel sheet. DataForSEO mocked in tests.

| Criterion | Verifying test (new) |
|---|---|
| **SC-5.1** own GSC-anchored figure rendered distinctly from volume-estimated competitor figures | `tests/test_brand_demand.py::test_own_vs_estimated_labeling` |
| **SC-5.2** branded query expansion inspectable/editable (from config) | `::test_modifiers_from_config` |
| **SC-5.3** growth computed over equal-length periods | `::test_growth_equal_length_periods` |
| **SC-5.4** generic brand names → manual pruning honored | `::test_generic_brand_pruned` |

---

## 9. Phase C6 / SC-8 — Reputation-Risk Radar  *(requires C2)*

**Reuse:** `get_volatility_alerts` (ranking_volatility feed), `get_feasibility_drift`
(Fragile Magnet), `velocity_module.VelocityTracker`/`market_history` (visibility series);
**C2's focus/cluster analysis** for the topical-mismatch signal. **New:** `src/risk_radar.py`
— `visibility_cliff` (step-change > X% over N days), `parasite_subfolder`/`affiliate_arm`
(topical mismatch **AND** commercial-intent keywords — subfolder name is a hint, not proof),
`ranking_volatility`, `thin_section`; severity from magnitude. New table `risk_signal(run_id,
domain, detected_at, signal_type TEXT, severity TEXT, evidence_json TEXT)`. Thresholds +
commercial-intent vocab in `shared_config.json → risk_signals`. Report: risk feed +
**prominent own-site warning** separated from competitor intel; label **"pattern detections,
not confirmed Google penalties."**

| Criterion | Verifying test (new) |
|---|---|
| **SC-8.1** synthetic 60% visibility drop over 30 days → `visibility_cliff` **high** with drop % in `evidence_json` | `tests/test_risk_radar.py::test_visibility_cliff_synthetic_60pct` |
| **SC-8.2** parasite detection requires topical mismatch **+** commercial intent, not subfolder name alone | `::test_parasite_requires_mismatch_and_intent` + adversarial `::test_subfolder_name_alone_does_not_flag` |
| **SC-8.3** own-site signals separated from competitor signals | `::test_own_site_signals_separated` |

---

## 10. Cross-cutting acceptance (tested once, referenced by all)

| Requirement | Verifying test |
|---|---|
| Own vs estimated — every competitor metric carries `estimation_basis` | `test_estimation_basis_labels` (C1 + C3 outputs) |
| Recompute from stored raw — no external calls on competitor add/remove | asserted in `SC-3.3` + `SC-6` recompute tests (monkeypatch network → assert un-called) |
| Config-driven — thresholds read from `shared_config.json` with fallbacks | per-feature `*_thresholds_from_config` tests |
| Themed-statistic labeling — framing captions present | `test_themed_framework_captions` (C2 barbell, C4 commodity) |

---

## 11. Criteria that cannot be fully code-tested (human-review proposals)

Per the "flag untestable criteria" rule:

1. **Visual legibility** of the C2 2×2 quadrant, C4 keyword×competitor heatmap, and C3
   ranked bars. These render as **markdown tables / Excel sheets** (no chart engine), so
   automated tests cover the *data, classification, and caption strings*; the *visual
   readability* of the rendered section is **human review** (eyeball one real report).
2. **LLM non-determinism / rolling averages (SC-3).** The averaging math is unit-tested on
   fixtures; the *real-world stability* of shares across probe runs is inherent to the LLMs
   and can only be observed, not asserted — **human review** of ≥2 real Discover exports.
3. **Live cross-repo integration (Phase 0 → C1; D2/D4 soft deps).** Unit tests use fixture
   export JSON. The *end-to-end* Discover-run → export → Compete-consume path is
   integration-only — **human review**: run a real Discover probe+export, then a Compete
   audit, and confirm the SoV section populates (and that absent exports degrade to
   `data_available:false`).
4. **Heuristic calibration of `parasite_subfolder`/`affiliate_arm` (SC-8.2)** on real
   competitor sites. The rule (mismatch + commercial intent) is tested on synthetic
   fixtures incl. an adversarial subfolder-name-only case; whether the thresholds flag the
   *right real domains* is **human review** on a live run before the signal is trusted.

---

## 12. Open decisions for your approval

1. **D5 export shape (Phase 0).** I recommend a **schema-validated JSON export in
   Discover's `output/`** mirroring `competitor_handoff_*.json` (decoupled, versioned,
   testable) over having Compete read Discover's SQLite directly (couples the two DBs,
   fragile to Discover schema changes). Confirm?
2. **Build cadence.** One phase per session, each with its own `csdp` + status report, in
   the order `Phase 0 → C4 → C2 → C1 → C3 → C6`. Confirm, or reprioritize.
3. **`competitor_id` → `domain`** adaptation (all new tables) — confirming this is the
   intended reconciliation (it matches every existing competitor table).
4. **Soft-dependency fallbacks** are acceptable for now: C4 uses a local commodity proxy
   until Discover D4 is exported; C3 leaves the own-site branded anchor `NULL` (labeled)
   until Discover D2 is exported. (These can be upgraded when D2/D4 exports exist.)

---

## 13. Definition of done (per phase)

Each phase: new table(s) + `save_*` in `database.py`; new `src/<feature>.py`; wired into
`run_audit()` (or the relevant entry point) with the SC-1 `enrichment.py`-style testable
seam; new `reporting.py` section + Excel sheet; new config block with fallbacks; the tests
above green; `PYTHONPATH=. pytest tests/` + root suite green; `learning-qa` sweep clean;
`suite_enhancement_spec_SERPCOMPETE_v1.md` + `docs/SPEC_COVERAGE_REPORT_v3.md` updated with
the new SC-ID and its `Spec:`/`Tests:` references; committed (explicit paths) and pushed.

**No implementation begins until this plan is approved.**
