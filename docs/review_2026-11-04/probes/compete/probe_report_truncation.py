"""reporting.py LIMIT 30 on eeat_scores/geo_profiles and LIMIT 20 on traffic_magnets truncates BOTH the markdown and the Excel sheet with no 'N of M'; None EEAT scores render as 'nan'."""
import sys, os, tempfile, datetime
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.database import DatabaseManager
from src.reporting import ReportGenerator
import pandas as pd
tmp = tempfile.mkdtemp(); db = DatabaseManager(os.path.join(tmp, "t.db")); run = db.create_run("c")
with db._get_connection() as c:
    for i in range(45):   # 15 competitors x 3 pages
        dom = f"{chr(97 + i // 3)}comp.com"
        c.execute("INSERT INTO eeat_scores (run_id, url, scored_at, experience_score, expertise_score, authoritativeness_score, trustworthiness_score, score_confidence) VALUES (?,?,?,?,?,?,?,?)",
                  (run, f"https://{dom}/p{i%3}", "t", 0.5, None, 0.2, 0.9, "medium"))
        c.execute("INSERT INTO geo_profiles (run_id, url, profiled_at, extractability_tier, question_heading_count, present_signals, why_cited) VALUES (?,?,?,?,?,?,?)",
                  (run, f"https://{dom}/p{i%3}", "t", "Weak", 0, "[]", "why"))
        c.execute("INSERT INTO traffic_magnets (run_id, domain, url, primary_keyword, est_traffic, medical_score, systems_score, systemic_label) VALUES (?,?,?,?,?,?,?,?)",
                  (run, dom, f"https://{dom}/p{i%3}", f"kw{i}", 0, 12, 0, "Surface-Level"))
os.chdir(tmp)
out = ReportGenerator(os.path.join(tmp, "t.db")).generate_summary("c", run_id=run)
x = pd.ExcelFile(f"audit_results_run_{run}.xlsx")
for sh in ["EEAT Scores", "GEO Extractability", "Traffic Magnets"]:
    df = x.parse(sh); print(sh, "rows in Excel:", len(df), "| in DB: 45 | domains present:", sorted({u.split('/')[2] for u in df.iloc[:,0] if isinstance(u,str) and u.startswith('http')} if sh!='Traffic Magnets' else set(df['domain'])))
print("expertise_score rendering for NULL:", x.parse("EEAT Scores")["expertise_score"].iloc[0], "| markdown:", [l for l in out.splitlines() if "acomp.com/p0" in l][0][:120])
print("vacuums listed in MD:", sum(1 for l in out.splitlines() if l.startswith("- **") and "Medical Score" in l), "of 45 Surface-Level magnets; openings for reframes:", len(db.identify_strategic_openings(run)))
