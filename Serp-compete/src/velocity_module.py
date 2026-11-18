"""Longitudinal memory: per-run market snapshots and the ONE authority-drift detector.

Spec:  compete-spec.md "Spec 4" (market velocity).
Tests: Serp-compete/tests/test_velocity.py

C-C-05 / C-M-06, fixed 2026-11-15. Three things were wrong here, and each of them
produced the single most action-oriented sentence in the briefing ("Strike this page
now.") out of nothing:

  * **Not run-scoped.** `SELECT DISTINCT url, keyword, domain FROM market_history`
    with no run filter, comparing the last two rows ever recorded. A competitor
    skipped this run (omitted, PA-filtered, DataForSEO 429, dropped from the handoff)
    kept being re-alerted with its last recorded drop, in every later briefing,
    forever. Snapshots now carry `run_id` and an alert exists only for a URL present
    in the run being reported.
  * **No threshold.** `da_drift < 0` fired on a 1-point PA move, and `rank_drift <=
    -2` fired on a 2-place rank move over a ≤10-keyword sample. The threshold is now
    `risk_signals.pa_drop_min` (editorial, uncalibrated, 2026-11-15) and only the
    authority drop triggers; rank drift travels as evidence.
  * **Zero stood in for unknown.** A Moz outage made PA 0, so every page of every
    affected domain showed a -35 authority collapse, and the next working run showed
    +35. PA is now stored NULL when unknown and a comparison with a NULL on either
    side is skipped, not treated as a drop.

There was also a second, independent "Fragile Magnet" detector in
`database.get_feasibility_drift` (`drift < -2`), rendering under its own heading for
the same event. It is gone: this is the only one.
"""
import sqlite3
import datetime
import os
import json
from typing import List, Dict, Any, Optional, Tuple

from src import db_connect

# Editorial default, uncalibrated, 2026-11-15 (shared_config
# `risk_signals.pa_drop_min`): the smallest Moz Page-Authority drop between two
# consecutive runs that is reported as a Fragile Magnet. 1-2 points is Moz noise.
DEFAULT_PA_DROP_MIN = 3


