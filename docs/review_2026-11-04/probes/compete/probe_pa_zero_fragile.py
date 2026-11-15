"""Transient Moz failure (pa=0 default in main.py:404/453) -> Fragile Magnet alerts; velocity alerts are all-time."""
import sys, os, tempfile, json
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.database import DatabaseManager
from src.velocity_module import VelocityTracker

tmp = tempfile.mkdtemp()
cfg = os.path.join(tmp, "shared_config.json")
json.dump({"technical": {"database_path": "t.db"}}, open(cfg, "w"))
db = DatabaseManager(os.path.join(tmp, "t.db"))
vel = VelocityTracker(cfg)
url = "https://comp.com/page"

# Run 1: Moz OK, PA 35
r1 = db.create_run("c"); db.save_competitor_history(r1, url, 5, 35, 100)
vel.save_market_snapshot("comp.com", url, "kw", 5, 35, 1.0, 5)
# Run 2: Moz raised (main.py except -> moz_metrics_map={} -> pa = .get(url, 0) = 0), page identical
r2 = db.create_run("c"); db.save_competitor_history(r2, url, 5, 0, 100)
vel.save_market_snapshot("comp.com", url, "kw", 5, 0, 1.0, 5)
print("run2 get_feasibility_drift:", db.get_feasibility_drift(r2))
print("run2 velocity alerts:", vel.get_market_alerts())

# Run 3: the URL is NOT in this run at all (domain skipped by DFS 429 / PA filter / omitted)
r3 = db.create_run("c")
print("run3 get_feasibility_drift (run-scoped):", db.get_feasibility_drift(r3))
print("run3 velocity alerts (NOT run-scoped, stale):", vel.get_market_alerts())
