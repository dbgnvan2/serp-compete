# Serp-comp Project Context

## Project Mission
To provide competitive SEO intelligence with a focus on Bowen Family Systems reframing.

## Tech Stack
- **Language:** Python
- **Libraries:** pandas, spaCy, BeautifulSoup4, requests, sqlite3
- **APIs:** DataForSEO, Moz V2

## Standards
- All features must have corresponding tests in the `tests/` directory.
- Maintain `spec.md` as the source of truth for requirements.
- Use `pytest` for testing.

## Current Status
- **Foundation:** Data ingestion and domain validation (`src/ingestion.py`).
- **API Clients:** DataForSEO and Moz V2 integration (`src/api_clients.py`).
- **Analysis:** Keyword intersection and feasibility checks (`src/analysis.py`).
- **Semantic Audit:** spaCy-powered entity extraction for Medical vs. Systems models (`src/semantic.py`).
- **Persistence:** SQLite for longitudinal tracking and volatility alerts (`src/database.py`).
- **GSC Intelligence (Module F):** Striking distance analysis and clinical title reframing (`src/gsc_performance.py`).
- **Runner:** Integrated audit flow (`src/main.py`).

## Testing
- **Suite:** All modules have 100% test coverage for core logic in `tests/`.
- **Run:** `PYTHONPATH=. pytest tests/`

# Tactical Rules: serp-compete

## 🎯 Analysis Standards
- **Semantic Rigor:** Use `clinical_dictionary.json` to calculate the "Systemic Vacuum." 
- **Penalty Logic:** Apply the Tier 1-to-Tier 2 penalty if Tier 3 keywords are absent.
- **Expert Reframing:** Automated reframes must avoid "Tools/Tips" language and use "Differentiation/Process" language.