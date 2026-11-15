"""Tests for src/brand_utils.derive_brand_name — the one canonical brand-token derivation.

Adjacent-fix #2 (P7/P4): the suffix strip is now case-INSENSITIVE (a prior case-sensitive
strip silently mis-derived mixed-case domains), and the suffix vocabulary is config-driven
(shared_config `brand.name_suffixes`) instead of hardcoded in logic. These tests lock the
case fix, the config override, and parity with the historical multi-suffix behavior.
"""
import pytest

from src.brand_utils import (
    DEFAULT_NAME_SUFFIXES, derive_brand_name, derive_display_brand, normalise_domain,
)


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


# ── C-C-01: `www.` hosts must not derive the brand "www" ─────────────────────
# Promotes docs/review_2026-11-04/probes/compete/probe_brand_www.py. Tool 1 writes
# `urlparse(url).netloc.lower()`, so 15 of 34 domains in the real handoff carry the
# prefix; every one of them derived the brand "www", which then drove branded demand,
# AI share-of-voice and the YouTube search term.

@pytest.mark.parametrize("domain,expected", [
    ("www.jerichocounselling.com", "jericho"),
    ("www.averytherapy.com", "avery"),
    ("www.psychologytoday.com", "psychologytoday"),
    ("WWW.JerichoCounselling.com", "jericho"),
])
def test_www_prefix_stripped_before_brand_derivation(domain, expected):
    assert derive_brand_name(domain) == expected


def test_www_and_bare_spellings_derive_the_same_brand():
    """The two forms Tool 1 can emit for one site must not become two brands."""
    assert derive_brand_name("www.jerichocounselling.com") == \
        derive_brand_name("jerichocounselling.com")


def test_two_different_www_domains_never_share_a_brand():
    """The failure that made every www competitor share one query set and one volume."""
    assert derive_brand_name("www.jerichocounselling.com") != \
        derive_brand_name("www.averytherapy.com")


def test_a_stem_that_is_itself_a_suffix_keeps_it():
    """An empty brand matches nothing, so 'therapy.com' derives 'therapy', not ''."""
    assert derive_brand_name("therapy.com") == "therapy"


# ── C-M-03: the display brand is what gets searched ──────────────────────────

@pytest.mark.parametrize("domain,expected", [
    ("lavendercounselling.com", "Lavender Counselling"),
    ("www.jerichocounselling.com", "Jericho Counselling"),
    ("bowentherapy.org", "Bowen Therapy"),
    ("hollyburn.ca", "Hollyburn"),            # no suffix → the token, title-cased
    ("xtherapycounselling.com", "X Therapy Counselling"),   # stacked, outermost last
    (None, ""),
])
def test_derive_display_brand(domain, expected):
    assert derive_display_brand(domain) == expected


def test_display_brand_differs_from_the_matching_token():
    """The bare token is for matching an export's brand to a domain; sending it to a
    search-volume API measures demand for a plant (C-M-03)."""
    assert derive_brand_name("lavendercounselling.com") == "lavender"
    assert derive_display_brand("lavendercounselling.com") == "Lavender Counselling"


def test_normalise_domain_is_the_one_canonical_form():
    assert normalise_domain(" WWW.Example.COM ") == "example.com"


def test_default_suffixes_are_lowercase_vocab():
    """The default vocab is editorial config mirrored from shared_config `brand.name_suffixes`;
    it must stay lowercase for the case-insensitive compare to behave."""
    assert all(s == s.lower() for s in DEFAULT_NAME_SUFFIXES)
