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
