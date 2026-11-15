"""competitor_feasibility rows come from db.get_competitor_das() = ALL rows in `competitors`, not this run's domains."""
import sys, os, tempfile
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.database import DatabaseManager
from src.serp_overlap import analyze_serp_overlap
tmp = tempfile.mkdtemp(); db = DatabaseManager(os.path.join(tmp, "t.db"))
db.save_competitor_summary("old-run-only.com", 60)   # audited in run 1 only
db.save_competitor_summary("current.com", 30)        # audited this run
r2 = db.create_run("c")
db.save_competitor_metrics([{"domain": "current.com", "url": "https://current.com/a", "keyword": "kw", "position": 3, "traffic": 1}], run_id=r2)
out = analyze_serp_overlap(db.get_competitor_positions(r2), {"kw": 4}, {"current.com": {"kw"}}, {"kw"}, "c", 35, db.get_competitor_das(), {}, "2026-11-04")
db.save_competitor_feasibility(r2, 35, out["feasibility"])
print("feasibility rows persisted for run", r2, ":", db._get_connection().execute("select domain, competitor_da, feasible from competitor_feasibility where run_id=?", (r2,)).fetchall())
print("positioning inputs (run-scoped, for contrast):", db.get_positioning_inputs(r2))
