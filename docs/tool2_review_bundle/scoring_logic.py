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

def calculate_weighted_score(medical_count: int, t2_count: int, t3_count: int) -> Tuple[float, str]:
    """
    Spec 2: Negative Weighting for 'Pseudo-Systems' Terms
    Formula: Raw_Score = (Tier_3 * 2.0) + (Tier_2 * 0.5)
    Penalty: If Tier_1 > 10 AND Tier_3 == 0, reduce Tier_2 by 50% and label 'Surface-Level'.
    """
    t2_weight = WEIGHTS.get("tier_2_systems", 0.5)
    t3_weight = WEIGHTS.get("tier_3_bowen", 2.0)
    
    t2_weighted = t2_count * t2_weight
    label = "Standard"

    # Apply Spec 2 Penalty Condition
    if medical_count > PENALTY_CFG.get("tier_1_max", 10) and t3_count == 0:
        t2_weighted *= PENALTY_CFG.get("tier_2_penalty_multiplier", 0.5)
        label = "Surface-Level"
        
    raw_score = (t3_count * t3_weight) + t2_weighted
    return raw_score, label

