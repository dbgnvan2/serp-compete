"""
Tests for Gap 3 — EEAT heuristic scoring.

Covers the three confidence tiers required by spec:
  - full-signal page (high confidence, all scores computed)
  - partial-signal page (medium confidence)
  - blocked/error page (low confidence, all-null scores)

Plus individual heuristic functions and score normalisation.
"""

import sys
import json
import pytest
from pathlib import Path
from types import SimpleNamespace

# Ensure src is importable from within Serp-compete/
sys.path.insert(0, str(Path(__file__).parent.parent / "Serp-compete"))

from src.eeat_scorer import EEATScorer, EEATScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_config():
    config_path = Path(__file__).parent.parent / "shared_config.json"
    with open(config_path) as f:
        return json.load(f)


@pytest.fixture
def scorer(sample_config):
    return EEATScorer(sample_config)


def make_metadata(**overrides):
    """Return a metadata dict with all signals populated, optionally overridden."""
    base = {
        "title": "Couples Counselling Guide",
        "meta_description": "A comprehensive guide",
        "author_byline": "Dr. Jane Smith, PhD, RCC",
        "publish_date": "2026-01-15T10:00:00Z",
        "update_date": "2026-04-20T14:30:00Z",
        "schema_types": ["Article", "Person"],
        "has_faq_schema": False,
        "has_article_schema": True,
        "has_localbusiness_schema": False,
        "image_count": 3,
        "image_hosts": ["example.com", "example.com", "livingsystems.ca"],
        "external_link_count": 12,
        "internal_link_count": 5,
        "internal_links": [],
        "is_https": True,
        "has_contact_link": True,
        "has_privacy_link": True,
    }
    base.update(overrides)
    return base


def make_page(
    url="https://example.com/test",
    extraction_status="complete",
    first_500_words=(
        "I have been working with couples for many years. "
        "We have tested our approach rigorously. "
        "In our experience, differentiation of self is key. "
        "Our research shows emotional cutoff patterns."
    ),
    metadata=None,
):
    """Create a SimpleNamespace mimicking ScrapedPage for scorer testing."""
    return SimpleNamespace(
        url=url,
        fetched_at="2026-04-30T00:00:00Z",
        http_status=200,
        extraction_status=extraction_status,
        extraction_errors=[],
        outline=[],
        first_500_words=first_500_words,
        full_text_word_count=150,
        metadata=metadata if metadata is not None else make_metadata(),
    )


# ---------------------------------------------------------------------------
# Scorer initialisation
# ---------------------------------------------------------------------------

class TestEEATScorerInit:

    def test_loads_eeat_weights(self, scorer):
        for dim in ("experience", "expertise", "authoritativeness", "trustworthiness"):
            assert dim in scorer.weights

    def test_loads_stock_image_hosts(self, scorer):
        assert "unsplash.com" in scorer.stock_image_hosts
        assert "shutterstock.com" in scorer.stock_image_hosts

    def test_loads_credential_list(self, scorer):
        assert "PhD" in scorer.credential_list
        assert "RCC" in scorer.credential_list
        assert "MSW" in scorer.credential_list

    def test_loads_case_study_triggers(self, scorer):
        assert "case study" in scorer.case_study_triggers
        assert "in our experience" in scorer.case_study_triggers

    def test_loads_tier_terms(self, scorer):
        assert len(scorer.tier_2_terms) > 0
        assert len(scorer.tier_3_terms) > 0
        assert "differentiation" in scorer.tier_2_terms
        assert "differentiation of self" in scorer.tier_3_terms


# ---------------------------------------------------------------------------
# Full-signal page — high confidence
# ---------------------------------------------------------------------------

class TestFullSignalPage:

    def test_returns_eeat_score(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=65)
        assert isinstance(result, EEATScore)

    def test_high_confidence(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=65)
        assert result.score_confidence == "high"

    def test_all_scores_non_null(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=65)
        for dim, score in result.scores.items():
            assert score is not None, f"{dim} score should not be None for full-signal page"

    def test_scores_in_0_1_range(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=65)
        for dim, score in result.scores.items():
            assert 0.0 <= score <= 1.0, f"{dim} score {score} out of [0, 1]"

    def test_url_preserved(self, scorer):
        result = scorer.score_page(make_page(url="https://livingsystems.ca/bowen"), domain_authority=35)
        assert result.url == "https://livingsystems.ca/bowen"

    def test_caveat_present(self, scorer):
        result = scorer.score_page(make_page())
        assert "Heuristic" in result.caveat

    def test_scored_at_iso8601(self, scorer):
        result = scorer.score_page(make_page())
        assert result.scored_at.endswith("Z")

    def test_to_dict_json_serialisable(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=50)
        d = result.to_dict()
        assert d["url"] == make_page().url
        assert "scores" in d
        assert "score_confidence" in d
        json.dumps(d)  # raises if not serialisable


