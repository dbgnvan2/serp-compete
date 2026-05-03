# Serp-compete (Tool 2) Upgrade Specification v3

**Version:** 3.0  
**Date:** 2026-05-02  
**Status:** APPROVED FOR IMPLEMENTATION  
**Based On:** v2 Spec + Implementation Review (tool2_review_2026-05-02)

---

## Executive Summary

Tool 2 (Serp-compete) has completed all 5 gaps defined in v2 specification. This v3 specification:

1. **Formalizes net-new features** (competitor_mining, orchestrator, strike_mapper) as core components
2. **Addresses technical debt** (hardcoded editorial content, legacy database tables, step dependency management)
3. **Plans third-party integrations** (Ahrefs, Moz) for enhanced internal-linking analysis
4. **Refines the 5 gaps** based on implementation learnings and production usage

Tool 2 is production-ready. v3 focuses on consolidating gains, paying down technical debt, and preparing for next-phase capabilities.

---

## Part 1: Gap Refinement (Gaps 1–5 Enhanced)

### Gap 1 — Competitor Handoff Ingestion (REFINED)

**v2 Requirement:**
Consume competitor_handoff_*.json from Tool 1 with validation.

**v3 Enhancement:**

**Implemented In:** `main.py:30–67`

**Current Implementation:**
- JSON Schema validation against `handoff_schema.json`
- Fallback to legacy `market_analysis_*.json` for backwards compatibility
- Automatic handoff file detection (glob by modification time)
- Format conversion to internal targets structure

**v3 Refinement — Handoff Version Management:**

The handoff schema evolves as Tool 1 improves. Tool 2 must handle multiple handoff versions gracefully.

**Requirements:**
- `handoff_schema.json` must include version field: `{ "version": "2.0", "targets": [...] }`
- Tool 2 validates against version-specific schema (e.g., `handoff_schema_v2.0.json`, `handoff_schema_v2.1.json`)
- If received handoff version is newer than supported, log warning and attempt parse with latest known schema
- If received handoff version is older than minimum supported, reject with clear error message
- Maintain backwards-compatibility window: support last 2 major versions minimum

**New Configuration (shared_config.json):**
```json
{
  "handoff": {
    "supported_versions": ["2.0", "2.1"],
    "schema_dir": ".",
    "minimum_version": "2.0",
    "legacy_fallback_enabled": true
  }
}
```

**Success Criteria:**
- ✅ Can parse handoff v2.0 and v2.1
- ✅ Gracefully degrades if newer version encountered
- ✅ Rejects older versions with actionable error
- ✅ Logs handoff version consumed for audit trail

---

### Gap 2 — Page Structure Extraction (REFINED)

**v2 Requirement:**
Replace 500-word concatenation with `ScrapedPage` dataclass capturing outline, metadata, dates, images, links.

**v3 Enhancement:**

**Implemented In:** `semantic.py:15–150` (ScrapedPage dataclass + scrape_content method)

**Current Implementation:**
- ScrapedPage dataclass with outline, metadata, text, status tracking
- Backwards-compatible `first_500_words` field preserved
- Extraction error tracking (extraction_errors list)
- Extraction status enum (complete, partial, blocked, error)

**v3 Refinement — Structured Metadata & Schema Extraction:**

The outline and metadata captured in v2 implementation are strong; v3 adds deeper structure for NLP and content analysis.

**Requirements:**

**Enhanced Outline Structure:**
```python
outline: List[Dict[str, Any]]  # Current: [{"level": "h1"|"h2"|"h3", "text": str, "order": int}]
# v3: Add context and relationships
# [{"level": "h1", "text": str, "order": int, "word_count": int, "contains_links": bool, 
#    "subheadings": List[str] (h2/h3 under this h1)}]
```

**Schema.org Extraction (Formalized):**
- JSON-LD schema detection with type mapping (Person, Organization, LocalBusiness, Article, etc.)
- Extracted fields: @type, name, description, author, datePublished, dateModified, image (URL + alt), rating, review count
- Store as `metadata.schema_markup` dict
- Support multiple schema objects per page (store as list if >1)

**Author Byline Enhancement:**
- Current: Detects presence of author byline
- v3: Extract actual author name(s) and credentials (if present)
- Store as `metadata.author_info` dict: { "names": [str], "credentials": [str] }

