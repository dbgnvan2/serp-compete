# Serp-comp Project Context

## Project Mission
To provide competitive SEO intelligence with a focus on Bowen Family Systems reframing.

## Tech Stack
- **Language:** Python
- **Libraries:** pandas, spaCy, BeautifulSoup4, requests, sqlite3
- **APIs:** DataForSEO, Moz V2

## Standards
- All features must have corresponding tests in the `tests/` directory.
- Maintain `spec.md` as the source of truth for requirements.
- Use `pytest` for testing.

## Current Status (v3 — Complete Implementation)

### Core Modules (Gap Refinements)
- **Gap 1: Handoff Ingestion** (`src/main.py`): Loads competitor_handoff_*.json from Tool 1 with schema validation + legacy fallback
- **Gap 2: Page Structure** (`src/semantic.py`): ScrapedPage dataclass extracts headers, metadata, internal links, EEAT signals with backwards-compat
- **Gap 3: EEAT Scoring** (`src/eeat_scorer.py`): Heuristic scoring for Experience, Expertise, Authoritativeness, Trustworthiness with database persistence
- **Gap 4: Internal Linking** (`src/cluster_detector.py`): Detects hub pages and link patterns across scraped pages with caveat
- **Gap 5: Strategic Briefing** (`src/reporting.py`): Generates Markdown + Excel report with competitive analysis, EEAT, clusters, and Bowen reframes

### Feature Authorizations (New)
- **Competitor Mining** (`src/competitor_mining.py`): Keyword gap mining from discovered competitors
- **Orchestrator UI** (`src/orchestrator.py`): Streamlit workflow for step orchestration with dependency tracking
- **Strike Mapping** (`src/strike_mapper.py`): GSC striking distance → publication planning

### Technical Infrastructure
- **Step DAG** (`src/step_dag.py`): Directed acyclic graph for step dependencies with topological sort and cycle detection
- **API Clients:** DataForSEO, Moz V2, with third-party skeletons for Ahrefs/Moz v4+ (`src/third_party_crawlers.py`)
- **Database:** SQLite with 3 new tables (eeat_scores, cluster_results, semantic_audit_results) + legacy compatibility
- **Config:** Externalized to shared_config.json with 5 new sections (clinical_pivots, handoff, orchestrator, step_dag, eeat_client_messaging)
- **Runner:** Integrated audit flow with config passing (`src/main.py`)

## Testing (v3)
- **Suite:** 158 tests across 13 test modules, 100% pass rate
  - Core: eeat_scorer (54), page_structure (18), handoff (14), step_dag (13), reframe_engine (5)
  - Infrastructure: database, config_integrity, api_clients, velocity, gsc, analysis, main
- **Run:** `PYTHONPATH=. pytest tests/`
- **Coverage:** All new modules tested; backwards compatibility verified

# Configuration & Architecture (v3)

## Configuration-Driven Design
All editorial content now lives in `shared_config.json`:
- **clinical_pivots:** 20 Bowen reframe mappings (non-engineers can edit without code changes)
- **handoff:** Version management for Tool 1 integration (supported_versions: 2.0, 2.1)
- **orchestrator:** Streamlit theme, timeouts, logging configuration
- **step_dag:** DAG-based workflow with dependencies and optional flags
- **eeat_client_messaging:** Caveat text and positioning for EEAT heuristic scores

## Safe Defaults Pattern
All modules use `.get()` with defaults to maintain backwards compatibility:
```python
self.pivot_map = config.get("clinical_pivots", DEFAULT_CLINICAL_PIVOTS)
```

## Data Persistence
Three new tables for enhanced analysis:
- `eeat_scores`: 26 columns for EEAT dimension signals
- `cluster_results`: 13 columns for internal link analysis
- `semantic_audit_results`: 14 columns for detailed tier scoring

# Tactical Rules: serp-compete

## 🎯 Analysis Standards
- **Semantic Rigor:** Use `clinical_dictionary.json` to calculate the "Systemic Vacuum." 
- **Penalty Logic:** Apply the Tier 1-to-Tier 2 penalty if Tier 3 keywords are absent.
- **Expert Reframing:** Automated reframes must avoid "Tools/Tips" language and use "Differentiation/Process" language.
- **EEAT Heuristics:** Scores are proxies based on SEO conventions, NOT Google's proprietary EEAT. Use for competitive analysis, not as authoritative measurement.
- **Cluster Limits:** Internal link analysis limited to N≤3 scraped pages per domain. Full site structure requires third-party APIs (Ahrefs, Moz v4+).