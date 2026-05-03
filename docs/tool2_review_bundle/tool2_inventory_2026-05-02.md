# Tool 2 (Serp-compete) — Current-State Inventory

**Date:** 2026-05-02  
**Location:** `/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete/`  
**Last Modified:** 2026-05-02

---

## Section A — Repository Structure

### Directory Tree (two levels deep)

```
Serp-compete/
├── src/
│   ├── __init__.py
│   ├── __pycache__/
│   ├── analysis.py
│   ├── api_clients.py
│   ├── cluster_detector.py
│   ├── competitor_mining.py
│   ├── database.py
│   ├── eeat_scorer.py
│   ├── gsc_performance.py
│   ├── infiltrator.py
│   ├── ingestion.py
│   ├── main.py
│   ├── orchestrator.py
│   ├── reframe_engine.py
│   ├── reporting.py
│   ├── scoring_logic.py
│   ├── semantic.py
│   ├── strike_mapper.py
│   └── velocity_module.py
├── tests/
│   ├── __init__.py
│   ├── __pycache__/
│   ├── conftest.py
│   ├── test_analysis.py
│   ├── test_api_clients.py
│   ├── test_cluster_detector.py
│   ├── test_config_integrity.py
│   ├── test_database.py
│   ├── test_eeat_scorer.py
│   ├── test_gsc.py
│   ├── test_ingestion.py
│   ├── test_main.py
│   ├── test_new_logic.py
│   ├── test_reframe_engine.py
│   ├── test_semantic.py
│   └── test_velocity.py
├── data/
│   ├── Key_domains.csv
│   └── dictionary.json
├── spec.md
├── GEMINI.md
├── audit_report.md
├── audit_report_2026-03-30_22-48-46.md
├── infil_report.md
├── strategic_briefing_run_2.md
├── strategic_briefing_run_3.md
├── strategic_briefing_run_4.md
├── strategic_briefing_run_8.md
├── strategic_briefing_run_9.md
├── strategic_briefing_run_11.md
├── token.json
├── .env
├── google-secrets.txt
├── run.sh
├── recalculate_scores.py
├── competitor_history.db
├── .pytest_cache/
├── .DS_Store
└── audit_results_run_*.xlsx (multiple files)
```

### Python Source File Line Counts

| File | Lines | Purpose |
|------|-------|---------|
| main.py | 460 | Entry point; orchestrates audit pipeline, handoff ingestion, reporting |
| semantic.py | 408 | Page structure extraction (Gap 2: ScrapedPage dataclass); entity scoring |
| database.py | 385 | SQLite persistence; 8 tables for longitudinal tracking |
| eeat_scorer.py | 338 | EEAT heuristic scoring (Gap 3) |
| gsc_performance.py | 366 | Google Search Console analysis; striking distance detection |
| api_clients.py | 157 | DataForSEO and Moz V2 API wrappers |
| competitor_mining.py | 161 | Extract top keywords from domains; gap analysis |
| orchestrator.py | 168 | Streamlit-based workflow UI for step selection/execution |
| reporting.py | 189 | Strategic briefing generation; markdown report assembly |
| velocity_module.py | 112 | Market velocity tracking; trend analysis |
| cluster_detector.py | 138 | Internal linking graph analysis (Gap 4) |
| reframe_engine.py | 110 | LLM-based Bowen reframing; hardcoded pivot mapping |
| strike_mapper.py | 66 | Map GSC "striking distance" keywords to publication drafts |
| scoring_logic.py | 80 | Tier 1/2/3 scoring formulas; penalty logic |
| infiltrator.py | 83 | Deprecated or exploratory module (small) |
| analysis.py | 34 | Keyword intersection and feasibility checks |
| ingestion.py | 35 | CSV domain validation and loading |
| __init__.py | 0 | Package marker |
| **TOTAL** | **3,290** | |

---

## Section B — Module-by-Module Summary

### main.py (460 lines)

**Docstring:** Entry point for the competitive SEO intelligence pipeline. Orchestrates data ingestion, API calls, semantic auditing, database persistence, and report generation.

**Public Functions & Classes:**
- `load_shared_config()` — Load central configuration from shared_config.json
- `load_handoff_schema()` — Load JSON Schema for handoff validation
- `find_latest_handoff_file()` — Locate most recent `competitor_handoff_*.json`
- `find_latest_legacy_file()` — Locate legacy `market_analysis_*.json` (backwards compat)
- `convert_handoff_to_targets()` — Transform Tool 1 handoff format to internal targets format
- `run_audit()` — Main execution loop; calls all downstream modules
- `main()` — CLI entry point

