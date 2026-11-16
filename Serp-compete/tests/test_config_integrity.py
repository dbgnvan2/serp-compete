import pytest
import json
import os

SHARED_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))

def test_config_exists():
    assert os.path.exists(SHARED_CONFIG_PATH), "shared_config.json is missing from root"

def test_gsc_config_integrity():
    with open(SHARED_CONFIG_PATH, 'r') as f:
        config = json.load(f)
    
    auth = config.get("auth", {})
    property_url = auth.get("gsc_property_url", "")
    
    # Requirement: GSC Property URL must be a valid HTTPS URL
    assert property_url.startswith("https://"), "GSC Property URL must use HTTPS"
    assert property_url.endswith("/"), "GSC Property URL should end with a trailing slash for GSC consistency"
    
    # Requirement, rewritten 2026-11-16: the client-secret path must be SAFE to
    # commit, which means it is normally EMPTY.
    #
    # This asserted the opposite — that the key carries a path, "absolute or
    # point[ing] to an existing file" — and so pinned in place the absolute
    # path to one developer's machine that `shared_config.json` shipped:
    # `/Users/<name>/ProjectsLocal/serp-compete/client_secret_<id>.apps.
    # googleusercontent.com.json`. That published the developer's local username
    # and the OAuth client ID in a file that is committed and pushed, and it
    # broke GSC auth on every other machine, because a configured-but-missing
    # path is truthy and `_authenticate`'s discovery fallback was skipped.
    #
    # `gsc_performance.find_client_secrets` finds `gsc_auth.json` or any
    # `client_secret_*.json` in the working directory or the repo root, so an
    # empty value is the working value. Set it only to reach a file OUTSIDE the
    # repo, and then keep it relative.
    secrets_path = auth.get("gsc_client_secrets", "")
    assert "gsc_client_secrets" in auth, (
        "the key must exist, even empty, so its comment stays discoverable")
    if secrets_path:
        assert not os.path.isabs(secrets_path), (
            "an absolute path here is machine-specific and ships in a committed "
            "file — leave it empty and let discovery find the secret")
        for marker in ("/Users/", "/home/", "C:\\Users"):
            assert marker not in secrets_path, (
                "this publishes a developer's local username")
        assert "apps.googleusercontent.com" not in secrets_path, (
            "this publishes the OAuth client ID")
    
def test_clinical_dictionary_integrity():
    CLINICAL_DICT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "clinical_dictionary.json"))
    assert os.path.exists(CLINICAL_DICT_PATH), "clinical_dictionary.json is missing from root"
    
    with open(CLINICAL_DICT_PATH, 'r') as f:
        data = json.load(f)
    
    assert "tier_1_medical" in data
    assert "tier_2_systems" in data
    assert "tier_3_bowen" in data
    assert len(data["tier_1_medical"]) > 0, "Clinical dictionary is empty"
