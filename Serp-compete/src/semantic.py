import spacy
from bs4 import BeautifulSoup
import requests
from typing import Dict, List, Tuple, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from urllib.parse import urlparse

from src.scoring_logic import TIER_1_MEDICAL, TIER_2_SYSTEMS, TIER_3_BOWEN_EXPERT, calculate_weighted_score


@dataclass
class ScrapedPage:
    """Structured page data extracted from HTML during web scraping."""
    url: str
    fetched_at: str  # ISO 8601
    http_status: int
    extraction_status: Literal["complete", "partial", "blocked", "error"]
    extraction_errors: List[str]
    outline: List[Dict[str, Any]]  # [{"level": "h1"|"h2"|"h3", "text": str, "order": int}]
    first_500_words: str  # Backwards compat for vocabulary scoring
    full_text_word_count: int
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "fetched_at": self.fetched_at,
            "http_status": self.http_status,
            "extraction_status": self.extraction_status,
            "extraction_errors": self.extraction_errors,
            "outline": self.outline,
            "first_500_words": self.first_500_words,
            "full_text_word_count": self.full_text_word_count,
            "metadata": self.metadata
        }

class SemanticAuditor:
    def __init__(self, model: str = "en_core_web_sm"):
        self.nlp = spacy.load(model)
        self.medical_terms = TIER_1_MEDICAL
        self.systems_t2 = TIER_2_SYSTEMS
        self.systems_t3 = TIER_3_BOWEN_EXPERT

    def scrape_content(self, url: str) -> ScrapedPage:
        """
        Gap 2: Extract full page structure while preserving backwards compatibility.

        Fetches page, extracts headers, metadata, links, schema, and full text.
        Returns ScrapedPage dataclass with all extracted fields.
        The `first_500_words` field preserves the original "headers + first 500 words"
        string for backwards compatibility with vocabulary scoring.
        """
        session = requests.Session()
        http_headers = {
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

        fetched_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        extraction_errors = []

        try:
            # First, visit the homepage to get any cookies (common anti-bot bypass)
            base_url = "{0.scheme}://{0.netloc}/".format(urlparse(url))
            session.get(base_url, headers=http_headers, timeout=10)

            # Now fetch the target URL
            response = session.get(url, headers=http_headers, timeout=15)

            # Handle 429 blocked
            if response.status_code == 429:
                print(f"⚠️ 429 Blocked: {url}")
                return ScrapedPage(
                    url=url,
                    fetched_at=fetched_at,
                    http_status=429,
                    extraction_status="blocked",
                    extraction_errors=["HTTP 429 - Rate limited"],
                    outline=[],
                    first_500_words="",
                    full_text_word_count=0,
                    metadata=self._build_empty_metadata()
                )

            if response.status_code >= 400:
                print(f"⚠️ HTTP {response.status_code}: {url}")
                return ScrapedPage(
                    url=url,
                    fetched_at=fetched_at,
                    http_status=response.status_code,
                    extraction_status="error",
                    extraction_errors=[f"HTTP {response.status_code}"],
                    outline=[],
                    first_500_words="",
                    full_text_word_count=0,
                    metadata=self._build_empty_metadata()
                )

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract outline (h1, h2, h3 with order)
            outline = self._extract_outline(soup)

            # Extract visible text (excluding nav, footer, script, style)
            for tag in soup(['nav', 'footer', 'script', 'style', 'aside']):
                tag.decompose()
            full_text = soup.get_text(separator=' ')
            full_text_words = full_text.split()
            first_500_words_list = full_text_words[:500]

            # Extract headers text for backwards compat
            headers_text = " ".join([h["text"] for h in outline])

            # Build backwards-compat string: headers + first 500 words
            backwards_compat_string = headers_text + " " + " ".join(first_500_words_list)

            # Extract metadata
            metadata = self._extract_metadata(soup, url)

            return ScrapedPage(
                url=url,
                fetched_at=fetched_at,
                http_status=response.status_code,
                extraction_status="complete" if not extraction_errors else "partial",
                extraction_errors=extraction_errors,
                outline=outline,
                first_500_words=backwards_compat_string,
                full_text_word_count=len(full_text_words),
                metadata=metadata
            )

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"⚠️ 429 Blocked: {url}")
                return ScrapedPage(
                    url=url,
                    fetched_at=fetched_at,
                    http_status=429,
                    extraction_status="blocked",
                    extraction_errors=["HTTP 429 - Rate limited"],
                    outline=[],
                    first_500_words="",
                    full_text_word_count=0,
                    metadata=self._build_empty_metadata()
                )
            print(f"Error scraping {url}: {e}")
            return ScrapedPage(
                url=url,
                fetched_at=fetched_at,
                http_status=e.response.status_code if e.response else 0,
                extraction_status="error",
                extraction_errors=[str(e)],
                outline=[],
                first_500_words="",
                full_text_word_count=0,
                metadata=self._build_empty_metadata()
            )
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ScrapedPage(
                url=url,
                fetched_at=fetched_at,
                http_status=0,
                extraction_status="error",
                extraction_errors=[str(e)],
                outline=[],
                first_500_words="",
                full_text_word_count=0,
                metadata=self._build_empty_metadata()
            )

    def _extract_outline(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract h1, h2, h3 headers with source order."""
        outline = []
        order = 0
        for tag_name in ['h1', 'h2', 'h3']:
            for tag in soup.find_all(tag_name):
                text = tag.get_text(strip=True)
                if text:
                    outline.append({
                        "level": tag_name,
                        "text": text,
                        "order": order
                    })
                    order += 1
        return outline

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract page metadata (title, author, dates, schema, links, etc)."""
        metadata = {
            "title": None,
            "meta_description": None,
            "author_byline": None,
            "publish_date": None,
            "update_date": None,
            "schema_types": [],
            "has_faq_schema": False,
            "has_article_schema": False,
            "has_localbusiness_schema": False,
            "image_count": 0,
            "image_hosts": [],
            "likely_original_images_count": 0,
            "external_link_count": 0,
            "internal_link_count": 0,
            "internal_links": [],
            "is_https": url.startswith("https"),
            "has_contact_link": False,
            "has_privacy_link": False,
            "case_study_signal": False,
        }

        # Title
        title_tag = soup.find('title')
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        # Meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            metadata["meta_description"] = meta_desc.get('content')

        # Author byline (check multiple sources)
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta:
            metadata["author_byline"] = author_meta.get('content')
        else:
            author_article = soup.find('meta', attrs={'property': 'article:author'})
            if author_article:
                metadata["author_byline"] = author_article.get('content')
            else:
                # Try common selectors
                author_elem = soup.select_one('[rel="author"], .author, .byline')
                if author_elem:
                    metadata["author_byline"] = author_elem.get_text(strip=True)

        # Publish and update dates
        pub_date = soup.find('meta', attrs={'property': 'article:published_time'})
        if pub_date:
            metadata["publish_date"] = pub_date.get('content')

        update_date = soup.find('meta', attrs={'property': 'article:modified_time'})
        if update_date:
            metadata["update_date"] = update_date.get('content')

        # JSON-LD schema
        try:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    schema_data = json.loads(script.string)
                    self._extract_schema_types(schema_data, metadata)
                except json.JSONDecodeError as e:
                    # Store error but continue
                    pass
        except Exception:
            pass

        # Images
        image_hosts_set = set()
        stock_image_hosts = {"shutterstock.com", "gettyimages.com", "istockphoto.com", "unsplash.com", "pexels.com", "pixabay.com", "stock.adobe.com"}
        for img in soup.find_all('img'):
            metadata["image_count"] += 1
            src = img.get('src', '')
            if src:
                parsed = urlparse(src)
                if parsed.netloc:
                    image_hosts_set.add(parsed.netloc)
                    # Count original images (not from stock hosts)
                    if parsed.netloc not in stock_image_hosts and parsed.netloc:
                        metadata["likely_original_images_count"] += 1
        metadata["image_hosts"] = list(image_hosts_set)

        # Links (internal vs external)
        page_domain = urlparse(url).netloc
        internal_links_set = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            link_text = link.get_text(strip=True).lower()

            # Check for contact/privacy links
            if 'contact' in link_text or 'contact' in href:
                metadata["has_contact_link"] = True
            if 'privacy' in link_text or 'privacy' in href:
                metadata["has_privacy_link"] = True

            # Classify as internal or external
            parsed_href = urlparse(href)
            link_domain = parsed_href.netloc or page_domain  # Relative URLs are internal

            if not parsed_href.scheme or parsed_href.netloc == page_domain:
                # Internal link
                metadata["internal_link_count"] += 1
                # Store raw URL for internal_links list
                internal_links_set.add(href)
            else:
                # External link
                metadata["external_link_count"] += 1

        metadata["internal_links"] = list(internal_links_set)

        # Case study signal detection
        page_text = soup.get_text().lower()
        case_study_triggers = ["we tested", "case study", "in our experience", "our research", "we conducted", "our findings"]
        for trigger in case_study_triggers:
            if trigger in page_text:
                metadata["case_study_signal"] = True
                break

        return metadata

    def _extract_schema_types(self, schema_data: Any, metadata: Dict[str, Any]) -> None:
        """Recursively extract @type values from JSON-LD schema."""
        if isinstance(schema_data, dict):
            schema_type = schema_data.get("@type")
            if schema_type:
                if isinstance(schema_type, list):
                    metadata["schema_types"].extend(schema_type)
                    for t in schema_type:
                        if t == "FAQPage":
                            metadata["has_faq_schema"] = True
                        elif t == "Article":
                            metadata["has_article_schema"] = True
                        elif t == "LocalBusiness":
                            metadata["has_localbusiness_schema"] = True
                else:
                    metadata["schema_types"].append(schema_type)
                    if schema_type == "FAQPage":
                        metadata["has_faq_schema"] = True
                    elif schema_type == "Article":
                        metadata["has_article_schema"] = True
                    elif schema_type == "LocalBusiness":
                        metadata["has_localbusiness_schema"] = True

            # Recurse into nested objects
            for value in schema_data.values():
                if isinstance(value, (dict, list)):
                    self._extract_schema_types(value, metadata)
        elif isinstance(schema_data, list):
            for item in schema_data:
                self._extract_schema_types(item, metadata)

    def _build_empty_metadata(self) -> Dict[str, Any]:
        """Build empty metadata dict with sensible defaults."""
        return {
            "title": None,
            "meta_description": None,
            "author_byline": None,
            "publish_date": None,
            "update_date": None,
            "schema_types": [],
            "has_faq_schema": False,
            "has_article_schema": False,
            "has_localbusiness_schema": False,
            "image_count": 0,
            "image_hosts": [],
            "likely_original_images_count": 0,
            "external_link_count": 0,
            "internal_link_count": 0,
            "internal_links": [],
            "is_https": False,
            "has_contact_link": False,
            "has_privacy_link": False,
            "case_study_signal": False,
        }

    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Gap 2: Backwards compatibility wrapper.

        Analyzes text (string or ScrapedPage.first_500_words) using vocabulary scoring.
        Works with both the old string input and new ScrapedPage structure.
        """
        # Handle both string and ScrapedPage inputs for backwards compat
        if isinstance(text, ScrapedPage):
            text_to_analyze = text.first_500_words
        else:
            text_to_analyze = text

        text_lower = text_to_analyze.lower()
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

        # 2. Check for multi-word phrases
        for phrase in self.systems_t2:
            if " " in phrase:
                t2_count += text_lower.count(phrase)

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
