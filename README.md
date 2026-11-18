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
With no argument the newest `competitor_handoff_*.json` in the project root is used.
To audit a specific one — and have the briefing header name it:
```bash
PYTHONPATH=. python3 src/main.py --handoff /path/to/competitor_handoff_….json
```
The GUI passes this flag for the handoff you select, so its selection now takes effect
whether or not "Copy handoff to root" is ticked.

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
- **[handoff_contract.md](docs/handoff_contract.md)** — What the serp-discover handoff and
  exports *mean*, as opposed to `handoff_schema.json`, which says only whether a file is
  well-formed: domain canonical form, rank semantics, which fields must survive ingestion,
  and what this tool does when the producer sends something it cannot trust
- **[FEATURE_GUIDE.md](docs/FEATURE_GUIDE.md)** — What each section measures, and §9 for the
  limitations and the provenance of every threshold that drives a verdict
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

**Audit universe:** the URLs and keywords Serp-Discover handed over — each target's
`url` audited on its `primary_keyword_for_url`, at the `rank` Tool 1 measured. DataForSEO's
per-domain `ranked_keywords` list is fetched as an *additional enrichment* only, and a keyword
from it is kept only when it is in the handoff set or carries a clinical term, and never when it
contains the competitor's own brand token. Every keyword in the report is labelled `handoff` or
`ranked_keywords`.

**Traffic Magnets:** competitor pages that meet all three parts of the definition — they rank
well (handoff rank ≤ `technical.magnet_max_position`), they use medical language
(`medical_score` ≥ `technical.vacuum_min_medical`), and their keyword passes the relevance test
above. Opportunity to capture traffic with a systems-focused alternative. The briefing states
how many of the audited pages qualified.

**Systemic Vacuum:** a Traffic Magnet with no systemic language (systems score 0 or the
Surface-Level label) — your keyword, met by a well-ranking medical-model page. Prime target for
reframing content, and the input to the automated reframes, which are the same query.

**Bowen Reframe:** Content outline that shifts from individual pathology ("What's wrong with me?") to relationship dynamics ("How does our system work?").

## Workflow

1. **Run Serp-Discover** to analyze keywords and competitors
2. **Generate competitor_handoff** from Serp-Discover
3. **Run Serp-Compete** to audit competitor pages
4. **Review strategic briefing** for reframing opportunities
5. **Create content** targeting traffic magnets with Bowen language

## Configuration

All settings in `shared_config.json`. They are read **when the step that uses
them starts** — the scoring vocabulary and weights once per run, when the
analyser is built — not when the code is loaded, so editing the file and running
again in the same GUI session uses the new values. Editing it while a run is in
progress does not change that run. One reader opens the file
(`src/config_io.py`) and it **raises** on a file that will not parse rather
than running on defaults: until review chunk Y16 the scoring path swallowed
that failure and scored every competitor with an empty clinical vocabulary
while reporting the result as a measurement. The single exception is the
database lock wait, which is not an editorial threshold and is logged when it
falls back.

Settings:
- `client.domain` — Your domain (for comparison)
- `client.da` — Your Domain Authority (for feasibility scoring)
- `clinical_pivots` — Bowen concepts for reframing (non-code editable)
- `technical.max_audit_pages_per_domain` — Pages scraped per competitor (default 3)
- `technical.vacuum_min_medical` — Minimum medical score before a page can be a Traffic Magnet,
  a Systemic Vacuum or a reframe target (**6** since 2026-11-15, was 10; editorial, uncalibrated —
  re-set because owner decision 3 shrank the Tier-1 vocabulary, see its `_source` note)
- `technical.scoring_window_words` — Body words vocabulary scoring reads, and the denominator of
  every reported density (default 500)
- `technical.position_thresholds` — `tag_competitor_position`'s Volume-Scaler / Generalist
  thresholds, previously hard-coded in `database.py`
- `technical.penalty_thresholds.tier_1_max_density_per_1000` — The Surface-Level trigger, a Tier-1
  density per 1000 scored words (12) with `tier_1_min_hits` (3) under its numerator; the old
  absolute-count `tier_1_max` remains only as the no-window fallback
- `clinical.*` / `clinical_dictionary.json` — The vocabulary. Entries are **lemmas**; Tier 1 is
  diagnostic vocabulary only, and `neutral_clinical` records the words owner decision 3 excluded
- `technical.magnet_max_position` — The "ranks well" ceiling, read against the handoff rank
  (default 10; encodes the documented "top 10")
- `branded_demand.ambiguous_brand_ratio` — Withhold a brand's share/growth when its bare stem
  pulls this many times the practice name's search volume (default 10; editorial, uncalibrated)
- `risk_signals.pa_drop_min` — Smallest Moz Page-Authority drop between consecutive runs
  reported as a Fragile Magnet (default 3; **editorial, uncalibrated 2026-11-15**)
- `risk_signals.cliff_min_sample` — Smallest per-run keyword sample a `visibility_cliff` may be
  computed on; below it the signal is withheld and the briefing says so (default 10; editorial,
  uncalibrated 2026-11-15)
- `reporting.markdown_row_cap` / `reporting.magnet_markdown_row_cap` — How many rows the
  **markdown** briefing prints per long section (30 / 20); every Excel sheet always carries the
  full set, and each capped section says "Showing the first N of M"
- `reporting.systems_depth_min_t2` — Tier-2 term count at which `systemic_depth` reads
  "Systems (Tier 2 only)" rather than "Trace" (default 3; editorial, uncalibrated 2026-11-15)
- `orchestrator.reports_dir` — Where the briefing and workbook are written (set in the GUI's
  Settings tab; honoured by the writer since 2026-11-15)
- `handoff.supported_versions` — Tool 1 handoff formats accepted (`1.0`, `1.1`, `2.0`,
  `2.1`; Tool 1 writes 2.0, or 2.1 with the Moz block, and the 1.x files on disk are the
  same shape with page-relative ranks). **Enforced** since 2026-11-15: an unlisted
  `schema_version` is a hard fail, not a silent audit. `handoff.absolute_rank_versions`
  lists the versions whose `rank` counts across the whole SERP
- `technical.feasibility_threshold` / `high_authority_max_pa` / `risk_signals.volatility_min_shift`
  — the DA head-start, the "too entrenched to audit" PA line, and the Volatility Alert trigger.
  All three were literals in Python until 2026-11-15
- `gsc_settings.date_range_days` / `country` / `device` — the GSC window (now read; it was hard-coded at 90),
  the market filter and the device filter, so your positions and your CTRs come from the same
  country and the same device as the SERP snapshot. `device: all` turns that filter off and the
  report then states the figures are not comparable (chunk X)
- `dataforseo_snapshot.location_code` / `country` / `device` — the market every DataForSEO SERP
  call requests. Promoted out of four `api_clients.py` literals in chunk X so the GSC pull note
  can CHECK that the two sides describe the same population instead of asserting it
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