**External Dependencies:**
- `src.api_clients` — DataForSEO, Moz clients
- `src.semantic` — SemanticAuditor, ScrapedPage
- `src.analysis` — AnalysisEngine
- `src.database` — DatabaseManager
- `src.reporting` — ReportGenerator
- `src.reframe_engine` — ReframeEngine
- `src.velocity_module` — VelocityTracker
- `src.gsc_performance` — GSCManager
- `jsonschema` — Handoff format validation
- `glob`, `json`, `datetime` — stdlib

**Database:** Reads and writes to `competitor_history.db` via DatabaseManager
- **Reads:** Latest handoff file, config
- **Writes:** Run records, audit results, reports

**Notable Design Decisions:**
- Implements **Gap 1**: Handoff ingestion with JSON Schema validation
- Fallback to legacy `market_analysis_*.json` for backwards compatibility
- Integrates Tool 1 outputs (competitor_handoff_*.json) seamlessly
- Coordinates 6+ downstream modules in a single run

---

### semantic.py (408 lines)

**Docstring:** Semantic tagging using spaCy and external dictionaries. Extracts page structure with headers, text, metadata. Scores content against Tier 1 (Medical), Tier 2 (Systems), Tier 3 (Bowen) vocabularies.

**Public Classes & Methods:**
- `ScrapedPage` (dataclass) — Captured page structure with outline, text, metadata (Gap 2)
  - Fields: url, fetched_at, http_status, extraction_status, extraction_errors, outline, first_500_words, full_text_word_count, metadata
  - Method: `to_dict()` — JSON serialization
- `SemanticAuditor` — Core semantic analysis engine
  - `scrape_content(url)` → ScrapedPage — Web scraping with structure preservation (Gap 2)
  - `score_page(page, medical_dict, systems_dict, bowen_dict)` → scores (Tier 1/2/3)
  - `assess_feasibility(client_da, competitor_da)` → bool — Authority comparison
  - `identify_gaps(client_keywords, competitor_keywords)` → gaps — Keyword intersection

**External Dependencies:**
- `spacy` — Entity recognition
- `BeautifulSoup4` — HTML parsing
- `requests` — HTTP client
- `src.scoring_logic` — Tier constants and `calculate_weighted_score()`
- `datetime`, `json`, `urllib.parse` — stdlib

**Database:** Reads and writes
- **Reads:** Tier vocabularies from config
- **Writes:** Via DatabaseManager (semantic_audits table)

**Notable Design Decisions:**
- **Gap 2 Implementation:** ScrapedPage dataclass captures full page structure (outline, metadata, text) while preserving the original "headers + first 500 words" string for backwards compatibility
- Extraction status enum: complete, partial, blocked, error
- Headers captured with level (h1/h2/h3) and order for structure preservation
- Backwards compat preserved by including `first_500_words` field alongside full_text_word_count

---

### eeat_scorer.py (338 lines)

**Docstring:** Gap 3 — EEAT heuristic scoring. Computes Experience, Expertise, Authoritativeness, Trustworthiness scores from page-level signals. CAVEAT: These are heuristic proxies, not Google's proprietary EEAT model.

**Public Classes & Methods:**
- `EEATScore` (dataclass) — Per-page EEAT record
  - Fields: url, scored_at, experience_signals, expertise_signals, authoritativeness_signals, trustworthiness_signals, scores dict, score_confidence, caveat
  - Method: `to_dict()` — JSON serialization
- `EEATScorer` — EEAT computation engine
  - `__init__(config)` — Load weights, credential list, case study triggers, stock image hosts from config
  - `score_page(page, domain_authority)` → EEATScore — Compute 4 EEAT dimensions

**External Dependencies:**
- `src.semantic` — ScrapedPage
- `json`, `re`, `datetime`, `urllib.parse` — stdlib

**Database:** No direct DB access (stateless scorer)

**Notable Design Decisions:**
- **Gap 3 Implementation:** Scores EEAT from extracted page signals (author byline, publish date, images, credentials, schema, domain authority, https, contact/privacy links)
- Score confidence levels: high, medium, low
- Uses stock image host list to distinguish original vs. stock photography
- Credential list (MD, PhD, RCC, MSW, etc.) used to detect expertise signals
- Case study triggers (we tested, our research, etc.) detect experience signals
- Includes caveat in output: "Heuristic proxy. Not Google's actual EEAT model."