# ---------------------------------------------------------------------------
# Partial-signal page — medium confidence
# ---------------------------------------------------------------------------

class TestPartialSignalPage:

    def test_missing_da_still_scores_trust_and_expertise(self, scorer):
        result = scorer.score_page(make_page(), domain_authority=None)
        # Trustworthiness and expertise don't need DA
        assert result.scores["trustworthiness"] is not None
        assert result.scores["expertise"] is not None

    def test_null_da_with_zero_signals_scores_zero_not_none(self, scorer):
        # external_link_count_normalised=0.0 and schema_organization_present=False are
        # still evaluable (2/3 ≥ 50%), so score is computed — just low (0.0).
        metadata = make_metadata(external_link_count=0, schema_types=[])
        result = scorer.score_page(make_page(metadata=metadata), domain_authority=None)
        assert result.scores["authoritativeness"] == pytest.approx(0.0)

    def test_confidence_high_when_all_signals_have_defaults(self, scorer):
        # All signal extractors produce non-None defaults for complete pages,
        # so confidence is always high for extraction_status="complete".
        metadata = make_metadata(external_link_count=0, schema_types=[])
        result = scorer.score_page(make_page(metadata=metadata), domain_authority=None)
        assert result.score_confidence == "high"

    def test_confidence_medium_when_weights_dimension_missing(self, scorer, sample_config):
        # Medium confidence occurs when a dimension has no weights configured.
        import copy
        cfg = copy.deepcopy(sample_config)
        del cfg["eeat_weights"]["trustworthiness"]
        partial_scorer = EEATScorer(cfg)
        result = partial_scorer.score_page(make_page(), domain_authority=50)
        assert result.scores["trustworthiness"] is None
        assert result.score_confidence == "medium"


# ---------------------------------------------------------------------------
# Blocked / error page — low confidence, all-null scores
# ---------------------------------------------------------------------------

class TestFailedExtractionPage:

    def test_blocked_low_confidence(self, scorer):
        assert scorer.score_page(make_page(extraction_status="blocked")).score_confidence == "low"

    def test_error_low_confidence(self, scorer):
        assert scorer.score_page(make_page(extraction_status="error")).score_confidence == "low"

    def test_blocked_all_scores_null(self, scorer):
        result = scorer.score_page(make_page(extraction_status="blocked"))
        for dim, score in result.scores.items():
            assert score is None, f"{dim} should be None for blocked page"

    def test_error_all_scores_null(self, scorer):
        result = scorer.score_page(make_page(extraction_status="error"))
        for dim, score in result.scores.items():
            assert score is None

    def test_blocked_experience_signals_empty(self, scorer):
        result = scorer.score_page(make_page(extraction_status="blocked"))
        exp = result.experience_signals
        assert exp["has_author_byline"] is False
        assert exp["first_person_count_normalised"] == 0.0
        assert exp["case_study_signal"] is False

    def test_blocked_trustworthiness_signals_empty(self, scorer):
        result = scorer.score_page(make_page(extraction_status="blocked"))
        trust = result.trustworthiness_signals
        assert trust["is_https"] is False
        assert trust["has_contact_link"] is False
        assert trust["has_privacy_link"] is False


# ---------------------------------------------------------------------------
# Experience signal extraction
# ---------------------------------------------------------------------------