**Image Analysis (Formalized):**
- Current: Image count + stock host detection
- v3: Categorize as "original", "stock", "mixed"
- Store as `metadata.image_analysis`: { "total_count": int, "original_count": int, "stock_count": int, "stock_hosts": [str] }

**Internal Link Detection (NEW):**
- Extract all internal links (same domain)
- Count by link type: navigation, content, footer, sidebar
- Store as `metadata.internal_links`: { "total": int, "navigation": int, "content": int, "footer": int, "sidebar": int }

**Success Criteria:**
- ✅ Outline structure includes subheading hierarchy
- ✅ Schema.org markup extracted with @type and key fields
- ✅ Author names and credentials extracted (not just presence flag)
- ✅ Images categorized as original vs. stock (with counts)
- ✅ Internal links counted and categorized
- ✅ Backwards compatibility maintained: `first_500_words` still present
- ✅ Extraction errors captured and logged

**Implementation Notes:**
- Use existing `metadata` dict in ScrapedPage to store enhanced fields
- No need for new table; metadata dict serialized as JSON in database
- Update eeat_scorer.py to use author_info, image_analysis, internal_links from enhanced metadata

---

### Gap 3 — EEAT Heuristic Scoring (REFINED)

**v2 Requirement:**
Compute Experience, Expertise, Authoritativeness, Trustworthiness heuristics.

**v3 Enhancement:**

**Implemented In:** `eeat_scorer.py:1–120` (EEATScore dataclass + EEATScorer)

**Current Implementation:**
- 4-dimension scoring (E, E, A, T) with signal-level granularity
- Configuration-driven weights (eeat_weights in shared_config.json)
- Score confidence levels (high, medium, low)
- **Critical Caveat:** "Heuristic proxy. Not Google's actual EEAT model."

**v3 Refinement — Confidence Scoring & Client Positioning:**

EEAT scores are structural signals, not authoritative measurements. v3 formalizes confidence scoring and client communication.

**Requirements:**

**Confidence Scoring (Formalized):**
- Current: Confidence enum (high, medium, low)
- v3: Confidence score (0.0–1.0) based on signal coverage
- Formula: `confidence = (signals_present / total_possible_signals)`
- Apply multiplier per dimension (Experience typically has fewer signals than Authoritativeness)
- Store as `score_confidence` (float 0.0–1.0) instead of enum

**Signal Weighting Transparency:**
- Each signal contributes a weight (currently in eeat_weights config)
- v3: Store actual weight applied in EEATScore for auditability
- `signal_breakdown`: Dict mapping signal_name → {weight, raw_value, weighted_value}
- Enables debugging and client explanation ("Why did this signal matter?")

**Per-Dimension Explanations (NEW):**
- Add `dimension_rationale` dict mapping each dimension to a human-readable explanation
- Example: `experience_rationale: "Author byline present (0.15) + case study trigger detected (0.25) = moderate experience signal"`
- Allows non-technical review of scoring logic

**Client-Facing Language (MANDATORY):**
- Always pair EEAT scores with caveat: "Heuristic structural signal, not Google's proprietary EEAT model"
- Recommend positioning to clients as "competitive analysis framework" not "SEO authority measurement"
- Add config option `eeat_client_messaging` with recommended language

**Success Criteria:**
- ✅ Confidence scores are floats (0.0–1.0) with formula documented
- ✅ Signal breakdown included in EEATScore for auditability
- ✅ Dimension rationales generated in plain English
- ✅ Client messaging template in shared_config.json
- ✅ Caveat always included in outputs (reporting.py, strategic_briefing, etc.)

**Implementation Notes:**
- Extend EEATScore dataclass to include confidence_score (float), signal_breakdown (dict), dimension_rationale (dict)
- Update eeat_scorer.py to compute signal_breakdown and rationale during scoring
- Update reporting.py to include dimension_rationale in strategic briefing

---

### Gap 4 — Internal Linking Detection (REFINED)

**v2 Requirement:**
Detect internal linking clusters; identify hub candidates; emit cluster signals.

**v3 Enhancement:**

**Implemented In:** `cluster_detector.py:1–120` (ClusterDetector + ClusterResult)