---

### cluster_detector.py (138 lines)

**Docstring:** Gap 4 — Internal linking cluster detection. Builds directed graph of internal links across scraped pages; identifies hub candidates; emits cluster signal.

**Public Classes & Methods:**
- `ClusterResult` (dataclass) — Per-domain cluster analysis
  - Fields: domain, pages_analyzed, internal_link_graph dict, hub_candidates list, cluster_signal enum, resolution_caveat
  - Method: `to_dict()` — JSON serialization
- `ClusterDetector` — Graph-based link analysis
  - `__init__(config)` — Load thresholds (hub_in_degree_threshold, min_pages_for_signal)
  - `analyze_domain(domain, pages)` → ClusterResult — Build graph, identify hubs, emit signal

**External Dependencies:**
- `urllib.parse` — URL normalization
- `dataclasses`, `typing` — stdlib

**Database:** No direct DB access

**Notable Design Decisions:**
- **Gap 4 Implementation:** Analyzes internal linking patterns only on pages scraped (typically 3 per domain)
- Cluster signals: isolated, linked, clustered, insufficient_data
- Hub candidates identified by in-degree threshold (default 2)
- Important caveat: Cannot see full site structure; results are suggestive, not definitive
- Notes that full internal-linking audit would require domain crawl or third-party API (Ahrefs, Moz)

---

### eeat_scorer.py (continued)

See section above.

---

### database.py (385 lines)

**Docstring:** SQLite persistence layer. Manages 8 tables for longitudinal tracking of competitor metrics, semantic audits, market gaps, and velocity data.

**Public Classes & Methods:**
- `DatabaseManager` — SQLite access layer
  - `__init__(db_path)` — Initialize or connect to existing DB
  - `create_run(client_domain)` → int — Insert new run record, return run_id
  - `get_latest_run_id()` → int | None
  - `insert_competitor_metrics()` — Bulk insert traffic magnet records
  - `insert_semantic_audit()` — Insert page scoring results
  - `insert_market_gaps()` — Insert keyword gaps
  - `get_volatility_alerts()` → list — Trending indicators for reporting
  - `get_feasibility_drift()` → list — Revision 4: PA drift detection (Fragile Magnets)
  - `_get_connection()` — Context manager for transactions

**Database Tables & Schema:**
1. **runs** (run_id, client_domain, created_at) — Run metadata
2. **competitors** (domain, avg_da, last_crawled_at) — Competitor metadata
3. **traffic_magnets** (id, run_id, domain, url, primary_keyword, est_traffic, medical_score, systems_score, systemic_label) — High-traffic pages
4. **market_gaps** (id, run_id, keyword, competitor_overlap_count, feasibility_status) — Keyword gaps
5. **competitor_metrics** (id, run_id, domain, url, keyword, position, traffic, timestamp) — Legacy table
6. **semantic_audits** (id, run_id, url, medical_score, systems_score, systemic_label, timestamp) — Tier scoring
7. **competitor_metadata** (domain, market_position, strategy, last_updated) — Revision 3: Market position tagging
8. **competitor_history** (id, run_id, url, position, pa, drift, timestamp) — Revision 4: Longitudinal PA tracking

**External Dependencies:**
- `sqlite3` — Database driver
- `datetime` — Timestamps

**Database:** Creates and manages the entire database

**Notable Design Decisions:**
- Revision 4 adds **Feasibility Drift** tracking: stores current PA, calculates drift from previous PA, flags "Fragile Magnets" if drift < -2
- Maintains legacy tables for backwards compatibility during migration
- Uses context manager pattern for transaction safety
- Foreign keys to runs table for audit traceability

---

### reporting.py (189 lines)

**Docstring:** Strategic briefing generation. Assembles markdown reports from audit results, reframes, GSC findings, volatility alerts, and market velocity alerts.

**Public Classes & Methods:**
- `ReportGenerator` — Report assembly engine
  - `__init__(db_path)` — Initialize with database connection
  - `generate_summary(client_domain, expected_competitors, run_id, reframes, token_usage, market_alerts, gsc_findings)` → str (markdown) — Assemble strategic briefing

**Report Sections (Gap 5 implementation):**
- **Section A (Deterministic Audit):**
  - Executive summary
  - GSC performance gaps (high impression / low CTR)
  - Low-hanging fruit (positions 11-20 on SERP)
  - Clinical mismatches (Systems-heavy pages found via Medical queries)
  - Volatility alerts (PA drift, rank volatility)
  - Feasibility drift alerts (Fragile Magnets)
