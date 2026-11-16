import spacy
import time
from bs4 import BeautifulSoup
import requests
from typing import Any, Dict, List, Literal, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from urllib.parse import urlparse

from src.scoring_logic import TIER_1_MEDICAL, TIER_2_SYSTEMS, TIER_3_BOWEN_EXPERT, calculate_weighted_score

#: Fallback only — `shared_config.json` → `stock_image_hosts` is the editorial
#: source of record, and `eeat_scorer` has always read it from there.
#:
#: This list was a literal set inside `_extract_metadata` while `eeat_scorer`
#: read the config key of the same name, so editing that key changed the EEAT
#: stock-image penalty and did NOT change `likely_original_images_count` — one
#: visible knob controlling half of what it appears to (the C-C-14 / C-M-18
#: class). Kept byte-identical to the config block and guarded by a test.
DEFAULT_STOCK_IMAGE_HOSTS = frozenset({
    "shutterstock.com", "gettyimages.com", "istockphoto.com", "unsplash.com",
    "pexels.com", "pixabay.com", "stock.adobe.com",
})


def stock_image_hosts() -> frozenset:
    """The hosts whose images are not the site's own work."""
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return DEFAULT_STOCK_IMAGE_HOSTS
    try:
        configured = load_shared_config().get("stock_image_hosts")
    except Exception:  # noqa: BLE001 - a config read must not break a scrape
        return DEFAULT_STOCK_IMAGE_HOSTS
    if isinstance(configured, (list, tuple, set, frozenset)) and configured:
        return frozenset(str(host).strip().lower() for host in configured if host)
    return DEFAULT_STOCK_IMAGE_HOSTS


@dataclass
class ScrapedPage:
    """Structured page data extracted from HTML during web scraping."""
    url: str
    fetched_at: str  # ISO 8601
    http_status: int
    extraction_status: Literal["complete", "partial", "blocked", "error"]
    extraction_errors: List[str]
    outline: List[Dict[str, Any]]  # [{"level": "h1"|"h2"|"h3", "text": str, "order": int}]
    first_500_words: str  # Backwards compat for vocabulary scoring (headings + body)
    full_text_word_count: int
    metadata: Dict[str, Any]
    # C-M-19: the text vocabulary scoring actually reads, and how many words it is.
    # `first_500_words` PREPENDS the outline text to the body, so every h1-h3 was
    # counted twice — and it has two other consumers (eeat_scorer's first-person and
    # case-study signals), so it keeps its shape. `scoring_text` is the body window
    # once, and `scoring_word_count` is the denominator for a density.
    scoring_text: str = ""
    scoring_word_count: int = 0

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
            "scoring_text": self.scoring_text,
            "scoring_word_count": self.scoring_word_count,
            "metadata": self.metadata
        }

DEFAULT_SCORING_WINDOW_WORDS = 500
# C-M-19: elements whose class or id marks them as site furniture. Their text is the
# same on every page of the domain, so counting it scores the template, not the page.
_MENU_MARKERS = ("menu", "nav", "breadcrumb", "sidebar", "widget", "offcanvas")


