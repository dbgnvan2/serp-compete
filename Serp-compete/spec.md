# Serp-comp: Competitive SEO Intelligence Tool Spec

## Overview
A professional-grade competitive intelligence tool designed to serve a Bowen Family Systems mission by identifying SEO gaps and differentiation opportunities in the North Vancouver market.

## Technical Pillars

### 1. Reverse Lookup Endpoint (DataForSEO)
- **Endpoint:** `POST https://api.dataforseo.com/v3/dataforseo_labs/google/relevant_pages/live`
- **Purpose:** Identify "Traffic Magnets" by sorting competitor URLs by estimated monthly traffic volume.
- **Requirement:** Know exactly which "pipe" to plug into to avoid wasting time on low-performing pages.

### 2. Keyword Intersection Logic
- **Logic:** If provided 3 competitors, flag keywords that all three rank for, but the client does not.
- **Purpose:** Identify "Industry Standard" topics and verified market gaps.

### 3. Entity Extraction & Scoring (Revisions 1 & 2)
- **Module:** Semantic Tagging using `spaCy` and External Dictionary.
- **External Dictionary:** Terms are loaded from `data/dictionary.json` for easy editing.
- **Revision 1: "Attachment Style" Data Trap:** Intercept "Attachment" keywords and force a systemic reframe into "Distance-Pursuit" or "Emotional Process".
- **Revision 2: Negative Weighting:** 
    - **Formula:** `Raw_Score = (Tier_3 * 2.0) + (Tier_2 * 0.5)`
    - **Penalty:** If `Tier_1 (Medical) > 10` AND `Tier_3 == 0`, apply a -50% penalty to the `Tier_2` score.

### 4. Database Schema & Longitudinal Tracking (Revision 4)
- **Persistence Layer:** SQLite (`competitor_history.db`).
- **Revision 4: Feasibility Drift:**
    - **Data:** Store `Snapshot_Date`, `URL`, `Position`, `PA`, and `Traffic_Value`.
    - **Calculation:** `Drift = Current_PA - Previous_PA`.
    - **Alert:** Flag as "Fragile Magnet" if `Drift < -2`.

### 5. Market Positioning (Revision 3)
- **Tagging Logic:**
    - **Volume Scaler:** High Traffic (>1000) + High Medical Score (>15).
    - **Generalist:** High Tier 2 Score (>10).
    - **Direct Systemic:** Presence of Tier 3 terms (>0).
- **UI Requirement:** Strategic Briefing includes a "Market Position" column for each competitor.

## Module Requirements

| Module | Technical Requirement |
| --- | --- |
| **Data Ingestion** | Read `Key_domains.csv` using `pandas`. Validate URLs are root domains. |
| **Reverse Lookup** | Use DataForSEO `relevant_pages/live`. Filter for `metrics.organic.pos <= 10`. |
| **Authority Check** | Call Moz V2 `url_metrics` for each "Traffic Magnet" URL to get `page_authority` (PA). |
| **Semantic Audit** | Use `BeautifulSoup` to pull `<h1>` through `<h3>` and first 500 words of text. |
| **Logic Layer** | `Feasibility = (Client_DA + 5) >= Competitor_DA`. If False, suggest Hyper-Local Pivot. |
| **Persistence** | Save results to `competitor_history.db` with a timestamp column for trend analysis. |
| **Module F: GSC Intel** | Pull 90 days of query data. Filter for "Striking Distance" (Pos 11-25). Cross-reference with clinical dictionary. Suggest systemic titles. |
| **Strategic Assets** | Drafted `pillar_north_shore_draft.md` and `neighborhood_pivots_draft.md` using market-driven keyword mapping and Bowen reframes. |

## Development Standards
- **Testing:** Comprehensive test suite updated with each new feature.
- **Documentation:** `GEMINI.md` maintained with project-specific context.
