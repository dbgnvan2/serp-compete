"""Fragility list: competitor pages with traffic and no systemic depth.

Purpose: find the pages worth reframing — they rank, they draw traffic, and
         they carry no Bowen systemic language at all.
Spec:    compete-spec.md#C3 ("Fragility list" → `infil_report.md`)
Tests:   Serp-compete/tests/test_infiltrator.py

Standalone: run it directly with domains as arguments. It is not part of
`run_audit`, and it makes live DataForSEO calls plus one scrape per page.

    python3 Serp-compete/src/infiltrator.py jerichocounselling.com

What this module got wrong until 2026-11-16, when it was first given tests
(coverage had it at 0%, and `compete-spec.md` lists it as a live
implementation):

* **It scored pages it had not read.** `scrape_content` returns a `ScrapedPage`
  dataclass, and the guard was `if not content:` — a dataclass instance with no
  `__bool__` is always truthy, so a page whose fetch was blocked or errored
  passed straight through and had its 403 body counted as content. `main.py`
  branches on `extraction_status`; this did not (C-C-09 / D-C-20).
* **It read unmeasured traffic as low traffic.** `est_traffic` fell back to 0
  and 0 was then compared with `> 500`, so a page whose traffic DataForSEO did
  not report was silently classified "Standard" — not fragile. "We did not
  measure it" and "it has little traffic" are different facts (H2).
* **Its threshold was a literal.** `est_traffic > 500` is editorial and now
  lives in `shared_config.json → infiltrator.fragility_min_traffic`.
* **It reported no coverage.** A run where every scrape was blocked produced an
  empty table that looked exactly like a run where no page was fragile (P2).
"""
from __future__ import annotations

import datetime
import sys
from typing import Any, Dict, List, Optional, Tuple

#: Minimum estimated monthly visits before a systems-free page is "fragile".
#: Editorial and uncalibrated; `shared_config.json → infiltrator` overrides.
DEFAULT_FRAGILITY_MIN_TRAFFIC = 500

#: How many of a domain's top pages to look at.
DEFAULT_PAGE_LIMIT = 20

HIGH_FRAGILITY = "**High Fragility**"
STANDARD = "Standard"
#: A page that cannot be classified either way, because its traffic was never
#: measured. Deliberately not `Standard`.
TRAFFIC_UNMEASURED = "Traffic not measured"


def _config() -> Dict[str, Any]:
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return {}
    try:
        return (load_shared_config().get("infiltrator") or {})
    except Exception:  # noqa: BLE001 - never block the tool on a config read
        return {}


def fragility_min_traffic() -> float:
    try:
        return float(_config().get("fragility_min_traffic",
                                   DEFAULT_FRAGILITY_MIN_TRAFFIC))
    except (TypeError, ValueError):
        return float(DEFAULT_FRAGILITY_MIN_TRAFFIC)


def page_traffic(page: Dict[str, Any]) -> Optional[float]:
    """Estimated monthly visits for a DataForSEO top-pages entry, or None.

    None, not 0: a page whose traffic the provider did not report has not been
    measured at 0 visits, and the fragility test must not read it as a quiet
    page (H2 / C-C-11).
    """
    organic = ((page.get("metrics") or {}).get("organic") or {})
    for candidate in (organic.get("etv"),
                      ((page.get("keyword_data") or {})
                       .get("keyword_info") or {}).get("search_volume")):
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def classify_fragility(traffic: Optional[float], systems_score: Optional[float],
                       threshold: Optional[float] = None) -> str:
    """Fragility for one page, with "could not tell" as a real answer."""
    if threshold is None:
        threshold = fragility_min_traffic()
    if traffic is None:
        return TRAFFIC_UNMEASURED
    if systems_score is None:
        return TRAFFIC_UNMEASURED
    if traffic > threshold and systems_score == 0:
        return HIGH_FRAGILITY
    return STANDARD


def _readable(page) -> bool:
    """Did the scrape actually return content?

    `ScrapedPage` is a dataclass, so `if not page` is ALWAYS False — which is
    how a blocked page's 403 body came to be scored as prose. An object without
    `extraction_status` (an older stub, or a plain string) is accepted, since
    that is what the pre-dataclass contract was.
    """
    if page is None:
        return False
    status = getattr(page, "extraction_status", None)
    if status is None:
        return bool(page)
    return status in ("complete", "partial")


