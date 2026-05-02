"""
Gap 3 — EEAT heuristic scoring.

Computes Experience, Expertise, Authoritativeness, and Trustworthiness scores
from page-level signals extracted during scraping.

IMPORTANT CAVEAT: These are heuristic proxies based on SEO industry conventions,
NOT Google's actual EEAT model. Google does not publish its exact EEAT criteria.
Use these scores as competitive structural signals, not as authoritative SEO measurements.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Literal, Optional
from urllib.parse import urlparse

from src.semantic import ScrapedPage


@dataclass
class EEATScore:
    """Per-page EEAT signal record."""
    url: str
    scored_at: str  # ISO 8601
    experience_signals: Dict[str, Any]
    expertise_signals: Dict[str, Any]
    authoritativeness_signals: Dict[str, Any]
    trustworthiness_signals: Dict[str, Any]
    scores: Dict[str, Optional[float]]  # experience, expertise, authoritativeness, trustworthiness
    score_confidence: Literal["high", "medium", "low"]
    caveat: str = "Heuristic proxy. Not Google's actual EEAT model."

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "scored_at": self.scored_at,
            "experience_signals": self.experience_signals,
            "expertise_signals": self.expertise_signals,
            "authoritativeness_signals": self.authoritativeness_signals,
            "trustworthiness_signals": self.trustworthiness_signals,
            "scores": self.scores,
            "score_confidence": self.score_confidence,
            "caveat": self.caveat
        }


class EEATScorer:
    """Score pages on EEAT heuristics from extracted page structure."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scorer with configuration.

        Args:
            config: shared_config.json with eeat_weights, stock_image_hosts, etc.
        """
        self.weights = config.get("eeat_weights", {})
        self.stock_image_hosts = set(config.get("stock_image_hosts", []))
        self.credential_list = config.get("credential_list", [])
        self.case_study_triggers = config.get("case_study_triggers", [])
        clinical = config.get("clinical", {})
        self.tier_2_terms = clinical.get("tier_2_systems", [])
        self.tier_3_terms = clinical.get("tier_3_bowen", [])

    def score_page(self, page: ScrapedPage, domain_authority: Optional[int] = None) -> EEATScore:
        """
        Score a ScrapedPage on EEAT dimensions.

        Args:
            page: ScrapedPage object from scraping
            domain_authority: Optional domain authority score (0-100)

        Returns:
            EEATScore with signals and computed scores
        """
        scored_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # If page failed to scrape, return low-confidence empty scores
        if page.extraction_status in ("blocked", "error"):
            return EEATScore(
                url=page.url,
                scored_at=scored_at,
                experience_signals=self._build_empty_experience_signals(),
                expertise_signals=self._build_empty_expertise_signals(),
                authoritativeness_signals=self._build_empty_authoritativeness_signals(domain_authority),
                trustworthiness_signals=self._build_empty_trustworthiness_signals(),
                scores={"experience": None, "expertise": None, "authoritativeness": None, "trustworthiness": None},
                score_confidence="low"
            )

        # Extract signals from page metadata and text
        experience_signals = self._extract_experience_signals(page)
        expertise_signals = self._extract_expertise_signals(page)
        authoritativeness_signals = self._extract_authoritativeness_signals(page, domain_authority)
        trustworthiness_signals = self._extract_trustworthiness_signals(page)

        # Compute weighted scores
        experience_score = self._compute_weighted_score("experience", experience_signals)
        expertise_score = self._compute_weighted_score("expertise", expertise_signals)
        authoritativeness_score = self._compute_weighted_score("authoritativeness", authoritativeness_signals)
        trustworthiness_score = self._compute_weighted_score("trustworthiness", trustworthiness_signals)

        scores = {
            "experience": experience_score,
            "expertise": expertise_score,
            "authoritativeness": authoritativeness_score,
            "trustworthiness": trustworthiness_score
        }

        # Determine confidence level
        null_count = sum(1 for s in scores.values() if s is None)
        if null_count == 0:
            confidence = "high"
        elif null_count == 4:
            confidence = "low"
        else:
            confidence = "medium"

        return EEATScore(
            url=page.url,
            scored_at=scored_at,
            experience_signals=experience_signals,
            expertise_signals=expertise_signals,
            authoritativeness_signals=authoritativeness_signals,
            trustworthiness_signals=trustworthiness_signals,
            scores=scores,
            score_confidence=confidence
        )

    def _extract_experience_signals(self, page: ScrapedPage) -> Dict[str, Any]:
        """Extract experience signals from page."""
        metadata = page.metadata
        text = page.first_500_words.lower()

        # First-person count
        first_person_count = self._count_first_person(text)

        # Original images heuristic
        has_original_images = self._detect_original_images(metadata)

        # Case study signal
        case_study_signal = self._detect_case_study(text)

        return {
            "has_author_byline": bool(metadata.get("author_byline")),
            "has_publish_date": bool(metadata.get("publish_date")),
            "has_update_date": bool(metadata.get("update_date")),
            "has_likely_original_images": has_original_images,
            "first_person_count_normalised": first_person_count / 10.0,  # capped at 10
            "case_study_signal": case_study_signal
        }

    def _extract_expertise_signals(self, page: ScrapedPage) -> Dict[str, Any]:
        """Extract expertise signals from page."""
        metadata = page.metadata
        text = page.first_500_words.lower()

        # Credentials in byline
        byline = metadata.get("author_byline", "")
        credentials = self._extract_credentials(byline) if byline else []

        # Schema author type — boolean: Person schema present
        schema_author_type_person = "Person" in metadata.get("schema_types", [])

        # Tier counts from text
        tier_2_count = self._count_tier_mentions(text, tier="tier_2")
        tier_3_count = self._count_tier_mentions(text, tier="tier_3")

        return {
            "has_credentials_in_byline": len(credentials) > 0,
            "matched_credentials": credentials,  # informational, not scored
            "schema_author_type_person": schema_author_type_person,
            "tier_3_or_tier_2_present": (tier_3_count > 0 or tier_2_count > 0)
        }

    def _extract_authoritativeness_signals(self, page: ScrapedPage, domain_authority: Optional[int]) -> Dict[str, Any]:
        """Extract authoritativeness signals from page."""
        metadata = page.metadata

        # Schema organization present
        has_org_schema = "Organization" in metadata.get("schema_types", [])

        # Normalise: DA 60+ → 1.0 (spec: min(da/60, 1.0)); 5+ external links → 1.0
        da_normalised = min(domain_authority / 60.0, 1.0) if domain_authority is not None else None
        ext_links = metadata.get("external_link_count", 0)
        ext_link_normalised = min(ext_links / 5.0, 1.0)

        return {
            "domain_authority_normalised": da_normalised,
            "external_link_count_normalised": ext_link_normalised,
            "schema_organization_present": has_org_schema
        }

    def _extract_trustworthiness_signals(self, page: ScrapedPage) -> Dict[str, Any]:
        """Extract trustworthiness signals from page."""
        metadata = page.metadata

        return {
            "is_https": metadata.get("is_https", False),
            "has_contact_link": metadata.get("has_contact_link", False),
            "has_privacy_link": metadata.get("has_privacy_link", False)
        }

    def _compute_weighted_score(self, dimension: str, signals: Dict[str, Any]) -> Optional[float]:
        """Compute weighted score for a dimension."""
        weights = self.weights.get(dimension, {})
        if not weights:
            return None

        total_weight = 0
        total_value = 0
        evaluable_signals = 0
        total_signals = 0

        for signal_name, weight in weights.items():
            total_signals += 1
            value = signals.get(signal_name)

            if value is None:
                continue

            evaluable_signals += 1

            # Normalize boolean to float; floats/ints pass through (already normalised)
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                value = float(value)

            total_weight += weight
            total_value += value * weight

        # If fewer than half signals could be evaluated, return None
        if evaluable_signals < (total_signals / 2):
            return None

        # Normalize to 0.0-1.0
        if total_weight > 0:
            return min(total_value / total_weight, 1.0)
        return None

    def _count_first_person(self, text: str) -> int:
        """Count first-person pronouns (I, we, our, us)."""
        # Word-bounded matching to avoid false positives
        pattern = r'\b(i|we|our|us)\b'
        matches = re.findall(pattern, text, re.IGNORECASE)
        # Cap at 10 for normalization purposes
        return min(len(matches), 10)

    def _detect_original_images(self, metadata: Dict[str, Any]) -> bool:
        """Detect whether images are likely original vs stock."""
        image_hosts = metadata.get("image_hosts", [])
        image_count = metadata.get("image_count", 0)

        if image_count == 0:
            return False

        if not image_hosts:
            return True  # No hosts found = likely original

        # Count stock image hosts
        stock_count = sum(1 for host in image_hosts if host in self.stock_image_hosts)

        # If ≥80% are stock hosts, likely not original
        if len(image_hosts) > 0:
            stock_ratio = stock_count / len(image_hosts)
            return stock_ratio < 0.8

        return True

    def _detect_case_study(self, text: str) -> bool:
        """Detect case study signals."""
        for trigger in self.case_study_triggers:
            if trigger.lower() in text:
                return True
        return False

    def _extract_credentials(self, byline: str) -> List[str]:
        """Extract credential abbreviations/titles from byline."""
        credentials = []
        byline_lower = byline.lower()
        for cred in self.credential_list:
            # Match with word boundaries
            pattern = r'\b' + re.escape(cred) + r'\b'
            if re.search(pattern, byline_lower, re.IGNORECASE):
                credentials.append(cred)
        return credentials

    def _count_tier_mentions(self, text: str, tier: str) -> int:
        """Count mentions of tier-specific terms in text (capped at 10)."""
        terms = self.tier_2_terms if tier == "tier_2" else self.tier_3_terms if tier == "tier_3" else []
        count = 0
        for term in terms:
            term_lower = term.lower()
            if " " in term_lower:
                count += text.count(term_lower)
            else:
                count += len(re.findall(r'\b' + re.escape(term_lower) + r'\b', text))
        return min(count, 10)

    def _build_empty_experience_signals(self) -> Dict[str, Any]:
        """Build empty experience signals (for failed extractions)."""
        return {
            "has_author_byline": False,
            "has_publish_date": False,
            "has_update_date": False,
            "has_likely_original_images": False,
            "first_person_count_normalised": 0.0,
            "case_study_signal": False
        }

    def _build_empty_expertise_signals(self) -> Dict[str, Any]:
        """Build empty expertise signals."""
        return {
            "has_credentials_in_byline": False,
            "matched_credentials": [],
            "schema_author_type_person": False,
            "tier_3_or_tier_2_present": False
        }

    def _build_empty_authoritativeness_signals(self, da: Optional[int]) -> Dict[str, Any]:
        """Build empty authoritativeness signals."""
        return {
            "domain_authority_normalised": (da / 100.0) if da is not None else None,
            "external_link_count_normalised": 0.0,
            "schema_organization_present": False
        }

    def _build_empty_trustworthiness_signals(self) -> Dict[str, Any]:
        """Build empty trustworthiness signals."""
        return {
            "is_https": False,
            "has_contact_link": False,
            "has_privacy_link": False
        }
