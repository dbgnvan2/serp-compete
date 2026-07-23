import sqlite3
import datetime
import json
import os
from typing import List, Tuple, Dict, Any

# Paths relative to serp-compete/src/
SHARED_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))

def load_db_path():
    if os.path.exists(SHARED_CONFIG_PATH):
        with open(SHARED_CONFIG_PATH, 'r') as f:
            config = json.load(f)
            db_name = config.get("technical", {}).get("database_path", "competitor_history.db")
            # Return absolute path relative to shared_config.json
            return os.path.abspath(os.path.join(os.path.dirname(SHARED_CONFIG_PATH), db_name))
    return "competitor_history.db"

class DatabaseManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or load_db_path()
        self._create_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _create_tables(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Runs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_domain TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Phase 3: Competitors Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitors (
                    domain TEXT PRIMARY KEY,
                    avg_da INTEGER,
                    last_crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Phase 3: Traffic Magnets Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS traffic_magnets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    domain TEXT,
                    url TEXT,
                    primary_keyword TEXT,
                    est_traffic REAL,
                    medical_score INTEGER,
                    systems_score INTEGER,
                    systemic_label TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # Phase 3: Market Gaps Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    keyword TEXT,
                    competitor_overlap_count INTEGER,
                    feasibility_status TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # Legacy tables maintained for compatibility during migration
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    keyword TEXT,
                    position INTEGER,
                    traffic REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS semantic_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    url TEXT NOT NULL,
                    medical_score INTEGER,
                    systems_score INTEGER,
                    systemic_label TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Revision 3: Competitor Metadata Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_metadata (
                    domain TEXT PRIMARY KEY,
                    market_position TEXT,
                    strategy TEXT,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Revision 4: Longitudinal History Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    url TEXT,
                    position INTEGER,
                    pa REAL,
                    traffic_value REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    drift REAL DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # v3: EEAT Scores Table (Gap 3 enhancement)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS eeat_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    scored_at TEXT NOT NULL,
                    has_author_byline BOOLEAN,
                    has_publish_date BOOLEAN,
                    has_update_date BOOLEAN,
                    has_likely_original_images BOOLEAN,
                    first_person_count_normalised REAL,
                    case_study_signal BOOLEAN,
                    experience_score REAL,
                    has_credentials_in_byline BOOLEAN,
                    schema_author_type_person BOOLEAN,
                    tier_3_or_tier_2_present BOOLEAN,
                    expertise_score REAL,
                    domain_authority_normalised REAL,
                    external_link_count_normalised REAL,
                    schema_organization_present BOOLEAN,
                    authoritativeness_score REAL,
                    is_https BOOLEAN,
                    has_contact_link BOOLEAN,
                    has_privacy_link BOOLEAN,
                    trustworthiness_score REAL,
                    score_confidence TEXT,
                    caveat TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_eeat_scores_url ON eeat_scores(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_eeat_scores_run ON eeat_scores(run_id)')

            # v3: Cluster Results Table (Gap 4 enhancement)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cluster_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    analysed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pages_analysed INTEGER,
                    internal_link_graph TEXT,
                    hub_candidates TEXT,
                    cluster_signal TEXT,
                    resolution_caveat TEXT,
                    avg_in_degree REAL,
                    max_in_degree INTEGER,
                    num_connected_components INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cluster_results_domain ON cluster_results(domain)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cluster_results_run ON cluster_results(run_id)')

            # v3: Semantic Audit Results Table (detailed tier scoring)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS semantic_audit_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    tier_1_medical_score INTEGER,
                    tier_1_medical_terms_found TEXT,
                    tier_2_systems_score INTEGER,
                    tier_2_systems_terms_found TEXT,
                    tier_3_bowen_score INTEGER,
                    tier_3_bowen_terms_found TEXT,
                    systemic_label TEXT,
                    medical_model_indicator BOOLEAN,
                    extraction_status TEXT,
                    content_length INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_url ON semantic_audit_results(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_run ON semantic_audit_results(run_id)')

            # --- MIGRATIONS: Add columns if they don't exist (Yolo Mode robustness) ---
            try:
                # Add systemic_label to semantic_audits
                cursor.execute("ALTER TABLE semantic_audits ADD COLUMN systemic_label TEXT DEFAULT 'Standard'")
            except sqlite3.OperationalError:
                pass # Already exists

            try:
                # Add systemic_label to traffic_magnets
                cursor.execute("ALTER TABLE traffic_magnets ADD COLUMN systemic_label TEXT DEFAULT 'Standard'")
            except sqlite3.OperationalError:
                pass # Already exists

            # SC-1: GEO / Extractability Profiles Table
            # (Spec: suite_enhancement_spec_v1.md#SC-1)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS geo_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    profiled_at TEXT NOT NULL,
                    extractability_tier TEXT,
                    has_faq_schema BOOLEAN,
                    has_article_schema BOOLEAN,
                    has_localbusiness_schema BOOLEAN,
                    has_person_schema BOOLEAN,
                    has_org_schema BOOLEAN,
                    has_author_byline BOOLEAN,
                    credential_count INTEGER,
                    question_heading_count INTEGER,
                    question_heading_ratio REAL,
                    has_publish_date BOOLEAN,
                    has_update_date BOOLEAN,
                    present_signals TEXT,
                    why_cited TEXT,
                    caveat TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_geo_profiles_url ON geo_profiles(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_geo_profiles_run ON geo_profiles(run_id)')

            # C4 / SC-6: SERP Overlap & Differentiation Gap matrix
            # (Spec: suite_enhancement_spec_v1.md#C4). Competitors keyed by domain.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS serp_overlap (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    snapshot_date TEXT,
                    competitors_ranking_json TEXT,
                    self_position INTEGER,
                    overlap_count INTEGER,
                    commodity_score REAL,
                    keyword_volume REAL,
                    cell TEXT,
                    all_competitor_gap BOOLEAN,
                    config_ref TEXT,
                    estimation_basis TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_serp_overlap_run ON serp_overlap(run_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_serp_overlap_cell ON serp_overlap(cell)')

            # C4 / SC-6: per-competitor feasibility (client DA vs each competitor DA),
            # the check_feasibility half of the AnalysisEngine wiring.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_feasibility (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    client_da INTEGER,
                    competitor_da INTEGER,
                    feasible BOOLEAN,
                    suggestion TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_competitor_feasibility_run ON competitor_feasibility(run_id)')

            # C2 / SC-4: Barbell Positioning (authority x focus 2x2). Domain-keyed.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positioning (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    is_client BOOLEAN,
                    computed_at TEXT,
                    authority_score REAL,
                    focus_score REAL,
                    quadrant TEXT,
                    rationale_json TEXT,
                    estimation_basis TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positioning_run ON positioning(run_id)')

            # C1 / SC-3: AI Answer Share-of-Voice (per engine, per entity). Consumed
            # from serp-discover's AI-visibility export; competitors keyed by domain.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sov_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    engine TEXT,
                    snapshot_date TEXT,
                    entity TEXT,
                    entity_type TEXT,
                    is_client BOOLEAN,
                    category TEXT,
                    mention_share REAL,
                    citation_share REAL,
                    presence_rate REAL,
                    avg_sentiment REAL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sov_daily_run ON sov_daily(run_id)')

            # C3 / SC-5: Branded-Demand Competitive Benchmark. Domain-keyed.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS brand_demand_bench (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT,
                    brand TEXT,
                    period TEXT,
                    branded_search_volume INTEGER,
                    branded_volume_share REAL,
                    branded_growth REAL,
                    est_branded_click_share REAL,
                    estimation_basis TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_brand_demand_run ON brand_demand_bench(run_id)')

            # C6 / SC-8: Reputation-Risk Radar. Domain-keyed; is_own_site separates
            # own-site warnings from competitor intel.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS risk_signal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT,
                    is_own_site BOOLEAN,
                    detected_at TEXT,
                    signal_type TEXT,
                    severity TEXT,
                    evidence_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_signal_run ON risk_signal(run_id)')

            conn.commit()

    def create_run(self, client_domain: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO runs (client_domain) VALUES (?)', (client_domain,))
            conn.commit()
            return cursor.lastrowid

    def save_competitor_summary(self, domain: str, avg_da: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO competitors (domain, avg_da, last_crawled_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET
                    avg_da = excluded.avg_da,
                    last_crawled_at = CURRENT_TIMESTAMP
            ''', (domain, avg_da))
            conn.commit()

    def save_traffic_magnet(self, run_id: int, domain: str, url: str, keyword: str, traffic: float, medical: int, systems: float, label: str = "Standard"):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO traffic_magnets (run_id, domain, url, primary_keyword, est_traffic, medical_score, systems_score, systemic_label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (run_id, domain, url, keyword, traffic, medical, systems, label))
            conn.commit()

    def save_geo_profile(self, run_id: int, profile: Any):
        """SC-1: persist a GeoProfile for a competitor URL.

        Accepts a src.geo_profiler.GeoProfile. present_signals is stored as a
        JSON string. (Spec: suite_enhancement_spec_v1.md#SC-1)
        """
        s = profile.signals
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO geo_profiles (
                    run_id, url, profiled_at, extractability_tier,
                    has_faq_schema, has_article_schema, has_localbusiness_schema,
                    has_person_schema, has_org_schema, has_author_byline,
                    credential_count, question_heading_count, question_heading_ratio,
                    has_publish_date, has_update_date, present_signals, why_cited, caveat)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run_id, profile.url, profile.profiled_at, profile.extractability_tier,
                s.get("has_faq_schema"), s.get("has_article_schema"),
                s.get("has_localbusiness_schema"), s.get("has_person_schema"),
                s.get("has_org_schema"), s.get("has_author_byline"),
                len(s.get("matched_credentials", [])), s.get("question_heading_count"),
                s.get("question_heading_ratio"), s.get("has_publish_date"),
                s.get("has_update_date"), json.dumps(profile.present_signals),
                profile.why_cited, profile.caveat,
            ))
            conn.commit()

    # Finding 1 (P8) — carry-forward allowlist. Never interpolate an arbitrary
    # table/column into SQL; only these structural-profile tables (keyed by the
    # named column) may be carried forward for a cache-served URL/domain.
    _CARRY_FORWARD_TABLES = {
        "geo_profiles": "url",
        "eeat_scores": "url",
        "cluster_results": "domain",
    }

    def carry_forward_profile(self, table: str, match_col: str, match_val: str,
                              run_id: int) -> bool:
        """Copy the latest prior structural profile for a cached URL/domain into run_id.

        Purpose: a re-run within the 7-day semantic-audit cache window must not blank
                 the EEAT/GEO/cluster report sections. On a cache hit no page is
                 re-scraped, so those engines cannot run; instead we re-associate the
                 most recent prior row (from another run) with the current run_id.
                 Honest — it reuses a real earlier scrape (original timestamps
                 preserved), exactly as was_audited_recently reuses prior scores; it
                 never fabricates a row.
        Spec:    suite_enhancement_spec_SERPCOMPETE_v1.md#SC-1 (Finding 1 fix)
        Tests:   tests/test_wiring.py::test_geo_carry_forward_populates_new_run_on_cache_hit

        Returns True if a prior row was carried forward, False if none existed
        (the caller counts the miss and surfaces it — see run_audit enrichment
        coverage summary).
        """
        if self._CARRY_FORWARD_TABLES.get(table) != match_col:
            raise ValueError(
                f"carry_forward_profile: {table}.{match_col} not in allowlist"
            )
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]  # row[1] = column name
            cursor.execute(
                f"SELECT * FROM {table} WHERE {match_col} = ? AND run_id != ? "
                f"ORDER BY id DESC LIMIT 1",
                (match_val, run_id),
            )
            row = cursor.fetchone()
            if not row:
                return False
            rowdict = dict(zip(cols, row))
            rowdict["run_id"] = run_id  # re-point the copy at the current run
            insert_cols = [c for c in cols if c != "id"]  # id is AUTOINCREMENT
            placeholders = ", ".join("?" for _ in insert_cols)
            cursor.execute(
                f"INSERT INTO {table} ({', '.join(insert_cols)}) "
                f"VALUES ({placeholders})",
                [rowdict[c] for c in insert_cols],
            )
            conn.commit()
            return True

    def save_competitor_metrics(self, metrics: List[Dict[str, Any]], run_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for metric in metrics:
                cursor.execute('''
                    INSERT INTO competitor_metrics (run_id, domain, url, keyword, position, traffic)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (run_id, metric['domain'], metric['url'], metric.get('keyword'),
                      metric.get('position'), metric.get('traffic')))
            conn.commit()

    def save_serp_overlap(self, run_id: int, rows: List[Dict[str, Any]]):
        """C4/SC-6: persist the classified who-ranks-where matrix rows.

        Spec:  suite_enhancement_spec_v1.md#C4
        Tests: tests/test_serp_overlap.py::test_sc6_save_and_read_roundtrip
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO serp_overlap (
                    run_id, keyword, snapshot_date, competitors_ranking_json,
                    self_position, overlap_count, commodity_score, keyword_volume,
                    cell, all_competitor_gap, config_ref, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r["keyword"], r.get("snapshot_date"),
                 json.dumps(r.get("competitors_ranking", {})),
                 r.get("self_position"), r.get("overlap_count"),
                 r.get("commodity_score"), r.get("keyword_volume"), r.get("cell"),
                 int(bool(r.get("all_competitor_gap"))), r.get("config_ref"),
                 r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def save_competitor_feasibility(self, run_id: int, client_da: int,
                                    feasibility: Dict[str, Dict[str, Any]]):
        """C4/SC-6: persist per-competitor feasibility (check_feasibility output), the
        second half of the AnalysisEngine wiring — surfaced, not discarded."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO competitor_feasibility
                    (run_id, domain, client_da, competitor_da, feasible, suggestion)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, domain, int(client_da or 0), v.get("competitor_da"),
                 int(bool(v.get("feasible"))), v.get("suggestion"))
                for domain, v in (feasibility or {}).items()
            ])
            conn.commit()

    def save_positioning(self, run_id: int, rows: List[Dict[str, Any]],
                         computed_at: str = None):
        """C2/SC-4: persist the barbell positioning rows (competitors + the client)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO positioning (run_id, domain, is_client, computed_at,
                    authority_score, focus_score, quadrant, rationale_json, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r["domain"], int(bool(r.get("is_client"))), computed_at,
                 r.get("authority_score"), r.get("focus_score"), r.get("quadrant"),
                 json.dumps(r.get("rationale", {})), r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def save_sov(self, run_id: int, rows: List[Dict[str, Any]]):
        """C1/SC-3: persist per-engine share-of-voice rows (from the AV export)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO sov_daily (run_id, engine, snapshot_date, entity, entity_type,
                    is_client, category, mention_share, citation_share, presence_rate, avg_sentiment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("engine"), r.get("snapshot_date"), r.get("entity"),
                 r.get("entity_type"), int(bool(r.get("is_client"))), r.get("category"),
                 r.get("mention_share"), r.get("citation_share"), r.get("presence_rate"),
                 r.get("avg_sentiment"))
                for r in rows
            ])
            conn.commit()

    def save_risk_signals(self, run_id: int, rows: List[Dict[str, Any]], detected_at: str = None):
        """C6/SC-8: persist reputation-risk signals (pattern detections)."""
        import json as _json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO risk_signal (run_id, domain, is_own_site, detected_at,
                    signal_type, severity, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("domain"), int(bool(r.get("is_own_site"))), detected_at,
                 r.get("signal_type"), r.get("severity"), _json.dumps(r.get("evidence", {})))
                for r in rows
            ])
            conn.commit()

    def get_visibility_series(self, domain: str) -> List[float]:
        """C6/SC-8: a per-domain visibility series (top-10 ranking count per snapshot
        date) from market_history, oldest→newest. [] when the table/data is absent."""
        try:
            with self._get_connection() as conn:
                rows = conn.execute('''
                    SELECT DATE(timestamp) AS d, SUM(CASE WHEN rank <= 10 THEN 1 ELSE 0 END)
                    FROM market_history WHERE domain = ?
                    GROUP BY d ORDER BY d
                ''', (domain,)).fetchall()
            return [float(v or 0) for _d, v in rows]
        except sqlite3.OperationalError:
            return []

    def get_parasite_candidates(self, run_id: int) -> List[Dict[str, Any]]:
        """C6/SC-8: per (domain, subfolder) keyword sets + the domain's core terms (from
        its OTHER subfolders) so a genuinely off-topic subfolder reads as a mismatch."""
        from urllib.parse import urlparse
        by_domain: Dict[str, Dict[str, set]] = {}
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT domain, url, keyword FROM competitor_metrics "
                "WHERE run_id = ? AND keyword IS NOT NULL AND url IS NOT NULL", (run_id,)
            ).fetchall()
        for domain, url, keyword in rows:
            path = urlparse(str(url)).path.strip("/")
            subfolder = "/" + path.split("/")[0] if path else "/"
            by_domain.setdefault(domain, {}).setdefault(subfolder, set()).add(keyword)
        candidates: List[Dict[str, Any]] = []
        for domain, subs in by_domain.items():
            for sub, kws in subs.items():
                if sub == "/":
                    continue  # the root is not a "parasite subfolder"
                core = set()
                for other_sub, other_kws in subs.items():
                    if other_sub != sub:
                        core |= other_kws
                if not core:
                    continue  # single-subfolder domain → can't judge mismatch
                candidates.append({"domain": domain, "subfolder": sub,
                                   "keywords": list(kws), "core_terms": list(core)})
        return candidates

    def save_brand_demand(self, run_id: int, rows: List[Dict[str, Any]]):
        """C3/SC-5: persist the branded-demand benchmark rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO brand_demand_bench (run_id, domain, brand, period,
                    branded_search_volume, branded_volume_share, branded_growth,
                    est_branded_click_share, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("domain"), r.get("brand"), r.get("period"),
                 r.get("branded_search_volume"), r.get("branded_volume_share"),
                 r.get("branded_growth"), r.get("est_branded_click_share"),
                 r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def get_positioning_inputs(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        """C2/SC-4: per-competitor {moz_da, top10_count, medical_total, systems_total}.

        Focus/tier signal from traffic_magnets; top-10 count from competitor_metrics;
        Moz DA from the competitors table (populated per run by save_competitor_summary,
        so competitors use the SAME authority formula as the client). Only domains
        audited this run are included.
        """
        inputs: Dict[str, Dict[str, Any]] = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # tier totals (the focus axis)
            cursor.execute('''SELECT domain, SUM(medical_score), SUM(systems_score)
                              FROM traffic_magnets WHERE run_id = ? GROUP BY domain''',
                           (run_id,))
            for domain, medical, systems in cursor.fetchall():
                d = inputs.setdefault(domain, {})
                d["medical_total"] = float(medical or 0)
                d["systems_total"] = float(systems or 0)
            # top-10 ranking count (an authority component)
            cursor.execute('''SELECT domain, COUNT(*) FROM (
                                SELECT domain, keyword, MIN(position) AS mp
                                FROM competitor_metrics
                                WHERE run_id = ? AND keyword IS NOT NULL AND position IS NOT NULL
                                GROUP BY domain, keyword)
                              WHERE mp <= 10 GROUP BY domain''', (run_id,))
            for domain, count in cursor.fetchall():
                inputs.setdefault(domain, {})["top10_count"] = int(count)
            # Moz DA per domain (the authority axis, shared with the client). Only
            # attach it to domains actually audited this run.
            cursor.execute('SELECT domain, avg_da FROM competitors WHERE avg_da IS NOT NULL')
            for domain, avg_da in cursor.fetchall():
                if domain in inputs:
                    inputs[domain]["moz_da"] = int(avg_da)
        return inputs

    def get_competitor_positions(self, run_id: int) -> Dict[str, Dict[str, int]]:
        """C4/SC-6: {keyword: {domain: best (lowest) position}} from competitor_metrics."""
        positions: Dict[str, Dict[str, int]] = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword, domain, MIN(position) FROM competitor_metrics
                WHERE run_id = ? AND keyword IS NOT NULL AND position IS NOT NULL
                GROUP BY keyword, domain
            ''', (run_id,))
            for keyword, domain, position in cursor.fetchall():
                positions.setdefault(keyword, {})[domain] = int(position)
        return positions

    def get_keyword_volumes(self, run_id: int) -> Dict[str, float]:
        """C4/SC-6: {keyword: max est-traffic} — per-keyword volume for cell rollups."""
        volumes: Dict[str, float] = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword, MAX(traffic) FROM competitor_metrics
                WHERE run_id = ? AND keyword IS NOT NULL
                GROUP BY keyword
            ''', (run_id,))
            for keyword, traffic in cursor.fetchall():
                volumes[keyword] = float(traffic or 0.0)
        return volumes

    def get_competitor_das(self) -> Dict[str, int]:
        """C4/SC-6: {domain: avg_da} from the competitors table (feasibility input).

        Returns {} when no DA data is stored — feasibility then degrades gracefully.
        """
        das: Dict[str, int] = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT domain, avg_da FROM competitors WHERE avg_da IS NOT NULL')
            for domain, avg_da in cursor.fetchall():
                das[domain] = int(avg_da)
        return das

    def save_semantic_audit(self, url: str, medical_score: int, systems_score: float, run_id: int, label: str = "Standard"):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO semantic_audits (run_id, url, medical_score, systems_score, systemic_label)
                VALUES (?, ?, ?, ?, ?)
            ''', (run_id, url, medical_score, systems_score, label))
            conn.commit()

    def save_competitor_history(self, run_id: int, url: str, position: int, pa: float, traffic: float):
        """
        Revision 4: Store snapshot data and calculate drift.
        Drift = Current_PA - Previous_PA.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Find previous PA for this URL
            cursor.execute('''
                SELECT pa FROM competitor_history 
                WHERE url = ? AND run_id < ? 
                ORDER BY run_id DESC LIMIT 1
            ''', (url, run_id))
            prev_row = cursor.fetchone()
            prev_pa = prev_row[0] if prev_row else pa
            drift = pa - prev_pa
            
            cursor.execute('''
                INSERT INTO competitor_history (run_id, url, position, pa, traffic_value, drift)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (run_id, url, position, pa, traffic, drift))
            conn.commit()

    def get_feasibility_drift(self, run_id: int) -> List[Dict[str, Any]]:
        """
        Revision 4: Identify 'Fragile Magnets'.
        Expert Alert: If Drift < -2 and Traffic_Value is stable, flag as a 'Fragile Magnet.'
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT url, pa, drift, traffic_value 
                FROM competitor_history 
                WHERE run_id = ? AND drift < -2
            ''', (run_id,))
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append({
                    "url": row[0],
                    "pa": row[1],
                    "drift": row[2],
                    "traffic": row[3],
                    "alert": "Fragile Magnet"
                })
            return alerts

    def tag_competitor_position(self, domain: str, medical_score: int, systems_t2: int, systems_t3: int, traffic: float):
        """
        Revision 3: Categorize competitor for 'Battle Strategy'.
        Volume Scaler: High Traffic + High Medical Score.
        Generalist: High Tier 2 Score.
        Direct Systemic: Presence of Tier 3 terms.
        """
        market_position = "Unknown"
        strategy = "General observation"
        
        if traffic > 1000 and medical_score > 15:
            market_position = "Volume Scaler"
            strategy = "Do not compete on volume; compete on clinical authority."
        elif systems_t3 > 0:
            market_position = "Direct Systemic"
            strategy = "Use 'Functional Facts' to provide a more rigorous Bowen alternative."
        elif systems_t2 > 10:
            market_position = "Generalist"
            strategy = "Target their lack of Tier 3 depth."

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO competitor_metadata (domain, market_position, strategy, last_updated)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET
                    market_position = excluded.market_position,
                    strategy = excluded.strategy,
                    last_updated = CURRENT_TIMESTAMP
            ''', (domain, market_position, strategy))
            conn.commit()

    def get_competitor_metadata(self, domain: str) -> Dict[str, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT market_position, strategy FROM competitor_metadata WHERE domain = ?', (domain,))
            row = cursor.fetchone()
            if row:
                return {"market_position": row[0], "strategy": row[1]}
            return {"market_position": "N/A", "strategy": "N/A"}

    def get_latest_run_id(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MAX(id) FROM runs')
            result = cursor.fetchone()
            return result[0] if result[0] else None

    def get_volatility_alerts(self, run_id: int) -> List[Dict[str, Any]]:
        """
        Logic: Flag if a competitor's average position moves by > 3 places compared to previous run.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Get previous run_id
            cursor.execute('SELECT id FROM runs WHERE id < ? ORDER BY id DESC LIMIT 1', (run_id,))
            prev_run = cursor.fetchone()
            if not prev_run:
                return []
            prev_run_id = prev_run[0]

            cursor.execute('''
                SELECT curr.domain, AVG(curr.position) as curr_avg, AVG(prev.position) as prev_avg
                FROM competitor_metrics curr
                JOIN competitor_metrics prev ON curr.domain = prev.domain AND curr.keyword = prev.keyword
                WHERE curr.run_id = ? AND prev.run_id = ?
                GROUP BY curr.domain
                HAVING ABS(AVG(curr.position) - AVG(prev.position)) >= 3
            ''', (run_id, prev_run_id))
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append({
                    "domain": row[0],
                    "shift": round(row[1] - row[2], 2),
                    "type": "Volatility Alert"
                })
            return alerts

    def identify_strategic_openings(self, run_id: int) -> List[Dict[str, Any]]:
        """
        Logic: High traffic meet total 'Systemic Vacuum' (systems_score = 0) or 'Surface-Level' label.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT url, primary_keyword, est_traffic, medical_score, systemic_label
                FROM traffic_magnets
                WHERE run_id = ? AND (systems_score = 0 OR systemic_label = 'Surface-Level')
                ORDER BY est_traffic DESC LIMIT 5
            ''', (run_id,))
            
            openings = []
            for row in cursor.fetchall():
                openings.append({
                    "url": row[0],
                    "keyword": row[1],
                    "traffic": row[2],
                    "medical_score": row[3],
                    "systemic_label": row[4]
                })
            return openings

    def update_traffic_magnet_scores(self, run_id: int, url: str, medical: int, systems: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE traffic_magnets
                SET medical_score = ?, systems_score = ?
                WHERE run_id = ? AND url = ?
            ''', (medical, systems, run_id, url))
            
            # Also update legacy semantic_audits table if applicable
            cursor.execute('''
                UPDATE semantic_audits
                SET medical_score = ?, systems_score = ?
                WHERE run_id = ? AND url = ?
            ''', (medical, systems, run_id, url))
            
            conn.commit()

    def get_run_urls(self, run_id: int) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT url FROM traffic_magnets WHERE run_id = ?', (run_id,))
            return [row[0] for row in cursor.fetchall()]

    def was_audited_recently(self, url: str, days: int = 7) -> Dict[str, Any]:
        """
        Optimization: Check if this URL has been audited in the last X days to avoid re-scraping.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT medical_score, systems_score, systemic_label 
                FROM semantic_audits 
                WHERE url = ? AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC LIMIT 1
            ''', (url, f'-{days} days'))
            row = cursor.fetchone()
            if row:
                return {
                    "medical_score": row[0],
                    "systems_score": row[1],
                    "systemic_label": row[2]
                }
            return None