**Current Implementation:**
- Directed graph of internal links across scraped pages
- Hub candidate identification (in-degree threshold)
- Cluster signals: isolated, linked, clustered, insufficient_data
- **Critical Caveat:** "Only sees scraped pages (typically 3 per domain). Full site structure invisible."

**v3 Refinement — Scope Acknowledgment & Third-Party Integration Plan:**

Current cluster detection is limited. v3 acknowledges scope and plans for full-site analysis via third-party APIs.

**Requirements:**

**Enhanced Cluster Signals (Formalized):**
- Current signals: isolated, linked, clustered, insufficient_data
- v3: Add confidence flags alongside signals
- `cluster_signal_confidence`: low (only 1–2 pages), medium (3 pages), high (>3 pages)
- Recommendation: "Upgrade to full-site crawl via [API] for definitive analysis"

**Third-Party API Integration Planning (NEW):**

v3 spec does NOT implement third-party APIs yet, but plans for them:

**Planned Capability — Ahrefs/Moz Full-Site Crawl (Future):**

When approved and budgeted:
- Call Ahrefs Site Explorer API or Moz API for full site crawl
- Cache crawl results with 7-day TTL (avoid over-calling APIs)
- Build complete site graph (all pages, all internal links)
- Run cluster detection on full graph
- Compare against limited-scope (3-page) signal to quantify difference

**New Config Section (Placeholder):**
```json
{
  "third_party_apis": {
    "enabled": false,
    "provider": "ahrefs|moz",
    "api_key_env_var": "AHREFS_API_KEY",
    "crawl_cache_ttl_days": 7,
    "full_site_detection_enabled": false
  }
}
```

**Success Criteria (v3):**
- ✅ Cluster signal confidence levels documented
- ✅ Caveat expanded: "Limited to scraped pages. For full-site analysis, enable third-party integration."
- ✅ Config structure added (disabled by default, no API calls in v3)
- ✅ Documentation links provided to Ahrefs/Moz signup and pricing
- ✅ Code structure supports API layer abstraction for future integration

**Implementation Notes:**
- Modify ClusterResult to include `signal_confidence` (low, medium, high)
- Update caveat text in cluster_detector.py
- Add third_party_apis section to shared_config.json (disabled by default)
- Design but don't implement API client (future PR)
- Document in spec: "Ready for third-party integration in v4 or later"

---

### Gap 5 — Strategic Briefing Structure (REFINED)

**v2 Requirement:**
Section A (deterministic audit) + Section B (LLM reframes). Include GSC findings, volatility alerts, market positioning.

**v3 Enhancement:**

**Implemented In:** `reporting.py:1–150` (ReportGenerator.generate_summary)

**Current Implementation:**
- Section A: GSC gaps (high impression/low CTR, low-hanging fruit, clinical mismatches), volatility alerts, feasibility drift
- Section B: Market velocity alerts, Bowen reframes
- Token usage tracking
- Markdown output

**v3 Refinement — Deterministic Audit Robustness & Reframe Quality:**

Section A is solid. v3 enhances its completeness and Section B's consistency.

**Requirements:**

**Section A Enhancements — Competitive Positioning Table:**

Add new sub-section in Section A: "Competitive Positioning Matrix"

```markdown
| Competitor | Market Position | Strategy | Authority Drift | Cluster Signal |
|-----------|-----------------|----------|-----------------|----------------|
| jericho... | Volume Scaler   | High Traffic Focus | +1.2 PA | Clustered |
| other...  | Generalist      | Broad Coverage    | -2.1 PA | Isolated |
```

Table populated from:
- `competitor_metadata.market_position` (Volume Scaler, Generalist, Direct Systemic)
- `competitor_metadata.strategy` (user-defined or auto-derived)
- `competitor_history.drift` (Feasibility Drift trend)
- `ClusterResult.cluster_signal` (Isolated, Linked, Clustered)

**Section B Enhancements — Reframe Quality Assurance:**

Current: ReframeEngine generates reframes via GPT-4o

v3 Requirements:
- Add reframe quality score (0.0–1.0) based on:
  - Does reframe use Bowen terminology? (presence of: differentiation, emotional process, triangulation, etc.)
  - Does reframe avoid "tools/tips" language? (keyword blacklist check)
  - Reframe length validation (50–200 words recommended)
  - Score = (bowen_terminology_match * 0.4) + (no_tools_tips * 0.3) + (length_valid * 0.3)
