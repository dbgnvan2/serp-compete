"""gsc_performance.analyze_gaps: `content != "BLOCK"` is dead since scrape_content returns ScrapedPage; a 429/timeout on the client's own page is saved as a 0/0 semantic audit (7-day cache)."""
import sys, os, tempfile
from unittest.mock import MagicMock, patch
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
import src.gsc_performance as gp
from src.semantic import ScrapedPage
from src.database import DatabaseManager

tmp = tempfile.mkdtemp()
db = DatabaseManager(os.path.join(tmp, "t.db"))
blocked = ScrapedPage(url="https://livingsystems.ca/anxiety", fetched_at="x", http_status=429, extraction_status="blocked",
                      extraction_errors=["HTTP 429"], outline=[], first_500_words="", full_text_word_count=0, metadata={})
auditor = MagicMock(); auditor.scrape_content.return_value = blocked
# real analyze_text on empty text (spaCy) would give 0/0; emulate exactly
auditor.analyze_text.return_value = {"medical_score": 0, "systems_score": 0.0, "systemic_label": "Standard", "t2_count": 0, "t3_count": 0}

gsc = gp.GSCManager.__new__(gp.GSCManager)
gsc.config = {"auth": {"gsc_property_url": "https://www.livingsystems.ca/"}, "clinical": {"tier_1_medical": ["anxiety"], "tier_2_systems": []}, "gsc_settings": {}}
gsc.auditor = auditor; gsc.db = db; gsc._cached_sites = [{"siteUrl": "https://www.livingsystems.ca/"}]
gsc.fetch_performance_data = lambda site_url=None, days=90: [{"keys": ["anxiety counselling", "https://livingsystems.ca/anxiety"], "clicks": 50, "impressions": 5000, "ctr": 0.01, "position": 3.0}]
gsc.analyze_gaps()
print("semantic_audits rows after a BLOCKED own-page scrape:", db._get_connection().execute("select url, medical_score, systems_score, run_id from semantic_audits").fetchall())
print("was_audited_recently next 7 days ->", db.was_audited_recently("https://livingsystems.ca/anxiety"))
