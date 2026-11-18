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



def _messages(messages=None):
    """The words, from `briefing_messages.json` (chunk Y17).

    Imported inside the function rather than at module scope so this module
    does not pull the messages file in at import time — a test that patches
    `builtins.open` around an unrelated call otherwise receives the read (the
    reason `GSCManager` holds its own instance).
    """
    if messages is not None:
        return messages
    from src.briefing_messages import Messages
    return Messages()

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
    #: Stored on the row, so it is read when the row is BUILT, not when the
    #: report renders. `extractability.profile_caveat` in
    #: `briefing_messages.json` (chunk Y17).
    caveat: str = field(
        default_factory=lambda: _messages().get(
            "extractability.profile_caveat"))

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
                why_cited=self._messages().get(
                    "extractability.why_cited_unreadable"),
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
        # C-M-14: a GENERIC byline is not credentialed authorship. "admin",
        # "editor", the site's own name — WordPress and Yoast emit these by
        # default, and counting them let a stock WP post out-score an FAQ page.
        has_author_byline = bool(byline) and not self._is_generic_byline(byline)
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

        # C-M-14: the tier is WEIGHTED, not a count of present signals. A stock
        # WordPress post (Organization + Person schema from Yoast, a byline of
        # "admin", a published_time, zero question headings) scored three signals and
        # read as Strong, while an FAQ page with FAQPage schema and two genuine
        # question headings but no byline or date read as Moderate. What an answer
        # engine quotes is a question-shaped, answer-first structure — so FAQPage
        # schema and question headings weigh more than an Organization stamp.
        tier = self._tier(self._signal_weight(
            has_faq=has_faq, has_question_headings=has_question_headings,
            q_headings=q_headings, has_article=has_article,
            has_localbusiness=has_localbusiness, has_person=has_person,
            has_org=has_org, credentialed_author=credentialed_author,
            has_author_byline=has_author_byline, is_fresh=is_fresh))
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

    def _tier(self, weight: float) -> str:
        if weight >= self.strong_tier_min:
            return "Strong"
        if weight >= self.moderate_tier_min:
            return "Moderate"
        return "Weak"

    # C-M-14: the weights. FAQPage schema and question-shaped headings are what make
    # a passage quotable; an Organization or Person stamp and a publish date are
    # ambient WordPress output. Editorial and uncalibrated, 2026-11-15 — these are a
    # judgement about what AI answer engines quote, not a measurement of citations
    # (the section header no longer claims otherwise, and `ai_citations` from the
    # serp-discover export is the only thing that could check it).
    _SIGNAL_WEIGHTS = {
        "faq_schema": 2.0,
        "question_headings": 1.5,
        "extra_question_headings": 0.5,   # a second and third question heading
        "credentialed_author": 1.0,
        "article_or_localbusiness_schema": 0.5,
        "org_or_person_schema": 0.25,
        "named_byline": 0.25,
        "fresh": 0.25,
    }

    def _signal_weight(self, has_faq: bool, has_question_headings: bool,
                       q_headings: int, has_article: bool, has_localbusiness: bool,
                       has_person: bool, has_org: bool, credentialed_author: bool,
                       has_author_byline: bool, is_fresh: bool) -> float:
        w = self._SIGNAL_WEIGHTS
        weight = 0.0
        if has_faq:
            weight += w["faq_schema"]
        if has_question_headings:
            weight += w["question_headings"]
            weight += min(max(q_headings - 1, 0), 2) * w["extra_question_headings"]
        if credentialed_author:
            weight += w["credentialed_author"]
        elif has_author_byline:
            weight += w["named_byline"]
        if has_article or has_localbusiness:
            weight += w["article_or_localbusiness_schema"]
        if has_org or has_person:
            weight += w["org_or_person_schema"]
        if is_fresh:
            weight += w["fresh"]
        return round(weight, 2)

    # Bylines that identify nobody (C-M-14).
    _GENERIC_BYLINES = ("admin", "administrator", "editor", "staff", "team",
                        "support", "webmaster", "author", "info", "office")

    def _is_generic_byline(self, byline: str) -> bool:
        text = " ".join(str(byline or "").lower().split())
        text = text.removeprefix("by ").strip(" -–—:")
        return text in self._GENERIC_BYLINES or not text

    def _messages(self):
        """The words, read once per profiler and held: this runs per page.

        `why_cited` is rendered verbatim into the briefing's extractability
        section, so the owner is the person who would reword it.
        """
        if getattr(self, "_messages_cache", None) is None:
            self._messages_cache = _messages()
        return self._messages_cache

    def _why_cited(self, present: List[str], tier: str) -> str:
        m = self._messages()
        if not present:
            return m.get("extractability.why_cited_none")
        # C-M-14: this sentence used to assert causation — "These structures make the
        # page easy for AI answer engines to quote" — under a section header reading
        # "Why Competitors Get Cited", while nothing here checks whether the page is
        # cited by anything. It states what was found and what it is believed to
        # support.
        return m.get("extractability.why_cited_signals", tier=tier,
                     joined="; ".join(present))

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
