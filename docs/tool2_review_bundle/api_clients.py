import requests
import json
import os
import base64
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

class DataForSEOClient:
    def __init__(self):
        self.login = os.getenv("DATAFORSEO_LOGIN")
        self.password = os.getenv("DATAFORSEO_PASSWORD")
        self.base_url = "https://api.dataforseo.com/v3"

    def get_relevant_pages(self, domain: str) -> List[Dict[str, Any]]:
        """
        POST https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live
        """
        url = f"{self.base_url}/dataforseo_labs/google/ranked_keywords/live"
        payload = [{
            "target": domain,
            "location_code": 2124, # Canada
            "language_code": "en",
            "limit": 10
        }]
        
        response = requests.post(
            url, 
            auth=(self.login, self.password),
            json=payload
        )
        
        if response.status_code != 200:
            print(f"DataForSEO API error: {response.status_code} - {response.text}")
            return []
            
        data = response.json()
        if not data.get('tasks') or not data['tasks'][0].get('result'):
            print(f"No results found for {domain}")
            return []
            
        items = data['tasks'][0]['result'][0].get('items')
        if not items:
            return []
            
        # Map fields to maintain compatibility with existing logic
        for item in items:
            item['url'] = item.get('ranked_serp_element', {}).get('serp_item', {}).get('url')
            # Extract keyword from the nested keyword_data if present, else use top-level
            keyword = item.get('keyword_data', {}).get('keyword') or item.get('keyword')
            item['keyword'] = keyword
            item['keyword_data'] = {'keyword': keyword}
            
        return items

    def get_top_pages(self, domain: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        POST https://api.dataforseo.com/v3/dataforseo_labs/google/relevant_pages/live
        Fetches the top organic pages for a domain.
        """
        url = f"{self.base_url}/dataforseo_labs/google/relevant_pages/live"
        payload = [{
            "target": domain,
            "location_code": 2124, # Canada
            "language_code": "en",
            "limit": limit
        }]
        
        response = requests.post(
            url, 
            auth=(self.login, self.password),
            json=payload
        )
        
        if response.status_code != 200:
            print(f"DataForSEO Relevant Pages API error: {response.status_code} - {response.text}")
            return []
            
        data = response.json()
        if not data.get('tasks') or not data['tasks'][0].get('result'):
            print(f"No relevant pages found for {domain}")
            return []
            
        items = data['tasks'][0]['result'][0].get('items')
        if items:
            for item in items:
                # Primary location for URL in relevant_pages is 'page_address'
                url = item.get('page_address') or item.get('url')
                if not url:
                    rse = item.get('ranked_serp_element', {})
                    if rse:
                        url = rse.get('serp_item', {}).get('url')
                
                # If still None, check relative_url
                if not url and item.get('relative_url'):
                    url = f"https://{domain}{item.get('relative_url')}"
                
                item['url'] = url
        return items if items else []

    def get_serp_data(self, keyword: str) -> Dict[str, Any]:
        """
        POST https://api.dataforseo.com/v3/serp/google/organic/live/advanced
        To get People Also Ask (PAA) data.
        """
        url = f"{self.base_url}/serp/google/organic/live/advanced"
        payload = [{
            "keyword": keyword,
            "location_code": 2124, # Canada
            "language_code": "en",
            "device": "desktop",
            "os": "windows",
            "depth": 20
        }]
        
        response = requests.post(
            url, 
            auth=(self.login, self.password),
            json=payload
        )
        
        if response.status_code != 200:
            print(f"DataForSEO SERP API error: {response.status_code} - {response.text}")
            return {}
            
        data = response.json()
        if not data.get('tasks') or not data['tasks'][0].get('result'):
            return {}
            
        return data['tasks'][0]['result'][0]

class MozClient:
    def __init__(self):
        # Moz V2 uses a different auth method usually, but let's assume standard V2 usage
        # MOZ_TOKEN from .env is already base64 encoded 'access_id:secret_key' if it follows standard pattern
        self.token = os.getenv("MOZ_TOKEN")
        self.base_url = "https://api.moz.com/v2"

    def get_url_metrics(self, urls: List[str]) -> List[Dict[str, Any]]:
        """
        Call Moz V2 url_metrics for each URL to get page_authority (PA).
        """
        url = f"{self.base_url}/url_metrics"
        headers = {
            "Authorization": f"Basic {self.token}",
            "Content-Type": "application/json"
        }
        payload = {"targets": urls}
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            # If 401, maybe token is not base64 encoded or is invalid
            raise Exception(f"Moz API error: {response.status_code} - {response.text}")
            
        return response.json().get('results', [])
