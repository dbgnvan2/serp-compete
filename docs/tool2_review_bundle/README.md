# Tool 2 Review Bundle — Spec Writing Reference

**Bundle Generated:** 2026-05-02  
**Purpose:** Complete context for spec writing session (separate Claude session without live repo access)  
**Bundle Size:** 280 KB | **File Count:** 25 files

---

## How to Use This Bundle

1. **Start here:** Read this README to understand bundle contents and reading order
2. **Read the review documents first:** `tool2_inventory_2026-05-02.md` and `tool2_delta_2026-05-02.md` provide the current-state analysis
3. **Read source code:** Use file list below to navigate modules in recommended order
4. **Reference config files:** Open `shared_config.json` to understand configuration structure

A separate Claude session should be able to write a complete Tool 2 upgrade specification using only these files, without needing the live repository.

---

## Reading Order (Recommended)

### Phase 1: Current State Assessment (Start Here)

1. **tool2_inventory_2026-05-02.md** (Section A–F)
   - Repository structure and file inventory
   - Module-by-module summaries with purposes and design decisions
   - Configuration file documentation
   - Database schema overview
   - Test coverage status
   - **Time:** 20–30 minutes
   - **Goal:** Understand what Tool 2 currently does

2. **tool2_delta_2026-05-02.md** (Gap-by-Gap Analysis)
   - Comparison of current code against v2 spec's 5 gaps
   - Status of each gap: completed, missing, or enhanced
   - Net-new features not in original spec
   - Hardcoded editorial content flagged
   - Bugs and limitations documented
   - **Time:** 15–20 minutes
   - **Goal:** Understand what's been implemented, what remains, what changed unexpectedly

### Phase 2: Configuration Deep Dive

3. **shared_config.json**
   - Central configuration with 12 sections
   - Clinical vocabularies (Tier 1/2/3)
   - EEAT weights and signal configuration
   - GSC settings and thresholds
   - Database path and scoring parameters
   - **Time:** 10 minutes
   - **Goal:** Understand how Tool 2 is configured

### Phase 3: Original Specification

4. **Serp-compete_spec.md** (Original v2 spec)
   - 5 technical pillars (reverse lookup, keyword intersection, entity extraction, database, market positioning)
   - Module requirements table
   - Operational sequence
   - Revisions 1–4 documented
   - **Time:** 10–15 minutes
   - **Goal:** See what was originally specified

### Phase 4: Tactical Rules & Current Context

5. **Serp-compete_GEMINI.md** (Project context)
   - Project mission (Bowen Family Systems focus)
   - Tech stack and standards
   - Current status and testing requirements
   - Tactical rules (semantic rigor, penalty logic, expert reframing)
   - **Time:** 5 minutes
   - **Goal:** Understand project standards and tactical rules

### Phase 5: Source Code (Module-by-Module)

Read in this order (roughly follows data flow):

#### Core Data Flow (Essential)

6. **main.py** (460 lines)
   - Entry point; orchestrates entire audit
   - Implements Gap 1 (handoff ingestion)
   - Coordinates 6+ downstream modules
   - **Key Functions:** `load_handoff_schema()`, `convert_handoff_to_targets()`, `run_audit()`
   - **Time:** 15 minutes

7. **ingestion.py** (35 lines)
   - CSV domain validation
   - Read Key_domains.csv for competitor list
   - **Key Functions:** `validate_domain()`, `read_key_domains()`
   - **Time:** 3 minutes

8. **semantic.py** (408 lines)
   - Implements Gap 2 (page structure extraction)
   - ScrapedPage dataclass with outline, metadata, text
   - **Key Classes:** `ScrapedPage`, `SemanticAuditor`
   - **Key Functions:** `scrape_content()`, `score_page()`, `assess_feasibility()`
   - **Time:** 20 minutes

#### Analysis & Scoring (Essential)

9. **api_clients.py** (157 lines)
   - DataForSEO and Moz API wrappers
   - Reverse lookup and authority metrics
   - **Key Classes:** `DataForSEOClient`, `MozClient`
   - **Time:** 10 minutes

10. **scoring_logic.py** (80 lines)
    - Tier 1/2/3 vocabulary constants
    - Weighted scoring formula with penalty logic
    - **Key Functions:** `calculate_weighted_score()`
    - **Time:** 5 minutes

11. **analysis.py** (34 lines)
    - Keyword intersection and feasibility checks
    - **Key Functions:** `keyword_intersection()`, `check_feasibility()`
    - **Time:** 3 minutes

