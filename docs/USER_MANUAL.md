# Serp-Compete: Competitive SEO Intelligence User Manual

## Table of Contents
1. [Overview](#overview)
2. [Core Purpose](#core-purpose)
3. [How the System Works](#how-the-system-works)
4. [Workflow & Steps](#workflow--steps)
5. [Key Concepts](#key-concepts)
6. [Configuration](#configuration)
7. [Understanding Your Results](#understanding-your-results)
8. [Troubleshooting](#troubleshooting)

---

## Overview

**Serp-Compete** (Tool 2) is a competitive intelligence platform designed to analyze how your competitors rank in search results and identify opportunities to reframe your content using Bowen Family Systems Theory.

**Client Focus:** Living Systems Counselling — a therapy practice providing Bowen-based family systems counseling.

**Core Goal:** Find keywords where competitors dominate with "Medical Model" language (symptom-focused, diagnostic) and create counter-positioning content using "Systems Approach" language (relationship-focused, process-oriented).

---

## Core Purpose

### The Problem
Many therapy websites (competitors) attract clients through medical terminology:
- "How to diagnose anxiety disorder"
- "Treatment for depression symptoms"
- "Is your child ADHD?"

These searches attract anxiety-driven, label-seeking clients who want quick diagnosis and medication lists.

### The Opportunity
The same clients are also searching for systemic/relational approaches:
- "Why am I anxious in relationships?"
- "How do I stop pursuer-distancer patterns?"
- "Understanding family emotional systems"

**Serp-Compete finds these gaps** and helps you reframe competitor content to serve clients seeking systemic understanding, not diagnostic labels.

---

## How the System Works

### Three Core Engines

#### 1. **Semantic Analysis Engine**
**What it does:** Reads competitor pages and measures their reliance on medical vs. systems language.

**How it works:**
- Scrapes the top 3 ranking pages for each competitor domain
- Extracts page structure (headers, links, metadata)
- Counts occurrences of:
  - **Tier 1 (Medical):** symptom, diagnosis, disorder, treatment, medication
  - **Tier 2 (Systems):** differentiation, triangles, emotional system, family process
  - **Tier 3 (Bowen):** emotional fusion, pursuit-distance, differentiation of self

**Why:** This scoring reveals whether competitors are medical-focused or systems-focused, helping you find gaps where medical competitors haven't addressed systemic language.

---

#### 2. **EEAT Scoring Engine**
**What it does:** Evaluates the credibility signals on competitor pages using a heuristic system.

**How it works:**
Scores four dimensions:

| Dimension | What We Measure | Why It Matters |
|-----------|-----------------|----------------|
| **Experience** | Author byline, publish date, original images, case studies | Shows real expertise and recent updates |
| **Expertise** | Author credentials (MD, LCSW, etc.), schema markup, Bowen terminology | Validates professional authority |
| **Authoritativeness** | Domain authority, external links, organizational schema | Shows how established the site is |
| **Trustworthiness** | HTTPS, contact page, privacy policy, HTTPS | Indicates basic security and transparency |

**Why:** High EEAT scores don't make competitors unbeatable—they just mean you need stronger credentials/signals in your counter-content.

**Important:** These scores are heuristics (educated guesses), not Google's proprietary EEAT model. Use them for competitive comparison, not as absolute truth.

---

#### 3. **Internal Linking Analyzer**
**What it does:** Maps how competitors link their own pages together to create authority clusters.

**How it works:**
- Identifies "hub" pages (pages that many other pages link to)
- Flags whether competitors have strong internal linking patterns
- Classifies sites as: **isolated** (no internal network), **linked** (some connections), **clustered** (strong hub pages)

**Why:** Well-linked internal structures help Google understand page relationships. Competitors with strong clusters make it harder to displace them. Isolated competitors are easier targets.

**Limitation:** Analysis only sees 3 scraped pages per competitor. Full site structure requires external APIs (Ahrefs/Moz).

---

## Workflow & Steps

The system executes in 5 optional steps (configurable via `shared_config.json`):

### **Step 1: Competitor Keyword Mining** (Optional)
**What:** Discover keyword gaps from competitors you've already analyzed.

**Input:** Existing competitor data from Tool 1 (Serp-Discover)

**Output:** New keywords not yet analyzed, sorted by opportunity

**When to use:** If you want to expand your target list automatically

---

### **Step 2: SERP Audit & Enrichment** (Required)
**What:** Scrape and analyze the top competitors for your target keywords.

**Detailed process:**

1. **Fetching**: Downloads the top N competitor pages for each keyword
   - Uses realistic browser headers to avoid blocking
   - Handles rate-limiting (429 errors trigger circuit breaker)
   - Retries on network errors, fails hard on 400+ errors

2. **Page Structure Extraction**:
   - Extracts all headers (H1, H2, H3) in order
   - Extracts metadata: title, meta description, author byline, publish/update dates
   - Extracts images and checks if they're stock images (Shutterstock, Getty, etc.)
   - Extracts all internal and external links
   - Detects JSON-LD schema (Article, FAQPage, LocalBusiness)
   - Extracts the first 500 words for vocabulary analysis

3. **Semantic Scoring**:
   - Analyzes text for Tier 1/2/3 keyword mentions
   - Calculates weighted score (Tier 3 weighted 2x, Tier 2 weighted 0.5x)
   - Assigns "Systemic Label": Bowen-Heavy, Systems-Moderate, Medical-Dominant, Standard

**Output:**
- Database records for each audited URL
- Scores showing medical vs. systems focus
- Metadata for EEAT and internal linking analysis

---

### **Step 3: Systematic Scoring** (Required)
**What:** Score all competitors and identify "Traffic Magnets" (high-value targets).

**Metrics calculated:**
- **Medical Score**: Raw count of medical terminology
- **Systems Score**: Weighted count of systems + Bowen terminology
- **Systemic Label**: Classification of content approach
- **Market Position**: Rank trend, authority, traffic estimate
- **Feasibility**: Can we realistically compete for this keyword?

**Output:**
- Competitor summary table (domain, top pages, avg position, systemic depth)
- Traffic magnets ranked by traffic potential
- Strategic targets identified (competitors using medical model in high-traffic areas)

---

### **Step 4: GSC Analysis** (Optional)
**What:** Analyze your own site's Google Search Console data to find internal opportunities.

**What it finds:**
- **High Impression / Low CTR**: Pages people see but don't click on
- **Page 2 Targets**: Keywords ranking positions 11-20 (one good page could push to #1)
- **Clinical Mismatches**: Cases where systems-heavy content ranks for medical queries (or vice versa)

**Output:**
- Internal gap analysis
- Publishing priorities for your own content

---

### **Step 5: Strike Mapping** (Optional)
**What:** Map the gap between your current content and what you need to publish.

**Identifies:**
- Keywords where you have no content (major gaps)
- Keywords where you rank but can improve (striking distance)
- Publication priorities based on traffic + feasibility

**Output:**
- Strike list for content team
- Publishing roadmap

---

## Key Concepts

### The Medical Model vs. Systems Approach

#### Medical Model (Competitor Language)
**Focus:** Individual pathology
- "You have anxiety disorder"
- "Symptoms of ADHD"
- "Treatment options"
- Assumes individual diagnosis and treatment

#### Systems Approach (Your Reframe)
**Focus:** Relationship patterns
- "How anxiety shows up in relationships"
- "Pursuit-distance dance in couples"
- "De-triangulation strategies for families"
- Assumes change happens through relational awareness

### Traffic Magnets
High-value competitor pages that:
- Rank well (top 10)
- Get significant traffic
- Use medical model language
- Represent unmet systems-approach demand

**Strategy:** Create systems-focused content for the same keyword, potentially converting a portion of that traffic.

### Systemic Vacuum
A keyword where:
- Competitors rank but use only medical model
- No strong systems approach content exists
- Users asking the question would benefit from relational framing

**Example:**
- Competitor ranks for "How to fix anxiety in relationships" with only medication advice
- Opportunity: Rank for same keyword with differentiation + emotional process education

### Bowen Reframes
Automated content outlines that reframe competitor content using Bowen Family Systems concepts:

| Concept | Meaning |
|---------|---------|
| **Differentiation of Self** | Defining your own values/reactions without blaming or merging with others |
| **Emotional Fusion** | Over-involvement; losing sense of self in relationships |
| **Pursuit-Distance** | One partner pursuing (more engaged), other distancing (withdrawing) |
| **Triangulation** | Three-person pattern; when two struggle, they pull in a third |
| **Anxiety Loop** | Chronic anxiety that perpetuates relationship reactivity |

---

## Configuration

All behavior is controlled via `shared_config.json`:

### **clinical_pivots**
```json
"clinical_pivots": {
  "anxiety": "Anxiety: Intercepting the Relationship Loop",
  "avoidant attachment": "Emotional Distance / Pursuer-Distancer",
  "boundaries": "Differentiation of Self"
}
```
Non-engineers can edit these to change reframe triggers without touching code.

### **step_dag**
```json
"step_dag": {
  "step_1_mining": {"optional": true, "depends_on": []},
  "step_2_audit": {"optional": false, "depends_on": ["step_1_mining"]}
}
```
Defines which steps are required, which are optional, and dependencies between them.

### **handoff**
```json
"handoff": {
  "supported_versions": ["2.0", "2.1"],
  "minimum_version": "2.0"
}
```
Controls compatibility with Tool 1 (Serp-Discover) data formats.

### **eeat_client_messaging**
```json
"eeat_client_messaging": {
  "caveat": "These are heuristic proxies, not Google's actual EEAT",
  "confidence_levels": {
    "high": "0.8-1.0: Reliable signals"
  }
}
```
Client-facing language for explaining EEAT scores.

---

## Understanding Your Results

### The Strategic Briefing Report

#### Section A: Executive Summary
Overview of what was analyzed and key findings.

#### Section B: EEAT Competitive Analysis
For each competitor URL audited:
- Experience score (author, dates, images)
- Expertise score (credentials, schema, Bowen terminology)
- Authoritativeness score (domain authority, links)
- Trustworthiness score (HTTPS, contact info)

**How to use:** Low EEAT scores on competitor pages = opportunity for you to build stronger signals.

#### Section C: Internal Linking Cluster Analysis
For each competitor domain:
- Pages analyzed (usually 3)
- Cluster signal: isolated | linked | clustered
- Average link degree, max link degree

**How to use:** "Isolated" competitors are easier to overtake. "Clustered" competitors have strong internal networks you'll need to match.

#### Section D: Competitor Ranking Summary
Table showing:
- Domain name
- Number of top pages
- Total keywords ranking
- Average position
- Systemic depth (Medical | Systems | High)
- Recommended strategy

**How to use:** Focus on "Medical-Dominant" competitors—they're your reframing opportunities.

#### Section E: Traffic Magnets
Top competitor pages ranked by traffic potential, showing:
- Domain & URL
- Keyword
- Estimated traffic
- Medical vs. systems score
- Systemic label

**How to use:** These are your target keywords. Create systems-focused content for each.

#### Section F: Strategic Targets (Systemic Vacuums)
Competitors using ONLY medical language. 

**Action:** Create systems-focused alternative content for these exact keywords.

#### Section G: Automated Bowen Reframes
AI-generated content outlines for reframing competitor content.

**Format:**
1. **Identify the Anxiety Loop**: How does the medical model reinforce chronic anxiety?
2. **The Systemic Reframe**: Shift from individual pathology to relationship system
3. **Bowen Concepts**: Apply differentiation, triangles, multigenerational process
4. **Differentiation Strategy**: Why Bowen is more effective than tools/tips

**How to use:** Use these as starting points for your content writers. Not production-ready, but provides structure.

---

## Troubleshooting

### "HTTP 429 — Rate Limited"
**Cause:** Domain is blocking requests after multiple accesses.

**Solution:** 
- The system stops analyzing that domain and moves on
- Try again in 24-48 hours
- Consider rotating IP addresses if analyzing same domain repeatedly

### "No data found for competitor"
**Cause:** Domain doesn't appear in top 10 for that keyword, or your keyword list is incomplete.

**Solution:**
- Verify the keyword actually has competitors
- Check if your keyword data came from Tool 1 (Serp-Discover)
- Expand keyword research in Tool 1

### "EEAT scores are all low"
**Cause:** Competitor pages lack structured metadata (author, dates, schema).

**Solution:**
- This is actually good for you—it's an opportunity to build stronger signals
- Create pages with clear author bylines, publish dates, original images, and FAQ schema

### "Cluster signal says 'isolated' but competitor still ranks well"
**Cause:** The competitor may have other pages not in our 3-page sample, or they rank through other signals (domain authority, backlinks).

**Solution:**
- Isolated pages are easier to outrank, but look at their overall domain authority first
- Consider using Ahrefs/Moz for full site crawl (planned for v4)

### Database grows very large
**Cause:** Running audits repeatedly adds new records for each run.

**Solution:**
- Keep only the most recent audit runs; old runs can be archived
- Database has 9+ years of capacity before cleanup is needed
- See docs/DATA_PERSISTENCE_MAP_v3.md for retention policy

---

## Quick Start Guide

### Minimal Setup (15 minutes)

1. **Prepare your keyword list** (CSV format)
   - One keyword per row
   - Include source (organic search, client request, etc.)

2. **Update shared_config.json**
   - Set your client domain
   - Set GSC credentials path (if running Step 4)
   - Adjust clinical_pivots if needed

3. **Run the audit**
   ```bash
   cd Serp-compete
   python3 src/main.py
   ```

4. **Check the results**
   - Output: `strategic_briefing_run_N.md` (Markdown) + `.xlsx` (Excel)
   - Open in your browser or spreadsheet

5. **Share with content team**
   - Traffic magnets = keywords to target
   - Systemic vacuums = reframing opportunities
   - Bowen reframes = content structure templates

### Advanced Features (30-60 minutes)

1. **Enable GSC analysis** (Step 4)
   - Provides internal gap analysis
   - Helps you find page 2 keywords to target

2. **Enable competitor mining** (Step 1)
   - Auto-discovers related keywords from competitors
   - Useful for expanding strategy

3. **Customize reframes**
   - Edit `shared_config.json` clinical_pivots
   - Changes how AI generates content outlines

4. **View full site structure**
   - Set up Ahrefs/Moz API tokens (v4 feature)
   - Get complete internal linking analysis

---

## Architecture Overview (For Technical Users)

### Data Flow
```
Tool 1 (Serp-Discover)
    ↓
    [Handoff JSON]
    ↓
Tool 2 (Serp-Compete)
├─ Step 1: Competitor Mining (optional)
├─ Step 2: Semantic Audit
│  ├─ Scrape & Extract (semantic.py)
│  └─ EEAT Scoring (eeat_scorer.py)
├─ Step 3: Scoring & Gaps
│  └─ Cluster Detection (cluster_detector.py)
├─ Step 4: GSC Analysis (optional)
│  └─ Internal gaps (gsc_performance.py)
├─ Step 5: Strike Mapping (optional)
│  └─ Content roadmap (strike_mapper.py)
└─ Reporting
   └─ Strategic Briefing (reporting.py)
        ↓
    [Markdown + Excel Output]
```

### Database Schema
- **runs**: Audit execution history
- **competitors**: Summary by domain
- **traffic_magnets**: High-value URLs
- **market_gaps**: Keyword opportunities
- **eeat_scores**: EEAT signals (new in v3)
- **cluster_results**: Internal linking analysis (new in v3)
- **semantic_audit_results**: Tier scoring (new in v3)

### Backwards Compatibility
- Maintains `first_500_words` field for legacy vocabulary scoring
- Supports handoff v2.0 and v2.1 formats
- All config access uses safe defaults (won't crash if sections missing)

---

## Support & Documentation

- **Specification**: `docs/serp_tools_upgrade_spec_v3.md`
- **Data Schema**: `docs/DATA_PERSISTENCE_MAP_v3.md`
- **Implementation Details**: `docs/SPEC_COVERAGE_REPORT_v3.md`
- **Configuration**: `shared_config.json` (fully commented)
- **Project Context**: `GEMINI.md`

---

## Key Takeaway

**Serp-Compete finds keyword opportunities where medical-model competitors dominate, then helps you reframe content to serve clients seeking systemic/relational understanding.**

By understanding competitor content (what they say, how credible they are, how they link internally) and analyzing your own site's performance, you can build a strategic roadmap to attract clients who want Bowen-based family systems work—not just symptom management.

---

**Version:** 3.0  
**Last Updated:** 2026-05-02  
**For questions, see:** docs/GEMINI.md & docs/SPEC_COVERAGE_REPORT_v3.md
