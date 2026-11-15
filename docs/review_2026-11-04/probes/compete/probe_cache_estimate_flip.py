"""main.py:508-509 cached-audit t2/t3 'rough estimate' flips tag_competitor_position between run 1 (fresh) and run 2 (cached)."""
import sys, os, tempfile
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.scoring_logic import calculate_weighted_score
from src.database import DatabaseManager

def cache_estimate(systems_score):
    # verbatim from main.py lines 508-509 (cached branch)
    t2 = systems_score / 0.5 if systems_score < 2.0 else 0
    t3 = systems_score / 2.0 if systems_score >= 2.0 else 0
    return t2, t3

tmp = tempfile.mkdtemp(); db = DatabaseManager(os.path.join(tmp, "t.db"))
cases = [(5, 4, 0), (5, 12, 0), (5, 1, 1), (5, 3, 0)]
for med, t2, t3 in cases:
    score, label = calculate_weighted_score(med, t2, t3)
    et2, et3 = cache_estimate(score)
    db.tag_competitor_position("fresh.com", med, t2, t3, 0);  fresh = db.get_competitor_metadata("fresh.com")["market_position"]
    db.tag_competitor_position("cached.com", med, et2, et3, 0); cached = db.get_competitor_metadata("cached.com")["market_position"]
    print(f"t2={t2:>2} t3={t3} score={score:>4} | run1 fresh: t2={t2},t3={t3} -> {fresh:<16} | run2 cached est: t2={et2},t3={et3} -> {cached}")
