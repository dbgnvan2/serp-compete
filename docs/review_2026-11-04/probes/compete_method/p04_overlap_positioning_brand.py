"""Probe 4 — SERP overlap cells, barbell positioning, brand derivation, SoV matching, YouTube scoring."""
import sys, json, re
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
cfg = json.load(open("/Users/davemini2/ProjectsLocal/serp-compete/shared_config.json"))

from src.serp_overlap import analyze_serp_overlap, classify_cell
print("== A. SERP overlap cells")
comp = {"jericho counselling": {"jerichocounselling.com": 1},
        "counselling north vancouver": {"a.ca": 3, "b.ca": 5, "c.ca": 9},
        "couples therapy vancouver": {"a.ca": 4, "b.ca": 11}}
res = analyze_serp_overlap(comp, {"counselling north vancouver": 2.0, "couples therapy vancouver": 11.4,
                                  "bowen family systems north vancouver": 1.0},
                           {"a.ca": set(comp), "b.ca": set(comp)}, {"counselling north vancouver"},
                           "livingsystems.ca", 35, {"a.ca": 30, "b.ca": 45}, cfg["serp_overlap"], "2026-11-04")
for r in res["rows"]:
    print(f"   {r['keyword']:40s} cell={r['cell']:22s} self_pos={r['self_position']} rivals={r['overlap_count']} commodity={r['commodity_score']}")
print("   -> a competitor's own brand name ('jericho counselling') lands in the exclusive-competitor action queue")
print("   -> client at GSC avg position 11.4 (90-day, global) vs rival snapshot rank 4 (Canada) = 'rivals rank, you're absent'")
print("   -> 'commoditized' = >= 3 of the tracked rivals' 10 sampled keywords coincide (commodity_high_overlap=3)")
res2 = analyze_serp_overlap(comp, {}, {}, set(), "livingsystems.ca", 35, {}, cfg["serp_overlap"], "2026-11-04")
print("   GSC map empty -> cells:", sorted({r['cell'] for r in res2['rows']}), "(withheld: good)")
print("   feasibility: client DA 35 vs competitor avg PA 45 ->", res["feasibility"]["b.ca"])

print("\n== B. Barbell positioning")
from src.positioning import compute_positioning, classify_query_tiers, compute_focus, compute_authority
pcfg = cfg["positioning"]
rows = compute_positioning(
    {"tiny.ca": {"moz_da": 20, "top10_count": 2, "medical_total": 3, "systems_total": 0.0},
     "mixed.ca": {"moz_da": 20, "top10_count": 2, "medical_total": 3, "systems_total": 1.5}},
    "livingsystems.ca",
    {"moz_da": 35, "top10_count": 240, "medical_total": 80, "systems_total": 60}, pcfg)
for r in rows:
    print(f"   {r['domain']:18s} authority={r['authority_score']} focus={r['focus_score']} quadrant={r['quadrant']}")
print("   -> 3 mentions of 'therapy' on <=3 pages and nothing else = focus 100 = 'niche_owner'; one 'relationship' word -> focus", compute_focus(3, 0.5))
print("   -> client top10_count comes from ALL GSC queries (saturates at 10); competitor from 10 sampled keywords")
print("   -> competitor 'moz_da' is avg Moz *Page* Authority of 10 URLs (main.py:418); client's is config Domain Authority 35")
print("   client focus from GSC query text via classify_query_tiers (substring match):",
      classify_query_tiers(["couples therapy north vancouver", "relationship counselling", "air conditioning", "food processing jobs"], cfg["clinical"]),
      "(medical, systems)")

print("\n== C. derive_brand_name on the run_11 competitor set -> the string whose Google Ads search volume becomes 'branded demand'")
from src.brand_utils import derive_brand_name
run11 = ["jerichocounselling.com", "lavendercounselling.com", "hollyburn.ca", "clearcounselling.ca", "bachcounselling.com",
         "goodlifetherapy.ca", "lonsdalepsychology.ca", "wongcounselling.com", "coastcounselling.ca", "urbanbalance.ca",
         "nightingalecounselling.com", "wellspringcounselling.ca", "boomerangcc.ca", "mapquest.com", "m.yelp.com", "livingsystems.ca"]
for d in run11:
    b = derive_brand_name(d, cfg["brand"]["name_suffixes"])
    pruned = b in cfg["branded_demand"]["generic_brand_prune"]
    print(f"   {d:28s} -> '{b}'{'  [pruned]' if pruned else ''}")
print("   queries sent for volume:", ["lavender"] + [f"lavender {m}" for m in cfg["branded_demand"]["branded_modifiers"]])

print("\n== D. SoV: competitor mentioned by display name but never cited -> 'other'")
from src.sov_analyzer import compute_sov
export = {"data_available": True, "engines": ["claude"],
          "brand_mentions": [{"engine": "claude", "brand": "Living Systems", "mention_count": 2, "questions_total": 5, "is_client": True, "source": "g"},
                             {"engine": "claude", "brand": "Jericho Counselling", "mention_count": 6, "questions_total": 5, "is_client": False, "source": "g"}],
          "ai_citations": [], "answer_sentiment": []}
sov = compute_sov(export, ["jerichocounselling.com"], "2026-11-04", competitor_brands=["jericho"])
for r in sov["rows"]:
    print("   ", {k: r[k] for k in ("entity", "category", "mention_share", "presence_rate")})
print("   report prints only category != 'other' -> 'Mention share: Living Systems (you) 25%' with no visible 75%")

print("\n== E. YouTube _score: a handle equal to the derived brand token is 'confirmed' / 'high'")
from src.youtube_presence import _score
print("   bachcounselling.com vs channel @bach   ->", _score({"description": "Music of J.S. Bach", "custom_url": "@bach", "title": "Bach"}, "bachcounselling.com", "bachcounselling", "bach"))
print("   clearcounselling.ca vs 'Clear Vision Films' ->", _score({"description": "", "custom_url": "@clearvisionfilms", "title": "Clear Vision Films"}, "clearcounselling.ca", "clearcounselling", "clear"))
print("   channel titled 'Dr Jane Smith' for janesmithcounselling.ca ->", _score({"description": "Therapist in North Van", "custom_url": "@drjanesmith", "title": "Dr Jane Smith"}, "janesmithcounselling.ca", "janesmithcounselling", "janesmith"), "-> none_found = 'no channel' in report")