- **Section B (LLM Reframes):**
  - Market velocity alerts
  - AI token usage tracking

**External Dependencies:**
- `pandas` — DataFrame to markdown conversion
- `src.database` — DatabaseManager
- `datetime` — Timestamps

**Database:** Reads from database
- **Reads:** volatility_alerts, feasibility_drift, latest_run_id
- **Writes:** None (read-only in this module)

**Notable Design Decisions:**
- **Gap 5 Implementation:** Separates deterministic audit results (Section A) from LLM reframes (Section B)
- Generates markdown output suitable for email or web publication
- Includes AI token usage tracking for cost analysis
- Volatility alerts, feasibility drift, and market velocity alerts all feed into the briefing
- Integrates GSC findings (target gaps, low-hanging fruit, clinical mismatches)

---

### gsc_performance.py (366 lines)

**Docstring:** Google Search Console analysis. Pulls 90 days of query data, identifies "striking distance" keywords (positions 11-25), cross-references with clinical dictionary, suggests systemic reframes.

**Public Classes & Methods:**
- `GSCManager` — GSC API integration
  - `__init__(config)` — Load GSC secrets, property URL, scopes
  - `authenticate()` → service — OAuth flow for Google Search Console
  - `get_90day_queries()` → DataFrame — Fetch query data
  - `identify_striking_distance(df)` → DataFrame — Filter positions 11-25
  - `cross_reference_clinical(df, tier_terms)` → DataFrame — Match against Tier 1/2/3 vocabularies
  - `suggest_title_reframes(queries)` → list — Generate systemic title suggestions

**External Dependencies:**
- `google-api-python-client` — Google Search Console API
- `google-auth-oauthlib` — OAuth authentication
- `pandas` — Data manipulation

**Database:** Reads and writes
- **Reads:** Config (GSC property URL, date range)
- **Writes:** Via DatabaseManager (striking distance records)

**Notable Design Decisions:**
- Focuses on "striking distance": positions 11-25 on SERP (low-hanging fruit)
- Includes clinical dictionary cross-reference (detects Medical vs. Systems keyword use)
- Suggests systemic title rewrites for mismatched pages
- 90-day window (configurable in shared_config.json)
- CTR and position thresholds configurable

---

### api_clients.py (157 lines)

**Docstring:** API client wrappers for DataForSEO (reverse lookup, organic keywords) and Moz V2 (page authority, domain authority).

**Public Classes & Methods:**
- `DataForSEOClient` — DataForSEO API wrapper
  - `__init__(api_login, api_password)` — Initialize with credentials
  - `get_relevant_pages(domain, limit)` → list — Traffic magnets (POST relevant_pages/live)
  - `get_organic_keywords(domain, limit)` → list — Top keywords ranking
- `MozClient` — Moz V2 API wrapper
  - `__init__(access_id, secret_key)` — Initialize with credentials
  - `get_url_metrics(url)` → dict — Page authority, domain authority, link metrics

**External Dependencies:**
- `requests` — HTTP client
- `json` — JSON serialization

**Database:** No direct DB access (stateless API wrappers)

**Notable Design Decisions:**
- Thin wrapper layer around HTTP APIs
- Handles API authentication via headers
- DataForSEO filters for positions <= 10 (top 10 SERP results)
- Moz returns normalized authority scores (0-100 scale)

---

### competitor_mining.py (161 lines)

**Docstring:** Extract top keywords from competitors discovered in audit results; gap analysis against existing keyword list. Generates `competitor_keyword_gap.md` markdown report.

**Public Functions:**
- `load_existing_keywords(path)` → Set[str] — Read from keyword CSV
- `get_top_domains(path, limit)` → List[str] — Extract top domains from audit_results_run_4.xlsx
- `derive_brand_name(domain)` → str — Strip suffixes (counselling, therapy, etc.) for brand extraction
- `contains_numbers(text)` → bool — Utility to filter numeric keywords
- `main()` — Run mining pipeline, generate gap report

**External Dependencies:**
- `pandas` — Read Excel audit results
- `csv` — Parse keyword CSV
- `src.api_clients` — DataForSEOClient
- `src.reframe_engine` — ReframeEngine
- `os`, `re` — stdlib

**Database:** No direct DB access

