# Data Persistence Map — Tool 2 v3

**Date:** 2026-05-02  
**Purpose:** Document all data storage requirements and SQL schema for Tool 2 enhanced features.

---

## Schema Overview

### Core Tables (Existing)

| Table | Purpose | Key Fields | Status |
|-------|---------|-----------|--------|
| `runs` | Audit run metadata | id (PK), client_domain, timestamp | Active |
| `competitors` | Competitor domain summary | domain (PK), avg_da, last_crawled_at | Active |
| `traffic_magnets` | High-value competitor URLs | id (PK), run_id (FK), domain, url, keyword, est_traffic, medical_score, systems_score, systemic_label | Active |
| `market_gaps` | Strategic keyword gaps | id (PK), run_id (FK), keyword, competitor_overlap_count, feasibility_status | Active |
| `competitor_history` | Longitudinal rank/traffic tracking | id (PK), run_id (FK), url, position, pa, traffic_value, drift, timestamp | Active (Rev 4) |
| `competitor_metadata` | Strategic positioning data | domain (PK), market_position, strategy, last_updated | Active (Rev 3) |

### Legacy Tables (Retained for Migration)

| Table | Purpose | Status |
|-------|---------|--------|
| `competitor_metrics` | Deprecated; use traffic_magnets | Deprecated |
| `semantic_audits` | Deprecated; use traffic_magnets | Deprecated |

---

## New Tables for v3 Features

### 1. EEAT Scores Table

**Purpose:** Persist EEAT heuristic signals for each audited page (Gap 3 enhancement).

**Table Name:** `eeat_scores`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS eeat_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    scored_at TEXT NOT NULL,  -- ISO 8601 timestamp
    
    -- Experience signals
    has_author_byline BOOLEAN,
    has_publish_date BOOLEAN,
    has_update_date BOOLEAN,
    has_likely_original_images BOOLEAN,
    first_person_count_normalised REAL,
    case_study_signal BOOLEAN,
    experience_score REAL,
    
    -- Expertise signals
    has_credentials_in_byline BOOLEAN,
    schema_author_type_person BOOLEAN,
    tier_3_or_tier_2_present BOOLEAN,
    expertise_score REAL,
    
    -- Authoritativeness signals
    domain_authority_normalised REAL,
    external_link_count_normalised REAL,
    schema_organization_present BOOLEAN,
    authoritativeness_score REAL,
    
    -- Trustworthiness signals
    is_https BOOLEAN,
    has_contact_link BOOLEAN,
    has_privacy_link BOOLEAN,
    trustworthiness_score REAL,
    
    -- Metadata
    score_confidence TEXT,  -- "high" | "medium" | "low"
    caveat TEXT,  -- "Heuristic proxy. Not Google's actual EEAT model."
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_eeat_scores_url ON eeat_scores(url);
CREATE INDEX IF NOT EXISTS idx_eeat_scores_run ON eeat_scores(run_id);
```

**Usage:**
- Scoring module writes after auditing each page
- Reporting module reads to include EEAT breakdown in strategic briefing
- Delta module uses for competitive EEAT comparison

---

### 2. Cluster Results Table

**Purpose:** Persist internal linking cluster analysis for each competitor domain (Gap 4 enhancement).

**Table Name:** `cluster_results`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS cluster_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    analysed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Analysis metadata
    pages_analysed INTEGER,
    
    -- Graph structure (JSON)
    internal_link_graph TEXT,  -- JSON: {url: {out_links_to_domain, in_links_from_domain, in_degree, out_degree}}
    
    -- Hub detection
    hub_candidates TEXT,  -- JSON: [url1, url2, ...]
    
    -- Cluster signal
    cluster_signal TEXT,  -- "isolated" | "linked" | "clustered" | "insufficient_data"
    resolution_caveat TEXT,  -- Explanation of limitations
    
    -- Linking summary
    avg_in_degree REAL,
    max_in_degree INTEGER,
    num_connected_components INTEGER,
    
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_results_domain ON cluster_results(domain);
CREATE INDEX IF NOT EXISTS idx_cluster_results_run ON cluster_results(run_id);
```

**Usage:**
- Cluster detector writes after analyzing each domain
- Reporting module reads to include cluster signal in competitive brief
- Feasibility module uses to adjust scoring for well-linked vs. isolated competitors

---

### 3. Semantic Audit Results Table

**Purpose:** Persist detailed semantic analysis (medical vs. systems tier scoring) for each URL.

**Table Name:** `semantic_audit_results` (renamed from legacy `semantic_audits` for clarity)

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS semantic_audit_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    
    -- Scoring tiers
    tier_1_medical_score INTEGER,
    tier_1_medical_terms_found TEXT,  -- JSON: [term1, term2, ...]
    
    tier_2_systems_score INTEGER,
    tier_2_systems_terms_found TEXT,  -- JSON: [term1, term2, ...]
    
    tier_3_bowen_score INTEGER,
    tier_3_bowen_terms_found TEXT,  -- JSON: [term1, term2, ...]
    
    -- Classification
    systemic_label TEXT,  -- "Bowen-Heavy" | "Systems-Moderate" | "Medical-Dominant" | "Standard"
    medical_model_indicator BOOLEAN,  -- Whether primarily medical terminology
    
    -- Audit quality
    extraction_status TEXT,  -- "complete" | "partial" | "blocked" | "error"
    content_length INTEGER,  -- Word count of analyzed content
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_url ON semantic_audit_results(url);
CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_run ON semantic_audit_results(run_id);
```

**Usage:**
- Semantic auditor writes after analyzing each page
- Scoring module reads tier counts for medical/systems weighting
- Reporting module reads for gap analysis and positioning recommendations

---

## Migration Strategy

### Yolo Mode Robustness

All new tables follow the **Yolo Mode** pattern already established in `database.py`:

```python
try:
    cursor.execute('CREATE TABLE IF NOT EXISTS table_name (...)')