class TestExperienceSignals:

    def test_author_byline_present(self, scorer):
        signals = scorer._extract_experience_signals(make_page(metadata=make_metadata(author_byline="Dr. Smith")))
        assert signals["has_author_byline"] is True

    def test_author_byline_absent(self, scorer):
        signals = scorer._extract_experience_signals(make_page(metadata=make_metadata(author_byline=None)))
        assert signals["has_author_byline"] is False

    def test_publish_date_present(self, scorer):
        signals = scorer._extract_experience_signals(make_page(metadata=make_metadata(publish_date="2026-01-01")))
        assert signals["has_publish_date"] is True

    def test_update_date_present(self, scorer):
        signals = scorer._extract_experience_signals(make_page(metadata=make_metadata(update_date="2026-04-01")))
        assert signals["has_update_date"] is True

    def test_first_person_normalised_in_range(self, scorer):
        page = make_page(first_500_words="I think we should consider our options.")
        signals = scorer._extract_experience_signals(page)
        assert 0.0 < signals["first_person_count_normalised"] <= 1.0

    def test_first_person_capped_at_1(self, scorer):
        page = make_page(first_500_words=" ".join(["I we our us"] * 10))
        signals = scorer._extract_experience_signals(page)
        assert signals["first_person_count_normalised"] == 1.0

    def test_first_person_zero(self, scorer):
        page = make_page(first_500_words="The patient received treatment for anxiety.")
        signals = scorer._extract_experience_signals(page)
        assert signals["first_person_count_normalised"] == 0.0

    def test_case_study_detected(self, scorer):
        page = make_page(first_500_words="In our experience this approach works.")
        assert scorer._extract_experience_signals(page)["case_study_signal"] is True

    def test_case_study_absent(self, scorer):
        page = make_page(first_500_words="Generic counselling page content here.")
        assert scorer._extract_experience_signals(page)["case_study_signal"] is False

    def test_original_images_detected(self, scorer):
        metadata = make_metadata(image_count=2, image_hosts=["example.com", "livingsystems.ca"])
        signals = scorer._extract_experience_signals(make_page(metadata=metadata))
        assert signals["has_likely_original_images"] is True

    def test_stock_images_detected(self, scorer):
        metadata = make_metadata(image_count=2, image_hosts=["unsplash.com", "shutterstock.com"])
        signals = scorer._extract_experience_signals(make_page(metadata=metadata))
        assert signals["has_likely_original_images"] is False


# ---------------------------------------------------------------------------
# Expertise signal extraction
# ---------------------------------------------------------------------------

class TestExpertiseSignals:

    def test_credentials_in_byline(self, scorer):
        page = make_page(metadata=make_metadata(author_byline="Jane Smith, PhD, RCC"))
        signals = scorer._extract_expertise_signals(page)
        assert signals["has_credentials_in_byline"] is True

    def test_matched_credentials_listed(self, scorer):
        page = make_page(metadata=make_metadata(author_byline="Jane Smith, PhD, RCC"))
        signals = scorer._extract_expertise_signals(page)
        assert "PhD" in signals["matched_credentials"] or "RCC" in signals["matched_credentials"]

    def test_no_credentials(self, scorer):
        page = make_page(metadata=make_metadata(author_byline="Jane Smith"))
        signals = scorer._extract_expertise_signals(page)
        assert signals["has_credentials_in_byline"] is False
        assert signals["matched_credentials"] == []

    def test_schema_author_type_person(self, scorer):
        page = make_page(metadata=make_metadata(schema_types=["Article", "Person"]))
        assert scorer._extract_expertise_signals(page)["schema_author_type_person"] is True

    def test_schema_author_type_not_person(self, scorer):
        page = make_page(metadata=make_metadata(schema_types=["Organization"]))
        assert scorer._extract_expertise_signals(page)["schema_author_type_person"] is False

    def test_tier_3_or_2_present_with_bowen_term(self, scorer):
        # "differentiation of self" is a tier_3_bowen phrase
        page = make_page(first_500_words="differentiation of self is central to Bowen theory.")
        assert scorer._extract_expertise_signals(page)["tier_3_or_tier_2_present"] is True

    def test_tier_2_term_triggers_present(self, scorer):
        # "differentiation" is a tier_2_systems term
        page = make_page(first_500_words="differentiation is a key concept in family therapy.")
        assert scorer._extract_expertise_signals(page)["tier_3_or_tier_2_present"] is True

    def test_no_tier_terms_absent(self, scorer):
        page = make_page(first_500_words="This page discusses general communication skills.")
        assert scorer._extract_expertise_signals(page)["tier_3_or_tier_2_present"] is False


# ---------------------------------------------------------------------------
# Authoritativeness signal extraction
# ---------------------------------------------------------------------------

