# Serp-Compete: Competitive SEO Intelligence Tool

Market intelligence platform for [Living Systems Counselling](https://livingsystems.ca) — Bowen Family Systems therapy practice in North Vancouver, BC.

**Serp-Compete** (Tool 2) analyzes how your competitors rank in search results and identifies strategic gaps where you can reframe content using **Bowen Family Systems Theory** instead of the traditional "Medical Model."

## What It Does

- **Analyzes top competitors** for your target keywords
- **Scores competitor pages** for medical vs. systems-based language
- **Identifies "Traffic Magnets"** — high-value pages you can reframe
- **Finds "Systemic Vacuums"** — keywords where competitors use only medical language
- **Generates Bowen reframes** — AI-powered content outlines for differentiation strategy

## Quick Start

### Prerequisites
- Python 3.12+
- Competitor data from **Serp-Discover** (Tool 1)
- Environment variables: `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `OPENAI_API_KEY`, `MOZ_TOKEN`

### Run the Analysis

**Option 1: GUI (Recommended)**
```bash
./run_gui.sh
```
Opens web interface at `http://localhost:8501` for running audits and browsing previous reports.

**Option 2: Command Line**
```bash
./run_audit.sh
```
Auto-finds latest competitor handoff from Serp-Discover and runs audit.

**Option 3: Direct Python**
```bash
cd Serp-compete
PYTHONPATH=. python3 src/main.py
```

## Output

Each audit generates:
- **`strategic_briefing_run_N.md`** — Complete competitive analysis + Bowen reframes
- **`audit_results_run_N.xlsx`** — Same data in spreadsheet format

## Features

✅ **Semantic Analysis** — Scores competitor pages for medical vs. systems language  
✅ **EEAT Heuristics** — Experience, Expertise, Authoritativeness, Trustworthiness scoring  
✅ **Internal Linking** — Detects competitor hub pages and link clusters  
✅ **Bowen Reframes** — OpenAI (`gpt-4o`) generates content outlines for reframing opportunities  
✅ **Strategic Briefing** — Executive summary + traffic magnets + reframing targets  
✅ **Web GUI** — Streamlit interface with previous reports browser  
✅ **Configurable** — All settings in `shared_config.json`

## Testing

There are two test suites:

```bash
# Core/unit suite (54 tests) — lives beside the source
cd Serp-compete
PYTHONPATH=. pytest tests/ -q

# v3 feature suite (EEAT, cluster detection, step DAG, page structure, handoff ingestion)
# lives at the project root
PYTHONPATH=Serp-compete pytest tests/ -q
```

The `Serp-compete/tests/` folder holds 54 tests. A separate, larger suite at the
project root (`tests/`, 158 tests) covers the v3 features (EEAT scoring, cluster
detection, `step_dag`, page-structure extraction, handoff ingestion). Run both to
validate the full feature set described in this README.

## Documentation

- **[USER_MANUAL.md](docs/USER_MANUAL.md)** — Comprehensive guide for end users
- **[SPEC_COVERAGE_REPORT_v3.md](docs/SPEC_COVERAGE_REPORT_v3.md)** — Implementation status
- **[DATA_PERSISTENCE_MAP_v3.md](docs/DATA_PERSISTENCE_MAP_v3.md)** — Database schema
- **[shared_config.json](shared_config.json)** — All configuration options (fully commented)

## Architecture

```
Serp-Discover (Tool 1)
    ↓ generates
competitor_handoff_*.json
    ↓ consumed by
Serp-Compete (Tool 2)
    ├─ Semantic Audit (medical vs. systems language)
    ├─ EEAT Scoring (credibility signals)
    ├─ Cluster Detection (internal linking)
    ├─ GSC Analysis (optional: internal gaps)
    └─ Strategic Briefing Report
        ├─ Traffic Magnets (high-value targets)
        ├─ Systemic Vacuums (reframing opportunities)
        └─ Bowen Reframes (AI content outlines)
```

## Key Concepts

**Traffic Magnets:** High-volume competitor pages that rank well but use only medical language. Opportunity to capture traffic with systems-focused alternative.

**Systemic Vacuum:** Keyword where competitors dominate with medical model but no strong systems approach exists. Prime target for reframing content.

**Bowen Reframe:** Content outline that shifts from individual pathology ("What's wrong with me?") to relationship dynamics ("How does our system work?").

## Workflow

1. **Run Serp-Discover** to analyze keywords and competitors
2. **Generate competitor_handoff** from Serp-Discover
3. **Run Serp-Compete** to audit competitor pages
4. **Review strategic briefing** for reframing opportunities
5. **Create content** targeting traffic magnets with Bowen language

## Configuration

All settings in `shared_config.json`:
- `client.domain` — Your domain (for comparison)
- `client.da` — Your Domain Authority (for feasibility scoring)
- `clinical_pivots` — Bowen concepts for reframing (non-code editable)
- `technical.max_audit_pages_per_domain` — Pages scraped per competitor (default 3)
- `handoff.supported_versions` — Tool 1 handoff formats accepted (e.g. `2.0`, `2.1`)
- `eeat_weights`, `cluster_thresholds`, `scoring_weights` — tuning for the scoring engines

> **Note:** the handoff source directory and reports directory are **not** stored in
> `shared_config.json` by default. They are entered in the GUI's Settings tab at runtime
> and only written to the `orchestrator` block once you save them there.

## Out of Scope

**Backlink / off-site authority analysis.** Serp-Compete audits competitor pages'
on-page and structural signals (language, EEAT, internal-link clusters, GEO/
extractability); it does **not** analyse competitors' backlink profiles. Backlink
discovery, toxic-link identification, and referring-domain diversity are
deliberately out of scope. Across the tool suite, Domain Authority (and Moz Page
Authority) serve as the single authority proxy; a full backlink graph requires a
paid third-party link-index provider (Ahrefs, Majestic, or DataForSEO backlinks)
and is judged low-ROI for a single nonprofit. This is a deliberate boundary, not
an omission — revisit only if scale or budget changes.

## Support

- **User Manual:** [docs/USER_MANUAL.md](docs/USER_MANUAL.md)
- **Implementation Details:** [docs/SPEC_COVERAGE_REPORT_v3.md](docs/SPEC_COVERAGE_REPORT_v3.md)
- **Database Schema:** [docs/DATA_PERSISTENCE_MAP_v3.md](docs/DATA_PERSISTENCE_MAP_v3.md)

## Version

**v3.0** — Complete implementation with EEAT scoring, internal linking detection, DAG-based workflow, and configurable architecture.

**Last Updated:** 2026-05-02
