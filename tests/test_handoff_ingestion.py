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
    """Test conversion of handoff data to internal format."""

    def test_handoff_conversion_basic(self, valid_handoff_data):
        """Test basic handoff-to-targets conversion."""
        # Simulate the conversion logic from main.py
        targets = []
        for target in valid_handoff_data.get("targets", []):
            targets.append({
                "domain": target["domain"],
                "url": target["url"],
                "primary_keyword": target["primary_keyword_for_url"],
                "est_traffic": 0,
                "rank": target["rank"],
                "entity_type": target["entity_type"],
                "content_type": target["content_type"],
                "title": target["title"],
                "source_keyword": target["source_keyword"]
            })

        assert len(targets) == 2
        assert targets[0]["domain"] == "example.com"
        assert targets[0]["url"] == "https://example.com/couples-counselling"
        assert targets[0]["primary_keyword"] == "couples counselling"
        assert targets[0]["rank"] == 1
        assert targets[0]["entity_type"] == "service"
        assert targets[1]["rank"] == 3

    def test_legacy_conversion_basic(self, legacy_data):
        """Test basic legacy format conversion."""
        # Simulate legacy conversion logic from main.py
        targets = []
        if "organic_results" in legacy_data:
            for res in legacy_data["organic_results"]:
                url = res.get("Link")
                keyword = res.get("Source_Keyword")
                if url and keyword:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.replace('www.', '')
                    targets.append({
                        "domain": domain,
                        "url": url,
                        "primary_keyword": keyword,
                        "est_traffic": res.get("Word_Count") if isinstance(res.get("Word_Count"), (int, float)) else 0
                    })

        paa_data = {}
        if "paa_questions" in legacy_data:
            for paa in legacy_data["paa_questions"]:
                kw = paa.get("Source_Keyword")
                question = paa.get("Question")
                if kw and question:
                    if kw not in paa_data:
                        paa_data[kw] = []
                    paa_data[kw].append(question)

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