**Notable Design Decisions:**
- Reads top domains from Excel audit results (`audit_results_run_4.xlsx`)
- Fetches top 20 keywords per domain via DataForSEO API
- Compares against existing keyword CSV to identify gaps
- Applies brand-name derivation (strip counselling/therapy suffixes) for readability
- Outputs markdown report (`competitor_keyword_gap.md`) with new opportunities

---

### orchestrator.py (168 lines)

**Docstring:** Streamlit-based workflow UI for step selection and execution. Allows user to choose which modules to run (mining, audit, scoring, GSC, strike mapping) and provides real-time log output.

**UI Components:**
- Keyword file dropdown selector
- Checkbox controls for Steps 1-5 (mining, audit, scoring, GSC, strike mapping)
- Run button to trigger selected steps
- Expandable log view for each step

**External Dependencies:**
- `streamlit` — UI framework
- `subprocess` — Run Python scripts as subprocesses
- `glob`, `yaml`, `re`, `datetime` — stdlib

**Database:** No direct DB access (orchestration only)

**Notable Design Decisions:**
- Provides user-friendly workflow UI instead of CLI
- Step 3 (scoring) includes Step 2 (audit) internally
- Real-time log streaming with st.expander
- Note in UI warns that Step 3 includes Step 2

---

### reframe_engine.py (110 lines)

**Docstring:** LLM-based Bowen Family Systems reframing. Applies clinical pivot mapping; generates pattern-first blueprints via OpenAI API (GPT-4o).

**Public Classes & Methods:**
- `ReframeEngine` — Reframing orchestrator
  - `__init__()` — Initialize OpenAI client (gpt-4o model)
  - `clinical_pivot(text)` → str — Apply hardcoded pivot mapping (Attachment Style → Emotional Distance/Pursuit, etc.)
  - `generate_bowen_reframe(keyword, competitor_url, medical_score, paa_questions)` → dict — LLM-based reframe with usage stats

**Hardcoded Editorial Content (DESIGN ISSUE):**
- **pivot_map dict** (20 entries): Maps trigger keywords to Bowen reframes
  - Examples: "avoidant attachment" → "Emotional Distance / Pursuer-Distancer", "boundaries" → "Differentiation of Self", "anxiety" → "Anxiety: Intercepting the Relationship Loop"
  - This mapping should be externalized to config per CLAUDE.md rule

**External Dependencies:**
- `openai` — GPT-4o API
- `dotenv` — Load OPENAI_API_KEY from .env
- `os`, `typing` — stdlib

**Database:** No direct DB access (stateless)

**Notable Design Decisions:**
- Uses GPT-4o model (premium, expensive)
- Includes clinical pivot mapping as fallback if OpenAI key missing
- **FLAGGED:** hardcoded pivot_map should be moved to shared_config.json per editorial content externalisation rule

---

### velocity_module.py (112 lines)

**Docstring:** Market velocity tracking. Calculates trend signals (rank drift, DA drift, traffic volatility) for market alert generation.

**Public Classes & Methods:**
- `VelocityTracker` — Velocity calculation engine
  - `__init__(db_path)` — Initialize database connection
  - `calculate_rank_drift(domain, keyword)` → float — Position change from previous run
  - `calculate_da_drift(domain)` → float — Domain authority change
  - `identify_market_alerts()` → list — Generate alerts for reporting

**External Dependencies:**
- `src.database` — DatabaseManager
- `datetime` — Timestamps

**Database:** Reads from database
- **Reads:** competitor_history, runs tables
- **Writes:** None (read-only)

**Notable Design Decisions:**
- Compares current run against previous run to compute deltas
- Fragile Magnet alert: DA drift < -2 (competitor losing authority)
- Velocity alerts feed into strategic briefing (Section B)

---

### strike_mapper.py (66 lines)

**Docstring:** Map GSC "striking distance" keywords to publication draft status. Outputs spreadsheet or markdown showing which GSC striking-distance keywords have corresponding publication drafts.

**Public Functions:**
- `map_striking_distance(gsc_data, drafts_dir)` → DataFrame — Cross-reference GSC striking distance against draft inventory
- `main()` — Generate strike mapping output

**External Dependencies:**
- `pandas` — DataFrame operations
- `glob` — File discovery
- `os` — Path operations

**Database:** No direct DB access

**Notable Design Decisions:**
- Maps internal GSC low-hanging fruit (positions 11-25) to existing content drafts
- Identifies which draft would best target each striking-distance keyword
- Output suitable for content planning workflow

