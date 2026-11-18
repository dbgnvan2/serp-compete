"""Scoring: the weighted vocabulary score and the Surface-Level penalty.

Every editorial number here — the tier weights, the penalty thresholds and the
clinical vocabulary itself — is read from `shared_config.json` **when it is
used**, not when this module is imported. On the scoring path that means once
per run: `SemanticAuditor` reads the config when it is built and passes the one
it holds to `calculate_weighted_score`, so a single score comes from a single
version of the file, and the read sits outside `scrape_content`'s per-page
`except Exception` (Y16 cold review, F1).

It used to be imported: `SHARED_CONFIG = load_shared_config()` ran at import
time into module globals, and the reader it used swallowed every exception and
returned `{}`. So a `shared_config.json` with a trailing comma meant every
competitor in the run was scored with the Python fallback weights and an EMPTY
clinical vocabulary — scoring every page 0, completing the run, and reporting
scores that reconciled with nothing the owner had configured. Nothing was
logged; the `except Exception: pass` was the only place that could have said
so. The same import-time read also meant that editing the config and
re-running inside one Streamlit process changed nothing, because the module
was already imported (P16, and the same shape as the bind-time trap of review
chunk Y4).

There is now **one** reader for this file — `config_io.load_config` — and it
raises on a file that exists and cannot be parsed, which is the rule
`database.load_shared_config` already documented: a caller reading an
editorial threshold must not silently score against a default. The one named
exception stays `database.config_for_lock_timeout`, because the lock wait is
not an editorial threshold.

Spec: docs/review_2026-11-04/PLAN_Y16_one_reader_for_the_shared_config.md
"""
import json
import logging
import os
from typing import Tuple

from src import config_io

logger = logging.getLogger(__name__)

DICTIONARY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "clinical_dictionary.json")


def shared_config():
    """`shared_config.json`, read now. Raises on a file it cannot parse.

    The reader is reached through the MODULE, not a name imported from it:
    `from src.config_io import load_config` binds at import, so patching
    the one reader did not reach the scoring path and a test that thought
    it had made the file unreadable was testing nothing (P43; Y16 cold
    review).
    """
    return config_io.load_config()


#: The tier weights, if the config is unreadable or says nothing. Verbatim
#: equal to `shared_config.json`'s own values, enforced by a test: otherwise
#: "degrades to the documented default" degrades to a different number than
#: the document.
DEFAULT_WEIGHTS = {
    "tier_1_medical": 1.0,
    "tier_2_systems": 0.5,
    "tier_3_bowen": 2.0,
}
DEFAULT_PENALTY_CFG = {
    "tier_1_max": 10,
    "tier_2_penalty_multiplier": 0.5,
}
# The Surface-Level trigger as a density per 1000 scored words (C-M-19). The default
# mirrors shared_config `technical.penalty_thresholds.tier_1_max_density_per_1000`;
# see that key's `_source` note for how the number was set.
DEFAULT_TIER_1_MAX_DENSITY = 12.0
# The density needs a minimum numerator too (see calculate_weighted_score).
DEFAULT_TIER_1_MIN_HITS = 3


def load_dictionary(config=None):
    """The three clinical tiers: `shared_config.json` first, then
    `clinical_dictionary.json`.

    *config* is the already-loaded config, so a caller holding it does not
    re-read the file (P25 — one config→argument mapping).
    """
    config = shared_config() if config is None else config
    clinical = config.get("clinical", {}) or {}
    if clinical:
        return {
            "tier_1_medical": clinical.get("tier_1_medical", []),
            "tier_2_systems": clinical.get("tier_2_systems", []),
            "tier_3_bowen_expert": clinical.get("tier_3_bowen", [])
        }

    # Fallback to clinical_dictionary.json. A file that exists and cannot be
    # read RAISES, the same rule as the config itself: this was
    # `except Exception: pass` followed by three empty lists, so "the
    # dictionary file is corrupt" and "the owner configured no vocabulary"
    # were one value, every page scored 0 / `Standard`, and the run reported
    # that as a measurement (P40 + P2; Y16 cold review, F6).
    if os.path.exists(DICTIONARY_PATH):
        with open(DICTIONARY_PATH, "r") as f:
            data = json.load(f)
        return {
            "tier_1_medical": data.get("tier_1_medical", []),
            "tier_2_systems": data.get("tier_2_systems", []),
            "tier_3_bowen_expert": data.get("tier_3_bowen", [])
        }

    # Neither source holds a vocabulary. That is a legitimate state — an
    # owner may configure none, and `reframe_engine` reports it as
    # NO_MEDICAL_VOCABULARY_NOTE rather than a score — but it is not a
    # silent one: with no vocabulary every page scores 0 in all three tiers.
    logger.warning(
        "No clinical vocabulary: `shared_config.json` has no `clinical` "
        "block and %s does not exist. Every page will score 0 in all three "
        "tiers.", DICTIONARY_PATH)
    return {"tier_1_medical": [], "tier_2_systems": [], "tier_3_bowen_expert": []}


