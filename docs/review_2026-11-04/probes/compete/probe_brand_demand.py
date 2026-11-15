"""C3 branded demand: (a) www-prefixed handoff domains -> brand 'www'; (b) one provider failure -> volume 0 labelled volume_estimated."""
import sys
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.brand_utils import derive_brand_name
from src.brand_demand import compute_branded_demand
cfg = {"branded_modifiers": ["reviews", "pricing"], "generic_brand_prune": ["therapy","counselling"], "growth_window_months": 3}
domains = ["www.jerichocounselling.com", "www.averytherapy.com", "clearcounselling.ca", "livingsystems.ca"]
brand_by_domain = {d: derive_brand_name(d) for d in domains}
print("brand_by_domain:", brand_by_domain)
calls = []
def provider(queries):
    calls.append(list(queries))
    if queries[0] == "clear":   # transient DataForSEO failure for ONE brand -> get_search_volume returns {}
        return {}
    return {q: {"search_volume": 1000 if q == queries[0] else 10, "monthly_searches": []} for q in queries}
rows = compute_branded_demand(brand_by_domain, provider, cfg, "2026-11", own_domain="livingsystems.ca")
print("queries sent:", calls)
for r in rows: print(r["domain"], r["brand"], r["branded_search_volume"], r["branded_volume_share"], r["estimation_basis"])
