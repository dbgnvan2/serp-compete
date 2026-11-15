"""Probe 3 — EEAT, cluster and GEO behaviour on minimal / default pages."""
import sys, json
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.semantic import ScrapedPage
from src.eeat_scorer import EEATScorer
from src.cluster_detector import ClusterDetector
from src.geo_profiler import GeoProfiler

cfg = json.load(open("/Users/davemini2/ProjectsLocal/serp-compete/shared_config.json"))
eeat = EEATScorer(cfg)
geo = GeoProfiler(cfg)
clu = ClusterDetector(cfg)


def page(url, text="", outline=None, **meta):
    m = {"title": None, "meta_description": None, "author_byline": None, "publish_date": None,
         "update_date": None, "schema_types": [], "has_faq_schema": False, "has_article_schema": False,
         "has_localbusiness_schema": False, "image_count": 0, "image_hosts": [],
         "likely_original_images_count": 0, "external_link_count": 0, "internal_link_count": 0,
         "internal_links": [], "is_https": url.startswith("https"), "has_contact_link": False,
         "has_privacy_link": False, "case_study_signal": False}
    m.update(meta)
    return ScrapedPage(url=url, fetched_at="2026-01-01T00:00:00Z", http_status=200,
                       extraction_status="complete", extraction_errors=[], outline=outline or [],
                       first_500_words=text, full_text_word_count=len(text.split()), metadata=m)

print("== A. EEAT on a bare https page with a 'Contact us' link, text 'our relationship with you' (no author, no dates, no schema)")
p = page("https://x.ca/", text="Contact us about our relationship with you and the process we use.",
         has_contact_link=True, image_count=3)
s = eeat.score_page(p, domain_authority=0)
print("   scores:", s.scores, "| confidence:", s.score_confidence)
print("   trust = 0.4 (https) + 0.3 (contact) = 0.7 ; expertise = 0.4 from the word 'relationship'/'process' ;",
      "experience: images(0.2) + first-person 'our'+'us' (2/10*0.2)")
print("   DA passed from main.py is the URL's Moz PA (main.py:453 pa = moz_metrics_map.get(url, 0)); 0 -> `or None` -> excluded")

print("\n== B. score_confidence is a null-count, not a signal-coverage measure")
p_fail = ScrapedPage(url="https://y.ca/", fetched_at="", http_status=429, extraction_status="blocked",
                     extraction_errors=["429"], outline=[], first_500_words="", full_text_word_count=0,
                     metadata=eeat._build_empty_experience_signals() | {"schema_types": []})
print("   blocked page ->", eeat.score_page(p_fail).score_confidence,
      "| any successfully scraped page ->", eeat.score_page(page("https://z.ca/")).score_confidence)
print("   config eeat_client_messaging.confidence_levels describes 0.0-0.5 / 0.5-0.8 / 0.8-1.0 bands — never computed")

print("\n== C. Trustworthiness value set (3 booleans, weights .4/.3/.3) rendered to 2 dp")
vals = set()
for h in (0, 1):
    for c in (0, 1):
        for pr in (0, 1):
            pp = page("https://a.ca/" if h else "http://a.ca/", has_contact_link=bool(c), has_privacy_link=bool(pr))
            vals.add(eeat.score_page(pp).scores["trustworthiness"])
print("   possible trust scores:", sorted(vals))

print("\n== D. Cluster detection with N=3 where two pages link to the homepage (logo/menu link)")
home = page("https://c.ca/", internal_links=["/services", "/about"])
svc = page("https://c.ca/services", internal_links=["/"])
about = page("https://c.ca/about", internal_links=["/"])
r = clu.analyze_domain("c.ca", [home, svc, about])
print("   signal:", r.cluster_signal, "| hubs:", r.hub_candidates, "| max in-degree possible with N=3 is 2 = hub threshold")
r2 = clu.analyze_domain("c.ca", [page("https://c.ca/a"), page("https://c.ca/b"), page("https://c.ca/c")])
print("   three pages, no links among the three ->", r2.cluster_signal, "(site may have 500 interlinked pages)")
r3 = clu.analyze_domain("c.ca", [home, svc])
print("   two pages ->", r3.cluster_signal)
# www vs non-www
home_w = page("https://www.c.ca/", internal_links=["https://c.ca/services", "https://c.ca/about"])
r4 = clu.analyze_domain("c.ca", [home_w, page("https://www.c.ca/services", internal_links=["https://c.ca/"]), page("https://www.c.ca/about", internal_links=["https://c.ca/"])])
print("   same site, absolute links without www ->", r4.cluster_signal, "(host string compared verbatim)")

print("\n== E. GEO tier on a stock WordPress+Yoast post: Organization+Person schema, 'admin' byline, published_time, 0 question headings")
wp = page("https://w.ca/blog/post", schema_types=["Organization", "Person", "WebPage"],
          author_byline="admin", publish_date="2024-01-01",
          outline=[{"level": "h2", "text": "Our approach", "order": 0}])
g = geo.profile_page(wp)
print("   tier:", g.extractability_tier, "| why_cited:", g.why_cited)
faq = page("https://f.ca/faq", has_faq_schema=True, schema_types=["FAQPage"],
           outline=[{"level": "h2", "text": f"How does couples therapy work?", "order": 0},
                    {"level": "h2", "text": "What does it cost?", "order": 1}])
print("   FAQ page w/ FAQPage schema + 2 question headings, no byline, no date ->", geo.profile_page(faq).extractability_tier)