---

### scoring_logic.py (80 lines)

**Docstring:** Tier 1 (Medical), Tier 2 (Systems), Tier 3 (Bowen Expert) vocabulary constants and scoring formulas. Implements penalty logic (Revision 2).

**Public Constants:**
- `TIER_1_MEDICAL` — List of medical terms (symptom, treatment, disorder, trauma, etc.)
- `TIER_2_SYSTEMS` — List of systems terms (differentiation, triangles, emotional system, etc.)
- `TIER_3_BOWEN_EXPERT` — List of Bowen expert terms (defining self, emotional fusion, differentiation of self, etc.)

**Public Functions:**
- `calculate_weighted_score(t1_count, t2_count, t3_count)` → dict — Compute Tier scores with penalty logic
  - Formula: `Raw_Score = (Tier_3 * 2.0) + (Tier_2 * 0.5)`
  - Penalty: If `Tier_1 > 10` AND `Tier_3 == 0`, apply -50% penalty to Tier_2 score

**External Dependencies:**
- None (pure data + logic)

**Database:** No database access

**Notable Design Decisions:**
- Tier 3 receives 2x weight (Bowen-focused)
- Tier 2 receives 0.5x weight
- **Penalty Logic (Revision 2):** If page is heavily medical (Tier 1 > 10) but has no Bowen content (Tier 3 == 0), penalize the systems score to prevent misclassification
- Constants loaded from shared_config.json clinical section at runtime

---

### infiltrator.py (83 lines)

**Docstring:** Deprecated or exploratory module. Small footprint suggests experimental functionality. (Details unclear without full code read.)

**Status:** Marked as exploratory; likely not core to current pipeline.

---

### analysis.py (34 lines)

**Docstring:** Keyword intersection and feasibility checks. Identifies keywords all competitors rank for but client does not. Compares domain authority for feasibility assessment.

**Public Functions:**
- `keyword_intersection(client_keywords, competitor_keywords_list)` → Set[str] — Shared keywords all competitors rank for
- `check_feasibility(client_da, competitor_da, threshold)` → bool — Determine if client DA is within range to compete

**External Dependencies:**
- None (pure set logic)

**Database:** No database access

**Notable Design Decisions:**
- Simple set intersection algorithm
- Feasibility formula: `Feasibility = (Client_DA + 5) >= Competitor_DA` (per spec)
- If not feasible, suggests Hyper-Local Pivot strategy

---

### ingestion.py (35 lines)

**Docstring:** CSV domain validation and loading. Reads `Key_domains.csv` with domain validation; returns competitor list and client domain.

**Public Functions:**
- `validate_domain(domain)` → bool — Regex check for root domain format
- `read_key_domains(file_path)` → Tuple[List[str], str] — Parse CSV, return competitors and client

**External Dependencies:**
- `pandas` — CSV reading
- `re` — Domain validation regex

**Database:** No database access

**Notable Design Decisions:**
- Validates root domain format (no paths, protocols, trailing slashes)
- Raises ValueError if invalid domains or missing client found
- Expected CSV format: columns = [domain, role]; roles = [competitor, client]

---

## Section C — Configuration Files

### shared_config.json (118 keys)

**File Location:** `/Users/davemini2/ProjectsLocal/serp-compete/shared_config.json`

**Top-Level Keys & Purposes:**

| Section | Keys | Purpose |
|---------|------|---------|
| client | name, domain, da, location, framework | Client metadata (Living Systems Counselling, domain livingsystems.ca) |
| auth | gsc_client_secrets, gsc_property_url, scopes | Google Search Console OAuth credentials and API scopes |
| gsc_settings | date_range_days, ctr_threshold, position_target_max | GSC query window (90 days), CTR filter (0.01), position target (20) |
| technical | database_path, feasibility_threshold, max_audit_pages_per_domain, moderate_feasibility_max_gap, score_normaliser, scoring_weights, penalty_thresholds | DB path (living_systems_intel.db), scoring parameters, weights |
| stop_words | (array) | Common words to exclude from keyword analysis |
| clinical | tier_1_medical, tier_2_systems, tier_3_bowen | Vocabulary lists for Tier scoring |
| filtering | omitted_domains_path | Path to domain exclusion list |
| eeat_weights | experience, expertise, authoritativeness, trustworthiness | EEAT signal weights (Gap 3 config) |
| stock_image_hosts | (array) | Stock photo services to detect non-original images |
| credential_list | (array) | Professional credentials (MD, PhD, RCC, MSW, etc.) for expertise signals |
| case_study_triggers | (array) | Text patterns indicating experience (we tested, case study, our research, etc.) |
| cluster_thresholds | hub_in_degree_threshold, min_pages_for_signal | Internal link cluster detection thresholds (Gap 4 config) |

