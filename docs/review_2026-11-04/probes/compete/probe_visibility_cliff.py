"""get_visibility_series counts top-10 rows among <=max_pages(3) market_history rows per run; one failed scrape or one lost keyword = 'visibility cliff'."""
import sys, os, tempfile, json, sqlite3
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.database import DatabaseManager
from src.risk_radar import detect_visibility_cliff
cfg = {"cliff_drop_pct": 0.3, "cliff_lookback": 6}
print("series 3,3,2 (one of 3 audited URLs slipped to rank 11 or its scrape errored):", detect_visibility_cliff([3,3,2], cfg))
print("series 2,2,1:", detect_visibility_cliff([2,2,1], cfg))
# same-day double count
tmp = tempfile.mkdtemp(); db = DatabaseManager(os.path.join(tmp, "t.db"))
with db._get_connection() as c:
    c.execute("CREATE TABLE market_history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, domain TEXT, url TEXT, keyword TEXT, rank INTEGER, da INTEGER, systems_score REAL, medical_score REAL)")
    for ts, n in [("2026-11-01 09:00:00", 3), ("2026-11-01 15:00:00", 3), ("2026-11-02 09:00:00", 3)]:
        for i in range(n):
            c.execute("INSERT INTO market_history (timestamp, domain, url, keyword, rank, da) VALUES (?,?,?,?,?,?)", (ts, "comp.com", f"u{i}", f"k{i}", 3, 30))
s = db.get_visibility_series("comp.com")
print("two identical runs on day 1 + one on day 2 -> series", s, "->", detect_visibility_cliff(s, cfg))
