# Serp Compete — Build Spec (Competitive AI-Era Visibility)

**For:** Claude Code implementation in the existing `serp-compete` repo. **Backend:** Python.
**Assumed data access:** SerpAPI / DataForSEO SERP + rank data, Google Search Console (own site only), LLM API (OpenAI today; Gemini/Anthropic/Perplexity only if a probe runner is added — see C1). Infrastructure out of scope — *functionality and logic only*.

> **Reconciliation note (2026-07-22).** Revised against the real repo. The draft assumed a REST/ORM/Pydantic web app; the reality is a **Python batch/CLI tool** with a thin **Streamlit** orchestration wrapper. Code lives under `Serp-compete/src/` (note the nested package: repo root holds `CLAUDE.md`, `README.md`, config JSON, `living_systems_intel.db`, `docs/`; Python is in `Serp-compete/src/…`). Persistence is raw `sqlite3` via `src/database.py` (`class DatabaseManager`). Invented names below are replaced with real ones; each feature carries a build-status marker. See `RECONCILIATION_CHANGES.md` for the full diff.

---

## Repo conventions this spec must follow

- **No web layer, no ORM.** Entry point is `Serp-compete/src/main.py::run_audit()` (driven by `run_audit.sh`, which finds the latest `competitor_handoff_*.json` from serp-discover and runs `python3 src/main.py`). The GUI is **Streamlit** (`run_gui.sh` → `streamlit run Serp-compete/src/orchestrator.py`), a thin wrapper that loads/saves `shared_config.json` and shells out to the audit — **not tkinter, not a web API**. No Flask/FastAPI/SQLAlchemy/Pydantic anywhere in `src/`. Validation is `jsonschema` against `handoff_schema.json`.
- **DB is raw `sqlite3`.** `src/database.py::DatabaseManager` creates tables in `_create_tables()` via `CREATE TABLE IF NOT EXISTS` + defensive `ALTER TABLE … ADD COLUMN`. The **active** DB path is `technical.database_path` in `shared_config.json` = `living_systems_intel.db` (repo root); `Serp-compete/competitor_history.db` is the legacy fallback default. Add new tables the same way; do not introduce an ORM.
- **Config is JSON, not a DB table.** Editorial content + scoring weights live in the repo-root `shared_config.json` (blocks: `client`, `technical` incl. `scoring_weights`/`penalty_thresholds`/`feasibility_threshold`/`score_normaliser`/`database_path`, `stop_words`, `clinical` tier vocab, `filtering`, `eeat_weights`, `stock_image_hosts`, `credential_list`, `case_study_triggers`, `geo_signals`, `cluster_thresholds`, `clinical_pivots`, `handoff`, `orchestrator`, `step_dag`, `eeat_client_messaging`). Fallbacks: `manual_targets.json` (developer competitor list), `omitted_domains.txt`, `clinical_dictionary.json`. **No `scoring_config` table, no `config_version` field.** New weights/thresholds go into `shared_config.json`; `scoring_logic.py` already reads them with hardcoded fallbacks — follow that pattern.
- **`shared_config.json` is the cross-tool contract** read by both serp-discover and serp-compete, but per the SC-1 decision **apps stay independent** (X-1 suite-orchestration was dropped). Each repo keeps its own copy; do not force a shared client profile.
- **Spec-ID system.** Commits carry `Spec: suite_enhancement_spec_v1.md#<item>`. The self-contained repo spec is `suite_enhancement_spec_SERPCOMPETE_v1.md` (repo root). Existing IDs: **SC-1** (Competitor GEO/extractability — SHIPPED, sub-criteria SC-1.1–SC-1.4), **SC-2** (competitor CWV — declined/out of scope), **X-1** (dropped), **X-4** (backlink-exclusion docs note). Older code comments use "Gap N"/"Revision N"/"Phase N" labels. **Give the features in this spec their own IDs** (proposed `SC-3 … SC-8` below, one per surviving draft feature). Coverage/status docs live under `docs/` (`docs/SPEC_COVERAGE_REPORT_v3.md`, `docs/tool2_review_bundle/Serp-compete_spec.md`).
- **Security.** `client_secret_*.json` OAuth files are in the repo root — verify `.gitignore` covers them before any commit (per `CLAUDE.md`). Never `git add .`.
- **Tests & venv.** venv at repo root; run `PYTHONPATH=. pytest tests/` (there is a `Serp-compete/tests/` and a second root `tests/`). External calls mocked. Add tests beside the existing `test_geo_profiler.py` / `test_wiring.py` / `test_analysis.py` etc.
- **Themed statistics are reference framings.** The barbell, "site-reputation abuse", "search is everywhere" are strategic framings — render as frameworks, not measured facts. Store any constants in `shared_config.json`, not code.