**New Keys Added Since v2 Spec:**
- `eeat_weights` (entire section) — Added for Gap 3 implementation
- `stock_image_hosts` — Added for EEAT Image signal detection
- `credential_list` — Added for EEAT Expertise signal detection
- `case_study_triggers` — Added for EEAT Experience signal detection
- `cluster_thresholds` — Added for Gap 4 implementation

**Immutable (Original to v2 Spec):**
- `client`, `auth`, `gsc_settings`, `technical`, `stop_words`, `clinical`, `filtering`

---

### .env (Key-Based)

**File Location:** `/Users/davemini2/ProjectsLocal/serp-compete/.env` (env vars only)

**Expected Keys (not read by this inventory):**
- `OPENAI_API_KEY` — For reframe_engine.py GPT-4o calls
- `DATAFORSEO_LOGIN` — DataForSEO API credentials
- `DATAFORSEO_PASSWORD` — DataForSEO API credentials
- `MOZ_ACCESS_ID` — Moz V2 API credentials
- `MOZ_SECRET_KEY` — Moz V2 API credentials

---

### token.json (Google Secrets)

**File Location:** `/Users/davemini2/ProjectsLocal/serp-compete/token.json`

**Purpose:** Cached OAuth token from Google Search Console authentication flow. Used by GSCManager to avoid re-authentication.

---

### data/dictionary.json

**File Location:** `/Users/davemini2/ProjectsLocal/serp-compete/data/dictionary.json`

**Purpose:** Legacy semantic dictionary. May be superseded by `clinical` section in shared_config.json.

---

## Section D — Database Schema

### Database File

**Location:** `competitor_history.db` (SQLite, 434 KB)

### Tables

| Table | Primary Key | Key Columns | Purpose |
|-------|-------------|------------|---------|
| runs | run_id | client_domain, created_at | Track audit runs with timestamps |
| competitors | domain | avg_da, last_crawled_at | Competitor metadata |
| traffic_magnets | id (autoincrement) | run_id, domain, url, est_traffic, medical_score, systems_score | High-traffic competitor pages (Gap 2) |
| market_gaps | id (autoincrement) | run_id, keyword, competitor_overlap_count, feasibility_status | Keywords all competitors rank for but client doesn't |
| competitor_metrics | id (autoincrement) | run_id, domain, url, keyword, position, traffic, timestamp | Legacy metrics table (migration phase) |
| semantic_audits | id (autoincrement) | run_id, url, medical_score, systems_score, systemic_label, timestamp | Tier 1/2/3 scoring results |
| competitor_metadata | domain (PK) | market_position, strategy, last_updated | Revision 3: Market position classification (Volume Scaler, Generalist, Direct Systemic) |
| competitor_history | id (autoincrement) | run_id, url, position, pa, drift, timestamp | Revision 4: Longitudinal PA tracking for Feasibility Drift detection (Fragile Magnets) |

### Foreign Keys

- `traffic_magnets.run_id` → `runs.id`
- `market_gaps.run_id` → `runs.id`
- `competitor_metrics.run_id` → `runs.id`
- `semantic_audits.run_id` → `runs.id`
- `competitor_history.run_id` → `runs.id`

### Indexes

- Likely indexes on `(run_id, domain)` for query performance (inferred from pattern; not explicitly validated)

### Schema Evolution

The schema reflects Revisions 1-4 from the spec:
- **Revision 3:** competitor_metadata table added (Market Positioning)
- **Revision 4:** competitor_history table added (Feasibility Drift tracking)
- **Legacy tables:** competitor_metrics, semantic_audits retained for backwards compatibility

### Migration Mechanism

No explicit migration system detected (e.g., no Alembic, no migration scripts). Schema created by `DatabaseManager.create_connection()` as `CREATE TABLE IF NOT EXISTS` statements. Supports backwards-compatible schema evolution by adding tables without removing old ones.

---

## Section E — Output Format

### Strategic Briefing Markdown

**Filename Pattern:** `strategic_briefing_run_*.md` (wildcard = run number)