#### Gap 3: EEAT Scoring

12. **eeat_scorer.py** (338 lines)
    - Implements Gap 3 (EEAT heuristic scoring)
    - EEATScore dataclass with 4-dimension signals
    - **Key Classes:** `EEATScore`, `EEATScorer`
    - **Key Functions:** `score_page()`
    - **Important:** Heuristic proxy caveat documented
    - **Time:** 15 minutes

#### Gap 4: Internal Linking

13. **cluster_detector.py** (138 lines)
    - Implements Gap 4 (internal linking detection)
    - Builds directed graph; identifies hub candidates
    - **Key Classes:** `ClusterResult`, `ClusterDetector`
    - **Key Functions:** `analyze_domain()`
    - **Important:** Scope limitation caveat (only sees scraped pages)
    - **Time:** 10 minutes

#### Persistence & Reporting (Essential)

14. **database.py** (385 lines)
    - SQLite persistence layer
    - 8 tables for longitudinal tracking
    - Implements Revisions 3–4 (market positioning, feasibility drift)
    - **Key Classes:** `DatabaseManager`
    - **Time:** 20 minutes

15. **reporting.py** (189 lines)
    - Implements Gap 5 (strategic briefing)
    - Assembles Section A (deterministic audit) + Section B (LLM reframes)
    - **Key Classes:** `ReportGenerator`
    - **Key Functions:** `generate_summary()`
    - **Time:** 10 minutes

#### LLM Integration (Optional)

16. **reframe_engine.py** (110 lines)
    - Bowen Family Systems reframing via GPT-4o
    - **FLAGGED:** hardcoded pivot_map should be externalized
    - **Key Classes:** `ReframeEngine`
    - **Key Functions:** `clinical_pivot()`, `generate_bowen_reframe()`
    - **Time:** 10 minutes

#### Market Intelligence (Optional)

17. **gsc_performance.py** (366 lines)
    - Google Search Console analysis
    - Identifies "striking distance" keywords (positions 11–25)
    - **Key Classes:** `GSCManager`
    - **Time:** 15 minutes

18. **velocity_module.py** (112 lines)
    - Market velocity tracking
    - Rank drift and DA drift detection
    - **Key Classes:** `VelocityTracker`
    - **Time:** 10 minutes

#### Net-New Features (Reference)

19. **competitor_mining.py** (161 lines)
    - Extract top keywords from competitors
    - Generate gap analysis
    - **Not in original spec**
    - **Time:** 10 minutes (optional)

20. **strike_mapper.py** (66 lines)
    - Map GSC striking distance to draft inventory
    - Content planning support
    - **Not in original spec**
    - **Time:** 5 minutes (optional)

21. **orchestrator.py** (168 lines)
    - Streamlit workflow UI
    - Step selection and execution
    - **Not in original spec; user interface only**
    - **Time:** 5 minutes (optional)

### Phase 6: Example Output

22. **strategic_briefing_run_11.md**
    - Most recent strategic briefing output (40 KB)
    - Shows Section A (deterministic audit) + Section B (reframes) structure
    - Example of what final briefing looks like
    - **Time:** 10 minutes
    - **Goal:** See the end product

---

## File Listing

