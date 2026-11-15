from typing import List, Set, Dict, Any

DEFAULT_FEASIBILITY_THRESHOLD = 5


def feasibility_threshold() -> float:
    """`technical.feasibility_threshold` — the DA head-start a counter-page is
    assumed to be worth. Editorial and uncalibrated; see its `_source` note."""
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return DEFAULT_FEASIBILITY_THRESHOLD
    technical = (load_shared_config().get("technical", {}) or {})
    return float(technical.get("feasibility_threshold", DEFAULT_FEASIBILITY_THRESHOLD))

class AnalysisEngine:
    def __init__(self, client_domain: str):
        self.client_domain = client_domain

    def find_keyword_intersection(self, competitor_keywords: Dict[str, Set[str]], client_keywords: Set[str]) -> Set[str]:
        """
        Flag keywords that all three (or all provided) rank for, but client doesn't.
        """
        if not competitor_keywords:
            return set()
            
        common_competitor_keywords = None
        for domain, keywords in competitor_keywords.items():
            if common_competitor_keywords is None:
                common_competitor_keywords = keywords
            else:
                common_competitor_keywords = common_competitor_keywords.intersection(keywords)
                
        if common_competitor_keywords is None:
            return set()
            
        return common_competitor_keywords.difference(client_keywords)

    def check_feasibility(self, client_da: int, competitor_da: int,
                          threshold: float = None) -> Dict[str, Any]:
        """
        Feasibility = (Client_DA + threshold) >= Competitor_DA.

        C-M-18 / C-C-14: the threshold was the literal `+ 5` here while
        `technical.feasibility_threshold: 5` sat in config with NO reader — so the
        documented knob did nothing and the real one was invisible. This reads the
        config key; `moderate_feasibility_max_gap` is still unread and is deleted
        from the config rather than left to look live.
        """
        if threshold is None:
            threshold = feasibility_threshold()
        feasible = (client_da + threshold) >= competitor_da
        return {
            "feasible": feasible,
            "suggestion": "Proceed" if feasible else "Hyper-Local Pivot"
        }
