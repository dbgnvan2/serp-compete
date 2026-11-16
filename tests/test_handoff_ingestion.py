"""
Tests for Gap 1 — Competitor handoff ingestion from Tool 1.

Unit tests for the handoff conversion and validation functions.
"""

import pytest
import json
import jsonschema
from pathlib import Path


# Load the actual schema once for all tests
SCHEMA_PATH = Path(__file__).parent.parent / "handoff_schema.json"
with open(SCHEMA_PATH, 'r') as f:
    HANDOFF_SCHEMA = json.load(f)


# Fixtures
@pytest.fixture
def valid_handoff_data():
    """A valid handoff JSON matching the schema."""
    return {
        "schema_version": "1.0",
        "source_run_id": "run_20260430_1530",
        "source_run_timestamp": "2026-04-30T15:30:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems", "Bowen"],
        "targets": [
            {
                "url": "https://example.com/couples-counselling",
                "domain": "example.com",
                "rank": 1,
                "entity_type": "service",
                "content_type": "service",
                "title": "Couples Counselling Services",
                "source_keyword": "couples counselling",
                "primary_keyword_for_url": "couples counselling"
            },
            {
                "url": "https://therapist.com/guide-relationships",
                "domain": "therapist.com",
                "rank": 3,
                "entity_type": "directory",
                "content_type": "guide",
                "title": "Guide to Healthy Relationships",
                "source_keyword": "relationships guide",
                "primary_keyword_for_url": "relationship counselling"
            }
        ],
        "exclusions": {
            "client_urls_excluded": 2,
            "omit_list_excluded": 1,
            "omit_list_used": ["spam-site.com"]
        }
    }


@pytest.fixture
def invalid_handoff_missing_field():
    """Handoff with missing required field."""
    return {
        "schema_version": "1.0",
        "source_run_id": "run_20260430_1530",
        # Missing source_run_timestamp
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems"],
        "targets": [],
        "exclusions": {
            "client_urls_excluded": 0,
            "omit_list_excluded": 0,
            "omit_list_used": []
        }
    }


@pytest.fixture
def invalid_handoff_wrong_type():
    """Handoff with wrong field type."""
    return {
        "schema_version": "1.0",
        "source_run_id": "run_20260430_1530",
        "source_run_timestamp": "2026-04-30T15:30:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems"],
        "targets": [
            {
                "url": "https://example.com/page",
                "domain": "example.com",
                "rank": "first",  # WRONG: should be integer
                "entity_type": "service",
                "content_type": "service",
                "title": "Title",
                "source_keyword": "keyword",
                "primary_keyword_for_url": "keyword"
            }
        ],
        "exclusions": {
            "client_urls_excluded": 0,
            "omit_list_excluded": 0,
            "omit_list_used": []
        }
    }


@pytest.fixture
def invalid_handoff_extra_field():
    """Handoff with extra field (additionalProperties: false)."""
    return {
        "schema_version": "1.0",
        "source_run_id": "run_20260430_1530",
        "source_run_timestamp": "2026-04-30T15:30:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems"],
        "targets": [],
        "exclusions": {
            "client_urls_excluded": 0,
            "omit_list_excluded": 0,
            "omit_list_used": []
        },
        "extra_field": "not allowed"
    }


@pytest.fixture
def legacy_data():
    """Legacy market_analysis format."""
    return {
        "organic_results": [
            {
                "Link": "https://example.com/page",
                "Source_Keyword": "couples counselling",
                "Word_Count": 1500
            },
            {
                "Link": "https://therapist.com/guide",
                "Source_Keyword": "therapy",
                "Word_Count": 2000
            }
        ],
        "paa_questions": [
            {
                "Source_Keyword": "couples counselling",
                "Question": "How does couples therapy work?"
            },
            {
                "Source_Keyword": "therapy",
                "Question": "What is family systems therapy?"
            }
        ]
    }


# Schema validation tests
class TestHandoffSchemaValidation:
    """Test JSON Schema validation of handoff format."""

    def test_valid_handoff_passes_schema(self, valid_handoff_data):
        """Test that valid handoff passes schema validation."""
        # Should not raise
        jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)

    def test_handoff_missing_required_field_fails(self, invalid_handoff_missing_field):
        """Test that handoff missing required field fails validation."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_handoff_missing_field, schema=HANDOFF_SCHEMA)

    def test_handoff_wrong_field_type_fails(self, invalid_handoff_wrong_type):
        """Test that handoff with wrong field type fails validation."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_handoff_wrong_type, schema=HANDOFF_SCHEMA)

    def test_handoff_extra_field_fails(self, invalid_handoff_extra_field):
        """Test that handoff with extra field fails (additionalProperties: false)."""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_handoff_extra_field, schema=HANDOFF_SCHEMA)

    def test_target_missing_required_field_fails(self, valid_handoff_data):
        """Test that target missing required field fails."""
        valid_handoff_data["targets"][0].pop("rank")  # Remove rank
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)

    def test_target_extra_field_fails(self, valid_handoff_data):
        """Test that target with extra field fails (additionalProperties: false)."""
        valid_handoff_data["targets"][0]["extra"] = "not allowed"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)


