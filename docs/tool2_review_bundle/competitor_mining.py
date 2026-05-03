import os
import pandas as pd
import csv
import re
from typing import List, Set
from api_clients import DataForSEOClient
from reframe_engine import ReframeEngine

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUDIT_XLSX = os.path.join(ROOT_DIR, "Serp-compete", "audit_results_run_4.xlsx")
KEYWORDS_CSV = os.path.join(ROOT_DIR, "serp-keyword", "keywords_Couple_Marriage_RelationshipLocal.csv")
OUTPUT_MD = os.path.join(ROOT_DIR, "competitor_keyword_gap.md")

def load_existing_keywords(path: str) -> Set[str]:
    keywords = set()
    if os.path.exists(path):
        with open(path, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    keywords.add(row[0].strip().lower())
    return keywords

def get_top_domains(path: str, limit: int = 5) -> List[str]:
    if not os.path.exists(path):
        print(f"Error: {path} not found.")
        return []
    df = pd.read_excel(path)
    if 'total_keywords' in df.columns:
        df = df.sort_values(by='total_keywords', ascending=False)
    return df['domain'].head(limit).tolist()

def derive_brand_name(domain: str) -> str:
    """Extract 'jericho' from 'jerichocounselling.com'"""
    name = domain.split('.')[0]
    # Handle common counselor/counselling suffix removal
    for suffix in ['counselling', 'counseling', 'therapy', 'counselor', 'counsellor', 'psychology']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.lower()

def contains_numbers(text: str) -> bool:
    return bool(re.search(r'\d', text))

def main():
    print("🚀 Starting Refined Competitor Keyword Mining (Module I)...")
    
    # 1. Load existing keywords for gap analysis
    existing_keywords = load_existing_keywords(KEYWORDS_CSV)
    print(f"Loaded {len(existing_keywords)} existing keywords.")

    # 2. Get top domains
    top_domains = get_top_domains(AUDIT_XLSX)
    print(f"Top domains for mining: {top_domains}")

    client = DataForSEOClient()
    engine = ReframeEngine()
    
    all_new_opportunities = []

    for domain in top_domains:
        brand = derive_brand_name(domain)
        print(f"Fetching top 100 keywords for: {domain} (Brand: {brand})...")
        
        url = f"{client.base_url}/dataforseo_labs/google/ranked_keywords/live"
        payload = [{
            "target": domain,
            "location_code": 2124, # Canada
            "language_code": "en",
            "limit": 100
        }]
        
        try:
            import requests
            response = requests.post(
                url, 
                auth=(client.login, client.password),
                json=payload
            )
            if response.status_code == 200:
                data = response.json()
                items = data['tasks'][0]['result'][0].get('items', [])
            else:
                print(f"API Error for {domain}: {response.status_code}")
                items = []
        except Exception as e:
            print(f"Request failed for {domain}: {e}")
            items = []

        count = 0
        for item in items:
            kdata = item.get('keyword_data', {})
            kw = kdata.get('keyword') or item.get('keyword')
            if not kw: continue
            
            kw_lower = kw.lower()
            
            # HARD FILTERS:
            # 1. Skip if already exists
            if kw_lower in existing_keywords:
                continue
            # 2. Skip if contains numbers (addresses)
            if contains_numbers(kw_lower):
                continue
            # 3. Skip if contains brand name
            if brand in kw_lower:
                continue
            
            # VOLUME CHECK:
            # Structure observed in raw response: keyword_data -> keyword_info -> search_volume
            kinfo = kdata.get('keyword_info', {})
            volume = kinfo.get('search_volume', 0)
            if volume < 10:
                continue
            
            # REFRAME:
            reframe = engine.clinical_pivot(kw)
            
            # Better reframe placeholder logic if clinical_pivot returns original kw
            if reframe == kw:
                reframe = f"Systemic Pattern Analysis: '{kw.title()}'"
            
            all_new_opportunities.append({
                "domain": domain,
                "keyword": kw,
                "reframe": reframe,
                "etv": volume
            })
            count += 1
        
        print(f"Found {count} qualified new keywords for {domain}.")

    # 3. Output to Markdown
    report = [
        "# Competitor Keyword Gap Analysis (Module I - Refined)",
        f"Generated on: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "\n## Gap Summary",
        "**Filters Applied:**",
        "- Depth: 100 keywords per domain",
        "- Excluded: Keywords with numbers (addresses)",
        "- Excluded: Brand names",
        "- Volume: Minimum search volume of 10",
        f"- Target CSV: `{os.path.basename(KEYWORDS_CSV)}`",
        "\n| Competitor Domain | Hidden Traffic Driver | Bowen Systemic Reframe | Est. Volume |",
        "| :--- | :--- | :--- | :--- |"
    ]

    # Sort opportunities by volume descending
    all_new_opportunities.sort(key=lambda x: x['etv'], reverse=True)

    for opt in all_new_opportunities:
        report.append(f"| {opt['domain']} | {opt['keyword']} | **{opt['reframe']}** | {opt['etv']} |")

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print(f"✅ Refined Gap analysis report generated: {OUTPUT_MD}")

if __name__ == "__main__":
    main()
