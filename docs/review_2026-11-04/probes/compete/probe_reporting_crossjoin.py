"""Competitor Ranking Summary: competitor_metrics x traffic_magnets cross-product inflates total_keywords."""
import sys, os, tempfile
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.database import DatabaseManager
from src.reporting import ReportGenerator

tmp = tempfile.mkdtemp()
db = DatabaseManager(os.path.join(tmp, "t.db"))
run = db.create_run("client.ca")
# one domain, 10 ranked keyword rows (DFS limit 10) across 3 URLs, 3 traffic magnets (max_pages=3)
metrics = []
for i in range(10):
    url = f"https://comp.com/p{i % 3}"
    metrics.append({"domain": "comp.com", "url": url, "keyword": f"kw{i}", "position": i + 1, "traffic": 10})
db.save_competitor_metrics(metrics, run_id=run)
for j in range(3):
    db.save_traffic_magnet(run, "comp.com", f"https://comp.com/p{j}", f"kw{j}", 10, 5, 0.0, "Standard")
os.chdir(tmp)
rep = ReportGenerator(os.path.join(tmp, "t.db"))
out = rep.generate_summary("client.ca", expected_competitors=["comp.com"], run_id=run)
for line in out.splitlines():
    if line.startswith("| comp.com") or "total_keywords" in line:
        print(line)
import pandas as pd
print(pd.read_excel(os.path.join(tmp, f"audit_results_run_{run}.xlsx"), sheet_name="Competitor Summary").to_string())
print("TRUE distinct keywords:", 10)
