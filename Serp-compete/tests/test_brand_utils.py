"""Tests for src/brand_utils.derive_brand_name — the one canonical brand-token derivation.

Adjacent-fix #2 (P7/P4): the suffix strip is now case-INSENSITIVE (a prior case-sensitive
strip silently mis-derived mixed-case domains), and the suffix vocabulary is config-driven
(shared_config `brand.name_suffixes`) instead of hardcoded in logic. These tests lock the
case fix, the config override, and parity with the historical multi-suffix behavior.
"""
import pytest

from src.brand_utils import DEFAULT_NAME_SUFFIXES, derive_brand_name


@pytest.mark.parametrize("domain,expected", [
    ("jerichocounselling.com", "jericho"),   # default vocab, 'counselling' stripped
    ("bowentherapy.org", "bowen"),           # 'therapy' stripped
    ("theravive.com", "theravive"),          # no suffix → domain stem
    ("SomePractice.CA", "somepractice"),     # lowercased
    (None, ""),                               # None-safe
    ("", ""),
])
def test_derive_brand_name_defaults(domain, expected):
    assert derive_brand_name(domain) == expected


@pytest.mark.parametrize("domain", [
    "JerichoCounselling.com", "JERICHOCOUNSELLING.COM", "jerichoCOUNSELLING.com",
])
def test_case_insensitive_suffix_strip(domain):
    """Adjacent-fix #2: the suffix strip must be case-insensitive — every casing of
    'jerichocounselling' derives 'jericho'. The pre-fix code stripped on the raw stem, so
    'JerichoCounselling' kept its suffix and derived the wrong brand."""
    assert derive_brand_name(domain) == "jericho"


def test_config_suffixes_override_default():
    """A caller (the run path) passes shared_config `brand.name_suffixes`; only those strip."""
    assert derive_brand_name("acmetherapy.com", ["therapy"]) == "acme"
    # 'counselling' is NOT in the passed list, so it is left intact:
    assert derive_brand_name("acmecounselling.com", ["therapy"]) == "acmecounselling"


def test_empty_suffix_list_disables_stripping():
    """An explicit empty list (config choice) means 'derive nothing' — brand == domain stem,
    NOT the default vocab. Guards against `name[:-0]` wiping the whole stem too."""
    assert derive_brand_name("acmetherapy.com", []) == "acmetherapy"


def test_stacked_suffixes_strip_in_order():
    """Parity with the historical loop: stacked suffixes reduce past each match in list order."""
    assert derive_brand_name("xtherapycounselling.com") == "x"


def test_default_suffixes_are_lowercase_vocab():
    """The default vocab is editorial config mirrored from shared_config `brand.name_suffixes`;
    it must stay lowercase for the case-insensitive compare to behave."""
    assert all(s == s.lower() for s in DEFAULT_NAME_SUFFIXES)