def clinical_tiers(config=None):
    """The three tiers as sets, read now."""
    data = load_dictionary(config)
    return (set(data.get("tier_1_medical", [])),
            set(data.get("tier_2_systems", [])),
            set(data.get("tier_3_bowen_expert", [])))


def weights(config=None):
    """`technical.scoring_weights`, read now."""
    config = shared_config() if config is None else config
    return ((config.get("technical", {}) or {}).get("scoring_weights")
            or DEFAULT_WEIGHTS)


def penalty_cfg(config=None):
    """`technical.penalty_thresholds`, read now."""
    config = shared_config() if config is None else config
    return ((config.get("technical", {}) or {}).get("penalty_thresholds")
            or DEFAULT_PENALTY_CFG)


def medical_density_per_1000(medical_count: int, window_words: int) -> float:
    """Tier-1 hits per 1000 scored words. 0.0 when the window is unknown."""
    if not window_words:
        return 0.0
    return 1000.0 * float(medical_count) / float(window_words)


def calculate_weighted_score(medical_count: int, t2_count: int, t3_count: int,
                             window_words: int = 0,
                             config=None) -> Tuple[float, str]:
    """
    Spec 2: Negative Weighting for 'Pseudo-Systems' Terms
    Formula: Raw_Score = (Tier_3 * 2.0) + (Tier_2 * 0.5)
    Penalty: heavy medical language AND no Tier-3 term → reduce Tier_2 by 50% and
    label 'Surface-Level'.

    C-M-19 / decision 3 (2026-11-15): "heavy medical language" is now a DENSITY, not
    an absolute count. The old test was `medical_count > tier_1_max` (10) over a
    window of up to 500 words, so a 60-word page with 9 medical words was "Standard"
    while an 800-word essay with 11 was "Surface-Level" — the same absolute count
    meant different things, and the count itself shrank when decision 3 removed five
    words from Tier 1. `window_words` is the number of words actually scored;
    with 0 (an unknown window, e.g. a bare string from an old caller) the absolute
    count threshold is used as before, so no caller silently changes behaviour.
    """
    weight_cfg = weights(config)
    penalties = penalty_cfg(config)
    t2_weight = weight_cfg.get("tier_2_systems",
                               DEFAULT_WEIGHTS["tier_2_systems"])
    t3_weight = weight_cfg.get("tier_3_bowen", DEFAULT_WEIGHTS["tier_3_bowen"])

    t2_weighted = t2_count * t2_weight
    label = "Standard"

    if window_words:
        threshold = penalties.get("tier_1_max_density_per_1000",
                                  DEFAULT_TIER_1_MAX_DENSITY)
        # A density needs a floor under its numerator as well: on a 40-word page one
        # medical word is 25 per 1000, which is noise, not a medical-model page. Same
        # reasoning as risk_signals.cliff_min_sample.
        min_hits = penalties.get("tier_1_min_hits", DEFAULT_TIER_1_MIN_HITS)
        heavy_medical = (medical_count >= min_hits
                         and medical_density_per_1000(medical_count, window_words) > threshold)
    else:
        heavy_medical = medical_count > penalties.get(
            "tier_1_max", DEFAULT_PENALTY_CFG["tier_1_max"])

    # Apply Spec 2 Penalty Condition
    if heavy_medical and t3_count == 0:
        t2_weighted *= penalties.get(
            "tier_2_penalty_multiplier",
            DEFAULT_PENALTY_CFG["tier_2_penalty_multiplier"])
        label = "Surface-Level"

    raw_score = (t3_count * t3_weight) + t2_weighted
    return raw_score, label

