import os
import sys
import json
from typing import List, Dict, Any
from src.api_clients import DataForSEOClient
from src.semantic import SemanticAuditor

class Infiltrator:
    def __init__(self, shared_config_path: str = "../shared_config.json"):
        # Load shared config for potential future needs, though currently relies on .env via api_clients
        self.auditor = SemanticAuditor()
        self.dfs_client = DataForSEOClient()

    def run_infiltration(self, domains: List[str], output_path: str = "infil_report.md"):
        report_lines = [
            "# Infiltrator Report: Strategic Content Targets",
            f"Generated on: {os.popen('date').read().strip()}",
            "\nThis report identifies competitor pages with high traffic but zero Bowen systemic depth ('High Fragility').",
            "\n| Domain | URL | Est. Traffic | Medical Score | Bowen Score | Fragility |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]
        
        all_targets = []

        for domain in domains:
            print(f"🕵️ Infiltrating {domain}...")
            top_pages = self.dfs_client.get_top_pages(domain, limit=20)
            
            for page in top_pages:
                url = page.get('url')
                # Try to extract traffic from different possible locations
                metrics = page.get('metrics', {}).get('organic', {})
                est_traffic = metrics.get('etv', 0)
                if est_traffic == 0:
                    est_traffic = page.get('keyword_data', {}).get('keyword_info', {}).get('search_volume', 0)
                
                if not url:
                    print(f"    ⚠️ Missing URL for entry with traffic {est_traffic}")
                    continue
                
                print(f"  Scrutinizing {url} (Est. Traffic: {est_traffic:.0f})...")
                content = self.auditor.scrape_content(url)
                if not content:
                    print(f"    ⚠️ Could not scrape {url}")
                    continue
                
                scores = self.auditor.analyze_text(content)
                med_score = scores.get('medical_score', 0)
                bowen_score = scores.get('systems_score', 0)
                
                # Fragility Scoring: >500 est. monthly visits but a Bowen Score of 0.
                fragility = "Standard"
                if est_traffic > 500 and bowen_score == 0:
                    fragility = "**High Fragility**"
                
                all_targets.append({
                    "domain": domain,
                    "url": url,
                    "traffic": est_traffic,
                    "medical": med_score,
                    "bowen": bowen_score,
                    "fragility": fragility
                })

        # Sort by fragility (High Fragility first) then traffic
        all_targets.sort(key=lambda x: (x['fragility'] == "**High Fragility**", x['traffic']), reverse=True)

        for t in all_targets:
            report_lines.append(f"| {t['domain']} | {t['url']} | {t['traffic']:.0f} | {t['medical']} | {t['bowen']} | {t['fragility']} |")

        with open(output_path, "w") as f:
            f.write("\n".join(report_lines))
        
        print(f"✅ Infiltration complete. Report saved to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_domains = sys.argv[1:]
    else:
        test_domains = ['jerichocounselling.com', 'wellspringcounselling.ca']
    
    infil = Infiltrator()
    infil.run_infiltration(test_domains)