- Flag low-quality reframes for human review
- Include quality score in strategic briefing: "Quality: 0.87 (High)"

**New Section — Implementation Roadmap (Added to Section B):**

Add section: "Next Steps for Client"
- Numbered action items derived from:
  - Low-hanging fruit (GSC positions 11–25)
  - Feasibility Drift alerts (when competitors weak, client should publish)
  - Clinical mismatch opportunities (Systems pages targeting Medical keywords)
- Format: `1. [Action]: [Target Keyword]. Confidence: [High/Medium/Low]. Est. Effort: [High/Medium/Low].`

**Success Criteria:**
- ✅ Section A includes Competitive Positioning Matrix
- ✅ Section B includes reframe quality scores
- ✅ Low-quality reframes flagged for review
- ✅ Section B includes Implementation Roadmap with actionable steps
- ✅ All data sourced from database (no new API calls)

**Implementation Notes:**
- Extend ReportGenerator.generate_summary() to include positioning table
- Add quality_score computation in reframe_engine.py
- Create roadmap generation logic in reporting.py based on alerts and opportunities
- Update database queries to fetch competitor_metadata.strategy (may need admin tool to populate)

---

## Part 2: Feature Authorization (Net-New Components)

### APPROVED FEATURE 1: Competitor Keyword Mining Module

**Module:** `competitor_mining.py` (161 lines)

**Purpose:** 
Extract top keywords from competitors discovered in audit results. Identify keyword gaps not yet in Tool 2's target list. Generate `competitor_keyword_gap.md` markdown report.

**Justification:**
- Gap 1 (handoff ingestion) gives us a starting competitor list
- competitor_mining.py extends that list by discovering additional competitors from audit results
- Enables continuous discovery without manual updates to Key_domains.csv
- Feeds back into audit loop: new competitors → new keywords → expanded audit scope

**Approved Scope:**
- Extract top N domains from `audit_results_run_*.xlsx` (configurable, default 5)
- For each domain: fetch top 20 keywords via DataForSEO API
- Compare against existing keyword CSV
- Output markdown with new opportunities
- Optionally add new keywords to Key_domains.csv (requires human approval)

**New Configuration (shared_config.json):**
```json
{
  "competitor_mining": {
    "enabled": true,
    "top_domains_limit": 5,
    "keywords_per_domain": 20,
    "audit_xlsx_path": "audit_results_run_4.xlsx",
    "existing_keywords_csv": "serp-keyword/keywords_Couple_Marriage_RelationshipLocal.csv",
    "output_markdown": "competitor_keyword_gap.md",
    "brand_suffix_removal": ["counselling", "counseling", "therapy", "therapist", "counselor", "counsellor"]
  }
}
```

**Success Criteria:**
- ✅ Extracts top domains from audit results
- ✅ Fetches keywords for each domain
- ✅ Identifies gaps (new keywords not in existing list)
- ✅ Generates markdown report
- ✅ No automatic modifications to Key_domains.csv (human review required)
- ✅ Configuration-driven behavior

---

### APPROVED FEATURE 2: Streamlit Orchestration UI

**Module:** `orchestrator.py` (168 lines)

**Purpose:** 
User-friendly workflow interface for step selection and execution. Replace CLI with visual dashboard.

**Justification:**
- Pipeline has 5+ steps (mining, audit, scoring, GSC, strike mapping)
- Non-technical stakeholders (operations, content team) need to run audits
- CLI is error-prone; UI provides visibility and error handling
- Real-time log streaming allows debugging without log files

**Approved Scope:**
- Dropdown selector for keyword CSV file
- Checkbox controls for Steps 1–5
- Run button to execute selected steps
- Expandable log view with real-time output
- Success/failure feedback per step

**Step Dependencies (Formalized in v3):**
- Step 1 (mining): Standalone (optional)
- Step 2 (audit): Requires Step 1 OR manual keyword input
- Step 3 (scoring): Includes Step 2 (cannot be disabled)
- Step 4 (GSC): Independent (requires GSC auth, no step dependencies)
- Step 5 (strike mapping): Requires Step 4 output

