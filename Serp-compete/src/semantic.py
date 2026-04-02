import spacy
from bs4 import BeautifulSoup
import requests
from typing import Dict, List, Tuple, Any

from src.scoring_logic import TIER_1_MEDICAL, TIER_2_SYSTEMS, TIER_3_BOWEN_EXPERT, calculate_weighted_score

class SemanticAuditor:
    def __init__(self, model: str = "en_core_web_sm"):
        self.nlp = spacy.load(model)
        self.medical_terms = TIER_1_MEDICAL
        self.systems_t2 = TIER_2_SYSTEMS
        self.systems_t3 = TIER_3_BOWEN_EXPERT

    def scrape_content(self, url: str) -> str:
        """
        Use BeautifulSoup to pull <h1> through <h3> and first 500 words of text.
        Uses browser headers and a session to avoid 403 Forbidden errors.
        """
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
        }
        try:
            # First, visit the homepage to get any cookies (common anti-bot bypass)
            from urllib.parse import urlparse
            base_url = "{0.scheme}://{0.netloc}/".format(urlparse(url))
            session.get(base_url, headers=headers, timeout=10)
            
            # Now fetch the target URL
            response = session.get(url, headers=headers, timeout=15)
            if response.status_code == 429:
                print(f"⚠️ 429 Blocked: {url}")
                return "BLOCK"
                
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract headers
            headers = []
            for tag in ['h1', 'h2', 'h3']:
                for h in soup.find_all(tag):
                    headers.append(h.get_text())
            
            # Extract text
            text = soup.get_text(separator=' ')
            words = text.split()[:500]
            
            return " ".join(headers) + " " + " ".join(words)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"⚠️ 429 Blocked: {url}")
                return "BLOCK"
            print(f"Error scraping {url}: {e}")
            return ""
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ""

    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Count frequency of entities and return weighted systems score.
        """
        text_lower = text.lower()
        doc = self.nlp(text_lower)
        
        medical_count = 0
        t2_count = 0
        t3_count = 0
        
        # 1. Check tokens for simple terms
        for token in doc:
            if token.text in self.medical_terms:
                medical_count += 1
            if token.text in self.systems_t2:
                t2_count += 1
            if token.text in self.systems_t3:
                t3_count += 1
                
        # 2. Check for multi-word phrases (higher tiers usually have more of these)
        # Tier 2 multi-word
        for phrase in self.systems_t2:
            if " " in phrase:
                t2_count += text_lower.count(phrase)
        
        # Tier 3 multi-word
        for phrase in self.systems_t3:
            if " " in phrase:
                t3_count += text_lower.count(phrase)

        weighted_systems_score, systemic_label = calculate_weighted_score(medical_count, t2_count, t3_count)

        return {
            "medical_score": medical_count,
            "systems_score": weighted_systems_score,
            "systemic_label": systemic_label,
            "t2_count": t2_count,
            "t3_count": t3_count
        }