class TestAuthoratativenessSignals:

    def test_da_normalised(self, scorer):
        # spec: min(da / 60, 1.0) — DA 60+ scores 1.0
        signals = scorer._extract_authoritativeness_signals(make_page(), domain_authority=30)
        assert signals["domain_authority_normalised"] == pytest.approx(0.5)

    def test_da_at_60_clamps_to_1(self, scorer):
        signals = scorer._extract_authoritativeness_signals(make_page(), domain_authority=60)
        assert signals["domain_authority_normalised"] == pytest.approx(1.0)

    def test_da_above_60_clamps_to_1(self, scorer):
        signals = scorer._extract_authoritativeness_signals(make_page(), domain_authority=90)
        assert signals["domain_authority_normalised"] == pytest.approx(1.0)

    def test_da_none(self, scorer):
        signals = scorer._extract_authoritativeness_signals(make_page(), domain_authority=None)
        assert signals["domain_authority_normalised"] is None

    def test_da_zero(self, scorer):
        signals = scorer._extract_authoritativeness_signals(make_page(), domain_authority=0)
        assert signals["domain_authority_normalised"] == pytest.approx(0.0)

    def test_external_link_normalised(self, scorer):
        # spec: min(count / 5, 1.0) — 5+ outbound links scores 1.0
        signals = scorer._extract_authoritativeness_signals(
            make_page(metadata=make_metadata(external_link_count=2)), domain_authority=None
        )
        assert signals["external_link_count_normalised"] == pytest.approx(0.4)

    def test_external_link_capped_at_5_plus(self, scorer):
        signals = scorer._extract_authoritativeness_signals(
            make_page(metadata=make_metadata(external_link_count=10)), domain_authority=None
        )
        assert signals["external_link_count_normalised"] == pytest.approx(1.0)

    def test_org_schema_present(self, scorer):
        page = make_page(metadata=make_metadata(schema_types=["Organization"]))
        assert scorer._extract_authoritativeness_signals(page, domain_authority=None)["schema_organization_present"] is True

    def test_org_schema_absent(self, scorer):
        page = make_page(metadata=make_metadata(schema_types=["Article"]))
        assert scorer._extract_authoritativeness_signals(page, domain_authority=None)["schema_organization_present"] is False


# ---------------------------------------------------------------------------
# Trustworthiness signal extraction
# ---------------------------------------------------------------------------

class TestTrustworthinessSignals:

    def test_https_true(self, scorer):
        assert scorer._extract_trustworthiness_signals(make_page(metadata=make_metadata(is_https=True)))["is_https"] is True

    def test_https_false(self, scorer):
        assert scorer._extract_trustworthiness_signals(make_page(metadata=make_metadata(is_https=False)))["is_https"] is False

    def test_contact_link_detected(self, scorer):
        signals = scorer._extract_trustworthiness_signals(make_page(metadata=make_metadata(has_contact_link=True)))
        assert signals["has_contact_link"] is True

    def test_privacy_link_detected(self, scorer):
        signals = scorer._extract_trustworthiness_signals(make_page(metadata=make_metadata(has_privacy_link=True)))
        assert signals["has_privacy_link"] is True

    def test_missing_links_false(self, scorer):
        metadata = make_metadata(has_contact_link=False, has_privacy_link=False)
        signals = scorer._extract_trustworthiness_signals(make_page(metadata=metadata))
        assert signals["has_contact_link"] is False
        assert signals["has_privacy_link"] is False


# ---------------------------------------------------------------------------
# Individual heuristic functions
# ---------------------------------------------------------------------------

