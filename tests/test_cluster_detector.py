"""
Tests for Gap 4 — Internal linking cluster detection.

Covers all four cluster_signal values:
  - insufficient_data (< 3 pages)
  - isolated         (3+ pages, no inter-page links)
  - linked           (inter-page links exist, no hub)
  - clustered        (at least one page with in-degree >= threshold)
"""

import sys
import json
import pytest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "Serp-compete"))

from src.cluster_detector import ClusterDetector, ClusterResult, RESOLUTION_CAVEAT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_config():
    config_path = Path(__file__).parent.parent / "shared_config.json"
    with open(config_path) as f:
        return json.load(f)


@pytest.fixture
def detector(sample_config):
    return ClusterDetector(sample_config)


def make_page(url, internal_links=None, extraction_status="complete"):
    """Build a SimpleNamespace mimicking ScrapedPage for cluster tests."""
    return SimpleNamespace(
        url=url,
        extraction_status=extraction_status,
        metadata={"internal_links": internal_links or []},
    )


# Convenience: 3-page set with a defined link topology
DOMAIN = "example.com"
PAGE_A = "https://example.com/page-a"
PAGE_B = "https://example.com/page-b"
PAGE_C = "https://example.com/page-c"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestClusterDetectorInit:

    def test_loads_hub_threshold(self, detector):
        assert detector.hub_in_degree_threshold == 2

    def test_loads_min_pages(self, detector):
        assert detector.min_pages_for_signal == 3

    def test_custom_thresholds(self, sample_config):
        import copy
        cfg = copy.deepcopy(sample_config)
        cfg["cluster_thresholds"] = {"hub_in_degree_threshold": 3, "min_pages_for_signal": 4}
        d = ClusterDetector(cfg)
        assert d.hub_in_degree_threshold == 3
        assert d.min_pages_for_signal == 4

    def test_empty_config_uses_defaults(self):
        d = ClusterDetector({})
        assert d.hub_in_degree_threshold == 2
        assert d.min_pages_for_signal == 3


# ---------------------------------------------------------------------------
# insufficient_data  (< min_pages_for_signal)
# ---------------------------------------------------------------------------