class SemanticAuditor:
    """Vocabulary scoring.

    C-M-19 / C-C-15, 2026-11-15 — the counting mechanics were rewritten. What they
    used to do, and why each part was wrong:

      * `token.text in set` — no lemmatisation, so "triangle" scored 0 while
        "triangles" scored 3, and "treatments" scored 0 against the entry
        "treatment". Dictionary entries are now LEMMAS and the text is lemmatised.
      * multi-word entries were matched with `str.count` on the raw lower-cased
        text, and only `if " " in phrase` — so the configured Tier-2 term
        `self-regulation` could NEVER match (spaCy splits it into `self`, `-`,
        `regulation` and it has no space), and `pursuer-distancer reciprocity`
        matched only by accident of its space. Every multi-token AND hyphenated
        entry now goes through a spaCy PhraseMatcher.
      * nested phrases were counted in two tiers at once: "differentiation of self"
        scored Tier-3 1 AND Tier-2 1 (for "differentiation"), inflating the weighted
        score by 0.5 for the same five words. Overlapping matches are now resolved
        LONGEST-FIRST across all three tiers, and each span is counted once.
      * the scored text was `headings + first 500 body words`, so every h1-h3 was
        counted twice, and `<header>` / div-based menus were never stripped.
      * the score was an absolute count over a window of up to 500 words, with no
        length normalisation, so 5 medical words scored 5 in a 5-word page and 5 in
        an 805-word page. Densities per 1000 words are reported alongside, and the
        Surface-Level penalty is a density threshold (see scoring_logic).
    """

    def __init__(self, model: str = "en_core_web_sm"):
        self.nlp = spacy.load(model)
        self.medical_terms = TIER_1_MEDICAL
        self.systems_t2 = TIER_2_SYSTEMS
        self.systems_t3 = TIER_3_BOWEN_EXPERT
        self._exact_tiers: Dict[str, str] = {}
        self._matcher, self._pattern_tiers = self._build_matcher()

    # ---- vocabulary matching (C-M-19) ---------------------------------------

    def _build_matcher(self):
        """One PhraseMatcher over LEMMAS for all three tiers.

        Matching on LEMMA means the dictionary carries lemmas and the text may carry
        any inflection. Patterns are built with the same pipeline that will analyse
        the text, so "triangles" in an entry and "triangle" in the page meet in the
        middle.
        """
        from spacy.matcher import PhraseMatcher
        matcher = PhraseMatcher(self.nlp.vocab, attr="LEMMA")
        tiers = {}
        for tier, terms in (("t1", self.medical_terms), ("t2", self.systems_t2),
                            ("t3", self.systems_t3)):
            for term in sorted({str(t).strip().lower() for t in terms if str(t).strip()}):
                key = f"{tier}:{term}"
                tiers[key] = (tier, term)
                self._exact_tiers.setdefault(term, tier)
                # The FULL pipeline, not `make_doc`: a LEMMA pattern needs the
                # lemmatiser to have run on the pattern too, or spaCy raises E155.
                # It also means the entry is matched by its own lemma, so "triangles"
                # as an entry matches "triangle" in the text and vice versa.
                matcher.add(key, [self.nlp(term)])
        return matcher, tiers

    # Tier precedence for a span no exact entry resolves: prefer the WEAKER claim.
    # Lemmatisation can collapse two entries that live in different tiers — the
    # Tier-2 entry "triangles" and the Tier-3 entry "triangling" both lemmatise to
    # "triangle" — and Tier 3 is the strong claim (Bowen-expert vocabulary, weighted
    # ×2.0, and the band that reads as "Bowen vocabulary present"). An ambiguous
    # match must not earn it.
    _TIER_PRECEDENCE = {"t1": 0, "t2": 1, "t3": 2}

    def _resolve_tier(self, span_text: str, pattern_tier: str) -> str:
        """The tier a matched span counts in.

        An EXACT surface form wins: the text "triangles" is the Tier-2 entry
        "triangles", whatever else shares its lemma, and "triangling" is the Tier-3
        entry. Only a form that is in no list by surface falls back to the pattern's
        tier, where the precedence above applies.
        """
        return self._exact_tiers.get(span_text.strip().lower(), pattern_tier)

    def count_terms(self, text: str) -> Dict[str, Any]:
        """Tier counts for `text`, longest-match-wins, each span counted once.

        Returns {t1_count, t2_count, t3_count, word_count, matches} where `matches`
        is the matched surface forms per tier — so a score can be explained, which
        an absolute count never could.
        """
        doc = self.nlp(str(text or "").lower())
        # One entry per (start, end): a span can be matched by several patterns (a
        # lemma collision, or the same term in two tiers), and it must be counted
        # ONCE. The resolved tier is the exact-surface tier when there is one, else
        # the weakest claim among the patterns that matched.
        by_extent: Dict[tuple, str] = {}
        for match_id, start, end in self._matcher(doc):
            key = self.nlp.vocab.strings[match_id]
            tier, _term = self._pattern_tiers.get(key, (None, None))
            if not tier:
                continue
            resolved = self._resolve_tier(doc[start:end].text, tier)
            current = by_extent.get((start, end))
            if current is None or (self._TIER_PRECEDENCE[resolved]
                                   < self._TIER_PRECEDENCE[current]):
                by_extent[(start, end)] = resolved
        # Longest match wins. `filter_spans` keeps the longest non-overlapping set,
        # which is what stops "differentiation of self" (Tier 3) from ALSO counting
        # as "differentiation" (Tier 2) — the same five words scored in two tiers.
        from spacy.util import filter_spans
        counts = {"t1": 0, "t2": 0, "t3": 0}
        matches: Dict[str, List[str]] = {"t1": [], "t2": [], "t3": []}
        candidates = [doc[start:end] for (start, end) in sorted(by_extent)]
        for span in filter_spans(candidates):
            tier = by_extent[(span.start, span.end)]
            counts[tier] += 1
            matches[tier].append(span.text)
        word_count = sum(1 for token in doc if not token.is_space and not token.is_punct)
        return {"t1_count": counts["t1"], "t2_count": counts["t2"],
                "t3_count": counts["t3"], "word_count": word_count,
                "matches": matches}

    @staticmethod
    def _scoring_window_words() -> int:
        """`technical.scoring_window_words` — how many body words are scored."""
        from src.scoring_logic import SHARED_CONFIG
        return int((SHARED_CONFIG.get("technical", {}) or {}).get(
            "scoring_window_words", DEFAULT_SCORING_WINDOW_WORDS))

    @staticmethod
    def _strip_boilerplate(soup) -> None:
        """Remove site furniture before the text is read (C-M-19)."""
        for tag in soup(['nav', 'footer', 'script', 'style', 'aside', 'header']):
            tag.decompose()
        for tag in soup.find_all(attrs={"class": True}):
            classes = " ".join(tag.get("class") or []).lower()
            if any(marker in classes for marker in _MENU_MARKERS):
                tag.decompose()
        for tag in soup.find_all(attrs={"id": True}):
            element_id = str(tag.get("id") or "").lower()
            if any(marker in element_id for marker in _MENU_MARKERS):
                tag.decompose()

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

        # C-C-18: the homepage pre-visit is a best-effort anti-bot warm-up, so it gets
        # its own guard. Inside the main try, a ReadTimeout on a competitor's HOMEPAGE
        # marked the TARGET page unreadable even when the target would have loaded —
        # and since main.py marks the URL as attempted before fetching, that spent one
        # of the domain's three audit slots and left no row anywhere.
        try:
            base_url = "{0.scheme}://{0.netloc}/".format(urlparse(url))
            session.get(base_url, headers=http_headers, timeout=10)
        except Exception as warm_err:  # noqa: BLE001 - best effort only
            print(f"  ℹ️ Homepage warm-up failed for {url} ({warm_err}) — "
                  f"fetching the page anyway.")

        try:
            # Now fetch the target URL, with one retry: a single transient network
            # error must not cost the page its audit slot (P5).
            response = self._get_with_one_retry(session, url, http_headers)

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

            # Extract visible text (excluding nav, footer, script, style, and —
            # C-M-19 — <header> and any element whose class/id looks like a menu).
            # A <header> or div-based menu listing seven treatment services scored
            # medical 9 on an about-page whose body was about distance and pursuit.
            # Captured BEFORE stripping: _strip_boilerplate decomposes every
            # <script>, which from 2026-11-15 to 2026-11-16 meant no page's
            # JSON-LD schema was ever seen. See _extract_metadata.
            json_ld = [script.string for script
                       in soup.find_all('script', type='application/ld+json')
                       if script.string]
            self._strip_boilerplate(soup)
            full_text = soup.get_text(separator=' ')
            full_text_words = full_text.split()
            window = self._scoring_window_words()
            scoring_words = full_text_words[:window]
            first_500_words_list = full_text_words[:500]

            # Extract headers text for backwards compat
            headers_text = " ".join([h["text"] for h in outline])

            # Build backwards-compat string: headers + first 500 words. Kept for
            # eeat_scorer, which reads it for first-person and case-study signals —
            # but NOT used for vocabulary scoring any more, because prepending the
            # outline counted every h1-h3 a second time.
            backwards_compat_string = headers_text + " " + " ".join(first_500_words_list)

            # Extract metadata
            metadata = self._extract_metadata(soup, url, json_ld=json_ld)

            return ScrapedPage(
                url=url,
                fetched_at=fetched_at,
                http_status=response.status_code,
                extraction_status="complete" if not extraction_errors else "partial",
                extraction_errors=extraction_errors,
                outline=outline,
                first_500_words=backwards_compat_string,
                full_text_word_count=len(full_text_words),
                scoring_text=" ".join(scoring_words),
                scoring_word_count=len(scoring_words),
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

    @staticmethod
    def _get_with_one_retry(session, url: str, http_headers: Dict[str, str],
                            timeout: int = 15):
        """GET the page, retrying ONCE after a transient network error (C-C-18).

        Only the exception path is retried. A 429 or a 4xx/5xx response is returned to
        the caller to classify — re-requesting a rate-limited page is exactly what the
        circuit breaker exists to avoid.
        """
        try:
            return session.get(url, headers=http_headers, timeout=timeout)
        except requests.RequestException as first_err:
            print(f"  ℹ️ Fetch failed for {url} ({first_err}) — retrying once.")
            time.sleep(1.5)
            return session.get(url, headers=http_headers, timeout=timeout)

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

    def _extract_metadata(self, soup: BeautifulSoup, url: str,
                          json_ld: Optional[List[str]] = None) -> Dict[str, Any]:
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

        # JSON-LD schema.
        #
        # `json_ld` is passed in because the soup reaching here has had its
        # <script> tags decomposed. `_strip_boilerplate` (C-M-19, 2026-11-15)
        # removes script/style so they do not enter the scored text window, and
        # it runs BEFORE this function — so from that date until 2026-11-16 no
        # page's JSON-LD was ever found. Every schema signal was therefore
        # permanently False: `has_faq_schema`, `has_article_schema`,
        # `has_localbusiness_schema`, `has_person_schema` and `has_org_schema`
        # in geo_profiler (five of its signals, including the FAQ/question ones
        # C-M-14 asked to be weighted highest), and
        # `schema_author_type_person` / `schema_organization_present` in
        # eeat_scorer. Two owner-facing composites were quietly degraded for
        # every competitor, and the tests covered neither.
        #
        # The blocks cannot simply be left in the soup: their JSON would then
        # be counted as prose in the scoring window.
        for raw in (json_ld or []):
            try:
                self._extract_schema_types(json.loads(raw), metadata)
            except (json.JSONDecodeError, TypeError, ValueError):
                # A rival's malformed schema must not cost us the page.
                continue
            except Exception:  # noqa: BLE001 - nor must an unexpected shape
                continue

        # Images
        image_hosts_set = set()
        # The config key, not a second copy of the list (see
        # DEFAULT_STOCK_IMAGE_HOSTS). Read once per page, not per image.
        stock_hosts = stock_image_hosts()
        for img in soup.find_all('img'):
            metadata["image_count"] += 1
            src = img.get('src', '')
            if src:
                parsed = urlparse(src)
                if parsed.netloc:
                    host = parsed.netloc.lower()
                    image_hosts_set.add(parsed.netloc)
                    # Count original images (not from stock hosts). Compared
                    # lower-cased: `IStockPhoto.com` in a src attribute used to
                    # count as the site's own photography.
                    if host not in stock_hosts:
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
        # Handle both string and ScrapedPage inputs for backwards compat.
        # C-M-19: a ScrapedPage is scored on `scoring_text` (the body window, once),
        # not on `first_500_words`, which prepends the outline and so counted every
        # h1-h3 twice. An older page object without the field falls back to it.
        if isinstance(text, ScrapedPage):
            text_to_analyze = text.scoring_text or text.first_500_words
            declared_window = text.scoring_word_count or 0
        else:
            text_to_analyze = text
            declared_window = 0

        counts = self.count_terms(text_to_analyze)
        medical_count = counts["t1_count"]
        t2_count = counts["t2_count"]
        t3_count = counts["t3_count"]
        window_words = declared_window or counts["word_count"]

        weighted_systems_score, systemic_label = calculate_weighted_score(
            medical_count, t2_count, t3_count, window_words=window_words)

        def per_1000(hits: float) -> float:
            # Length normalisation (C-M-19): 5 medical words meant the same thing in
            # a 5-word page and an 805-word page. The window travels with the figure
            # so the density can be checked rather than taken on trust.
            if not window_words:
                return 0.0
            return round(1000.0 * float(hits) / float(window_words), 1)

        return {
            "medical_score": medical_count,
            "systems_score": weighted_systems_score,
            "systemic_label": systemic_label,
            "t2_count": t2_count,
            "t3_count": t3_count,
            "scoring_window_words": window_words,
            "medical_density_per_1000": per_1000(medical_count),
            "t2_density_per_1000": per_1000(t2_count),
            "t3_density_per_1000": per_1000(t3_count),
            "matched_terms": counts["matches"],
        }
