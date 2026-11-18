import pytest
import os
import json
import pandas as pd
from unittest.mock import MagicMock, patch
from src.gsc_performance import GSCManager

@pytest.fixture
def mock_gsc_manager(tmp_path):
    # An ISOLATED database. GSCManager() otherwise opens the one shared_config.json
    # points at — the repo's own file — so this suite wrote semantic_audits rows with
    # run_id 0 into it and then passed off its own 7-day cache on the next run. The
    # mismatch assertion below therefore depended on residue from an earlier run and
    # would fail on a blank machine, which is exactly what CI is (P8).
    from src.database import DatabaseManager
    with patch('src.gsc_performance.GSCManager._authenticate') as mock_auth:
        mock_auth.return_value = MagicMock()
        with patch('src.gsc_performance.build') as mock_build:
            manager = GSCManager()
            manager.service = MagicMock()
            manager.db = DatabaseManager(str(tmp_path / "gsc.db"))
            yield manager


def _scraped(url="https://livingsystems.ca/x", status="complete"):
    """A ScrapedPage-shaped stand-in: `analyze_gaps` branches on extraction_status
    (C-C-09), so a bare string is not a valid scrape result."""
    from src.semantic import ScrapedPage
    return ScrapedPage(url=url, fetched_at="2026-11-15T00:00:00Z",
                       http_status=200 if status == "complete" else 429,
                       extraction_status=status,
                       extraction_errors=[], outline=[], first_500_words="text",
                       full_text_word_count=1, metadata={})

def test_analyze_gaps_logic(mock_gsc_manager):
    # Mock list_sites
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://livingsystems.ca/', 'permissionLevel': 'siteOwner'}]
    }
    
    # Mock fetch_performance_data
    # dimensions: ['query', 'page']
    mock_data = [
        {'keys': ['anxiety treatment', 'https://livingsystems.ca/anxiety'], 'clicks': 5, 'impressions': 1000, 'ctr': 0.005, 'position': 12},
        {'keys': ['family therapy', 'https://livingsystems.ca/family'], 'clicks': 20, 'impressions': 100, 'ctr': 0.2, 'position': 3},
        {'keys': ['differentiation of self', 'https://livingsystems.ca/bowen'], 'clicks': 10, 'impressions': 500, 'ctr': 0.02, 'position': 15}
    ]
    
    with patch.object(mock_gsc_manager, 'fetch_performance_data', return_value=mock_data):
        # Mock SemanticAuditor.scrape_content and analyze_text
        with patch.object(mock_gsc_manager.auditor, 'scrape_content', return_value=_scraped()):
            with patch.object(mock_gsc_manager.auditor, 'analyze_text') as mock_analyze:
                # Page 1: /anxiety (Tier 1 Medical)
                # Page 2: /family (Other)
                # Page 3: /bowen (Tier 2/3 Systems)
                mock_analyze.side_effect = [
                    {'medical_score': 15, 'systems_score': 2}, # /anxiety
                    {'medical_score': 1, 'systems_score': 1},  # /family
                    {'medical_score': 2, 'systems_score': 12}  # /bowen
                ]
                
                gaps, low_hanging, mismatches = mock_gsc_manager.analyze_gaps()
                
                # Check High Imp / Low CTR Gap
                # 'anxiety treatment' has CTR 0.005 (< 0.01) and impressions 1000 (> 100)
                assert not gaps.empty
                assert 'anxiety treatment' in gaps['query'].values
                
                # Check Low-Hanging Fruit (Positions 11-20)
                # 'anxiety treatment' (12) and 'differentiation of self' (15)
                assert len(low_hanging) >= 2
                
                # Check Mismatches
                # 'differentiation of self' is Tier 2/3 (Systems)
                # Wait, the mismatch logic in gsc_performance.py is:
                # if scores['systems_score'] > 5 and get_tier(query) == "Tier 1 (Medical)":
                # Let's mock a Medical query hitting a Bowen page
                
                # Reset and re-run with a mismatch case
                mock_data_mismatch = [
                    {'keys': ['anxiety symptoms', 'https://livingsystems.ca/bowen'], 'clicks': 15, 'impressions': 200, 'ctr': 0.075, 'position': 5}
                ]
                with patch.object(mock_gsc_manager, 'fetch_performance_data', return_value=mock_data_mismatch):
                    mock_analyze.side_effect = [{'medical_score': 2, 'systems_score': 12}]
                    gaps, low_hanging, mismatches = mock_gsc_manager.analyze_gaps()
                    
                    assert len(mismatches) == 1
                    assert mismatches[0]['query'] == 'anxiety symptoms'
                    assert "Bowen page attracting Medical Model audience" in mismatches[0]['reason']

