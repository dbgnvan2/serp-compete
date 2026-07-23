"""Brand-name derivation — a dependency-free helper.

Purpose: derive a comparable brand token from a domain ('jerichocounselling.com' -> 'jericho')
         for C1 AI Share-of-Voice and C3 Branded-Demand. Deliberately imports NOTHING heavy
         (no pandas / API clients), so the run path can use it without dragging in the offline
         mining script's deps — its import is safe to sit outside the per-feature guards (P13).
Spec:    suite_enhancement_spec_v1.md#C1 / #C3
Tests:   tests/test_brand_utils.py
"""
from __future__ import annotations

from typing import Iterable, Optional

# Editorial vocab (P4): practice-name suffixes stripped from a domain stem to get the bare
# brand. shared_config.json `brand.name_suffixes` is authoritative on the run path; this
# constant mirrors it as the fallback for callers that run without loading config
# (e.g. competitor_mining.py, the standalone keyword-gap script).
DEFAULT_NAME_SUFFIXES = (
    "counselling", "counseling", "therapy", "counselor", "counsellor", "psychology",
)


def derive_brand_name(domain: str, suffixes: Optional[Iterable[str]] = None) -> str:
    """'jerichocounselling.com' -> 'jericho'.

    - None-safe: a None/empty domain returns ''.
    - The suffix strip is case-INSENSITIVE: 'JerichoCounselling.com' derives the same
      'jericho' as the lowercase form. (A prior case-sensitive strip on the raw stem
      silently mis-derived mixed-case domains — 'JerichoCounselling' kept its suffix.)
    - `suffixes` overrides the default vocab (pass shared_config `brand.name_suffixes`);
      None uses DEFAULT_NAME_SUFFIXES, an explicit empty list disables stripping.

    Every matching suffix is stripped in order (mirrors the original behaviour), so a
    stacked stem like 'xtherapycounselling' reduces past both.
    """
    name = str(domain or "").split(".")[0].lower()
    for suffix in (DEFAULT_NAME_SUFFIXES if suffixes is None else suffixes):
        s = str(suffix).lower()
        if s and name.endswith(s):
            name = name[: -len(s)]
    return name