**Core object — reuse what exists, don't invent `competitor_set`.** The draft's `competitor_set`/`competitor` tables do not exist. The real competitor model is: the ingested **handoff** defines `client_domain` + `client_brand_names` + `targets[]`; competitors are persisted in the **`competitors`** and **`competitor_metadata`** tables (with `market_position` labels), and per-run metrics in **`competitor_metrics`** / **`competitor_history`**. The client's own domain is `client.domain` in `shared_config.json`. Read every "competitor set" reference below as "the ingested target set for this run".

---

## Handoff ingestion (the real integration point — already-exists)

serp-discover → serp-compete is wired: `main.py::get_latest_market_data()` → `find_latest_handoff_file()` (globs `competitor_handoff_*.json` at repo root) → `jsonschema.validate` against `handoff_schema.json` (hard-fail `sys.exit(1)`) → `convert_handoff_to_targets()`. Fallback order: handoff → legacy `market_analysis_*.json` (DeprecationWarning) → `manual_targets.json`. Schema (draft-07) requires `schema_version, source_run_id, source_run_timestamp, client_domain, client_brand_names, targets, exclusions`; each target requires `url, domain, rank, entity_type, content_type, title, source_keyword, primary_keyword_for_url`. Sample: `competitor_handoff_couples_therapy_20260502_1634.json`. **Any feature below that needs competitor brand terms or SERP positions should read them from the handoff / `competitors` table, not a new source.**

---

## C1 — AI Answer Share-of-Voice vs Competitors · **new** (proposed SC-3)

**Problem.** Not "do I rank" but "when someone asks the models a category question, whose brand and sources come back — mine or my competitors'?" Measure share of mentions, citations, and comparative sentiment across engines.

**Reality check.** serp-compete does **not** probe any AI answer engine today. The only LLM use here is OpenAI `gpt-4o` in `src/reframe_engine.py` (Bowen reframes — content generation, not measurement). **The AI-probe runner lives in serp-discover** (`probe_ai_visibility.py` with `ClaudeProbe`/`GeminiProbe`/`ChatGPTProbe`/`PerplexityProbe`, plus `brand_mentions.py`, `citation_table.py`, `answer_sentiment.py`, `aivi.py`).

**Integration decision — DECIDED (product owner, 2026-07-22): CONSUME, do not re-probe.** serp-discover owns the single AI-probe runner (`probe_ai_visibility.py`); Compete adds only the *comparative* layer on top of Discover's already-computed outputs. This honors the "apps stay independent" decision and the existing one-way handoff — no runner is forked or duplicated.

Concretely: serp-discover's `brand_mentions` leaderboard scores mentions per brand (with `is_client`) over the client's persona questions, and `ai_citations` records cited domains per engine. Compete reads those rows — via a new optional input path in `shared_config.json` pointing at Discover's export (the analysis JSON and/or the `brand_mentions`/`ai_citations` tables), following the same `data_available: false` (no crash, no fabricated data) convention used elsewhere in the suite — and computes competitor **share** from the competitors already in scope for the run.

> **Rejected alternative (recorded for traceability):** porting `probe_ai_visibility.py` + detectors into Compete as a shared module. Rejected because it duplicates the most-built part of Discover and contradicts the single-runner design. Revisit only if the owner later wants Compete to run without Discover.

**Data model (new tables in `src/database.py`; populated from consumed Discover outputs).**
```
sov_probe_result (run_id, ai_probe_ref, competitor_id,
                  mentioned INT, mention_count INT,
                  cited INT, cited_urls_json TEXT,
                  sentiment TEXT, sentiment_score REAL,
                  rank_in_answer INT)
sov_daily        (run_id, engine, date, competitor_id,
                  mention_share REAL, citation_share REAL,
                  avg_sentiment REAL, presence_rate REAL)
```
`competitor_id` FKs the existing `competitors` table. Reuse Discover's detectors (mention = brand-term/domain match, not substring; citation = registrable-domain) — do not re-implement them differently.

**Core logic.** One answer per category prompt × engine; evaluate **all** competitors against that single answer (never per-competitor probes). `mention_share_i = mentions_i / Σ mentions_all`; `citation_share_i` over cited URLs; `presence_rate_i`; `rank_in_answer` = order of first appearance.

