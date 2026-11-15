import pytest
from src.semantic import SemanticAuditor

def test_analyze_text():
    auditor = SemanticAuditor()
    text = "Our clinical approach focuses on differentiation and triangles within the emotional system. We treat anxiety disorder and other symptoms."
    
    # "differentiation" (T2), "triangles" (T2), "emotional system" (T2)
    # Counts: T2=3, T3=0, Medical=3
    # Weighted Score: (0 * 2.0) + (3 * 0.5) = 1.5
    
    scores = auditor.analyze_text(text)
    
    assert scores['systems_score'] == 1.5
    assert scores['medical_score'] == 3
    assert scores['t2_count'] == 3
    assert scores['systemic_label'] == "Standard"

def test_analyze_text_penalty():
    auditor = SemanticAuditor()
    # High medical count (> 10) and T3 == 0 -> -50% penalty to T2
    text = " ".join(["symptom"] * 11) + " differentiation triangles"
    
    # Medical=11, T2=2, T3=0
    # Weighted Score: (0 * 2.0) + (2 * 0.5 * 0.5 penalty) = 0.5
    
    scores = auditor.analyze_text(text)
    assert scores['systems_score'] == 0.5
    assert scores['medical_score'] == 11
    assert scores['systemic_label'] == "Surface-Level"

def test_scrape_content_mock(requests_mock):
    auditor = SemanticAuditor()
    url = "https://example.com"
    requests_mock.get(url, text="<html><h1>Heading</h1><p>Some text and more text.</p></html>")

    page = auditor.scrape_content(url)
    assert page.url == url
    assert page.http_status == 200
    assert "Heading" in page.first_500_words
    assert "Some text" in page.first_500_words


# ── C-C-18: a failing homepage warm-up must not cost the page its audit slot ──
# main.py marks a URL as attempted BEFORE fetching it, so an error here spent one of
# the domain's three slots and left no traffic_magnets / market_history row at all.

def test_cc18_homepage_warmup_failure_still_audits_the_page(requests_mock):
    import requests as _requests
    auditor = SemanticAuditor()
    requests_mock.get("https://example.com/", exc=_requests.exceptions.ReadTimeout)
    requests_mock.get("https://example.com/page",
                      text="<html><h1>Couples counselling</h1><p>Body text.</p></html>")

    page = auditor.scrape_content("https://example.com/page")
    assert page.extraction_status == "complete"
    assert "Couples counselling" in page.first_500_words


def test_cc18_a_transient_page_error_is_retried_once(requests_mock):
    import requests as _requests
    auditor = SemanticAuditor()
    requests_mock.get("https://example.com/", text="<html></html>")
    requests_mock.get("https://example.com/page", [
        {"exc": _requests.exceptions.ConnectionError},
        {"text": "<html><h1>Second try</h1></html>"},
    ])

    page = auditor.scrape_content("https://example.com/page")
    assert page.extraction_status == "complete"
    assert "Second try" in page.first_500_words


def test_cc18_a_429_is_still_blocked_and_not_retried(requests_mock):
    """Only the exception path is retried: re-requesting a rate-limited page is what
    the circuit breaker exists to avoid."""
    auditor = SemanticAuditor()
    requests_mock.get("https://example.com/", text="<html></html>")
    page_mock = requests_mock.get("https://example.com/page", status_code=429)

    page = auditor.scrape_content("https://example.com/page")
    assert page.extraction_status == "blocked"
    assert page_mock.call_count == 1
