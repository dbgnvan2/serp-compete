"""Probe 1 — semantic scoring edges (scoring_logic.py + semantic.py).

Run: PYTHONPATH=/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete python3 -I p01_semantic_scoring.py
"""
import sys
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.scoring_logic import calculate_weighted_score, TIER_1_MEDICAL, TIER_2_SYSTEMS, TIER_3_BOWEN_EXPERT
from src.semantic import SemanticAuditor

print("== A. Surface-Level threshold edge (tier_1_max=10, tier3=0, t2=4)")
for med in (9, 10, 11):
    print(f"  medical={med:2d} t2=4 t3=0 ->", calculate_weighted_score(med, 4, 0))
print("  medical=100 t2=4 t3=1 ->", calculate_weighted_score(100, 4, 1), "  (one Tier-3 hit cancels the penalty)")
print("  medical=0 t2=0 t3=0  ->", calculate_weighted_score(0, 0, 0), "  (empty page = 'Standard', systems 0 -> vacuum)")

aud = SemanticAuditor()

print("\n== B. Hyphenated single-token dictionary entries are unreachable by token match")
for term in sorted(TIER_2_SYSTEMS | TIER_3_BOWEN_EXPERT):
    if "-" in term and " " not in term:
        r = aud.analyze_text(f"We teach {term} every day. {term} matters. {term}.")
        print(f"  '{term}' x3 -> t2={r['t2_count']} t3={r['t3_count']}")

print("\n== C. Double counting: 'differentiation of self' (T3 phrase) also fires 'differentiation' (T2 token)")
r = aud.analyze_text("differentiation of self")
print("  text='differentiation of self' ->", r)
r = aud.analyze_text("emotional process")
print("  text='emotional process' ->", r, " ('process' token + 'emotional process' phrase)")

print("\n== D. Generic words: a Bowen practice's own copy scores 'medical'")
client_like = ("Living Systems Counselling offers family therapy and couples therapy in North Vancouver. "
               "Our therapy approach is Bowen theory. Book a therapy session. Therapy fees. Therapy FAQ.")
print("  client-like copy ->", aud.analyze_text(client_like))
print("  'therapy' in TIER_1_MEDICAL:", "therapy" in TIER_1_MEDICAL, "| 'therapy' is also in shared_config.stop_words")

print("\n== E. Generic Tier-2 words")
generic = ("Our booking process is simple. The intake process takes ten minutes. "
           "We value the relationship with our clients. Attachment: see the PDF attachment. "
           "The internal family systems model is not Bowen theory.")
print("  non-systemic copy ->", aud.analyze_text(generic))

print("\n== F. No length normalisation")
short = "symptom treatment disorder diagnosis clinical"
long_ = short + " " + " ".join(["the family and the relationships we have"] * 100)
print("  5 medical words in 5-word text  ->", aud.analyze_text(short)["medical_score"])
print("  5 medical words in 805-word text ->", aud.analyze_text(long_)["medical_score"], " (same score, 160x the dilution)")

print("\n== G. Plural/singular: 'triangles' is T2, 'triangle' is not; 'treatments' not T1")
print("  'triangle' x3 ->", aud.analyze_text("triangle triangle triangle")["t2_count"],
      "| 'triangles' x3 ->", aud.analyze_text("triangles triangles triangles")["t2_count"])
print("  'treatments' x3 ->", aud.analyze_text("treatments treatments treatments")["medical_score"],
      "| 'treatment' x3 ->", aud.analyze_text("treatment treatment treatment")["medical_score"])

print("\n== H. Navigation menus in <header>/<div> survive decompose() and feed the 500-word window")
import requests
html = """<html><head><title>Clinic</title></head><body>
<header><div class="menu">
<a href="/anxiety-treatment">Anxiety Treatment</a> <a href="/depression-treatment">Depression Treatment</a>
<a href="/trauma-therapy">Trauma Therapy</a> <a href="/adhd-diagnosis">ADHD Diagnosis</a>
<a href="/ocd-treatment">OCD Treatment</a> <a href="/ptsd-treatment">PTSD Treatment</a>
<a href="/eating-disorder-treatment">Eating Disorder Treatment</a> <a href="/contact">Contact</a>
</div></header>
<main><h1>About us</h1><p>We work with families on patterns of distance and pursuit across generations.</p></main>
<nav><a href="/symptoms">Symptoms</a></nav>
</body></html>"""
class FakeResp:
    status_code = 200
    text = html
orig = requests.Session.get
requests.Session.get = lambda self, url, **kw: FakeResp()
try:
    page = aud.scrape_content("https://example.com/about")
finally:
    requests.Session.get = orig
print("  first_500_words =", repr(page.first_500_words[:200]))
print("  score ->", aud.analyze_text(page))
print("  (menu text in <header><div> is counted; only <nav>/<footer>/<aside> are stripped)")
