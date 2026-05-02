"""
Gap 4 — Internal linking cluster detection.

Builds a directed graph of internal links across the pages scraped for a single
competitor domain, identifies hub candidates, and emits a cluster signal.

IMPORTANT CAVEAT: Cluster detection runs only on the pages this audit scraped
(typically 3 per competitor). It cannot see the wider site structure. A domain
marked 'isolated' may still have a strong internal-link cluster invisible to
this audit. Treat the signal as suggestive, not decisive.

A full internal-linking audit would require crawling the domain or a third-party
API (Ahrefs, Moz). Both are out of scope for this iteration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any
from urllib.parse import urlparse, urlunparse, urljoin

RESOLUTION_CAVEAT = (
    "Cluster detection runs only on the pages this audit scraped (typically 3 per "
    "competitor). It cannot see the wider site structure. A domain marked 'isolated' "
    "may still have a strong internal-link cluster invisible to this audit. Treat the "
    "signal as suggestive, not decisive."
)


@dataclass
class ClusterResult:
    """Per-domain internal link cluster analysis."""
    domain: str
    pages_analyzed: int
    internal_link_graph: Dict[str, Any]
    hub_candidates: List[str]
    cluster_signal: str  # "isolated" | "linked" | "clustered" | "insufficient_data"
    resolution_caveat: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "pages_analyzed": self.pages_analyzed,
            "internal_link_graph": self.internal_link_graph,
            "hub_candidates": self.hub_candidates,
            "cluster_signal": self.cluster_signal,
            "resolution_caveat": self.resolution_caveat,
        }


class ClusterDetector:
    """Detect internal linking patterns across scraped pages for a competitor domain."""

    def __init__(self, config: Dict[str, Any]):
        thresholds = config.get("cluster_thresholds", {})
        self.hub_in_degree_threshold = thresholds.get("hub_in_degree_threshold", 2)
        self.min_pages_for_signal = thresholds.get("min_pages_for_signal", 3)

    def analyze_domain(self, domain: str, pages: List[Any]) -> ClusterResult:
        """
        Analyse internal linking across scraped pages for one domain.

        Args:
            domain: Competitor domain string (e.g. "example.com")
            pages:  List of ScrapedPage-compatible objects with .url,
                    .extraction_status, and .metadata["internal_links"]

        Returns:
            ClusterResult with graph, hub candidates, and cluster signal.
        """
        usable = [
            p for p in pages
            if p.extraction_status in ("complete", "partial")
        ]
        n = len(usable)

        if n < self.min_pages_for_signal:
            return ClusterResult(
                domain=domain,
                pages_analyzed=n,
                internal_link_graph={},
                hub_candidates=[],
                cluster_signal="insufficient_data",
                resolution_caveat=f"Based on N={n} scraped pages. Low resolution.",
            )

        # Normalise each scraped page URL → canonical key
        scraped_norm = {self._normalise(p.url): p for p in usable}
        scraped_urls = set(scraped_norm.keys())

        # Seed graph with all scraped nodes
        graph: Dict[str, Dict[str, Any]] = {
            url: {"out_links_to_domain": [], "in_links_from_domain": [], "in_degree": 0, "out_degree": 0}
            for url in scraped_urls
        }

        # Walk each page's internal_links and record edges between scraped nodes
        for page in usable:
            src = self._normalise(page.url)
            for raw_link in page.metadata.get("internal_links", []):
                resolved = urljoin(page.url, raw_link)
                dst = self._normalise(resolved)
                if dst in scraped_urls and dst != src:
                    if dst not in graph[src]["out_links_to_domain"]:
                        graph[src]["out_links_to_domain"].append(dst)
                    if src not in graph[dst]["in_links_from_domain"]:
                        graph[dst]["in_links_from_domain"].append(src)

        # Compute degrees
        for node in graph.values():
            node["out_degree"] = len(node["out_links_to_domain"])
            node["in_degree"] = len(node["in_links_from_domain"])

        hub_candidates = [
            url for url, node in graph.items()
            if node["in_degree"] >= self.hub_in_degree_threshold
        ]

        total_edges = sum(node["out_degree"] for node in graph.values())
        if total_edges == 0:
            signal = "isolated"
        elif hub_candidates:
            signal = "clustered"
        else:
            signal = "linked"

        return ClusterResult(
            domain=domain,
            pages_analyzed=n,
            internal_link_graph=graph,
            hub_candidates=hub_candidates,
            cluster_signal=signal,
            resolution_caveat=f"Based on N={n} scraped pages. Low resolution.",
        )

    def _normalise(self, url: str) -> str:
        """Strip fragment, normalise trailing slash for URL comparison."""
        p = urlparse(url)
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme, p.netloc, path, p.params, p.query, ""))