class Infiltrator:
    def __init__(self, auditor=None, dfs_client=None,
                 shared_config_path: str = None):
        """Clients are injectable so this can be exercised without network.

        They default to the real ones, so the command line is unchanged.
        """
        if auditor is None:
            from src.semantic import SemanticAuditor
            auditor = SemanticAuditor()
        if dfs_client is None:
            from src.api_clients import DataForSEOClient
            dfs_client = DataForSEOClient()
        self.auditor = auditor
        self.dfs_client = dfs_client

    def collect(self, domains: List[str], limit: int = DEFAULT_PAGE_LIMIT
                ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """`(rows, coverage)` for these domains. Makes the calls; renders nothing."""
        threshold = fragility_min_traffic()
        rows: List[Dict[str, Any]] = []
        coverage = {"pages_seen": 0, "scored": 0, "unreadable": 0,
                    "no_url": 0, "traffic_unmeasured": 0, "domains": len(domains)}

        for domain in domains:
            print(f"🕵️ Infiltrating {domain}...")
            top_pages = self.dfs_client.get_top_pages(domain, limit=limit) or []
            for page in top_pages:
                coverage["pages_seen"] += 1
                url = page.get("url")
                traffic = page_traffic(page)
                if not url:
                    coverage["no_url"] += 1
                    print(f"    ⚠️ Missing URL for an entry with traffic "
                          f"{'unmeasured' if traffic is None else f'{traffic:.0f}'}")
                    continue

                shown = "unmeasured" if traffic is None else f"{traffic:.0f}"
                print(f"  Scrutinizing {url} (Est. Traffic: {shown})...")
                content = self.auditor.scrape_content(url)
                if not _readable(content):
                    status = getattr(content, "extraction_status", "no content")
                    coverage["unreadable"] += 1
                    print(f"    ⚠️ Not scored — scrape returned {status}: {url}")
                    continue

                scores = self.auditor.analyze_text(content) or {}
                systems_score = scores.get("systems_score")
                fragility = classify_fragility(traffic, systems_score, threshold)
                if fragility == TRAFFIC_UNMEASURED:
                    coverage["traffic_unmeasured"] += 1
                coverage["scored"] += 1
                rows.append({
                    "domain": domain,
                    "url": url,
                    "traffic": traffic,
                    "medical": scores.get("medical_score"),
                    "bowen": systems_score,
                    "fragility": fragility,
                })

        rows.sort(key=lambda r: (r["fragility"] == HIGH_FRAGILITY,
                                 r["traffic"] if r["traffic"] is not None else -1),
                  reverse=True)
        return rows, coverage

    def run_infiltration(self, domains: List[str],
                         output_path: str = "infil_report.md") -> str:
        """Collect, render, write. Returns the markdown.

        `compete-spec.md`#C3 documents this entry point by name, so it stays a
        method; `run_infiltration` at module level is the same thing for a
        caller that does not want to build the object first.
        """
        rows, coverage = self.collect(domains)
        markdown = render(rows, coverage)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"✅ Infiltration complete. Report saved to: {output_path}")
        return markdown


def render(rows: List[Dict[str, Any]], coverage: Dict[str, int],
           threshold: Optional[float] = None) -> str:
    """The markdown report. Pure, so its wording is testable."""
    if threshold is None:
        threshold = fragility_min_traffic()
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Infiltrator Report: Strategic Content Targets",
        f"Generated on: {generated}",
        "",
        f"Competitor pages with more than {threshold:.0f} estimated monthly "
        f"visits and a Bowen systems score of 0 — traffic with no systemic "
        f"framing. The threshold is "
        f"`infiltrator.fragility_min_traffic`: editorial and uncalibrated.",
    ]

    # Coverage first, so an empty table can never read as "nothing is fragile".
    lines.append(
        f"\n**Coverage:** scored {coverage.get('scored', 0)} of "
        f"{coverage.get('pages_seen', 0)} page(s) across "
        f"{coverage.get('domains', 0)} domain(s)."
        + (f" {coverage['unreadable']} could not be read (blocked or errored) "
           f"and were NOT scored." if coverage.get("unreadable") else "")
        + (f" {coverage['no_url']} entr(ies) carried no URL."
           if coverage.get("no_url") else "")
        + (f" {coverage['traffic_unmeasured']} page(s) had no traffic figure, "
           f"so they are listed as '{TRAFFIC_UNMEASURED}' rather than as not "
           f"fragile." if coverage.get("traffic_unmeasured") else ""))
    if coverage.get("unreadable") or coverage.get("traffic_unmeasured"):
        lines.append(
            "_An absent page is not a page without fragility — it is a page "
            "this run could not judge._")

    lines += [
        "",
        "| Domain | URL | Est. Traffic | Medical Score | Bowen Score | Fragility |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in rows:
        traffic = ("—" if row["traffic"] is None else f"{row['traffic']:.0f}")
        medical = "—" if row["medical"] is None else row["medical"]
        bowen = "—" if row["bowen"] is None else row["bowen"]
        lines.append(f"| {row['domain']} | {row['url']} | {traffic} | "
                     f"{medical} | {bowen} | {row['fragility']} |")
    if not rows:
        lines.append("")
        lines.append("_No page was scored this run — see the coverage line above._"
                     if not coverage.get("scored") else
                     "_No page met the fragility definition this run._")
    return "\n".join(lines)


def run_infiltration(domains: List[str], output_path: str = "infil_report.md",
                     infiltrator: Optional[Infiltrator] = None) -> str:
    """Module-level convenience wrapper around `Infiltrator.run_infiltration`."""
    return (infiltrator or Infiltrator()).run_infiltration(domains, output_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_infiltration(sys.argv[1:])
    else:
        print("Usage: python3 Serp-compete/src/infiltrator.py <domain> [domain …]")
        print("\nNo domains were given. This used to default to two hard-coded "
              "competitor domains, which spent DataForSEO credits and scraped "
              "two real sites for anyone who ran it to see what it did.")
        sys.exit(2)