**New Configuration (shared_config.json):**
```json
{
  "orchestrator": {
    "enabled": true,
    "streamlit_theme": "light",
    "step_timeout_seconds": 3600,
    "log_level": "INFO",
    "show_advanced_options": false
  }
}
```

**Success Criteria:**
- ✅ UI displays all 5 steps with clear naming
- ✅ Step dependencies documented and enforced (Step 3 includes Step 2)
- ✅ Real-time log streaming
- ✅ Success/failure feedback per step
- ✅ Logs saved to timestamped file
- ✅ Error handling with user recovery options (retry, skip, abort)

**v3 Enhancement — Step Dependency Manager:**
Current: Hardcoded dependency logic in orchestrator UI
v3: Propose DAG (Directed Acyclic Graph) specification in config

```json
{
  "step_dag": {
    "step_1_mining": { "name": "Competitor Mining", "depends_on": [], "optional": true },
    "step_2_audit": { "name": "SERP Audit", "depends_on": ["step_1_mining"], "optional": false },
    "step_3_scoring": { "name": "Scoring", "depends_on": ["step_2_audit"], "optional": false, "includes": ["step_2_audit"] },
    "step_4_gsc": { "name": "GSC Analysis", "depends_on": [], "optional": true },
    "step_5_strike": { "name": "Strike Mapping", "depends_on": ["step_4_gsc"], "optional": true }
  }
}
```

This allows future steps to be added without code changes.

---

### APPROVED FEATURE 3: Strike Mapping (GSC → Content Planning)

**Module:** `strike_mapper.py` (66 lines)

**Purpose:** 
Map GSC "striking distance" keywords (positions 11–25) to existing publication drafts. Support content planning workflow.

**Justification:**
- GSC analysis identifies low-hanging fruit (positions 11–25 are close to Page 1)
- Content team needs to know: "Which draft should I publish to rank for this keyword?"
- strike_mapper bridges analytics → content execution gap
- Enables prioritization: which keyword targets have draft ready?

**Approved Scope:**
- Input: GSC striking distance keywords (from gsc_performance.py)
- Input: Directory of draft files (markdown, .docx, or .md)
- Output: DataFrame mapping keyword → best-matching draft (with confidence)
- Output: Markdown report for content team

**Matching Algorithm:**
- Keyword to draft matching via:
  - Exact title match (highest confidence)
  - Keyword presence in draft (medium confidence)
  - Semantic similarity via spaCy (low confidence)
- Return top 3 candidate drafts per keyword with confidence scores

**New Configuration (shared_config.json):**
```json
{
  "strike_mapper": {
    "enabled": true,
    "gsc_keywords_source": "gsc_performance",
    "drafts_directory": "publication/",
    "draft_extensions": [".md", ".docx", ".txt"],
    "min_confidence_threshold": 0.6,
    "output_markdown": "strike_mapping_report.md",
    "output_spreadsheet": "strike_mapping_report.xlsx"
  }
}
```

**Success Criteria:**
- ✅ Reads striking distance keywords from GSC data
- ✅ Matches keywords to draft files
- ✅ Returns top 3 candidate drafts per keyword with confidence
- ✅ Generates markdown and/or spreadsheet output
- ✅ Ready for content team workflow

---

## Part 3: Technical Debt Remediation

### DEBT 1: Hardcoded Editorial Content (PRIORITY: HIGH)

**Issue:** reframe_engine.py contains hardcoded pivot_map dictionary (20 Bowen reframes)

**Current Code:** `reframe_engine.py:22–41`
```python
self.pivot_map = {
    "avoidant attachment": "Emotional Distance / Pursuer-Distancer",
    "anxious attachment": "Emotional Fusion / Pursuit",
    # ... 18 more entries
}
```

**Problem:**
- Non-engineers cannot edit reframes without code changes
- Reframes are editorial content (should be in config per CLAUDE.md rule)
- No version control on reframe changes
- Difficult to A/B test different reframe variants

**Remediation Plan:**

**Step 1: Move pivot_map to shared_config.json**

