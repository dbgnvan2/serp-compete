"""Keyword-gap miner: what the top competitors rank for and we do not.

Spec:  compete-spec.md#C3 → `competitor_keyword_gap.md`
Tests: Serp-compete/tests/test_competitor_mining.py

Standalone. It bills DataForSEO per competitor, so it is not on the audit path.

Fixed 2026-11-16, after coverage put this module at 19% and the two other
standalone tools (`strike_mapper`, `infiltrator`) were each found carrying real
defects:

* **It mined run 4 forever.** `AUDIT_XLSX` hard-coded
  `audit_results_run_4.xlsx`, so an owner who had since done eleven more audits
  was ranking competitors from the fourth. There is no such workbook in the repo
  now, so the tool printed "Error: … not found" and produced an EMPTY gap report
  that looked like a finding.
* **Its "already have this keyword" filter could not fire.** `KEYWORDS_CSV`
  points into `serp-keyword/`, which is gitignored and absent, so
  `load_existing_keywords` returned an empty set and every keyword read as a
  gap. The report then listed "Filters Applied: … Target CSV: …" naming a file
  it had never opened.
* **It had its own raw `requests.post`** to the same `ranked_keywords/live`
  endpoint `DataForSEOClient` already calls — no timeout, no retry, unguarded
  `['tasks'][0]['result'][0]` indexing, and a second copy of the payload to
  drift from the first (C-C-12).
* **Its brand filter was a substring test** (`if brand in kw_lower`), the exact
  thing `audit_universe.contains_brand_token` was written for in C1: a short
  stem matches inside unrelated words.
* **`volume < 10` and `limit: 100` were literals** (P4).
"""
import csv
import glob
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

try:  # importable as a submodule: `from src.competitor_mining import derive_brand_name`
    from src.api_clients import DataForSEOClient
    from src.reframe_engine import ReframeEngine
    from src.brand_utils import derive_brand_name
    from src.briefing_messages import Messages
except ImportError:  # run standalone: `python3 src/competitor_mining.py` (src/ is on sys.path)
    from api_clients import DataForSEOClient
    from reframe_engine import ReframeEngine
    from brand_utils import derive_brand_name
    from briefing_messages import Messages

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
#: Where audit workbooks land. The LATEST is mined, not a pinned run number.
AUDIT_XLSX_GLOB = os.path.join(ROOT_DIR, "Serp-compete", "audit_results_run_*.xlsx")
KEYWORDS_CSV = os.path.join(ROOT_DIR, "serp-keyword", "keywords_Couple_Marriage_RelationshipLocal.csv")
OUTPUT_MD = os.path.join(ROOT_DIR, "competitor_keyword_gap.md")

#: Fallbacks; `shared_config.json → competitor_mining` is the source of record.
DEFAULT_MIN_SEARCH_VOLUME = 10
DEFAULT_KEYWORDS_PER_DOMAIN = 100
DEFAULT_TOP_DOMAINS_LIMIT = 5


def _config() -> Dict[str, Any]:
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return {}
    try:
        return (load_shared_config().get("competitor_mining") or {})
    except Exception:  # noqa: BLE001
        return {}


def min_search_volume() -> int:
    try:
        return int(_config().get("min_search_volume", DEFAULT_MIN_SEARCH_VOLUME))
    except (TypeError, ValueError):
        return DEFAULT_MIN_SEARCH_VOLUME


def keywords_per_domain() -> int:
    try:
        return int(_config().get("keywords_per_domain",
                                 DEFAULT_KEYWORDS_PER_DOMAIN))
    except (TypeError, ValueError):
        return DEFAULT_KEYWORDS_PER_DOMAIN


