"""
SC-1 — GEO / extractability profiling.

Spec: suite_enhancement_spec_v1.md#SC-1 (per-repo:
suite_enhancement_spec_SERPCOMPETE_v1.md).

Aggregates the structural signals AI answer engines use when deciding whether a
competitor page is quotable/citable — schema types, credentialed authorship,
question-shaped headings, and content freshness — into a per-page GEO profile
and a plain-language "why this page gets cited" rationale for the strategic
briefing. It reuses signals already extracted into a scraped page
(``outline`` + ``metadata``); it performs **no** additional network fetch.

Design notes
------------
* Duck-typed input: ``profile_page`` accepts any object exposing ``url``,
  ``extraction_status``, ``outline`` (list of ``{"level","text","order"}``) and
  ``metadata`` (dict). This deliberately avoids importing ``src.semantic`` (and
  therefore spaCy) so the profiler and its tests stay lightweight.
* Editorial content lives in config (``geo_signals`` + the shared
  ``credential_list``), per the project convention — no hardcoded vocab beyond
  the safe fallbacks below.

HONESTY CAVEAT: these are heuristic structural proxies for *why* an AI engine
might cite a page, not a measured citation. Two signals named in the SC-1 spec —
answer-first placement and FAQ-answers-in-raw-HTML — require DOM-position / JS
render analysis that the current scraper does not capture. They are reported in
``not_measured`` rather than approximated with a weak proxy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Safe fallbacks used only when shared_config omits the editorial lists.
DEFAULT_INTERROGATIVES = [
    "how", "what", "why", "when", "where", "who", "which",
    "can", "does", "do", "is", "are", "should", "will",
]
DEFAULT_STRONG_TIER_MIN = 3
DEFAULT_MODERATE_TIER_MIN = 1

# Signals from the SC-1 spec that need extraction the scraper does not do yet.
NOT_MEASURED = ["answer_first_placement", "faq_answers_in_raw_html"]


@dataclass
class GeoProfile:
    """Per-page GEO / extractability signal record."""
    url: str
    profiled_at: str  # ISO 8601
    extractability_tier: str  # "Strong" | "Moderate" | "Weak" | "Unknown"
    signals: Dict[str, Any]
    present_signals: List[str]
    why_cited: str
    not_measured: List[str] = field(default_factory=lambda: list(NOT_MEASURED))
    caveat: str = (
        "Heuristic structural proxy for AI citability, not a measured citation."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "profiled_at": self.profiled_at,
            "extractability_tier": self.extractability_tier,
            "signals": self.signals,
            "present_signals": self.present_signals,
            "why_cited": self.why_cited,
            "not_measured": self.not_measured,
            "caveat": self.caveat,
        }


class GeoProfiler:
    """Compute a GEO / extractability profile from an already-scraped page."""

    def __init__(self, config: Dict[str, Any]):
        geo = config.get("geo_signals", {}) or {}
        self.interrogatives = [
            w.lower() for w in geo.get("interrogatives", DEFAULT_INTERROGATIVES)
        ]
        self.strong_tier_min = geo.get("strong_tier_min_signals", DEFAULT_STRONG_TIER_MIN)
        self.moderate_tier_min = geo.get("moderate_tier_min_signals", DEFAULT_MODERATE_TIER_MIN)
        # Reuse the same credential vocabulary the EEAT scorer uses.
        self.credential_list = config.get("credential_list", [])

    # ── public API ──────────────────────────────────────────────────────────
    def profile_page(self, page: Any) -> GeoProfile:
        """Return a GeoProfile for a scraped page (duck-typed: see module docs)."""
        profiled_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        url = getattr(page, "url", "") or ""
        status = getattr(page, "extraction_status", "error")

        # Blocked / errored scrapes carry no reliable structure — state that,
        # never fabricate signals (data_available honesty).
        if status in ("blocked", "error"):
            return GeoProfile(
                url=url,
                profiled_at=profiled_at,
                extractability_tier="Unknown",
                signals=self._empty_signals(),
                present_signals=[],
                why_cited="Page could not be fully retrieved; extractability not assessed.",
            )

        metadata = getattr(page, "metadata", {}) or {}
        outline = getattr(page, "outline", []) or []
        schema_types = metadata.get("schema_types", []) or []

        # ── schema ───────────────────────────────────────────────────────────
        has_faq = bool(metadata.get("has_faq_schema"))
        has_article = bool(metadata.get("has_article_schema"))
        has_localbusiness = bool(metadata.get("has_localbusiness_schema"))
        has_person = "Person" in schema_types
        has_org = "Organization" in schema_types
        has_high_value_schema = any(
            [has_faq, has_article, has_localbusiness, has_person, has_org]
        )

        # ── credentialed authorship ───────────────────────────────────────────
        byline = metadata.get("author_byline") or ""
        matched_credentials = self._match_credentials(byline)
        has_author_byline = bool(byline)
        credentialed_author = len(matched_credentials) > 0

        # ── question-shaped headings (from the h2/h3 outline) ──────────────────
        q_headings, subhead_count = self._count_question_headings(outline)
        question_heading_ratio = (
            round(q_headings / subhead_count, 3) if subhead_count else 0.0
        )
        has_question_headings = q_headings > 0

        # ── freshness ─────────────────────────────────────────────────────────
        has_publish_date = bool(metadata.get("publish_date"))
        has_update_date = bool(metadata.get("update_date"))
        is_fresh = has_publish_date or has_update_date

        signals = {
            "schema_types": schema_types,
            "has_faq_schema": has_faq,
            "has_article_schema": has_article,
            "has_localbusiness_schema": has_localbusiness,
            "has_person_schema": has_person,
            "has_org_schema": has_org,
            "has_author_byline": has_author_byline,
            "matched_credentials": matched_credentials,
            "question_heading_count": q_headings,
            "subheading_count": subhead_count,
            "question_heading_ratio": question_heading_ratio,
            "has_publish_date": has_publish_date,
            "has_update_date": has_update_date,
        }

        # Present high-value signals → tier + human rationale.
        present: List[str] = []
        if has_high_value_schema:
            present.append(self._schema_label(has_faq, has_article, has_org, has_person, has_localbusiness))
        if credentialed_author:
            present.append(f"credentialed author ({', '.join(matched_credentials)})")
        elif has_author_byline:
            present.append("named author byline")
        if has_question_headings:
            present.append(f"{q_headings} question-shaped heading{'s' if q_headings != 1 else ''}")
        if is_fresh:
            present.append("dated / fresh content")

        tier = self._tier(len(present))
        why_cited = self._why_cited(present, tier)

        return GeoProfile(
            url=url,
            profiled_at=profiled_at,
            extractability_tier=tier,
            signals=signals,
            present_signals=present,
            why_cited=why_cited,
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    def _match_credentials(self, byline: str) -> List[str]:
        if not byline:
            return []
        found = []
        low = byline.lower()
        for cred in self.credential_list:
            if re.search(r"\b" + re.escape(cred.lower()) + r"\b", low):
                found.append(cred)
        return found

    def _count_question_headings(self, outline: List[Dict[str, Any]]) -> "tuple[int, int]":
        """Count h2/h3 headings that read as questions. Returns (q_count, subhead_count)."""
        q = 0
        subheads = 0
        for h in outline:
            if not isinstance(h, dict):
                continue
            if h.get("level") not in ("h2", "h3"):
                continue
            subheads += 1
            text = (h.get("text") or "").strip().lower()
            if not text:
                continue
            first_word = re.split(r"[^\w]+", text, maxsplit=1)[0]
            # P7 (gameable proxy): require an actual question mark AND an
            # interrogative/auxiliary opener. A declarative heading that merely
            # starts with an interrogative word ("How We Help", "Why differentiation
            # matters", "What Sets Us Apart") is NOT a citable Q&A heading and must
            # not inflate the extractability tier. Precision over recall here — a
            # citability proxy that over-triggers rewards the wrong page.
            if text.endswith("?") and first_word in self.interrogatives:
                q += 1
        return q, subheads

    def _schema_label(self, faq, article, org, person, local) -> str:
        types = []
        if faq:
            types.append("FAQPage")
        if article:
            types.append("Article")
        if org:
            types.append("Organization")
        if person:
            types.append("Person")
        if local:
            types.append("LocalBusiness")
        return "schema markup (" + ", ".join(types) + ")"

    def _tier(self, n_present: int) -> str:
        if n_present >= self.strong_tier_min:
            return "Strong"
        if n_present >= self.moderate_tier_min:
            return "Moderate"
        return "Weak"

    def _why_cited(self, present: List[str], tier: str) -> str:
        if not present:
            return (
                "No strong extractability signals detected — this page carries "
                "little structural advantage for AI citation, so a well-structured "
                "systemic alternative can compete on citability."
            )
        joined = "; ".join(present)
        return (
            f"{tier} extractability: {joined}. These structures make the page "
            f"easy for AI answer engines to quote — match or exceed them on the "
            f"client's equivalent page."
        )

    def _empty_signals(self) -> Dict[str, Any]:
        return {
            "schema_types": [],
            "has_faq_schema": False,
            "has_article_schema": False,
            "has_localbusiness_schema": False,
            "has_person_schema": False,
            "has_org_schema": False,
            "has_author_byline": False,
            "matched_credentials": [],
            "question_heading_count": 0,
            "subheading_count": 0,
            "question_heading_ratio": 0.0,
            "has_publish_date": False,
            "has_update_date": False,
        }