| # | File | Type | Lines | Notes |
|---|------|------|-------|-------|
| — | **REFERENCE DOCUMENTS** | | |
| 1 | tool2_inventory_2026-05-02.md | Review | — | Current-state inventory (Section A–F) |
| 2 | tool2_delta_2026-05-02.md | Review | — | Delta report vs. v2 spec |
| 3 | shared_config.json | Config | — | Central configuration (12 sections) |
| 4 | Serp-compete_spec.md | Spec | — | Original v2 specification |
| 5 | Serp-compete_GEMINI.md | Context | — | Project mission and standards |
| 6 | clinical_dictionary.json | Data | — | Semantic/clinical dictionary |
| — | **SOURCE CODE (src/)** | | |
| 7 | main.py | Python | 460 | Entry point; Gap 1 (handoff ingestion) |
| 8 | ingestion.py | Python | 35 | CSV domain validation |
| 9 | semantic.py | Python | 408 | Gap 2 (page structure); ScrapedPage dataclass |
| 10 | api_clients.py | Python | 157 | DataForSEO and Moz wrappers |
| 11 | scoring_logic.py | Python | 80 | Tier 1/2/3 scoring formula |
| 12 | analysis.py | Python | 34 | Keyword intersection; feasibility |
| 13 | eeat_scorer.py | Python | 338 | Gap 3 (EEAT heuristic scoring) |
| 14 | cluster_detector.py | Python | 138 | Gap 4 (internal linking detection) |
| 15 | database.py | Python | 385 | SQLite persistence (8 tables) |
| 16 | reporting.py | Python | 189 | Gap 5 (strategic briefing) |
| 17 | reframe_engine.py | Python | 110 | Bowen reframing via GPT-4o |
| 18 | gsc_performance.py | Python | 366 | Google Search Console analysis |
| 19 | velocity_module.py | Python | 112 | Market velocity tracking |
| 20 | competitor_mining.py | Python | 161 | **Net-new:** Keyword mining |
| 21 | strike_mapper.py | Python | 66 | **Net-new:** GSC → drafts mapping |
| 22 | orchestrator.py | Python | 168 | **Net-new:** Streamlit workflow UI |
| — | **EXAMPLE OUTPUT** | | |
| 23 | strategic_briefing_run_11.md | Output | — | Most recent briefing (40 KB) |
| — | **TESTING & SUPPLEMENTARY** | | |
| 24 | __init__.py | Python | 0 | Package marker |
| 25 | This file | Markdown | — | Bundle README |

---

## Key Findings for Spec Writer

### All 5 Gaps Implemented ✅

1. **Gap 1 (Handoff):** ✅ Implemented in main.py with JSON Schema validation + legacy fallback
2. **Gap 2 (Page Structure):** ✅ Implemented via ScrapedPage dataclass in semantic.py with backwards-compat
3. **Gap 3 (EEAT):** ✅ Implemented in eeat_scorer.py with 4-dimension heuristic scoring
4. **Gap 4 (Internal Linking):** ✅ Implemented in cluster_detector.py with graph analysis + caveat
5. **Gap 5 (Strategic Briefing):** ✅ Implemented in reporting.py with Section A (deterministic) + Section B (reframes)

### Major Changes Since v2 Spec

- **Revisions 3–4:** Market positioning tagging and Feasibility Drift detection implemented in database schema
- **Backwards Compatibility:** ScrapedPage preserves first_500_words field for legacy vocab scoring
- **Configuration-Driven:** EEAT weights, cluster thresholds, credential lists, case study triggers all moved to shared_config.json
- **Net-New Features:** competitor_mining.py, orchestrator.py (Streamlit UI), strike_mapper.py added (not in original spec)

### Issues Flagged for Spec Writer

1. **Hardcoded Editorial Content:** reframe_engine.py has hardcoded pivot_map (20 Bowen reframes). Should be externalized to shared_config.json per CLAUDE.md rule.
2. **EEAT Caveat:** Scores are heuristic proxies, not Google's actual EEAT model. Important for client communication.
3. **Cluster Detection Scope:** Only analyzes pages scraped (typically 3 per domain). Full site structure invisible. Suggest third-party integration (Ahrefs, Moz) for future.
4. **Legacy Database Tables:** competitor_metrics, semantic_audits marked as legacy for migration. Deprecation timeline needed.
5. **Orchestrator Step Dependencies:** UI notes that "Step 3 includes Step 2" but dependencies are hardcoded. Propose DAG-based specification.

### Recommendations for Next Spec

1. **Formalize net-new features:** competitor_mining.py, orchestrator.py, strike_mapper.py should be explicitly authorized if they're core to Tool 2
2. **Externalize editorial content:** Move pivot_map to shared_config.json
3. **Plan database migration:** Set deprecation date for legacy tables
4. **Clarify EEAT positioning:** Document that EEAT scores are structural signals, not authoritative measurements
5. **Consider third-party integrations:** Ahrefs/Moz APIs for full site structure visibility (internal linking)

---

## Bundle Completeness Check

✅ All 18 Python modules from src/ (including __init__.py)  
✅ Spec and GEMINI reference documents  
✅ Shared config with all 12 sections  
✅ Clinical dictionary  
✅ Most recent strategic briefing example  
✅ This README with reading order and key findings  

**Total Bundle Size:** 280 KB (well under 1 MB limit)  
**Spec Writer Ready:** ✅ Yes — this bundle contains everything needed to write a complete spec without live repo access.

---

**Generated by Tool 2 Review Process — 2026-05-02**
