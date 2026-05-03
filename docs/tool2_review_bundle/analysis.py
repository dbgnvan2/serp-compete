from typing import List, Set, Dict, Any

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

    def check_feasibility(self, client_da: int, competitor_da: int) -> Dict[str, Any]:
        """
        Feasibility = (Client_DA + 5) >= Competitor_DA.
        """
        feasible = (client_da + 5) >= competitor_da
        return {
            "feasible": feasible,
            "suggestion": "Proceed" if feasible else "Hyper-Local Pivot"
        }