def test_get_striking_distance_keywords(mock_gsc_manager):
    # Mock performance data with positions 12, 18, and 5.
    # 'anxiety disorder symptoms' is Tier 1 (diagnostic vocabulary).
    # 'relationship help' contains 'relationship' (Tier 2).
    # 'couples therapy' is Tier 1 NO LONGER — decision 3 (2026-11-15) made "therapy"
    # neutral, so this client's own service term stops reading as the medical model.
    mock_data = [
        {'keys': ['anxiety disorder symptoms', 'url1'], 'clicks': 5, 'impressions': 1000, 'ctr': 0.005, 'position': 12},
        {'keys': ['relationship help', 'url2'], 'clicks': 2, 'impressions': 500, 'ctr': 0.004, 'position': 18},
        {'keys': ['couples therapy', 'url4'], 'clicks': 1, 'impressions': 400, 'ctr': 0.003, 'position': 14},
        {'keys': ['family therapy', 'url3'], 'clicks': 20, 'impressions': 100, 'ctr': 0.2, 'position': 5}
    ]

    with patch.object(mock_gsc_manager, 'fetch_performance_data', return_value=mock_data):
        striking = mock_gsc_manager.get_striking_distance_keywords()

        # Should only have positions 12, 18 and 14
        assert len(striking) == 3
        assert 'anxiety disorder symptoms' in striking['query'].values
        assert 'relationship help' in striking['query'].values
        assert 'family therapy' not in striking['query'].values

        # Diagnostic vocabulary is still Tier 1 — and "symptoms" matches the LEMMA
        # entry "symptom" (decision 3 de-duplicated the plural entries).
        row_anxiety = striking[striking['query'] == 'anxiety disorder symptoms'].iloc[0]
        assert "Tier 1 (Medical)" in row_anxiety['clinical_pivot']

        # Check clinical pivot for 'relationship help' (T2 systems)
        row_rel = striking[striking['query'] == 'relationship help'].iloc[0]
        assert "Tier 2 (Systems)" in row_rel['clinical_pivot']

        # C-M-08 / decision 3: the client's own service term is NOT medical model.
        row_therapy = striking[striking['query'] == 'couples therapy'].iloc[0]
        assert "Tier 1 (Medical)" not in row_therapy['clinical_pivot']

def test_suggest_systemic_title(mock_gsc_manager):
    # Test specific trigger
    title1 = mock_gsc_manager.suggest_systemic_title("avoidant attachment")
    assert "Emotional Distance / Pursuer-Distancer" in title1
    
    # Test "how to fix" pattern
    title2 = mock_gsc_manager.suggest_systemic_title("how to fix my marriage")
    assert "Beyond Fixing My Marriage" in title2
    assert "Relationship Process" in title2
    
    # Test default
    title3 = mock_gsc_manager.suggest_systemic_title("general counseling")
    assert "A Systems View" in title3

def test_generate_strike_report(mock_gsc_manager, tmpdir):
    report_path = os.path.join(tmpdir, "gsc_strike_list.md")
    
    striking_df = pd.DataFrame([
        {'query': 'anxiety fix', 'position': 12.5, 'impressions': 1000, 'page': 'https://url.com', 'clinical_pivot': 'Tier 1'}
    ])
    
    with patch('builtins.open', create=True) as mock_open:
        # Mocking the output path to be in tmpdir for the test is hard due to the hardcoded path in the method
        # but we can at least check if open was called.
        mock_gsc_manager.generate_strike_report(striking_df)
        mock_open.assert_called()

def test_test_connection_success(mock_gsc_manager):
    # Mock list_sites with Owner access (matching the 'www' config)
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://www.livingsystems.ca/', 'permissionLevel': 'siteOwner'}]
    }
    # Mock query to succeed
    mock_gsc_manager.service.searchanalytics().query().execute.return_value = {}
    
    success, message = mock_gsc_manager.test_connection()
    assert success is True
    assert "Successfully connected" in message

