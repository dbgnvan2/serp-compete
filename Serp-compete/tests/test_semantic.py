import pytest
from src.semantic import SemanticAuditor

def test_analyze_text():
    """The tier counts. Note what is NOT medical any more: this text says "anxiety"
    and "treat", and decision 3 (2026-11-15) took "therapy", "patient", "condition"
    and "trauma" out of Tier 1 — Tier 1 is diagnostic vocabulary only."""
    auditor = SemanticAuditor()
    text = ("Our clinical approach focuses on differentiation and triangles within "
            "the emotional system. We treat anxiety disorder and other symptoms. "
            # Enough prose that 3 medical words is a LOW density — the label is a
            # density now, so the length of the page is part of the test.
            + "Filler words to give the window a realistic length. " * 40)

    # Medical: "clinical", "disorder", "symptoms" (lemma of the entry "symptom") = 3
    # T2: "differentiation", "triangles", "emotional system" = 3; T3 = 0
    # Weighted: (0 * 2.0) + (3 * 0.5) = 1.5
    scores = auditor.analyze_text(text)

    assert scores['medical_score'] == 3
    assert scores['t2_count'] == 3
    assert scores['t3_count'] == 0
    assert scores['systems_score'] == 1.5
    assert scores['systemic_label'] == "Standard"
    # C-M-19: the window travels with the score, and the density is derived from it.
    assert scores['scoring_window_words'] > 0
    assert scores['medical_density_per_1000'] == pytest.approx(
        1000 * 3 / scores['scoring_window_words'], abs=0.1)
    # …and the score can be explained, which a bare count never could.
    assert sorted(scores['matched_terms']['t1']) == ["clinical", "disorder", "symptoms"]


def test_analyze_text_penalty():
    """Surface-Level is now a DENSITY trigger (C-M-19): heavy medical language for the
    length of the page, with no Tier-3 term, halves the Tier-2 contribution."""
    auditor = SemanticAuditor()
    text = " ".join(["symptom"] * 11) + " differentiation triangles"

    # Medical=11 over a 13-word window = 846 per 1000, far above the threshold; T3=0
    # Weighted Score: (0 * 2.0) + (2 * 0.5 * 0.5 penalty) = 0.5
    scores = auditor.analyze_text(text)
    assert scores['medical_score'] == 11
    assert scores['systems_score'] == 0.5
    assert scores['systemic_label'] == "Surface-Level"


def test_the_same_count_in_a_long_page_is_not_surface_level():
    """C-M-19's core complaint: 5 medical words scored 5 in a 5-word text and 5 in an
    805-word text. The label now depends on the density, so the identical count over
    a long page is Standard."""
    auditor = SemanticAuditor()
    dense = " ".join(["symptom"] * 5) + " differentiation"
    diluted = dense + " " + ("ordinary prose about distance and pursuit. " * 120)

    assert auditor.analyze_text(dense)['systemic_label'] == "Surface-Level"
    diluted_scores = auditor.analyze_text(diluted)
    assert diluted_scores['medical_score'] == 5          # the same five hits
    assert diluted_scores['systemic_label'] == "Standard"


def test_one_medical_word_on_a_short_page_is_not_surface_level():
    """The density needs a minimum numerator (`tier_1_min_hits`): one hit in 40 words
    is 25 per 1000, which is noise, not a medical-model page."""
    auditor = SemanticAuditor()
    text = "symptom " + ("short page with little else on it. " * 5)
    scores = auditor.analyze_text(text)
    assert scores['medical_score'] == 1
    assert scores['systemic_label'] == "Standard"


# ── C-M-19 / C-C-15: the matching mechanics ──────────────────────────────────
# Promotes docs/review_2026-11-04/probes/compete/probe_semantic_terms.py and
# probes/compete_method/p01_semantic_scoring.py.

def test_cc15_hyphenated_entries_are_reachable():
    """`self-regulation` is a CONFIGURED Tier-2 term that could never match: spaCy
    splits it into `self`, `-`, `regulation`, and the phrase path only ran for entries
    containing a space. A competitor page built around it scored 0 on systems
    language — and so became a Systemic Vacuum and a gpt-4o reframe target."""
    auditor = SemanticAuditor()
    scores = auditor.analyze_text("Self-regulation and self-regulation again. " * 2)
    assert scores['t2_count'] == 4


@pytest.mark.parametrize("text,expected_t3", [
    ("over-under functioning", 1),
    ("pursuer-distancer reciprocity", 1),
    ("emotional cutoff in the family", 1),
])
def test_cm19_hyphenated_and_multiword_tier3_entries_match(text, expected_t3):
    auditor = SemanticAuditor()
    assert auditor.analyze_text(text)['t3_count'] == expected_t3


def test_cm19_a_nested_phrase_is_counted_once_in_the_longest_tier():
    """"differentiation of self" scored Tier-3 1 AND Tier-2 1 (for
    "differentiation"), inflating the weighted score by 0.5 for the same five words."""
    auditor = SemanticAuditor()
    scores = auditor.analyze_text("differentiation of self")
    assert scores['t3_count'] == 1
    assert scores['t2_count'] == 0
    assert scores['systems_score'] == 2.0      # was 2.5


def test_cm19_lemmas_match_inflections():
    """"triangle" scored 0 while "triangles" scored 3; "treatments" scored 0 against
    the entry "treatment"."""
    auditor = SemanticAuditor()
    assert auditor.analyze_text("a triangle forms")['t2_count'] == 1
    assert auditor.analyze_text("treatments for the illness")['medical_score'] == 2


def test_cm19_a_lemma_collision_does_not_earn_the_stronger_tier():
    """The Tier-2 entry "triangles" and the Tier-3 entry "triangling" share the lemma
    "triangle". An exact surface form must win its own tier, so "triangles" stays
    Tier 2 — Tier 3 is the strong claim (×2.0, and the band that reads as "Bowen
    vocabulary present")."""
    auditor = SemanticAuditor()
    t2_text = auditor.analyze_text("triangles and triangulation")
    assert (t2_text['t2_count'], t2_text['t3_count']) == (2, 0)
    t3_text = auditor.analyze_text("triangling in the family")
    assert (t3_text['t2_count'], t3_text['t3_count']) == (0, 1)


def test_cm08_the_neutral_words_no_longer_score_as_medical():
    """Decision 3: "therapy", "patient", "condition", "trauma" are this market's
    neutral vocabulary. Bowen-practice copy used to score medical 6 on this text."""
    auditor = SemanticAuditor()
    text = ("Family therapy and couples therapy for every patient. Book a therapy "
            "session to talk about trauma and the condition you are facing. " * 3)
    scores = auditor.analyze_text(text)
    assert scores['medical_score'] == 0
    assert scores['systemic_label'] == "Standard"


def test_cm08_diagnostic_vocabulary_still_scores():
    auditor = SemanticAuditor()
    text = ("The diagnosis names a disorder; the medication treats the symptom and "
            "the prognosis follows the pathology of the disease. " * 3)
    scores = auditor.analyze_text(text)
    assert scores['medical_score'] >= 15

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
