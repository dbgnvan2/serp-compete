"""Probe 2 — report-level SQL artifacts, vacuum selection, velocity / fragile-magnet / cliff routes.

Builds a throwaway SQLite DB with the real DatabaseManager + VelocityTracker schemas and seeds
the shapes main.py produces (10 competitor_metrics rows per domain, <=3 traffic_magnets rows).
"""
import os, sys, sqlite3, tempfile, json, shutil
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
import pandas as pd
from src.database import DatabaseManager
from src.velocity_module import VelocityTracker

tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "probe.db")
db = DatabaseManager(db_path)

# ---------- A. total_keywords is multiplied by the LEFT JOIN on traffic_magnets ----------
run = db.create_run("livingsystems.ca")
metrics = [{"domain": "bcacc.ca", "url": f"https://bcacc.ca/p{i%4}", "keyword": f"kw{i}", "position": i + 1, "traffic": 10.0}
           for i in range(10)]
db.save_competitor_metrics(metrics, run)
for i in range(3):   # 3 audited pages -> 3 traffic_magnets rows (max_audit_pages_per_domain)
    db.save_traffic_magnet(run, "bcacc.ca", f"https://bcacc.ca/p{i}", f"kw{i}", 10.0, 18, 0.0, "Surface-Level")
# a domain with 1 magnet row
db.save_competitor_metrics([{"domain": "one.ca", "url": "https://one.ca/", "keyword": f"k{i}", "position": 3, "traffic": 1.0} for i in range(10)], run)
db.save_traffic_magnet(run, "one.ca", "https://one.ca/", "k0", 1.0, 0, 0.0, "Standard")

with db._get_connection() as conn:
    df = pd.read_sql_query('''
        SELECT m.domain, COUNT(DISTINCT m.url) as top_pages,
               SUM(CASE WHEN m.keyword IS NOT NULL AND m.keyword != "" THEN 1 ELSE 0 END) as total_keywords,
               AVG(m.position) as avg_pos
        FROM competitor_metrics m
        LEFT JOIN competitor_metadata meta ON m.domain = meta.domain
        LEFT JOIN traffic_magnets tm ON m.run_id = tm.run_id AND m.domain = tm.domain
        WHERE m.run_id = ? GROUP BY m.domain''', conn, params=(run,))
    truth = pd.read_sql_query("SELECT domain, COUNT(DISTINCT keyword) AS real_keywords FROM competitor_metrics WHERE run_id=? GROUP BY domain", conn, params=(run,))
print("== A. Competitor Ranking Summary query (reporting.py:107-123) vs ground truth")
print(df.merge(truth, on="domain").to_string(index=False))
print("   -> total_keywords = (#keyword rows) x (#traffic_magnet rows for the domain). run_11 shows 30 for nearly every domain.")

# ---------- B. identify_strategic_openings: zero-medical, zero-systems page is an 'opening' ----------
db.save_traffic_magnet(run, "rcav.org", "https://rcav.org/", "archdiocese of vancouver", 1094.4, 0, 0.0, "Standard")
db.save_traffic_magnet(run, "bowen.ca", "https://bowen.ca/fusion", "emotional fusion", 900.0, 25, 0.0, "Surface-Level")
print("\n== B. identify_strategic_openings(run) — ordered by est_traffic, no medical floor, no keyword relevance check")
for o in db.identify_strategic_openings(run):
    print("  ", o)

# ---------- C. systemic_depth label mixes a raw count (max_med) with a weighted score (max_sys) ----------
print("\n== C. get_systemic_depth: 'Medical' iff max_med > max_sys (raw count vs weighted score)")
print("   page with medical=2, t2=3 (systems 1.5): 2 > 1.5 -> 'Medical' although 3 systems words vs 2 medical words")

# ---------- D. Fragile Magnet via competitor_history when Moz fails (pa=0) ----------
run2 = db.create_run("livingsystems.ca")
db.save_competitor_history(run, "https://bcacc.ca/", 1, 38.0, 500.0)      # run 1: PA 38
db.save_competitor_history(run2, "https://bcacc.ca/", 1, 0, 500.0)        # run 2: Moz call failed -> main.py passes pa=0
print("\n== D. get_feasibility_drift after a Moz failure (main.py:404 `or 0`, :453 `.get(url, 0)`)")
print("  ", db.get_feasibility_drift(run2), " -> report prints 'losing authority ... publish now'")

# ---------- E. VelocityTracker 'Fragile Magnet' fires on ANY 1-point PA drop ----------
cfg_dir = tmp
with open(os.path.join(cfg_dir, "shared_config.json"), "w") as f:
    json.dump({"technical": {"database_path": "probe.db"}}, f)
vt = VelocityTracker(os.path.join(cfg_dir, "shared_config.json"))
vt.save_market_snapshot("bcacc.ca", "https://bcacc.ca/", "bc association", 1, 38, 0.0, 18)
vt.save_market_snapshot("bcacc.ca", "https://bcacc.ca/", "bc association", 1, 37, 0.0, 18)
print("\n== E. VelocityTracker.get_market_alerts with PA 38 -> 37, rank unchanged")
print("  ", vt.get_market_alerts())
vt.save_market_snapshot("x.ca", "https://x.ca/", "kw", 3, 20, 0.0, 1)
vt.save_market_snapshot("x.ca", "https://x.ca/", "kw", 5, 20, 0.0, 1)
print("   rank 3 -> 5, DA flat:", [a for a in vt.get_market_alerts() if a['domain'] == 'x.ca'])
print("   (two independent 'Fragile Magnet' detectors: drift < -2 in competitor_history vs da_drift < 0 here)")

# ---------- F. Volatility alert threshold is hard-coded (>=3), not risk_signals.volatility_high_shift ----------
db.save_competitor_metrics([{"domain": "v.ca", "url": "https://v.ca/", "keyword": "kw", "position": 4, "traffic": 1}], run)
db.save_competitor_metrics([{"domain": "v.ca", "url": "https://v.ca/", "keyword": "kw", "position": 7, "traffic": 1}], run2)
print("\n== F. get_volatility_alerts(run2): single keyword moved 4 -> 7")
print("  ", db.get_volatility_alerts(run2))

# ---------- G. Visibility series groups by DATE -> several runs on one day stack ----------
with sqlite3.connect(db_path) as conn:
    conn.execute("DELETE FROM market_history")
    for day, n in (("2026-05-01", 3), ("2026-05-02", 12), ("2026-05-03", 3)):   # 4 runs on 05-02 (like runs 5-8)
        for i in range(n):
            conn.execute("INSERT INTO market_history (timestamp, domain, url, keyword, rank, da, systems_score, medical_score) VALUES (?,?,?,?,?,?,?,?)",
                         (day + " 12:00:00", "d.ca", f"https://d.ca/{i%3}", f"k{i%3}", 2, 30, 0, 1))
    conn.commit()
from src.risk_radar import detect_visibility_cliff
series = db.get_visibility_series("d.ca")
print("\n== G. get_visibility_series('d.ca') with 4 runs on one day:", series)
print("   detect_visibility_cliff ->", detect_visibility_cliff(series, {"cliff_drop_pct": 0.3, "cliff_lookback": 6}))
print("   3 audited pages, one 429-blocked next run -> series [3,2]:", detect_visibility_cliff([3, 2]), "| [3,1]:", detect_visibility_cliff([3, 1]))

shutil.rmtree(tmp)