def test_test_connection_fail_permission(mock_gsc_manager):
    # Mock list_sites with Unverified access
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://www.livingsystems.ca/', 'permissionLevel': 'siteUnverifiedUser'}]
    }
    
    success, message = mock_gsc_manager.test_connection()
    assert success is False
    assert "Insufficient permissions" in message

def test_test_connection_fail_url_mismatch(mock_gsc_manager):
    # Mock list_sites with a DIFFERENT URL (non-www in account, but config is www)
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://livingsystems.ca/', 'permissionLevel': 'siteOwner'}]
    }
    # Config is already https://www.livingsystems.ca/
    success, message = mock_gsc_manager.test_connection()
    assert success is False
    assert "URL Mismatch" in message
    assert "found 'https://livingsystems.ca/'" in message

def test_generate_report(mock_gsc_manager, tmpdir):
    report_path = os.path.join(tmpdir, "gsc_strategic_gap.md")
    
    gaps = pd.DataFrame([{'query': 'gap query', 'impressions': 1000, 'ctr': 0.005, 'tier': 'Tier 1 (Medical)'}])
    low_hanging = pd.DataFrame([{'query': 'low hanging', 'page': 'url', 'position': 12, 'impressions': 500}])
    mismatches = [{'page': 'url', 'query': 'med query', 'medical_hits': 10, 'reason': 'reason'}]
    
    with patch('builtins.open', create=True) as mock_open:
        mock_gsc_manager.generate_report(gaps, low_hanging, mismatches)
        # Ensure it tried to write to gsc_strategic_gap.md
        # (It defaults to "gsc_strategic_gap.md" in current dir, let's just check it was called)
        mock_open.assert_called()


# ── C-C-09: a blocked scrape of the client's OWN page is not a 0/0 audit ──────
# Promotes docs/review_2026-11-04/probes/compete/probe_gsc_block_sentinel.py. The
# dead `content != "BLOCK"` test was always true after the ScrapedPage refactor, so a
# 429 on the client's own site wrote medical 0 / systems 0 with run_id 0 — and the
# 7-day cache then served that for a week, suppressing the Clinical Mismatch check as
# a confident "no mismatches".

def test_cc09_blocked_own_page_is_not_persisted_as_a_zero_audit(mock_gsc_manager):
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://livingsystems.ca/', 'permissionLevel': 'siteOwner'}]
    }
    data = [{'keys': ['anxiety counselling', 'https://livingsystems.ca/anxiety'],
             'clicks': 50, 'impressions': 5000, 'ctr': 0.01, 'position': 3.0}]
    blocked = _scraped("https://livingsystems.ca/anxiety", status="blocked")

    with patch.object(mock_gsc_manager, 'fetch_performance_data', return_value=data), \
         patch.object(mock_gsc_manager.auditor, 'scrape_content', return_value=blocked), \
         patch.object(mock_gsc_manager.auditor, 'analyze_text') as mock_analyze:
        mock_gsc_manager.analyze_gaps()

    mock_analyze.assert_not_called()          # an unreadable page is not scored
    with mock_gsc_manager.db.connection() as conn:
        rows = conn.execute("SELECT url, medical_score, systems_score FROM semantic_audits").fetchall()
    assert rows == []                          # nothing cached for the next 7 days
    assert mock_gsc_manager.db.was_audited_recently("https://livingsystems.ca/anxiety") is None


def test_cc09_an_errored_own_page_is_also_not_persisted(mock_gsc_manager):
    mock_gsc_manager.service.sites().list().execute.return_value = {
        'siteEntry': [{'siteUrl': 'https://livingsystems.ca/', 'permissionLevel': 'siteOwner'}]
    }
    data = [{'keys': ['anxiety counselling', 'https://livingsystems.ca/anxiety'],
             'clicks': 50, 'impressions': 5000, 'ctr': 0.01, 'position': 3.0}]
    errored = _scraped("https://livingsystems.ca/anxiety", status="error")

    with patch.object(mock_gsc_manager, 'fetch_performance_data', return_value=data), \
         patch.object(mock_gsc_manager.auditor, 'scrape_content', return_value=errored):
        _gaps, _low, mismatches = mock_gsc_manager.analyze_gaps()

    with mock_gsc_manager.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM semantic_audits").fetchone()[0] == 0
    assert mismatches == []       # no mismatch CLAIMED either way — the page is unknown
