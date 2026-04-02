import os
import re

# Paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GSC_STRIKE_LIST_PATH = os.path.join(ROOT_DIR, "gsc_strike_list.md")
PILLAR_DRAFT_PATH = os.path.join(ROOT_DIR, "pillar_north_shore_draft.md")

# Bowen Systemic Reframes for common GSC keywords
REFRAMES = {
    "couples counselling north vancouver": "Observing the Reciprocal Pursuit-Distance Cycle",
    "relationship therapy north vancouver": "From Individual Pathology to Systemic Process",
    "anxiety clinic north vancouver": "Intercepting the Anxiety Loop through Differentiation",
    "marriage therapist north shore": "Defining a Self in the Marriage System",
    "family systems therapy bc": "The Multigenerational Transmission of Anxiety",
    "counselling north vancouver": "Beyond Symptoms: Focus on the Relationship System",
    "marriage counselling north vancouver": "Observing the Emotional System in Conflict",
    "relationship counselling north vancouver": "Tracing the Reciprocity in Relationship Anxiety"
}

def get_top_gsc_keywords():
    keywords = []
    if os.path.exists(GSC_STRIKE_LIST_PATH):
        with open(GSC_STRIKE_LIST_PATH, 'r') as f:
            lines = f.readlines()
            for line in lines:
                if "|" in line and "Current Position" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) > 2 and parts[1] != "No data":
                        keywords.append(parts[1]) # Query column
    
    # Fallback if no data
    if not keywords:
        keywords = [
            "couples counselling north vancouver",
            "relationship therapy north vancouver",
            "anxiety clinic north vancouver",
            "marriage therapist north shore",
            "family systems therapy bc"
        ]
    return keywords[:5]

def inject_headers():
    keywords = get_top_gsc_keywords()
    with open(PILLAR_DRAFT_PATH, 'r') as f:
        content = f.read()

    new_headers = []
    for kw in keywords:
        reframe = REFRAMES.get(kw.lower(), "Observing the Relationship Process")
        new_headers.append(f"## {kw.title()}: {reframe}")

    # Inject headers before the "Hyper-Local Support" section
    injection_point = "## [H2] Hyper-Local Support"
    if injection_point in content:
        parts = content.split(injection_point)
        updated_content = parts[0] + "\n".join(new_headers) + "\n\n" + injection_point + parts[1]
        
        with open(PILLAR_DRAFT_PATH, 'w') as f:
            f.write(updated_content)
        print(f"Successfully injected {len(new_headers)} GSC-mapped headers into {PILLAR_DRAFT_PATH}")
    else:
        print("Could not find injection point in pillar draft.")

if __name__ == "__main__":
    inject_headers()
