import requests
import json
import os
import time
import base64
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

# C-C-12 / LEARNINGS rule 1 (P5): external calls are hardened as a CLASS, not one at
# a time. `get_search_volume` had timeout + retry + backoff while its siblings
# `get_relevant_pages` and `get_url_metrics` had neither, so a DataForSEO 429 on
# domain 17 of 34 dropped that competitor with no trace and a `ConnectionError`
# aborted the whole run after `create_run` had already written a row.
DEFAULT_TIMEOUT = 30
DEFAULT_ATTEMPTS = 3
RETRY_STATUS = (429, 500, 502, 503, 504)


def post_with_retries(url: str, label: str, attempts: int = DEFAULT_ATTEMPTS,
                      timeout: int = DEFAULT_TIMEOUT,
                      **kwargs) -> Tuple[Optional[requests.Response], Optional[str]]:
    """POST with timeout, bounded retries and backoff. Returns `(response, error)`.

    Exactly one of the two is None. A 429 or 5xx is transient and retried; any other
    4xx is terminal and returned at once (retrying a 401 only burns time). A network
    exception never escapes — the caller decides what an outage means for its own
    contract, which is the distinction between "unknown" and "zero" this repo keeps
    getting wrong (P1).
    """
    last_error = "no attempt made"
    for attempt in range(max(1, attempts)):
        try:
            response = requests.post(url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"  ⚠️ {label} attempt {attempt + 1} failed: {last_error}")
        else:
            if response.status_code == 200:
                return response, None
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUS:
                print(f"  ⚠️ {label} failed: {last_error} (terminal, not retried)")
                return None, last_error
            print(f"  ⚠️ {label} attempt {attempt + 1}: {last_error} (retrying)")
        if attempt + 1 < max(1, attempts):
            time.sleep(1.5 * (attempt + 1))  # backoff before retry (429-friendly)
    return None, last_error