```json
{
  "clinical_pivots": {
    "avoidant attachment": "Emotional Distance / Pursuer-Distancer",
    "anxious attachment": "Emotional Fusion / Pursuit",
    "boundaries": "Differentiation of Self",
    "toxic person": "Functional Position in the System",
    "trauma": "Multigenerational Emotional Process",
    "anger": "Anger as a Systemic Reactive Process",
    "infidelity": "Infidelity: Reciprocity in the Relationship System",
    "grief": "Grief as a Family Emotional Process",
    "depression": "Depression: A Systemic Functioning Perspective",
    "anxiety": "Anxiety: Intercepting the Relationship Loop",
    "marriage counselling": "Observing the Marriage as an Emotional System",
    "couples counselling": "Relationship Reciprocity and Differentiation",
    "introvert": "Introversion as a Function of Systemic Anxiety",
    "gottman": "Beyond Gottman: A Systemic Differentiation Approach",
    "sexuality": "Sexuality and the Emotional System",
    "narcissist": "The Narcissism Label vs. Systemic Reciprocity",
    "cbt": "Beyond CBT: Focus on Emotional Process",
    "adhd": "ADHD as a Systemic Functioning Variation",
    "attachment styles": "From Attachment Labels to Pursuit-Distance Cycles",
    "self care": "Self-Care as a Differentiation Strategy"
  }
}
```

**Step 2: Update reframe_engine.py**

```python
def __init__(self, config: Dict[str, Any]):
    self.api_key = os.getenv("OPENAI_API_KEY")
    self.client = OpenAI(api_key=self.api_key) if self.api_key else None
    self.model = "gpt-4o"
    # Load from config instead of hardcoded
    self.pivot_map = config.get("clinical_pivots", {})
```

**Step 3: Update main.py**

Pass config to ReframeEngine:
```python
config = load_shared_config()
reframe_engine = ReframeEngine(config)
```

**Acceptance Criteria:**
- ✅ No hardcoded pivot_map in source code
- ✅ pivot_map loaded from shared_config.json
- ✅ Changes to reframes don't require code redeploy
- ✅ Reframe history tracked in git (config changes visible in commits)

**Effort:** 1–2 hours (small, high-impact change)

---

### DEBT 2: Legacy Database Tables (PRIORITY: MEDIUM)

**Issue:** competitor_metrics and semantic_audits tables retained for backwards compatibility but no longer populated

**Current State:** 
- New data written to traffic_magnets and other newer tables
- Legacy tables untouched but still in schema
- Creates confusion: which table is source of truth?

**Remediation Plan:**

**Timeline: v4 or 2026-Q4 (whichever is later)**

**Phase 1 (v3 — Current):**
- Document migration status in GEMINI.md
- Add comment in database.py: "competitor_metrics and semantic_audits deprecated. Removed in v4."
- No data written to legacy tables (already true)
- New installations skip creating legacy tables (via schema versioning)

**Phase 2 (v4 or 2026-Q4):**
- Run migration script: export legacy data to CSV if needed
- Drop competitor_metrics and semantic_audits tables
- Remove legacy table creation from DatabaseManager
- Update documentation

**Current Action (v3):**
1. Add version comment to database.py:
```python
# DEPRECATED: competitor_metrics and semantic_audits tables.
# These tables are retained for backwards-compatibility only.
# No new data written to these tables as of v3.
# Scheduled for removal in v4 (target: 2026-Q4).
# Use traffic_magnets and eeat_scorer results instead.
```

2. Document in GEMINI.md:
```markdown
## Schema Evolution

### Legacy Tables (Deprecated)
- `competitor_metrics` — Deprecated as of v3. Removed in v4.
- `semantic_audits` — Deprecated as of v3. Removed in v4.

All new data written to:
- `traffic_magnets` (replaces competitor_metrics)
- Database stored EEAT results (replaces semantic_audits)
```

**Acceptance Criteria:**
- ✅ Deprecation clearly marked in code
- ✅ Removal date specified (v4 or 2026-Q4)
- ✅ Migration path documented
- ✅ No breaking changes in v3 (legacy tables still readable)

**Effort:** 0.5 hours (documentation only in v3; actual removal in v4)

---

### DEBT 3: Orchestrator Step Dependencies (PRIORITY: MEDIUM)

**Issue:** Step dependencies hardcoded in orchestrator.py UI logic. Adding new steps requires code changes.

**Current Code:** orchestrator.py:47
```python
st.sidebar.warning("Note: Step 3 includes Step 2 internally.")
```

This is a UI note, not enforced logic. Confusing for users.