except sqlite3.OperationalError:
    pass  # Table or column already exists
```

**Benefits:**
- Safe idempotent migrations
- No schema versioning overhead
- Forward-compatible with existing databases

### Existing Migration Code (database.py:128–139)

Current migrations handle backwards compatibility:

```python
try:
    cursor.execute("ALTER TABLE semantic_audits ADD COLUMN systemic_label TEXT DEFAULT 'Standard'")
except sqlite3.OperationalError:
    pass  # Already exists
```

### New Migrations (to be added to database.py)

Three new tables will be created via Yolo Mode in `_create_tables()`:

1. **eeat_scores** — 15 columns for EEAT signals
2. **cluster_results** — 10 columns for internal linking analysis
3. **semantic_audit_results** — 13 columns for detailed tier scoring

All are wrapped in `CREATE TABLE IF NOT EXISTS`, so they're safe to run multiple times.

---

## Data Flow & Lifecycle

### Audit Run Lifecycle

```
1. create_run() → runs.id created
   ↓
2. For each competitor domain:
   a. SemanticAuditor.scrape_content() + analyze_text()
      → Save to traffic_magnets
      → Save to semantic_audit_results (new)
   b. EEATScorer.score_page()
      → Save to eeat_scores (new)
   c. ClusterDetector.analyze_domain()
      → Save to cluster_results (new)
   d. DatabaseManager.tag_competitor_position()
      → Update competitors, competitor_history
   ↓
3. ReportGenerator.generate_summary()
   → Read all tables above
   → Emit strategic_briefing_run_N.md
```

### Data Retention

| Table | Retention | Archival |
|-------|-----------|----------|
| `runs` | 9+ years (audit history) | None; longitudinal data |
| `traffic_magnets` | 9+ years | Aggregated via competitor_history |
| `eeat_scores` | 3+ runs | Aggregated EEAT trends table (future) |
| `cluster_results` | 3+ runs | Cluster drift detection (future) |
| `competitor_history` | 9+ years | Primary longitudinal record |
| `semantic_audit_results` | 3+ runs | Trend analysis (future) |

---

## Index Strategy

All new tables include indices on:
- **Foreign keys** (run_id) — for filtering by audit run
- **Domain/URL** — for competitor lookups and reconciliation

Example:
```sql
CREATE INDEX IF NOT EXISTS idx_eeat_scores_url ON eeat_scores(url);
CREATE INDEX IF NOT EXISTS idx_eeat_scores_run ON eeat_scores(run_id);
```

---

## JSON Columns

Some columns store nested data as JSON strings (SQLite does not have native JSON types):

| Table | Column | Format | Example |
|-------|--------|--------|---------|
| `cluster_results` | `internal_link_graph` | JSON object | `{"url1": {"in_degree": 2}, "url2": {...}}` |
| `cluster_results` | `hub_candidates` | JSON array | `["url1", "url2", "url3"]` |
| `semantic_audit_results` | `tier_1_medical_terms_found` | JSON array | `["symptom", "treatment", "diagnosis"]` |
| `semantic_audit_results` | `tier_2_systems_terms_found` | JSON array | `["differentiation", "triangles"]` |
| `semantic_audit_results` | `tier_3_bowen_terms_found` | JSON array | `["emotional fusion", "pursuer-distancer"]` |

**Handling in Python:**
```python
import json

# Write
graph_json = json.dumps(internal_link_graph)
cursor.execute('INSERT INTO cluster_results (..., internal_link_graph) VALUES (..., ?)', (graph_json,))

# Read
row = cursor.fetchone()
graph = json.loads(row['internal_link_graph'])
```

---

## Schema Evolution Roadmap

### v3 (Current)
- ✅ eeat_scores
- ✅ cluster_results
- ✅ semantic_audit_results

### v4 (Future)
- `eeat_trends` — Aggregated EEAT changes across runs
- `cluster_drift` — Linking pattern changes over time
- `third_party_signals` — Ahrefs/Moz data cache
- `reframe_performance` — Which reframes convert

---

## Compliance & Privacy

### Data Stored
- **Competitor URLs** (public SERPs)
- **Public page metadata** (author, publish date, credentials)
- **Internal linking structure** (from public content)
- **Audit metadata** (when audited, scoring, run ID)

**Not Stored:**
- Client credentials or API keys
- Private internal linking (not in public pages)
- Personal data beyond public bylines

### Query Examples for Data Export/Deletion

```sql
-- Get all data for one run
SELECT * FROM eeat_scores WHERE run_id = 5;
SELECT * FROM cluster_results WHERE run_id = 5;

-- Get all data for one domain
SELECT * FROM eeat_scores WHERE url LIKE 'https://example.com%';

-- Delete old runs (retention policy)
DELETE FROM runs WHERE timestamp < date('now', '-10 years');
DELETE FROM eeat_scores WHERE run_id IN (SELECT id FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT 20));
```

---

## Status

| Item | Status |
|------|--------|
| Core schema | ✅ Existing (runs, competitors, traffic_magnets, etc.) |
| EEAT scores table | ✅ Designed, ready for migration |
| Cluster results table | ✅ Designed, ready for migration |
| Semantic audit results table | ✅ Designed, ready for migration |
| Index strategy | ✅ Planned |
| JSON handling | ✅ Documented |
| Migration code | 🚀 To be added to database.py |

---

**Generated by:** Implementation Plan Task 4.7  
**Date:** 2026-05-02  
**Document:** `/Users/davemini2/ProjectsLocal/serp-compete/docs/DATA_PERSISTENCE_MAP_v3.md`