**Access surface.** A "Competitive AI Share-of-Voice" section in the audit report (`src/reporting.py`) + Excel sheet: leaderboard (client vs competitors) per engine with mention/citation/sentiment/presence + a "cited-but-you're-not" gap list. Show rolling averages (LLM non-determinism).

**Acceptance criteria.** Shares within an engine sum to ~100% (unlisted → "other"). One engine failing doesn't block others. Adding a competitor recomputes shares from stored answers without re-probing. Per-competitor sentiment uses only that competitor's mention sentences.

---

## C2 — Barbell Positioning Diagnostic · **partially-exists** (proposed SC-4)

**Problem.** Winners are large-and-authoritative or small-and-niche; the undifferentiated middle loses. Classify each domain onto the barbell and flag "danger zone" domains.

**What already exists (reuse — do not rebuild the ingredients).**
- **Discrete positioning labels:** `database.py::tag_competitor_position()` writes `market_position` to `competitor_metadata` — **"Volume Scaler"** (traffic>1000 & medical>15), **"Direct Systemic"** (tier_3>0), **"Generalist"** (tier_2>10), else "Unknown" — each paired with a `strategy` string.
- **Authority proxy:** `src/eeat_scorer.py::EEATScorer.score_page()` → experience/expertise/authoritativeness/trustworthiness sub-scores (config `eeat_weights`), table `eeat_scores`. Authoritativeness uses Moz PA as the DA proxy.
- **Focus proxy:** `src/cluster_detector.py::ClusterDetector.analyze_domain()` → `ClusterResult` (internal-link graph, `hub_candidates` via `cluster_thresholds.hub_in_degree_threshold`, `cluster_signal`, in-degree stats), table `cluster_results`. Plus the `clinical`/tier vocab concentration from `semantic.py` + `scoring_logic.py`.

**What is new.** Combining an authority axis (EEAT/DA) and a focus axis (cluster/tier concentration) into a **2×2 quadrant** with an `emerging`/`insufficient_data` handling. Today there is no quadrant model, only the discrete labels.

**Data model (new table).**
```
positioning (run_id, competitor_id, computed_at,
             authority_score REAL,   -- 0..100 from eeat_scores + Moz PA + top-10 count
             focus_score REAL,       -- 0..100 = 1 - normalized_entropy(topic/tier distribution)
             quadrant TEXT,          -- authoritative | niche_owner | middle | emerging | insufficient_data
             rationale_json TEXT)
```

**Core logic (heuristic; thresholds in `shared_config.json → positioning`).** `authority_score` = normalized composite of EEAT authoritativeness + Moz PA + count of top-10 keyword rankings (from `competitor_metrics`). `focus_score = 1 - normalized_entropy(tier/topic distribution)` (reuse cluster/semantic outputs). Quadrant assignment with config thresholds; thin/new domains → `emerging`/`insufficient_data`, never silently `middle`. Store the driving numbers in `rationale_json`.

**Access surface.** A 2×2 scatter (x=focus, y=authority) with the client always plotted, danger-zone shaded, per-domain rationale + one-line implication. Caption as a strategic framework, not a measured law.

**Acceptance criteria.** Client always plotted. Thresholds from config. Concentrated + low-authority → `niche_owner`; broad + high-authority → `authoritative`; low/low → `middle`. Rationale contains the numbers.

---

## C3 — Branded-Demand Competitive Benchmark · **new** (proposed SC-5)

**Problem.** How does the client's brand-demand strength compare to competitors? You can't read competitors' GSC, so estimate from public signals.

**Reality check.** No branded-demand or branded-search-volume-per-competitor benchmark exists. `search_volume` is read only as a generic per-keyword ETV/volume proxy in `src/infiltrator.py` and `src/competitor_mining.py` (DataForSEO `keyword_info.search_volume`), never segmented into branded vs non-branded or aggregated per competitor brand. Brand names exist as identifiers (`client_brand_names` from the handoff; `derive_brand_name()` in `competitor_mining.py`) — reuse those; do not invent a new brand model.

**Data model (new table).**
```
brand_demand_bench (run_id, competitor_id, period,
                    branded_search_volume INT,
                    branded_volume_share REAL,
                    branded_growth REAL,
                    est_branded_click_share REAL)  -- own site only, from serp-discover GSC (D2), else NULL
```

