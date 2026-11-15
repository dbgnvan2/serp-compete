import sys; sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.brand_utils import derive_brand_name
for d in ["www.jerichocounselling.com", "www.averytherapy.com", "jerichocounselling.com", "www.psychologytoday.com"]:
    print(d, "->", repr(derive_brand_name(d)))