class VelocityTracker:
    def __init__(self, shared_config_path: str):
        self.config = self._load_config(shared_config_path)
        # DB path is relative to the root if not absolute
        db_name = self.config.get("technical", {}).get("database_path", "living_systems_intel.db")
        # Ensure we are pointing to the root
        self.db_path = os.path.abspath(os.path.join(os.path.dirname(shared_config_path), db_name))
        # The same configured wait as `DatabaseManager`, read from the config
        # this instance already loaded (review chunk Y11).
        self.lock_timeout = db_connect.lock_timeout_from_config(self.config)
        self._initialize_db()

    def _load_config(self, path: str):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}

    def connection(self):
        """A managed connection: committed on a clean exit, always closed
        (review chunk Y10, the same change as `DatabaseManager`)."""
        return db_connect.connection(self.db_path, timeout=self.lock_timeout)

    @property
    def pa_drop_min(self) -> float:
        return float(self.config.get("risk_signals", {})
                     .get("pa_drop_min", DEFAULT_PA_DROP_MIN))

    def _initialize_db(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    run_id INTEGER,
                    domain TEXT,
                    url TEXT,
                    keyword TEXT,
                    rank INTEGER,
                    da INTEGER,
                    systems_score REAL,
                    medical_score REAL
                )
            ''')
            # ALTER beside CREATE (the convention TODO.md asks for, and the fifth
            # occurrence of this class in the repo): a DB written before run_id
            # existed is repaired here rather than breaking every query below.
            try:
                cursor.execute("ALTER TABLE market_history ADD COLUMN run_id INTEGER")
            except sqlite3.OperationalError:
                pass  # Already exists
            conn.commit()

    def save_market_snapshot(self, domain: str, url: str, keyword: str, rank: int,
                             da: int, systems_score: float, medical_score: float,
                             run_id: int = None):
        """One snapshot per (run, url, keyword).

        `rank` and `da` are nullable on purpose. A page whose scrape errored is
        recorded with `rank = NULL` rather than omitted, so the run's attempt is on
        record and a later reader can tell "we could not read it" from "it was not
        attempted" (C-C-06); `da = NULL` means Moz had no figure (C-C-03).
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO market_history (run_id, domain, url, keyword, rank, da, systems_score, medical_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (run_id, domain, url, keyword, rank, da, systems_score, medical_score))
            conn.commit()

    def calculate_velocity(self, url: str, keyword: str,
                           run_id: int = None) -> Dict[str, Any]:
        """Drift for one (url, keyword) between `run_id` and the previous run holding it.

        With `run_id` omitted the two most recent snapshots are compared (the historic
        behaviour, kept for ad-hoc inspection). Returns {} when there is nothing
        comparable; a drift whose two sides are not both measured is None, never 0 —
        "we don't know" and "it did not move" are different facts (P1).
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            if run_id is None:
                cursor.execute('''
                    SELECT rank, da, systems_score, medical_score, timestamp, run_id
                    FROM market_history
                    WHERE url = ? AND keyword = ?
                    ORDER BY id DESC LIMIT 2
                ''', (url, keyword))
                rows = cursor.fetchall()
                if len(rows) < 2:
                    return {}
                curr, prev = rows[0], rows[1]
            else:
                cursor.execute('''
                    SELECT rank, da, systems_score, medical_score, timestamp, run_id
                    FROM market_history
                    WHERE url = ? AND keyword = ? AND run_id = ?
                    ORDER BY id DESC LIMIT 1
                ''', (url, keyword, run_id))
                curr = cursor.fetchone()
                if not curr:
                    return {}
                cursor.execute('''
                    SELECT rank, da, systems_score, medical_score, timestamp, run_id
                    FROM market_history
                    WHERE url = ? AND keyword = ? AND run_id IS NOT NULL AND run_id < ?
                    ORDER BY run_id DESC, id DESC LIMIT 1
                ''', (url, keyword, run_id))
                prev = cursor.fetchone()
                if not prev:
                    return {}

        def drift(curr_value, prev_value, improving_down: bool = False):
            if curr_value is None or prev_value is None:
                return None
            return (prev_value - curr_value) if improving_down else (curr_value - prev_value)

        return {
            # Positive means rank improved (e.g. 5 -> 3)
            "rank_drift": drift(curr[0], prev[0], improving_down=True),
            "da_drift": drift(curr[1], prev[1]),
            "systems_drift": drift(curr[2], prev[2]),
            "medical_drift": drift(curr[3], prev[3]),
            "prev_run_id": prev[5],
            "run_id": curr[5],
        }

    def get_market_alerts(self, run_id: int = None) -> List[Dict[str, Any]]:
        """Fragile Magnets for ONE run: pages whose Page Authority fell measurably.

        A row is reported only when (a) the URL/keyword was snapshotted in `run_id`,
        (b) the same URL/keyword has a snapshot from an earlier run, (c) both have a
        measured PA, and (d) the drop is at least `risk_signals.pa_drop_min`. Rank
        drift is carried as evidence and never triggers on its own.

        `run_id` omitted → the latest run in the table, so a caller that does not know
        its run still gets a run-scoped answer rather than the whole history.
        """
        alerts: List[Dict[str, Any]] = []
        threshold = self.pa_drop_min
        with self.connection() as conn:
            cursor = conn.cursor()
            if run_id is None:
                row = cursor.execute(
                    'SELECT MAX(run_id) FROM market_history').fetchone()
                run_id = row[0] if row else None
                if run_id is None:
                    return []
            targets = cursor.execute(
                'SELECT DISTINCT url, keyword, domain FROM market_history '
                'WHERE run_id = ?', (run_id,)).fetchall()

        for url, keyword, domain in targets:
            v = self.calculate_velocity(url, keyword, run_id=run_id)
            if not v:
                continue
            da_drift = v["da_drift"]
            if da_drift is None or da_drift > -threshold:
                continue
            alerts.append({
                "type": "Fragile Magnet",
                "domain": domain,
                "url": url,
                "keyword": keyword,
                "rank_drift": v["rank_drift"],
                "da_drift": da_drift,
                "pa_drop_min": threshold,
                "prev_run_id": v["prev_run_id"],
                "run_id": v["run_id"],
                "advice": "Strike this page now.",
            })
        return alerts