**Remediation Plan:**

**Step 1: Formalize DAG in shared_config.json**

Already designed in Feature 2 section above. Add this section to config:

```json
{
  "step_dag": {
    "step_1_mining": { "name": "Competitor Mining", "depends_on": [], "optional": true },
    "step_2_audit": { "name": "SERP Audit", "depends_on": ["step_1_mining"], "optional": false },
    "step_3_scoring": { "name": "Scoring", "depends_on": ["step_2_audit"], "optional": false, "includes": ["step_2_audit"] },
    "step_4_gsc": { "name": "GSC Analysis", "depends_on": [], "optional": true },
    "step_5_strike": { "name": "Strike Mapping", "depends_on": ["step_4_gsc"], "optional": true }
  }
}
```

**Step 2: Update orchestrator.py**

- Load step_dag from config
- Disable checkboxes for dependent steps when prerequisite unchecked
- Validate selections against DAG before execution
- Show clear dependency chain to user: "Step 3 requires Step 2. Step 2 will run automatically."

**Step 3: Benefit**

- Adding new steps requires config change, not code change
- Dependencies enforced programmatically, not via UI notes
- Clear visibility: users see "Step 3 requires Step 2" before clicking Run

**Acceptance Criteria:**
- ✅ Step dependencies defined in shared_config.json
- ✅ Orchestrator loads and enforces DAG
- ✅ UI clearly shows dependencies
- ✅ No hardcoded dependency logic in source code

**Effort:** 2–3 hours (moderate refactor)

---

## Part 4: Third-Party Integrations (Future-Readiness)

### INTEGRATION 1: Ahrefs API (Internal Linking Full-Site Crawl)

**Current Limitation:** cluster_detector.py only sees 3 pages per domain (scope limitation)

**Future Enhancement:** Enable full-site analysis via Ahrefs Site Explorer API

**When to Implement:** Post-v3 (v4 or later), pending budget and Ahrefs subscription

**Architecture Plan:**

**1. New Module: `src/third_party_crawlers.py`**
```python
class AhrefsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.ahrefs.com/v3"
    
    def crawl_site(self, domain: str, cache_ttl_days: int = 7) -> Dict[str, Any]:
        """
        Fetch full site graph for domain.
        Returns: {pages: [...], internal_links: [...], crawl_date: ...}
        """
        pass
    
    def get_cached_crawl(self, domain: str) -> Dict[str, Any]:
        """Retrieve cached crawl if < TTL."""
        pass
```

**2. Integration Point: cluster_detector.py Enhancement**

```python
class ClusterDetector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.use_full_site = config.get("cluster_detection_full_site_enabled", False)
        if self.use_full_site:
            self.crawler = AhrefsClient(os.getenv("AHREFS_API_KEY"))
    
    def analyze_domain(self, domain: str, pages: List[Any]) -> ClusterResult:
        """
        Enhanced: If full_site enabled, fetch via Ahrefs instead of limited pages.
        """
        if self.use_full_site:
            crawl = self.crawler.get_cached_crawl(domain)
            pages = crawl.get("pages", [])
        
        # Rest of logic unchanged
        result = self._build_graph(domain, pages)
        return result
```

**3. New Configuration**

```json
{
  "third_party_apis": {
    "ahrefs": {
      "enabled": false,
      "api_key_env_var": "AHREFS_API_KEY",
      "crawl_cache_ttl_days": 7
    }
  },
  "cluster_detection_full_site_enabled": false,
  "cluster_detection_full_site_provider": "ahrefs"
}
```

**4. Cost-Benefit Analysis**

| Aspect | Details |
|--------|---------|
| Cost | Ahrefs: ~$99/month for API access + crawl credits |
| Benefit | Full-site internal linking analysis (not limited to 3 pages) |
| Use Case | Competitive analysis where internal structure is strategic differentiator |
| Decision | Enable if client willing to pay; otherwise use limited-scope signal |

**Success Criteria (Future):**
- ✅ Ahrefs API integrated without breaking limited-scope version
- ✅ Crawl results cached to avoid quota overages
- ✅ ClusterResult confidence increases when based on full-site crawl
- ✅ Fallback to limited-scope if API fails or budget unavailable
- ✅ Documentation clearly states: "Full-site results via Ahrefs" vs. "Limited-scope results"

