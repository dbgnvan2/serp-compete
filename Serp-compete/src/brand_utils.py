"""Brand-name derivation — a dependency-free helper.

Purpose: derive a comparable brand token from a domain ('jerichocounselling.com' -> 'jericho')
         for C1 AI Share-of-Voice and C3 Branded-Demand. Deliberately imports NOTHING heavy
         (no pandas / API clients), so the run path can use it without dragging in the offline
         mining script's deps — its import is safe to sit outside the per-feature guards (P13).
Spec:    suite_enhancement_spec_v1.md#C1 / #C3
Tests:   tests/test_brand_utils.py
"""
from __future__ import annotations

from urllib.parse import urlparse

from typing import Iterable, Optional

# Editorial vocab (P4): practice-name suffixes stripped from a domain stem to get the bare
# brand. shared_config.json `brand.name_suffixes` is authoritative on the run path; this
# constant mirrors it as the fallback for callers that run without loading config
# (e.g. competitor_mining.py, the standalone keyword-gap script).
DEFAULT_NAME_SUFFIXES = (
    "counselling", "counseling", "therapy", "counselor", "counsellor", "psychology",
)


def _stem_and_suffixes(domain: str,
                       suffixes: Optional[Iterable[str]] = None) -> tuple[str, list]:
    """Internal: (bare stem, suffixes stripped in strip order).

    `normalise_domain` runs FIRST, so a `www.` host derives from its real stem.
    Without it `www.jerichocounselling.com` derived the brand 'www' (C-C-01) —
    15 of 34 domains in a real Tool 1 handoff carry that prefix, and every one
    of them got the same meaningless brand.
    """
    name = normalise_domain(domain).split(".")[0]
    stripped: list = []
    for suffix in (DEFAULT_NAME_SUFFIXES if suffixes is None else suffixes):
        s = str(suffix).lower()
        if s and name.endswith(s) and name != s:
            name = name[: -len(s)]
            stripped.append(s)
    return name, stripped


def derive_brand_name(domain: str, suffixes: Optional[Iterable[str]] = None) -> str:
    """'jerichocounselling.com' -> 'jericho'; 'www.jerichocounselling.com' -> 'jericho'.

    - None-safe: a None/empty domain returns ''.
    - The domain is normalised first (lower-cased, `www.` stripped), so the two
      spellings Tool 1 can emit for the same site derive the same brand (C-C-01).
    - The suffix strip is case-INSENSITIVE: 'JerichoCounselling.com' derives the same
      'jericho' as the lowercase form. (A prior case-sensitive strip on the raw stem
      silently mis-derived mixed-case domains — 'JerichoCounselling' kept its suffix.)
    - `suffixes` overrides the default vocab (pass shared_config `brand.name_suffixes`);
      None uses DEFAULT_NAME_SUFFIXES, an explicit empty list disables stripping.

    Every matching suffix is stripped in order (mirrors the original behaviour), so a
    stacked stem like 'xtherapycounselling' reduces past both. A stem that IS a suffix
    ('therapy.com') keeps it rather than deriving '' — an empty brand matches nothing.
    """
    return _stem_and_suffixes(domain, suffixes)[0]


def derive_display_brand(domain: str, suffixes: Optional[Iterable[str]] = None) -> str:
    """'lavendercounselling.com' -> 'Lavender Counselling' — the brand as searched.

    The bare token `derive_brand_name` returns is for *matching* (comparing an
    export's brand to a domain). It is the wrong string to send to a search-volume
    API: 'lavender', 'bach', 'clear', 'coast' are dictionary words, so their volume
    is demand for plants, composers and shorelines, not for a counselling practice
    (C-M-03). This reassembles the stem into the practice name instead.

    No suffix matched ('hollyburn.ca') → the token title-cased ('Hollyburn'); the
    display brand then equals the token, which is what the ambiguous-brand gate in
    `brand_demand` exists to catch.
    """
    token, stripped = _stem_and_suffixes(domain, suffixes)
    if not token:
        return ""
    return " ".join(part.title() for part in [token, *reversed(stripped)])


#: Host prefixes the web treats as aliases of the apex. Must stay identical to
#: serp-discover's `domain_utils.ALIAS_PREFIXES` — the producer and the
#: consumer disagreeing about which host is which is what chunk X was about.
ALIAS_PREFIXES = ("www.", "m.")


def normalise_domain(domain) -> str:
    """Lower-cased, www-stripped domain, for comparing domains from two sources.

    Tool 1 emits target domains as `urlparse(url).netloc.lower()`, so many
    carry a `www.` prefix; `omitted_domains.txt` holds bare domains. Comparing
    them raw let four entries on the omit list through — including
    psychologytoday.com — so a directory the client explicitly excluded could
    be audited and named in the report (P3/P6).

    Review chunk Y1: `m.` is stripped too, and prefixes are stripped to a
    fixed point, matching serp-discover's `domain_utils.normalize_domain`
    exactly. A mobile host that this side counted as a separate competitor
    while the producer counted it as the apex is the same join failure chunk X
    fixed for `www.`. A prefix is only stripped when something that can still
    be a site is left: `m.ca` is a registrable domain whose first label
    happens to be "m".

    The cold review of Y1 found this function mirrored only the prefix list:
    it kept a scheme, a path, a port and userinfo, so `https://m.x.ca/p` came
    back whole here and as `x.ca` on the producer's side. The whole rule is
    mirrored now — netloc, no userinfo, no port, and free text (anything with
    a space in it) is not a host and comes back `""`. `tests/
    test_handoff_contract.py` asserts the two sides agree over a shared case
    table, rather than grepping the sibling repo for a constant.
    """
    raw = str(domain or "").strip()
    if not raw or any(ch.isspace() for ch in raw):
        return ""
    if "//" in raw:
        host = urlparse(raw).netloc
    elif "/" in raw:
        host = urlparse("//" + raw).netloc
    else:
        host = raw
    host = host.lower()
    if "@" in host:                         # userinfo@host
        host = host.rsplit("@", 1)[-1]
    if host.startswith("["):                # IPv6 literal, keep the brackets
        head, _, _port = host.partition("]")
        host = head + "]"
    elif ":" in host:
        host = host.split(":", 1)[0]
    changed = True
    while changed:
        changed = False
        for prefix in ALIAS_PREFIXES:
            if host.startswith(prefix) and "." in host[len(prefix):]:
                host = host[len(prefix):]
                changed = True
                break
    return host
