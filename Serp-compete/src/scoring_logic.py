import json
import os
from typing import Tuple

DICTIONARY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "clinical_dictionary.json")
SHARED_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json")

def load_shared_config():
    if os.path.exists(SHARED_CONFIG_PATH):
        try:
            with open(SHARED_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

SHARED_CONFIG = load_shared_config()

def load_dictionary():
    clinical = SHARED_CONFIG.get("clinical", {})
    if clinical:
        return {
            "tier_1_medical": clinical.get("tier_1_medical", []),
            "tier_2_systems": clinical.get("tier_2_systems", []),
            "tier_3_bowen_expert": clinical.get("tier_3_bowen", [])
        }

    # Fallback to clinical_dictionary.json
    if os.path.exists(DICTIONARY_PATH):
        try:
            with open(DICTIONARY_PATH, "r") as f:
                data = json.load(f)
                return {
                    "tier_1_medical": data.get("tier_1_medical", []),
                    "tier_2_systems": data.get("tier_2_systems", []),
                    "tier_3_bowen_expert": data.get("tier_3_bowen", [])
                }
        except Exception:
            pass
            
    return {"tier_1_medical": [], "tier_2_systems": [], "tier_3_bowen_expert": []}

dict_data = load_dictionary()
TIER_1_MEDICAL = set(dict_data.get("tier_1_medical", []))
TIER_2_SYSTEMS = set(dict_data.get("tier_2_systems", []))
TIER_3_BOWEN_EXPERT = set(dict_data.get("tier_3_bowen_expert", []))

# Pull weights from SHARED_CONFIG
WEIGHTS = SHARED_CONFIG.get("technical", {}).get("scoring_weights", {
    "tier_1_medical": 1.0,
    "tier_2_systems": 0.5,
    "tier_3_bowen": 2.0
})

# Pull penalty thresholds from SHARED_CONFIG
PENALTY_CFG = SHARED_CONFIG.get("technical", {}).get("penalty_thresholds", {
    "tier_1_max": 10,
    "tier_2_penalty_multiplier": 0.5
})
# The Surface-Level trigger as a density per 1000 scored words (C-M-19). The default
# mirrors shared_config `technical.penalty_thresholds.tier_1_max_density_per_1000`;
# see that key's `_source` note for how the number was set.
DEFAULT_TIER_1_MAX_DENSITY = 12.0
# The density needs a minimum numerator too (see calculate_weighted_score).
DEFAULT_TIER_1_MIN_HITS = 3

def medical_density_per_1000(medical_count: int, window_words: int) -> float:
    """Tier-1 hits per 1000 scored words. 0.0 when the window is unknown."""
    if not window_words:
        return 0.0
    return 1000.0 * float(medical_count) / float(window_words)


def calculate_weighted_score(medical_count: int, t2_count: int, t3_count: int,
                             window_words: int = 0) -> Tuple[float, str]:
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
    t2_weight = WEIGHTS.get("tier_2_systems", 0.5)
    t3_weight = WEIGHTS.get("tier_3_bowen", 2.0)

    t2_weighted = t2_count * t2_weight
    label = "Standard"

    if window_words:
        threshold = PENALTY_CFG.get("tier_1_max_density_per_1000",
                                    DEFAULT_TIER_1_MAX_DENSITY)
        # A density needs a floor under its numerator as well: on a 40-word page one
        # medical word is 25 per 1000, which is noise, not a medical-model page. Same
        # reasoning as risk_signals.cliff_min_sample.
        min_hits = PENALTY_CFG.get("tier_1_min_hits", DEFAULT_TIER_1_MIN_HITS)
        heavy_medical = (medical_count >= min_hits
                         and medical_density_per_1000(medical_count, window_words) > threshold)
    else:
        heavy_medical = medical_count > PENALTY_CFG.get("tier_1_max", 10)

    # Apply Spec 2 Penalty Condition
    if heavy_medical and t3_count == 0:
        t2_weighted *= PENALTY_CFG.get("tier_2_penalty_multiplier", 0.5)
        label = "Surface-Level"

    raw_score = (t3_count * t3_weight) + t2_weighted
    return raw_score, label

