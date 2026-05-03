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