class TestHeuristics:

    def test_count_first_person_basic(self, scorer):
        assert scorer._count_first_person("I think we should share our ideas with us.") == 4

    def test_count_first_person_all_forms(self, scorer):
        count = scorer._count_first_person("I we our us")
        assert count == 4

    def test_count_first_person_capped(self, scorer):
        assert scorer._count_first_person(" ".join(["I"] * 20)) == 10

    def test_count_first_person_no_matches(self, scorer):
        assert scorer._count_first_person("The patient received treatment.") == 0

    def test_count_first_person_word_boundary(self, scorer):
        # "issue", "their", "using" contain i/we/our/us as substrings but not as words
        assert scorer._count_first_person("issue their using") == 0

    def test_detect_original_images_no_images(self, scorer):
        assert scorer._detect_original_images({"image_count": 0}) is False

    def test_detect_original_images_original_hosts(self, scorer):
        metadata = {"image_count": 2, "image_hosts": ["example.com", "livingsystems.ca"]}
        assert scorer._detect_original_images(metadata) is True

    def test_detect_original_images_all_stock(self, scorer):
        metadata = {"image_count": 2, "image_hosts": ["unsplash.com", "shutterstock.com"]}
        assert scorer._detect_original_images(metadata) is False

    def test_detect_original_images_80pct_threshold(self, scorer):
        # 4 of 5 hosts stock = 80% → considered stock (≥80% threshold)
        metadata = {"image_count": 5,
                    "image_hosts": ["unsplash.com", "shutterstock.com", "pexels.com", "pixabay.com", "example.com"]}
        assert scorer._detect_original_images(metadata) is False

    def test_detect_original_images_below_80pct_stock(self, scorer):
        # 3 of 5 hosts stock = 60% < 80% → considered original
        metadata = {"image_count": 5,
                    "image_hosts": ["unsplash.com", "shutterstock.com", "pexels.com", "example.com", "livingsystems.ca"]}
        assert scorer._detect_original_images(metadata) is True

    def test_detect_case_study_triggers(self, scorer):
        for phrase in ("we tested", "case study", "in our experience", "our research"):
            assert scorer._detect_case_study(phrase), f"Phrase '{phrase}' should trigger case study"

    def test_detect_case_study_no_trigger(self, scorer):
        assert scorer._detect_case_study("general counselling information") is False

    def test_extract_credentials_rcc_ma(self, scorer):
        creds = scorer._extract_credentials("Jane Smith, RCC, MA")
        assert "RCC" in creds
        assert "MA" in creds

    def test_extract_credentials_case_insensitive(self, scorer):
        creds = scorer._extract_credentials("Jane Smith, phd")
        assert len(creds) > 0  # should match PhD regardless of case

    def test_extract_credentials_no_match(self, scorer):
        assert scorer._extract_credentials("Jane Smith") == []

    def test_extract_credentials_word_boundary(self, scorer):
        # "MAster" should not match the credential "MA"
        creds = scorer._extract_credentials("MAster therapist")
        assert "MA" not in creds


# ---------------------------------------------------------------------------
# Weighted score computation
# ---------------------------------------------------------------------------

class TestWeightedScoring:

    def test_all_true_booleans_score_1(self, scorer):
        signals = {"is_https": True, "has_contact_link": True, "has_privacy_link": True}
        assert scorer._compute_weighted_score("trustworthiness", signals) == pytest.approx(1.0)

    def test_all_false_booleans_score_0(self, scorer):
        signals = {"is_https": False, "has_contact_link": False, "has_privacy_link": False}
        assert scorer._compute_weighted_score("trustworthiness", signals) == pytest.approx(0.0)

    def test_partial_booleans_weighted_average(self, scorer):
        # Only is_https = True (weight 0.40); rest False
        # 1.0*0.40 / (0.40+0.30+0.30) = 0.40
        signals = {"is_https": True, "has_contact_link": False, "has_privacy_link": False}
        assert scorer._compute_weighted_score("trustworthiness", signals) == pytest.approx(0.40)

    def test_returns_none_for_unknown_dimension(self, scorer):
        assert scorer._compute_weighted_score("nonexistent", {"foo": True}) is None

    def test_returns_none_when_insufficient_evaluable_signals(self, scorer):
        # 1 of 3 trustworthiness signals evaluable → 33% < 50% → None
        signals = {"is_https": None, "has_contact_link": None, "has_privacy_link": True}
        assert scorer._compute_weighted_score("trustworthiness", signals) is None

    def test_returns_score_when_2_of_3_evaluable(self, scorer):
        # 2 of 3 evaluable → 67% ≥ 50% → not None
        signals = {"is_https": True, "has_contact_link": True, "has_privacy_link": None}
        score = scorer._compute_weighted_score("trustworthiness", signals)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_score_never_exceeds_1(self, scorer):
        # Inflated normalised value should be clamped
        signals = {
            "has_author_byline": True,
            "has_publish_date": True,
            "has_update_date": True,
            "has_likely_original_images": True,
            "first_person_count_normalised": 5.0,  # artificially > 1
            "case_study_signal": True,
        }
        score = scorer._compute_weighted_score("experience", signals)
        assert score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