def top_domains_limit() -> int:
    try:
        return int(_config().get("top_domains_limit", DEFAULT_TOP_DOMAINS_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_TOP_DOMAINS_LIMIT


def _configured_path(key: str, fallback: str) -> str:
    """A repo-relative path from config, or *fallback*."""
    value = str(_config().get(key) or "").strip()
    if not value:
        return fallback
    return value if os.path.isabs(value) else os.path.join(ROOT_DIR, value)


def latest_audit_workbook(pattern: str = None) -> Optional[str]:
    """The newest `audit_results_run_N.xlsx`, by run number.

    By run NUMBER, not mtime: a re-saved older workbook must not become "the
    latest audit". Returns None when there is none, so the caller can say that
    rather than mine an empty frame.
    """
    matches = glob.glob(pattern or AUDIT_XLSX_GLOB)
    if not matches:
        return None

    def _run_number(path):
        found = re.search(r"audit_results_run_(\d+)\.xlsx$", os.path.basename(path))
        return int(found.group(1)) if found else -1

    return max(matches, key=_run_number)

def load_existing_keywords(path: str) -> Tuple[Set[str], bool]:
    """`(keywords, found)` — the keywords we already target.

    `found` matters more than the set: the file this points at lives in
    `serp-keyword/`, which is gitignored and absent here, so the gap filter
    silently never fired and every competitor keyword read as a gap. An empty
    set and a missing file must not look the same to the caller (P2).
    """
    keywords: Set[str] = set()
    if not os.path.exists(path):
        return keywords, False
    try:
        with open(path, mode='r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if row and row[0].strip():
                    keywords.add(row[0].strip().lower())
    except OSError as exc:
        print(f"⚠️ Could not read {path}: {exc}")
        return keywords, False
    return keywords, True

def get_top_domains(path: Optional[str] = None, limit: int = 5) -> List[str]:
    """The widest-ranking domains in an audit workbook.

    `path` defaults to the LATEST workbook. It used to default to a pinned
    `audit_results_run_4.xlsx`, so eleven audits later the tool was still
    ranking competitors from the fourth run — and with no such file in the repo
    it printed an error and returned [], producing an empty gap report that
    read like a finding.
    """
    if path is None:
        path = latest_audit_workbook()
        if path is None:
            print(f"❌ No audit workbook found matching {AUDIT_XLSX_GLOB}.")
            print("   Run an audit first — there is nothing to mine, which is "
                  "NOT the same as there being no keyword gaps.")
            return []
        print(f"📘 Mining the latest audit workbook: {os.path.basename(path)}")
    if not os.path.exists(path):
        print(f"Error: {path} not found.")
        return []
    df = pd.read_excel(path)
    # C-C-02: the column is `sampled_keywords` since 2026-11-15 — the distinct
    # keywords a run audited for the domain. It used to be `total_keywords`, inflated
    # by a cross join (keywords × audited pages), which is what this sort read. The
    # old name is still accepted so an older workbook can be mined, but note that
    # sorting a pre-2026-11-15 workbook by it ranks by pages audited as much as by
    # breadth.
    for column in ('sampled_keywords', 'total_keywords'):
        if column in df.columns:
            df = df.sort_values(by=column, ascending=False)
            break
    return df['domain'].head(limit).tolist()

def contains_numbers(text: str) -> bool:
    return bool(re.search(r'\d', text))


def _is_brand_keyword(keyword: str, brand: str) -> bool:
    """Does *keyword* carry the competitor's own brand token?

    Delegates to the one canonical matcher so this tool and the audit agree.
    Falls back to a word-boundary regex when `audit_universe` is unavailable
    (the standalone path) — never to a substring test.
    """
    if not brand or len(brand) < 2:
        return False
    try:
        from src.audit_universe import contains_brand_token
        return contains_brand_token(keyword, brand)
    except ImportError:  # pragma: no cover - standalone use
        return bool(re.search(rf"\b{re.escape(brand)}\b", keyword))

def main(client=None, engine=None, keywords_csv: str = None,
         workbook: str = None, output_md: str = None):
    print("🚀 Starting Refined Competitor Keyword Mining (Module I)...")
    # Read before any provider call: an absent or unparseable messages file
    # stops the run here rather than after a paid DataForSEO pass, and the two
    # filter warnings this report carries are the reason it must not degrade.
    messages = Messages()
    per_domain = keywords_per_domain()
    min_volume = min_search_volume()
    keywords_csv = keywords_csv or _configured_path(
        "existing_keywords_csv", KEYWORDS_CSV)
    output_md = output_md or _configured_path("output_markdown", OUTPUT_MD)

    # 1. Load existing keywords for gap analysis
    existing_keywords, csv_found = load_existing_keywords(keywords_csv)
    if csv_found:
        print(f"Loaded {len(existing_keywords)} existing keywords from "
              f"{os.path.basename(keywords_csv)}.")
    else:
        print(f"⚠️ The existing-keyword list was NOT found "
              f"({keywords_csv}).")
        print("   The 'we already target this' filter is therefore NOT applied: "
              "every competitor keyword below will read as a gap, including the "
              "ones already on the plan.")

    # 2. Get top domains
    # `audit_xlsx_path` is the spec's key, honoured as an OVERRIDE; empty means
    # "the latest workbook", which is what the spec's pinned run 4 could not do.
    workbook = workbook or (_configured_path("audit_xlsx_path", "") or None)
    top_domains = get_top_domains(workbook, limit=top_domains_limit())
    print(f"Top domains for mining: {top_domains}")

    client = client or DataForSEOClient()
    engine = engine or ReframeEngine()

    all_new_opportunities = []
    failed_domains: List[Tuple[str, str]] = []

    for domain in top_domains:
        brand = derive_brand_name(domain)
        print(f"Fetching top {per_domain} keywords for: {domain} (Brand: {brand})...")
        
        # The hardened client, not a second raw `requests.post` to the same
        # endpoint: this path had no timeout, no retry, unguarded
        # `['tasks'][0]['result'][0]` indexing (a 200 with an empty result
        # raised IndexError and was reported as "Request failed", conflating a
        # response-shape change with a network failure), and its own copy of
        # the payload to drift from the client's (C-C-12).
        items = client.get_relevant_pages(domain, limit=per_domain)
        if client.last_error:
            print(f"   ⚠️ {domain}: {client.last_error} — its keywords are "
                  f"UNMEASURED this run, not absent.")
            failed_domains.append((domain, client.last_error))

        count = 0
        unmeasured_volume = 0
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
            # 3. Skip the competitor's own brand — on WORD BOUNDARIES, and
            # only for a brand token long enough to mean something. `if brand
            # in kw_lower` dropped any keyword containing the stem as a
            # substring, which is what audit_universe.contains_brand_token was
            # written for in C1 (`m.yelp.com` derives the token "m").
            if _is_brand_keyword(kw_lower, brand):
                continue

            # VOLUME CHECK:
            # Structure observed in raw response: keyword_data -> keyword_info -> search_volume
            kinfo = kdata.get('keyword_info', {})
            volume = kinfo.get('search_volume')
            if volume is None:
                # Unmeasured, not low. The old code defaulted to 0 and then
                # compared `< 10`, so a keyword whose volume DataForSEO did not
                # report was dropped as too small (H2).
                unmeasured_volume += 1
                continue
            if volume < min_volume:
                continue
            
            # REFRAME:
            reframe = engine.clinical_pivot(kw)
            
            # Better reframe placeholder logic if clinical_pivot returns original kw
            if reframe == kw:
                reframe = messages.get("mining_report.reframe_placeholder",
                                       keyword=kw.title())
            
            all_new_opportunities.append({
                "domain": domain,
                "keyword": kw,
                "reframe": reframe,
                "etv": volume
            })
            count += 1
        
        print(f"Found {count} qualified new keywords for {domain}."
              + (f" {unmeasured_volume} dropped for want of a volume figure "
                 f"(unmeasured, not small)." if unmeasured_volume else ""))

    # 3. Output to Markdown
    #
    # Every sentence below comes from `briefing_messages.json`
    # (`mining_report.*`). The filter list is this report's own account of what
    # it applied, and the two warnings on it are the hedges that stop a reader
    # taking the table as a complete set of gaps — editorial, and the owner is
    # who would reword them (review chunk Y17, cold review M8).
    report = [
        messages.get("mining_report.title"),
        messages.get("mining_report.generated_on",
                     timestamp=pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')),
        messages.get("mining_report.gap_summary_heading"),
        messages.get("mining_report.mined", domains=len(top_domains)),
        messages.get("mining_report.filters_heading"),
        messages.get("mining_report.filter_depth", per_domain=per_domain),
        messages.get("mining_report.filter_numbers"),
        messages.get("mining_report.filter_brand"),
        messages.get("mining_report.filter_volume", min_volume=min_volume),
        (messages.get("mining_report.filter_targeted_applied",
                      filename=os.path.basename(keywords_csv),
                      count=len(existing_keywords))
         if csv_found else
         messages.get("mining_report.filter_targeted_missing",
                      filename=os.path.basename(keywords_csv))),
    ]
    if failed_domains:
        report.append(messages.get(
            "mining_report.unmeasured",
            items="; ".join(
                messages.get("mining_report.unmeasured_item",
                             domain=domain, reason=reason)
                for domain, reason in failed_domains)))
    report += [
        messages.get("mining_report.table_header"),
        messages.get("mining_report.table_rule"),
    ]

    # Sort opportunities by volume descending
    all_new_opportunities.sort(key=lambda x: x['etv'], reverse=True)

    for opt in all_new_opportunities:
        report.append(messages.get("mining_report.row",
                                   domain=opt['domain'],
                                   keyword=opt['keyword'],
                                   reframe=opt['reframe'],
                                   volume=opt['etv']))

    if not all_new_opportunities:
        report.append("")
        report.append(
            messages.get("mining_report.empty_no_domains") if not top_domains
            else messages.get("mining_report.empty_no_keywords"))

    with open(output_md, "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(messages.get("mining_report.written", path=output_md))
    return "\n".join(report)

if __name__ == "__main__":
    main()