class DataForSEOClient:
    def __init__(self):
        self.login = os.getenv("DATAFORSEO_LOGIN")
        self.password = os.getenv("DATAFORSEO_PASSWORD")
        self.base_url = "https://api.dataforseo.com/v3"

    def get_relevant_pages(self, domain: str) -> List[Dict[str, Any]]:
        """
        POST https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live

        Keyword ENRICHMENT for one domain (the audit universe itself comes from the
        handoff — see src/audit_universe.py). Hardened like `get_search_volume`
        (timeout + retry + backoff, 429/5xx retried, other 4xx terminal) and it never
        raises: `self.last_error` carries the reason so `run_audit` can name the
        domain in the report instead of dropping it silently (C-C-12).
        """
        self.last_error = None
        url = f"{self.base_url}/dataforseo_labs/google/ranked_keywords/live"
        payload = [{
            "target": domain,
            "location_code": 2124, # Canada
            "language_code": "en",
            "limit": 10
        }]

        response, error = post_with_retries(
            url, f"DataForSEO ranked_keywords({domain})",
            auth=(self.login, self.password), json=payload)
        if response is None:
            self.last_error = error
            print(f"DataForSEO API error for {domain}: {error}")
            return []

        try:
            data = response.json()
        except ValueError as exc:
            self.last_error = f"unparseable response: {exc}"
            print(f"DataForSEO API error for {domain}: {self.last_error}")
            return []
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

    def get_search_volume(self, keywords: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
        """C3/SC-5: monthly + current search volume for a keyword list.

        POST .../keywords_data/google_ads/search_volume/live, hardened via
        `post_with_retries`.

        Returns {keyword_lower: {'search_volume': int, 'monthly_searches': [...]}} when
        the API answered with rows, and **None when it did not** (C-C-11): a non-200
        after retries, a network failure, an unparseable body, or a 200 whose `result`
        is empty for a non-empty keyword list — DataForSEO normally returns one item
        per keyword, so an empty result is an anomaly, not a measured zero. A brand
        with no demand comes back as rows with `search_volume` 0.

        The distinction is the point: `None` means "we do not know", and the caller
        must then write NULL and `estimation_basis = volume_unavailable` for that
        brand, not 0 volume and a 0.00% share, which is how a 429 on the third of
        twenty per-brand calls turned a competitor into a brand with no demand (P1).
        """
        if not keywords:
            return {}
        url = f"{self.base_url}/keywords_data/google_ads/search_volume/live"
        payload = [{"keywords": [str(k) for k in keywords][:1000],
                    "location_code": 2124, "language_code": "en"}]
        response, error = post_with_retries(
            url, "DataForSEO search_volume", auth=(self.login, self.password),
            json=payload)
        if response is None:
            print(f"DataForSEO search_volume unavailable: {error}")
            return None
        try:
            data = response.json()
        except ValueError as exc:
            print(f"DataForSEO search_volume unparseable: {exc}")
            return None
        result = (data.get('tasks') or [{}])[0].get('result') or []
        out: Dict[str, Dict[str, Any]] = {}
        for item in result:
            kw = str(item.get('keyword') or '').lower()
            if kw:
                out[kw] = {'search_volume': item.get('search_volume') or 0,
                           'monthly_searches': item.get('monthly_searches') or []}
        if not out:
            print("DataForSEO search_volume returned no rows for "
                  f"{len(keywords)} keyword(s) — treated as unavailable, not as zero.")
            return None
        return out

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
            json=payload,
            timeout=30
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
            json=payload,
            timeout=30
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

        Hardened like its siblings (timeout + retry + backoff, 429/5xx retried, other
        4xx terminal) and still raises on terminal failure — the caller treats that as
        "PA unknown" and writes NULL, never 0 (C-C-03).

        C-C-04 is NOT closed by this change and cannot be from a sandbox: Moz's
        url-metrics objects identify the target as `page` (scheme-less), not `url`,
        and serp-discover has already migrated to JSON-RPC `api.moz.com/jsonrpc`.
        `identify_target` below therefore accepts either key and matches
        scheme-insensitively, and the caller logs "Moz returned N metrics for M URLs"
        so a shape mismatch shows up as 0-of-M on the next live run rather than as a
        silent map of one arbitrary URL. See docs/TEST_RUN_CHECKLIST.md §1.
        """
        if not urls:
            return []
        url = f"{self.base_url}/url_metrics"
        headers = {
            "Authorization": f"Basic {self.token}",
            "Content-Type": "application/json"
        }
        payload = {"targets": urls}

        response, error = post_with_retries(
            url, "Moz url_metrics", headers=headers, json=payload)
        if response is None:
            # If 401, maybe token is not base64 encoded or is invalid
            raise Exception(f"Moz API error: {error}")

        return response.json().get('results', [])


def identify_target(result: Dict[str, Any]) -> Optional[str]:
    """The URL a Moz url-metrics object is about: `url`, or `page` (C-C-04)."""
    return result.get('url') or result.get('page')


def _strip_scheme(url: Any) -> str:
    text = str(url or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.rstrip("/")


def domain_authority_map(results: List[Dict[str, Any]],
                         requested_urls: List[str]) -> Dict[str, float]:
    """{requested url: DOMAIN authority} from the same url_metrics response.

    C-M-09: the barbell's authority axis and the feasibility table both called their
    competitor figure "DA" while it was the average Moz PAGE Authority of the sampled
    URLs, compared against a real Domain Authority for the client. Moz's url_metrics
    returns both per target, so the domain figure is available from the call already
    being made — it just has to be read. Absent is ABSENT (C-C-03): a missing
    `domain_authority` is never backfilled from `page_authority`, because conflating
    the two is the finding.
    """
    return _metric_map(results, requested_urls, ("domain_authority", "da"))


def page_authority_map(results: List[Dict[str, Any]],
                       requested_urls: List[str]) -> Dict[str, float]:
    """{requested url: page authority} for the results Moz actually returned.

    Matched scheme-insensitively and without a trailing slash, because Moz echoes the
    target in its own normalised form. A URL Moz had no record for is ABSENT from the
    map — not present with 0 — so the caller cannot mistake "no record" for "authority
    zero" and report a -35 authority drop (C-C-03).
    """
    return _metric_map(results, requested_urls, ("page_authority", "pa"))


def _metric_map(results: List[Dict[str, Any]], requested_urls: List[str],
                keys: Tuple[str, ...]) -> Dict[str, float]:
    """{requested url: the first of `keys` the result carries}, matched on target."""
    by_target = {}
    for result in results or []:
        target = identify_target(result)
        if not target:
            continue
        value = next((result.get(key) for key in keys
                      if result.get(key) is not None), None)
        if value is None:
            continue
        by_target[_strip_scheme(target)] = float(value)
    out: Dict[str, float] = {}
    for requested in requested_urls or []:
        value = by_target.get(_strip_scheme(requested))
        if value is not None:
            out[requested] = value
    return out