**Target Timeline:** v4 or later (not in v3)

---

### INTEGRATION 2: Moz API (Authority Trend Analysis)

**Current Limitation:** Database tracks PA per URL, but one-off measurements don't show trends

**Future Enhancement:** Subscribe to Moz API for weekly PA updates across all tracked competitors

**When to Implement:** Post-v3 (v4 or later)

**Architecture Plan:**

**1. New Module: `src/moz_authority_tracker.py`**

```python
class MozAuthorityTracker:
    def __init__(self, config: Dict[str, Any]):
        self.moz_client = MozClient(
            access_id=os.getenv("MOZ_ACCESS_ID"),
            secret_key=os.getenv("MOZ_SECRET_KEY")
        )
        self.scheduler = ... # Background scheduler for weekly updates
    
    def schedule_weekly_updates(self, domains: List[str]):
        """Schedule weekly PA checks for all tracked domains."""
        pass
    
    def fetch_current_pa(self, domain: str) -> Dict[str, Any]:
        """Get current PA and store in database."""
        pass
    
    def calculate_pa_trend(self, domain: str, window_days: int = 90) -> Dict[str, Any]:
        """Compute PA trend over window (increasing, decreasing, stable)."""
        pass
```

**2. Integration Point: velocity_module.py Enhancement**

Current: Compares current vs. previous run (2 snapshots)
Enhanced: Historical trend analysis (90-day rolling window)

**3. New Database Table: `authority_history`**

```sql
CREATE TABLE authority_history (
    id INTEGER PRIMARY KEY,
    domain TEXT,
    pa REAL,
    da REAL,
    measured_at DATETIME,
    source TEXT,  -- "manual_audit" | "moz_weekly"
    FOREIGN KEY(domain) REFERENCES competitors(domain)
);
```

**4. Benefits**

| Benefit | Details |
|---------|---------|
| Trend Detection | Identify competitors gaining/losing authority over time |
| Alert Triggers | "Competitor X trending up; consider defensive content" |
| Long-Term Planning | Assess if competitor momentum is sustainable |
| Market Velocity | Feed into market_alerts for strategic briefing |

**Target Timeline:** v4 or later (not in v3)

---

## Part 5: Implementation Roadmap (v3 → v4+)

### v3 Deliverables (This Specification)

**Timeline:** Immediate (completion date: TBD)

- ✅ Enhance Gap 2 (structured metadata, schema extraction)
- ✅ Enhance Gap 3 (confidence scoring, client messaging)
- ✅ Enhance Gap 4 (third-party integration planning)
- ✅ Enhance Gap 5 (competitive positioning matrix, reframe quality, implementation roadmap)
- ✅ Authorize Features: competitor_mining, orchestrator, strike_mapper
- ✅ Remediate Debt 1: Externalize pivot_map to config
- ✅ Remediate Debt 2: Mark legacy tables for deprecation
- ✅ Remediate Debt 3: Formalize step dependencies as DAG

### v4 Roadmap (Future, Pending Approval)

**Timeline:** Post-v3, pending budget and client needs

- Implement full-site internal linking via Ahrefs API (Debt 3 remediation)
- Implement weekly PA trend tracking via Moz API
- Remove legacy database tables (Debt 2 final step)
- Enhanced clustering with full-site data
- Deprecation warnings for old APIs

### Long-Term Vision (v5+)

- Multi-competitor concurrent tracking (currently single client vs. N competitors)
- Automated competitor discovery (continuous monitoring)
- Predictive ranking alerts (ML-based)
- Integration with content calendar (direct post scheduling)

---

## Approval & Sign-Off

**Specification Status:** ✅ APPROVED FOR IMPLEMENTATION

**Approved By:** Code Review Process (tool2_review_2026-05-02)

**Effective Date:** 2026-05-02

**Next Steps:**
1. Engineering team reviews v3 specification
2. Break v3 deliverables into sprint tasks
3. Estimate effort and plan timeline
4. Begin implementation (priority: technical debt remediation)
5. Plan v4 roadmap pending budget decisions

---

**Document:** serp_tools_upgrade_spec_v3.md  
**Version:** 3.0  
**Generated:** 2026-05-02  
**Based On:** Implementation Review + v2 Spec + 4 Enhancement Areas