**Core logic.** Build each competitor's branded query set from its brand name + auto-expanded modifiers ("<brand> login/pricing/reviews/vs"), editable per competitor. Sum DataForSEO search volume → `branded_search_volume`; compute share + period-over-period growth. For the **own** domain only, attach the GSC-anchored branded share from serp-discover D2 (via the handoff/export) and label competitor figures as volume-estimated, not click-measured.

**Access surface.** Ranked bars (client vs competitors) + a growth column; clearly label competitor numbers as search-volume estimates (`estimation_basis`).

**Acceptance criteria.** Own domain's GSC-anchored figure rendered distinctly from volume-estimated competitor figures. Branded query expansion inspectable/editable. Growth over equal-length periods. Generic brand names → manual pruning.

---

## C4 — SERP Overlap & Differentiation Gap · **partially-exists (this is the tool's spine)** (proposed SC-6)

**Problem.** Where do you and competitors collide on commoditized SERPs (shared AI-absorption risk), and where are you uniquely present (defensible)?

**What already exists (multiple implementations — unify, don't restart).**
- **Wired, live "differentiation gap":** `database.py::identify_strategic_openings(run_id)` — the **"Systemic Vacuum"** query: `traffic_magnets` with `systems_score == 0` OR `systemic_label == 'Surface-Level'`, top 5 by traffic. These become the Bowen reframe targets. This is the strategic core and runs in `run_audit()`. Rendered by `src/reporting.py` as "Strategic Targets: Systemic Vacuums".
- **Keyword-overlap gap engine (built but UNWIRED):** `src/analysis.py::AnalysisEngine.find_keyword_intersection(competitor_keywords, client_keywords)` (competitors' shared keywords minus client's) and `check_feasibility(client_da, competitor_da)` (feasible if `client_da+5 ≥ competitor_da`, else "Hyper-Local Pivot"). **`AnalysisEngine` is imported in `main.py` but never instantiated in `run_audit()`** — exercised only by `test_analysis.py`. Wiring this in is part of this feature, not a new build.
- **Offline competitor keyword gap:** `src/competitor_mining.py` (own `main()`, not in `run_audit`) → `competitor_keyword_gap.md`: top-100 ranked keywords per top competitor (DataForSEO `ranked_keywords/live`) minus the client's keyword CSV.
- **Fragility list:** `src/infiltrator.py::Infiltrator.run_infiltration()` → `infil_report.md` (competitor pages with high traffic + zero Bowen depth).

**What is new.** A single, wired **who-ranks-where matrix** with explicit cell classification (`shared_commodity` / `shared_defensible` / `exclusive_self` / `exclusive_competitor` / `absent`) that combines competitor positions with a commodity signal. Today the differentiation gap (systemic vacuum) is wired; the keyword-overlap matrix is scattered/unwired.

**Data model (new table; commodity input comes from serp-discover D4 via handoff/export, else compute a local proxy).**
```
serp_overlap (run_id, keyword, snapshot_date,
              competitors_ranking_json TEXT,   -- {competitor_id: position}
              self_position INT,
              overlap_count INT,
              commodity_score REAL,            -- from serp-discover D4 if available, else entity-dominance proxy
              cell TEXT,                        -- shared_commodity | shared_defensible | exclusive_self | exclusive_competitor | absent
              config_ref TEXT)
```

**Core logic.** Per keyword, record which target-set members rank top-N and at what position (from `competitor_metrics` / SERP data). Classify the cell (self + ≥2 competitors + high commodity → `shared_commodity`; self + competitors + low commodity → `shared_defensible`; only self → `exclusive_self`; only competitors → `exclusive_competitor`). Roll up counts per cell.

**Access surface.** A keywords × competitors matrix/heatmap with commodity shading + cell filters in `src/reporting.py`; default action queues = `exclusive_competitor` (rivals win, you're absent) and `shared_commodity` (differentiate or deprioritize). Fold in the existing systemic-vacuum list rather than duplicating it.

**Acceptance criteria.** Cell classification deterministic given snapshot + commodity + config top-N. `exclusive_self` requires zero competitors in top-N. Volume rollups match member keyword volumes. `AnalysisEngine.find_keyword_intersection` is wired into `run_audit()` and covered by more than `test_analysis.py`.

---

## C5 — Off-Platform Share-of-Attention Tracker · **DEFERRED — future todo** (proposed SC-7)

> **Status — DEFERRED (product owner, 2026-07-22).** Not in the current build. Recorded here as a future todo so the interface is designed for but not implemented now. **Do not implement in this pass.** The blocker is data access, not effort: this is the only feature needing sources beyond the three confirmed (SERP/rank, GSC, LLM APIs), and each platform is a paid/rate-limited provider — low ROI for one nonprofit until scale or budget changes (cf. the X-4 backlink-exclusion reasoning in `suite_enhancement_spec_SERPCOMPETE_v1.md`). Revisit trigger: the owner wants cross-platform presence tracking AND a provider budget is approved. When picked up, add it as `SC-7` with the design below.

**Problem.** "Search is everywhere" (YouTube, TikTok, Instagram, Reddit, podcasts, newsletters). Track presence/attention beyond Google, client vs competitors.

**Reality check.** No off-platform data sources exist (`youtube|tiktok|reddit|instagram|attention` → none in `src/`). `src/third_party_crawlers.py` is not a social tracker. Each platform needs its own provider (YouTube Data API, a social-data provider, Reddit API). When built, treat each platform as a pluggable adapter and do not block the rest of Compete on it. The design below is the *target interface*, retained for when the feature is un-deferred.

**Data model (new tables).**
```
attention_source (competitor_id, platform TEXT, handle TEXT, verified INT)
attention_metric_daily (attention_source_id, date, followers INT, engagement REAL,
                        mention_volume INT, source TEXT, is_stale INT)
attention_rollup (run_id, date, competitor_id, presence_platforms INT, attention_index REAL)
```

**Core logic.** Per platform, normalize to a 0–100 sub-score; `attention_index` = weighted mean across connected platforms (weights in `shared_config.json`). `presence_platforms` = count of verified active presences. Missing platform data → partial index + `coverage_pct`, never a hard failure.

**Access surface.** Cross-platform leaderboard + per-platform breakdown + diversification indicator; "not connected" for platforms without an adapter.

**Acceptance criteria.** Adding/removing an adapter changes `attention_index` composition without code changes. Partial data degrades gracefully. Client vs competitor in one view. Unverified handles excluded until confirmed.

---

## C6 — Reputation-Risk / Site-Reputation-Abuse Radar · **partially-exists** (proposed SC-8)

**Problem.** Flag competitors (and warn on the own site) showing patterns Google penalizes — parasite/affiliate sections on authoritative domains — and detect sudden visibility collapses.

**What already exists (volatility only — reuse).**
- `database.py::get_volatility_alerts(run_id)` — flags competitors whose avg SERP position shifts ≥3 places vs the previous run (JOIN on `competitor_metrics` across runs); rendered as "Volatility Alerts" in `reporting.py`.
- `database.py::get_feasibility_drift()` — "Fragile Magnet" (Moz PA drift < -2).
- `src/velocity_module.py::VelocityTracker` — market-velocity alerts (rank/DA drift), table `market_history`.

**What is new.** `visibility_cliff` step-change detection, `parasite_subfolder` / `affiliate_arm` structural detection, and a unified reputation radar. `cliff|parasite|reputation|penalty|subfolder` → the only "penalty" in code is the *scoring* penalty in `scoring_logic.py` (Surface-Level tier-2), unrelated to SERP penalties. (Note: dedicated volatility *visualization* lives in serp-discover's `metrics.py` + `visualize_volatility.py`, not here.)

**Data model (new table).**
```
risk_signal (run_id, competitor_id, detected_at,
             signal_type TEXT,   -- visibility_cliff | parasite_subfolder | affiliate_arm | thin_section | ranking_volatility
             severity TEXT,      -- low | medium | high
             evidence_json TEXT)
```

**Core logic (heuristics; thresholds in `shared_config.json`).** `visibility_cliff` = step-change drop beyond X% over N days on a domain's visibility series (build on the velocity/volatility data above). `parasite_subfolder`/`affiliate_arm` = a subfolder ranking for commercial/off-topic terms disproportionate to the domain's core clusters — reuse the C2 focus/cluster analysis for the topical-mismatch signal; require mismatch **and** commercial-intent keywords (subfolder name is a hint, not proof). `ranking_volatility` = feed from `get_volatility_alerts`. Severity from magnitude.

**Access surface.** A risk feed (competitor, signal, severity, evidence, date) + a prominent own-site warning when the client's domain trips a signal. Competitor cliffs = opportunity intel; own-site = warnings. **Label as pattern detections, not confirmed Google penalties.**

**Acceptance criteria.** A synthetic 60% visibility drop over 30 days → `visibility_cliff` high severity with the drop % in `evidence_json`. Parasite detection requires topical mismatch + commercial intent, not subfolder name alone. Own-site signals separated from competitor signals.

---

## Already-built features the spec must NOT re-propose (SC-1, shipped)

These exist and are wired (post the 2026-07-21 SC-1 fixes) — build on top of them, never re-spec them:
- **`src/geo_profiler.py` — `GeoProfiler`/`GeoProfile` (SC-1).** Per-competitor-page extractability from an already-scraped page (duck-typed, decoupled from spaCy): schema presence (`has_faq_schema`/`has_article_schema`/`has_localbusiness_schema`/`has_person_schema`/`has_org_schema`), credentialed authorship (`credential_list`), question-shaped headings (trailing `?` + interrogative opener, P7 fix), freshness, an `extractability_tier` (via `geo_signals` thresholds), and a `why_cited` rationale. Table `geo_profiles`. Rendered as "GEO / Extractability — Why Competitors Get Cited". Deferred-honest fields in `not_measured`.
- **`src/eeat_scorer.py` — `EEATScorer`/`EEATScore`.** Four heuristic dimensions, config `eeat_weights`, Moz PA as DA proxy, `score_confidence` + `caveat`. Table `eeat_scores`. Framed as proxies, not Google's EEAT (`eeat_client_messaging`).
- **`src/cluster_detector.py` — `ClusterDetector`/`ClusterResult`.** Internal-link graph over ≤3 scraped pages, `hub_candidates`, `cluster_signal`, with an N≤3 `resolution_caveat`. Table `cluster_results`.
- **"Systemic Vacuum" core.** `semantic.py::analyze_text` + `scoring_logic.py::calculate_weighted_score` → medical/tier-2/tier-3 counts, weighted `systems_score`, `systemic_label`; `identify_strategic_openings` selects the reframe targets.
- **Bowen reframe.** `src/reframe_engine.py::ReframeEngine.generate_bowen_reframe()` (OpenAI gpt-4o) using `clinical_pivots` + handoff PAA context.
- **Enrichment plumbing.** `src/enrichment.py` (fresh/carried-forward/cache-hit coverage, 429 circuit-breaker on `extraction_status`, `db.carry_forward_profile` allowlisted to `geo_profiles`/`eeat_scores`/`cluster_results`).

**Note for C2:** the GEO/EEAT/cluster engines currently compute per-competitor-page profiles but are not rendered as a side-by-side **client-vs-competitor delta** (SC-1.2 asks for this only opportunistically). The genuinely-new comparative value in this spec is the **comparison layer** (C1 SoV, C2 quadrant, C4 overlap matrix) on top of the existing single-page engines — not the engines themselves.

---

## Boundary note (Compete vs Discover)

The draft's **Compete = comparative** framing holds. Confirmed re-assignments/clarifications vs the draft:
- **C1's probe runner is not here.** AI-engine probing lives in serp-discover (`probe_ai_visibility.py`). **Decided:** C1 consumes Discover's mention/citation outputs (`brand_mentions`/`ai_citations`) — it does not fork or port the runner. This is the one integration point the draft got structurally right ("reuse D5's runner") but pointed at an invented `ai_probe` table instead of the real `ai_visibility_probes`/`brand_mentions`/`ai_citations`.
- **Own-site branded share (C3's anchor) comes from Discover D2**, via the handoff/export — Compete cannot read the client's GSC directly beyond what `gsc_performance.py` already does.
- Everything else in C1–C6 is correctly comparative and stays in Compete.

---

## Cross-cutting requirements (Compete)

- **One probe, many competitors:** never per-competitor LLM probes when one category answer serves all (C1).
- **Own vs estimated:** own-domain metrics use first-party GSC (from Discover) where available; competitor metrics are SERP/LLM/volume-estimated and must carry an `estimation_basis` label in every output.
- **Recompute from stored raw:** adding/removing a competitor recomputes shares/cells from stored snapshots/answers without new external calls.
- **Config-driven, reproducible:** all new weights/thresholds in `shared_config.json` with hardcoded fallbacks (existing `scoring_logic.py` pattern); no magic numbers in Python. There is no `config_version` today — if run-stamping is wanted, store the weights used alongside the row.
- **Themed-statistic labeling:** barbell, site-reputation-abuse, "search is everywhere" are industry framings, labeled as such — not measured facts about the client's market.
- **Security & git hygiene:** confirm `client_secret_*.json` is gitignored before committing; never `git add .`.