**Current Output Files:**
- `strategic_briefing_run_2.md` (20,758 bytes) — Run 2 output
- `strategic_briefing_run_3.md` (25,181 bytes) — Run 3 output
- `strategic_briefing_run_4.md` (24,820 bytes) — Run 4 output
- `strategic_briefing_run_8.md` (6,034 bytes) — Run 8 output
- `strategic_briefing_run_9.md` (23,848 bytes) — Run 9 output
- `strategic_briefing_run_11.md` (40,011 bytes) — Run 11 output (most recent, largest)

**Most Recent Example:** `strategic_briefing_run_11.md`

**Structure (Gap 5 Implementation):**

1. **Header:** Run ID, client domain, timestamp
2. **Executive Summary:** High-level overview of findings
3. **Section A — Deterministic Audit:**
   - 📈 Internal GSC Performance Gaps
     - High Impression / Low CTR gaps
     - Low-hanging fruit (positions 11-20)
     - Clinical mismatches (Systems vs. Medical)
   - 📉 Volatility Alerts (PA drift, rank volatility)
   - 🚩 Fragile Magnets (Revision 4 Feasibility Drift alerts)
4. **Section B — LLM Reframes:**
   - ⚡ Market Velocity Alerts
   - Bowen-based reframing suggestions
5. **Appendices:**
   - 💰 AI Token Usage (if LLM reframes used)
   - Data tables in markdown format

**Output Method:** `ReportGenerator.generate_summary()` assembles markdown from database records and returns as string. CLI writes to timestamped file.

---

## Section F — Test Coverage

### Test Files

| Test File | Lines | Modules Under Test | Status |
|-----------|-------|-------------------|--------|
| test_main.py | 2,924 | main.py, integration | Present |
| test_gsc.py | 8,649 | gsc_performance.py | Present |
| test_semantic.py | 1,445 | semantic.py | Present |
| test_database.py | 1,789 | database.py | Present |
| test_api_clients.py | 1,911 | api_clients.py | Present |
| test_reframe_engine.py | 2,480 | reframe_engine.py | Present |
| test_config_integrity.py | 1,473 | config validation | Present |
| test_new_logic.py | 2,224 | integration tests | Present |
| test_velocity.py | 1,656 | velocity_module.py | Present |
| test_analysis.py | 1,001 | analysis.py | Present |
| test_ingestion.py | 1,214 | ingestion.py | Present |
| test_cluster_detector.py | NEW | cluster_detector.py (Gap 4) | Present |
| test_eeat_scorer.py | NEW | eeat_scorer.py (Gap 3) | Present |
| conftest.py | Fixtures | pytest fixtures | Present |

### Test Execution

**Command:** `PYTHONPATH=. pytest tests/` (per GEMINI.md)

**Coverage Claim:** 100% for core logic (per GEMINI.md)

**Modules With Test Files:**
- ✅ main.py
- ✅ gsc_performance.py
- ✅ semantic.py
- ✅ database.py
- ✅ api_clients.py
- ✅ reframe_engine.py
- ✅ velocity_module.py
- ✅ analysis.py
- ✅ ingestion.py
- ✅ cluster_detector.py (NEW)
- ✅ eeat_scorer.py (NEW)
- ❓ competitor_mining.py (unclear; check test_new_logic.py for coverage)
- ❓ orchestrator.py (Streamlit UI, may not have pytest coverage)
- ❓ strike_mapper.py (check test_new_logic.py)
- ❓ infiltrator.py (status unclear)
- ✅ scoring_logic.py (likely covered via semantic.py tests)

### Test Infrastructure

**Fixtures (conftest.py):**
- Pytest fixtures for common test data (sample domains, config, database fixtures)

**Configuration Validation:**
- test_config_integrity.py validates shared_config.json structure

---

## Summary Stats

| Metric | Value |
|--------|-------|
| **Total Python Modules** | 18 |
| **Lines of Code (src/)** | 3,290 |
| **Test Files** | 13 |
| **Database Tables** | 8 |
| **Configuration Sections** | 12 (in shared_config.json) |
| **Strategic Briefing Files** | 11 (most recent: run 11) |
| **New Modules (not in v2 spec)** | 5 (cluster_detector, eeat_scorer, competitor_mining, orchestrator, strike_mapper) |
| **Hardcoded Editorial Content** | 1 section (reframe_engine.py pivot_map) |

---

**Document Generated:** 2026-05-02 by code review  
**Next Step:** Review against v2 spec for delta report