class TestInsufficientData:

    def test_zero_pages(self, detector):
        result = detector.analyze_domain(DOMAIN, [])
        assert result.cluster_signal == "insufficient_data"

    def test_one_page(self, detector):
        result = detector.analyze_domain(DOMAIN, [make_page(PAGE_A)])
        assert result.cluster_signal == "insufficient_data"

    def test_two_pages(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "insufficient_data"

    def test_two_pages_pages_analyzed(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.pages_analyzed == 2

    def test_insufficient_data_empty_graph(self, detector):
        result = detector.analyze_domain(DOMAIN, [make_page(PAGE_A)])
        assert result.internal_link_graph == {}
        assert result.hub_candidates == []

    def test_insufficient_data_has_resolution_caveat(self, detector):
        result = detector.analyze_domain(DOMAIN, [make_page(PAGE_A)])
        assert "Low resolution" in result.resolution_caveat

    def test_blocked_pages_excluded_from_count(self, detector):
        # 3 pages, but 2 blocked → only 1 usable → insufficient_data
        pages = [
            make_page(PAGE_A, extraction_status="complete"),
            make_page(PAGE_B, extraction_status="blocked"),
            make_page(PAGE_C, extraction_status="error"),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "insufficient_data"
        assert result.pages_analyzed == 1

    def test_returns_cluster_result(self, detector):
        result = detector.analyze_domain(DOMAIN, [])
        assert isinstance(result, ClusterResult)


# ---------------------------------------------------------------------------
# isolated  (3+ pages, no inter-page links)
# ---------------------------------------------------------------------------

class TestIsolated:

    def test_three_pages_no_links(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "isolated"

    def test_isolated_pages_analyzed(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.pages_analyzed == 3

    def test_isolated_graph_has_zero_degrees(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        for url, node in result.internal_link_graph.items():
            assert node["in_degree"] == 0
            assert node["out_degree"] == 0

    def test_isolated_no_hub_candidates(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.hub_candidates == []

    def test_links_to_external_domains_do_not_create_edges(self, detector):
        # Page A links to external.com — should not affect cluster signal
        pages = [
            make_page(PAGE_A, internal_links=["https://external.com/page"]),
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "isolated"

    def test_self_links_ignored(self, detector):
        # Page A links to itself — should not create an edge
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_A]),
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "isolated"


# ---------------------------------------------------------------------------
# linked  (inter-page links exist, no hub)
# ---------------------------------------------------------------------------

class TestLinked:

    def test_one_directional_link(self, detector):
        # A → B, but B has in_degree=1 which is below default threshold of 2
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "linked"

    def test_linked_edges_recorded(self, detector):
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        norm_a = detector._normalise(PAGE_A)
        norm_b = detector._normalise(PAGE_B)
        assert result.internal_link_graph[norm_a]["out_degree"] == 1
        assert result.internal_link_graph[norm_b]["in_degree"] == 1

    def test_linked_no_hub_candidates(self, detector):
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.hub_candidates == []

    def test_bidirectional_links_not_hub(self, detector):
        # A → B and C → A — each page has in_degree=1, below threshold
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C, internal_links=[PAGE_A]),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "linked"


# ---------------------------------------------------------------------------
# clustered  (at least one hub with in_degree >= threshold)
# ---------------------------------------------------------------------------

class TestClustered:

    def test_two_pages_link_to_hub(self, detector):
        # A and C both link to B → B has in_degree=2 = threshold
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C, internal_links=[PAGE_B]),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.cluster_signal == "clustered"

    def test_hub_candidate_identified(self, detector):
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C, internal_links=[PAGE_B]),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        norm_b = detector._normalise(PAGE_B)
        assert norm_b in result.hub_candidates

    def test_hub_in_degree_correct(self, detector):
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C, internal_links=[PAGE_B]),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        norm_b = detector._normalise(PAGE_B)
        assert result.internal_link_graph[norm_b]["in_degree"] == 2

    def test_duplicate_links_counted_once(self, detector):
        # A links to B twice in the raw list — should only count once
        pages = [
            make_page(PAGE_A, internal_links=[PAGE_B, PAGE_B]),
            make_page(PAGE_B),
            make_page(PAGE_C, internal_links=[PAGE_B]),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        norm_b = detector._normalise(PAGE_B)
        assert result.internal_link_graph[norm_b]["in_degree"] == 2  # from A and C, not duplicated A


# ---------------------------------------------------------------------------
# Output shape and serialisation
# ---------------------------------------------------------------------------

class TestOutputShape:

    def test_to_dict_json_serialisable(self, detector):
        pages = [make_page(PAGE_A, internal_links=[PAGE_B]), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        d = result.to_dict()
        json.dumps(d)  # raises if not serialisable

    def test_to_dict_has_required_keys(self, detector):
        result = detector.analyze_domain(DOMAIN, [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)])
        d = result.to_dict()
        for key in ("domain", "pages_analyzed", "internal_link_graph", "hub_candidates",
                    "cluster_signal", "resolution_caveat"):
            assert key in d

    def test_domain_preserved(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert result.domain == DOMAIN

    def test_resolution_caveat_mentions_n(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        assert "N=3" in result.resolution_caveat

    def test_each_graph_node_has_required_fields(self, detector):
        pages = [make_page(PAGE_A), make_page(PAGE_B), make_page(PAGE_C)]
        result = detector.analyze_domain(DOMAIN, pages)
        for url, node in result.internal_link_graph.items():
            for field in ("out_links_to_domain", "in_links_from_domain", "in_degree", "out_degree"):
                assert field in node, f"Node {url} missing field {field}"


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

class TestURLNormalisation:

    def test_trailing_slash_stripped(self, detector):
        assert detector._normalise("https://example.com/page/") == detector._normalise("https://example.com/page")

    def test_fragment_stripped(self, detector):
        assert detector._normalise("https://example.com/page#section") == detector._normalise("https://example.com/page")

    def test_root_path_preserved(self, detector):
        norm = detector._normalise("https://example.com/")
        assert norm == "https://example.com/"

    def test_relative_links_resolved(self, detector):
        # A relative internal link should be resolved against the page URL and matched
        pages = [
            make_page(PAGE_A, internal_links=["/page-b"]),  # relative URL
            make_page(PAGE_B),
            make_page(PAGE_C),
        ]
        result = detector.analyze_domain(DOMAIN, pages)
        norm_b = detector._normalise(PAGE_B)
        assert result.internal_link_graph[norm_b]["in_degree"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
