import sqlite3
import datetime
import os
import json
from typing import List, Dict, Any, Tuple

class VelocityTracker:
    def __init__(self, shared_config_path: str):
        self.config = self._load_config(shared_config_path)
        # DB path is relative to the root if not absolute
        db_name = self.config.get("technical", {}).get("database_path", "living_systems_intel.db")
        # Ensure we are pointing to the root
        self.db_path = os.path.abspath(os.path.join(os.path.dirname(shared_config_path), db_name))
        self._initialize_db()

    def _load_config(self, path: str):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    domain TEXT,
                    url TEXT,
                    keyword TEXT,
                    rank INTEGER,
                    da INTEGER,
                    systems_score REAL,
                    medical_score REAL
                )
            ''')
            conn.commit()

    def save_market_snapshot(self, domain: str, url: str, keyword: str, rank: int, da: int, systems_score: float, medical_score: float):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO market_history (domain, url, keyword, rank, da, systems_score, medical_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (domain, url, keyword, rank, da, systems_score, medical_score))
            conn.commit()

    def calculate_velocity(self, url: str, keyword: str) -> Dict[str, Any]:
        """
        Spec 4: Compare Current entry to the most recent previous entry.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Get last two entries for this URL/Keyword, ordering by ID to handle identical timestamps
            cursor.execute('''
                SELECT rank, da, systems_score, medical_score, timestamp
                FROM market_history
                WHERE url = ? AND keyword = ?
                ORDER BY id DESC LIMIT 2
            ''', (url, keyword))
            rows = cursor.fetchall()
            
            if len(rows) < 2:
                return {} # Not enough data for drift

            curr = rows[0]
            prev = rows[1]

            return {
                "rank_drift": prev[0] - curr[0], # Positive means rank improved (e.g. 5 -> 3)
                "da_drift": curr[1] - prev[1],
                "systems_drift": curr[2] - prev[2],
                "medical_drift": curr[3] - prev[3]
            }

    def get_market_alerts(self) -> List[Dict[str, Any]]:
        """
        Spec 4: Expert Alerts
        """
        alerts = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Fragile Magnet: Dropping Rank/DA
            # We look at all unique URL/Keywords and check their drift
            cursor.execute('SELECT DISTINCT url, keyword, domain FROM market_history')
            targets = cursor.fetchall()
            
            for url, keyword, domain in targets:
                v = self.calculate_velocity(url, keyword)
                if not v: continue
                
                if v["rank_drift"] < 0 or v["da_drift"] < 0:
                    # Heuristic for Fragile: If dropping significantly
                    if v["rank_drift"] <= -2 or v["da_drift"] < 0:
                        alerts.append({
                            "type": "Fragile Magnet",
                            "domain": domain,
                            "url": url,
                            "keyword": keyword,
                            "rank_drift": v["rank_drift"],
                            "da_drift": v["da_drift"],
                            "advice": "Strike this page now."
                        })

            # 2. Rising Competitor: Appearing in top 10 twice in a row (simplified)
            # This would require more complex grouping, for now focusing on Fragile Magnet
            
        return alerts