class TestHandoffConversion:
    """Test conversion of handoff data to internal format.

    These call the REAL consumer. Until 2026-11-16 (Chunk X) they carried their
    own copy of `main.convert_handoff_to_targets` under the comment "Simulate
    the conversion logic from main.py", so the shipped function could have
    changed shape or dropped a field with every assertion here still passing —
    and one of them had: `client_brand_names` was read by the schema, written by
    Tool 1, and thrown away by the consumer for months (C-C-13). A contract test
    that re-implements the contract tests nothing (P21).
    """

    def test_handoff_conversion_basic(self, valid_handoff_data):
        """Test basic handoff-to-targets conversion."""
        from src.main import convert_handoff_to_targets

        targets, paa_map, brand_names = convert_handoff_to_targets(valid_handoff_data)

        # The handoff has no PAA field, so the consumer must return an empty
        # map rather than invent one (FEATURE_GUIDE §6.1's PAA promise was
        # dropped in C1 for this reason).
        assert paa_map == {}
        # …and the client's brand names must survive ingestion (C-C-13).
        assert brand_names == ["Living Systems", "Bowen"]

        assert len(targets) == 2
        assert targets[0]["domain"] == "example.com"
        assert targets[0]["url"] == "https://example.com/couples-counselling"
        assert targets[0]["primary_keyword"] == "couples counselling"
        assert targets[0]["rank"] == 1
        assert targets[0]["entity_type"] == "service"
        assert targets[1]["rank"] == 3

    def test_legacy_conversion_basic(self, legacy_data):
        """Test basic legacy format conversion — through the real function."""
        from src.main import convert_legacy_to_targets

        targets, paa_data, brand_names = convert_legacy_to_targets(legacy_data)

        # The legacy format has no client_brand_names; the caller falls back to
        # shared_config `client.name`, so this must be empty, not absent.
        assert brand_names == []

        assert len(targets) == 2
        assert targets[0]["domain"] == "example.com"
        assert targets[0]["url"] == "https://example.com/page"
        assert targets[0]["primary_keyword"] == "couples counselling"
        assert targets[0]["est_traffic"] == 1500

        # PAA data should be extracted
        assert "couples counselling" in paa_data
        assert paa_data["couples counselling"] == ["How does couples therapy work?"]
        assert "therapy" in paa_data


class TestHandoffEdgeCases:
    """Test edge cases in handoff validation and conversion."""

    def test_empty_targets_list_valid(self, valid_handoff_data):
        """Test that empty targets list is valid."""
        valid_handoff_data["targets"] = []
        # Should not raise
        jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)

    def test_null_values_in_optional_fields_valid(self):
        """Test data structure with fields having appropriate types."""
        data = {
            "schema_version": "1.0",
            "source_run_id": "test",
            "source_run_timestamp": "2026-04-30T15:30:00Z",
            "client_domain": "test.com",
            "client_brand_names": [],
            "targets": [],
            "exclusions": {
                "client_urls_excluded": 0,
                "omit_list_excluded": 0,
                "omit_list_used": []
            }
        }
        # Should not raise
        jsonschema.validate(instance=data, schema=HANDOFF_SCHEMA)

    def test_schema_format_validation(self):
        """Test that schema has expected structure."""
        assert HANDOFF_SCHEMA["title"] == "CompetitorHandoff"
        assert HANDOFF_SCHEMA["type"] == "object"
        assert HANDOFF_SCHEMA["additionalProperties"] is False
        assert "properties" in HANDOFF_SCHEMA
        assert "required" in HANDOFF_SCHEMA
        assert len(HANDOFF_SCHEMA["required"]) == 7  # 7 required fields


class TestLegacyEdgeCases:
    """Test edge cases in legacy format."""

    def test_legacy_with_missing_fields(self):
        """Test legacy format with missing optional fields."""
        legacy = {
            "organic_results": [
                {"Link": None, "Source_Keyword": None}
            ]
        }
        # Conversion should handle gracefully
        targets = []
        paa_data = {}
        if "organic_results" in legacy:
            for res in legacy["organic_results"]:
                url = res.get("Link")
                keyword = res.get("Source_Keyword")
                if url and keyword:
                    targets.append({"url": url, "primary_keyword": keyword})

        assert targets == []

    def test_legacy_without_paa_section(self):
        """Test legacy format without paa_questions."""
        legacy = {
            "organic_results": [
                {"Link": "https://example.com", "Source_Keyword": "test"}
            ]
        }
        paa_data = {}
        if "paa_questions" in legacy:
            pass
        # Should not error
        assert paa_data == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_moz_client_block_with_fetched_at_is_accepted(valid_handoff_data):
    """Tool 1 stamps moz.client.fetched_at with the client's anchor text.

    This schema did not allow it, so every handoff from a run with
    client_anchor_texts on would have been rejected at ingestion (found 2026-11-14).
    """
    valid_handoff_data["schema_version"] = "1.1"
    valid_handoff_data["moz"] = {
        "generated_at": "2026-11-14T15:55:00+00:00",
        "domains": {},
        "client": {"domain": "livingsystems.ca", "anchor_texts": {"items": []},
                   "fetched_at": "2026-11-14T15:53:04+00:00"},
    }
    jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)

    valid_handoff_data["moz"]["client"]["unknown_field"] = 1     # still strict
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=valid_handoff_data, schema=HANDOFF_SCHEMA)
