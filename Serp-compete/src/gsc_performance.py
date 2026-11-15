import os
import json
import datetime
import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from src.semantic import SemanticAuditor
from src.reframe_engine import ReframeEngine
from src.database import DatabaseManager

# Paths relative to serp-compete/src/
SHARED_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))
CLINICAL_DICT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "clinical_dictionary.json"))
# Move token.json to root of serp-main
TOKEN_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "token.json"))

class GSCManager:
    def __init__(self):
        self.config = self._load_json(SHARED_CONFIG_PATH)
        self.clinical_dict = self._load_json(CLINICAL_DICT_PATH)
        self.creds = self._authenticate()
        self.service = build('searchconsole', 'v1', credentials=self.creds)
        self.auditor = SemanticAuditor()
        self.reframe_engine = ReframeEngine()
        self.db = DatabaseManager()
        self._cached_sites = None

    def _load_json(self, path):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}

    def _authenticate(self):
        creds = None
        # Default to scopes in config if not provided
        scopes = self.config.get("auth", {}).get("scopes", ["https://www.googleapis.com/auth/webmasters.readonly"])
        
        # Check for client secrets in config
        client_secrets = self.config.get("auth", {}).get("gsc_client_secrets")
        # Fallback to gsc_auth.json if specified in spec but not in config
        if not client_secrets or not os.path.exists(client_secrets):
            if os.path.exists("gsc_auth.json"):
                client_secrets = "gsc_auth.json"
        
        if not client_secrets:
            # Try to find a client secret file in the root if none specified
            import glob
            secrets = glob.glob("client_secret_*.json")
            if secrets:
                client_secrets = secrets[0]

        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, scopes)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not client_secrets or not os.path.exists(client_secrets):
                    raise Exception("GSC Client Secrets file not found.")
                flow = InstalledAppFlow.from_client_secrets_file(client_secrets, scopes)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
        return creds

    # C-C-17 / C-M-11: GSC's row cap per request. The old call asked for one page of
    # 5000 rows and stopped; GSC returns rows by clicks descending, so everything past
    # row 5000 — the zero-click long tail, which is most of a real property — was
    # simply missing, and `serp_overlap` read every missing query as "the client is
    # absent", feeding the top action queue.
    GSC_PAGE_SIZE = 5000
    GSC_MAX_PAGES = 20          # 100k rows; a safety stop, not an expected limit

    def fetch_performance_data(self, site_url=None, days=None):
        if not site_url:
            site_url = self.config.get("auth", {}).get("gsc_property_url")

        # C-C-14: `gsc_settings.date_range_days` was documented and had no reader —
        # the window was hard-coded at 90 days. The argument still wins when given.
        if days is None:
            days = int((self.config.get("gsc_settings", {}) or {}).get(
                "date_range_days", 90))

        end_date = datetime.date.today().strftime('%Y-%m-%d')
        start_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')

        # C-M-11: `country=can` matches the DataForSEO side, which is a Canada
        # snapshot (location_code 2124). Comparing a global GSC average with a
        # Canadian SERP rank is comparing two different measurements, and the overlap
        # matrix tests them against each other with a symmetric `<= top_n`.
        country = str((self.config.get("gsc_settings", {}) or {}).get(
            "country", "can") or "").strip().lower()

        rows = []
        start_row = 0
        for _page in range(self.GSC_MAX_PAGES):
            request = {
                'startDate': start_date,
                'endDate': end_date,
                'dimensions': ['query', 'page'],
                'rowLimit': self.GSC_PAGE_SIZE,
                'startRow': start_row,
            }
            if country:
                request['dimensionFilterGroups'] = [{
                    'filters': [{'dimension': 'country', 'operator': 'equals',
                                 'expression': country}]
                }]
            try:
                response = self.service.searchanalytics().query(
                    siteUrl=site_url, body=request).execute()
            except Exception as e:
                print(f"⚠️ GSC Data Fetch Error for {site_url}: {e}")
                # Partial data is still data, but it must not be mistaken for all of
                # it: say how much was read before the failure (P2).
                if rows:
                    print(f"   ⚠️ Returning {len(rows)} row(s) read before the error — "
                          f"the rest of the window is UNREAD, not empty.")
                return rows
            page_rows = response.get('rows', []) or []
            rows.extend(page_rows)
            if len(page_rows) < self.GSC_PAGE_SIZE:
                break
            start_row += self.GSC_PAGE_SIZE
        else:
            print(f"⚠️ GSC pagination stopped at {self.GSC_MAX_PAGES} pages "
                  f"({len(rows)} rows) — there may be more.")
        return rows

    def get_query_position_map(self) -> dict:
        """C4/SC-6: {normalized query: best (lowest) client position} from GSC.

        The client's own SERP rank per query — the source of ``self_position`` in
        the overlap matrix (the competitor handoff excludes the client, so the
        client's positions can only come from first-party GSC). Aggregates to the
        best position across pages. Absent/failed GSC data → ``{}`` (graceful; the
        client is then treated as absent from the top-N, never fabricated present).
        """
        best: dict = {}
        for r in self.fetch_performance_data() or []:
            keys = r.get('keys') or []
            pos = r.get('position')
            if not keys or pos is None:
                continue
            query = str(keys[0] or "").strip().lower()
            if not query:
                continue
            pos = int(round(float(pos)))
            if query not in best or pos < best[query]:
                best[query] = pos
        return best

    def list_sites(self):
        if self._cached_sites:
            return self._cached_sites
            
        try:
            response = self.service.sites().list().execute()
            sites = response.get('siteEntry', [])
            for s in sites:
                print(f"- Site: {s['siteUrl']}, Permission: {s.get('permissionLevel')}")
            self._cached_sites = sites
            return sites
        except Exception as e:
            print(f"⚠️ GSC List Sites Error: {e}")
            return []

    def test_connection(self):
        """
        Verify that we can actually connect and have sufficient permissions.
        Returns (bool, message)
        """
        site_url = self.config.get("auth", {}).get("gsc_property_url")
        try:
            sites = self.list_sites()
            if not sites:
                return False, "No GSC properties found for this account."

            target_site = next((s for s in sites if s['siteUrl'] == site_url), None)
            if not target_site:
                # Expert Logic: Check for common variations (www vs non-www) to provide a better error
                alt_url = site_url.replace("://www.", "://") if "://www." in site_url else site_url.replace("://", "://www.")
                found_alt = next((s for s in sites if s['siteUrl'] == alt_url), None)
                if found_alt:
                    return False, f"URL Mismatch: Configured '{site_url}' but found '{alt_url}' in GSC. Please update shared_config.json."
                return False, f"Property {site_url} not found in account. Available sites: {', '.join([s['siteUrl'] for s in sites])}"

            perm = target_site.get('permissionLevel')
            if perm in ['siteUnverifiedUser', 'siteRestrictedUser']:
                return False, f"Insufficient permissions for {site_url} (Permission: {perm}). Please grant 'Owner' or 'Full' access."

            # Attempt a tiny query to verify data fetch
            end_date = datetime.date.today().strftime('%Y-%m-%d')
            request = {'startDate': end_date, 'endDate': end_date, 'rowLimit': 1}
            self.service.searchanalytics().query(siteUrl=site_url, body=request).execute()
            
            return True, f"Successfully connected to {site_url} with {perm} access."
        except Exception as e:
            return False, f"GSC Connection Test Failed: {str(e)}"

    def get_striking_distance_keywords(self):
        """
        Spec 6: Module F - Identify 'Striking Distance' keywords (Avg Position 11-25).
        """
        site_url = self.config.get("auth", {}).get("gsc_property_url")
        data = self.fetch_performance_data(site_url=site_url)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame([
            {
                'query': r['keys'][0],
                'page': r['keys'][1],
                'clicks': r['clicks'],
                'impressions': r['impressions'],
                'ctr': r['ctr'],
                'position': r['position']
            } for r in data
        ])

        # 1. Position Filter: 11-25
        striking = df[(df['position'] >= 11) & (df['position'] <= 25)].copy()

        # Debug: Print top 50 by impressions
        print("\n--- DEBUG: Top 50 Keywords by Impressions ---")
        top_50 = df.sort_values('impressions', ascending=False).head(50)
        for _, r in top_50.iterrows():
            print(f"Query: {r['query']} | Pos: {r['position']:.1f} | Imp: {r['impressions']}")
        print("-------------------------------------------\n")

        # 2. Efficiency Filter: Sort by Impressions Descending
        striking = striking.sort_values('impressions', ascending=False)

        # 3. Clinical Filter: Cross-reference with clinical_dictionary.json
        t1 = set(self.clinical_dict.get("tier_1_medical", []))
        t2 = set(self.clinical_dict.get("tier_2_systems", []))

        def get_clinical_pivot(query):
            query_lower = query.lower()
            # If query contains any T1 terms, it's a primary candidate
            for term in t1:
                if term in query_lower:
                    return "Tier 1 (Medical) -> Systems Reframe"
            for term in t2:
                if term in query_lower:
                    return "Tier 2 (Systems) -> Deepen Bowen Depth"
            return "General -> Systemic Pivot"

        striking['clinical_pivot'] = striking['query'].apply(get_clinical_pivot)
        
        return striking

    def suggest_systemic_title(self, query):
        """
        AI-powered systemic title suggestion to improve CTR.
        """
        # Mapping rules as fallback or logic guides
        pivot_map = self.reframe_engine.pivot_map
        query_lower = query.lower()
        
        for trigger, pivot in pivot_map.items():
            if trigger in query_lower:
                return f"Shifting from {trigger.title()} to {pivot}"
        
        # Default pattern: Shift from diagnostic/symptom to process
        if "how to" in query_lower or "fix" in query_lower:
            core = query_lower.replace("how to", "").replace("fix", "").strip()
            return f"Beyond Fixing {core.title()}: Observing the Relationship Process"
            
        return f"A Systems View of {query.title()}"

    def generate_strike_report(self, striking_df):
        """
        Spec 6: Generate gsc_strike_list.md
        """
        report = [
            "# GSC Intelligence: The Reality Check (Strike List)",
            f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d')}",
            "\n## 🎯 Striking Distance Opportunities (Positions 11-25)",
            "These keywords are almost winning. Moving them to Page 1 could cause a massive traffic spike.",
            "\n| Query | Current Position | Impressions | Associated URL | Clinical Pivot | Systemic Title recommendation |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ]

        if striking_df.empty:
            report.append("| No data | - | - | - | - | - |")
            print("No striking distance keywords found. Generating empty report.")
        else:
            # Limit to top 20 for the report
            for _, row in striking_df.head(20).iterrows():
                suggested_title = self.suggest_systemic_title(row['query'])
                report.append(
                    f"| {row['query']} | {row['position']:.1f} | {row['impressions']} | {row['page']} | {row['clinical_pivot']} | **{suggested_title}** |"
                )

        # Output to project root as expected by serp-main context
        output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "gsc_strike_list.md"))
        with open(output_path, 'w') as f:
            f.write("\n".join(report))
        print(f"✅ GSC Strike List generated: {output_path}")

    def analyze_gaps(self):
        site_url = self.config.get("auth", {}).get("gsc_property_url")
        try:
            sites = self.list_sites()
            if not sites:
                return pd.DataFrame(), pd.DataFrame(), []

            found = False
            for s in sites:
                if s['siteUrl'] == site_url:
                    found = True
            if not found:
                print(f"⚠️ Warning: {site_url} not found in accessible sites. Using {sites[0]['siteUrl']} instead.")
                site_url = sites[0]['siteUrl']
        except Exception as e:
            print(f"Error listing sites: {e}")
            return pd.DataFrame(), pd.DataFrame(), []

        data = self.fetch_performance_data(site_url=site_url)
        if not data:
            print(f"ℹ️ No GSC data returned for {site_url}. (Check permissions/verification)")
            return pd.DataFrame(), pd.DataFrame(), []

        df = pd.DataFrame([
            {
                'query': r['keys'][0],
                'page': r['keys'][1],
                'clicks': r['clicks'],
                'impressions': r['impressions'],
                'ctr': r['ctr'],
                'position': r['position']
            } for r in data
        ])

        # 1. High Impression / Low CTR (< 1%)
        ctr_threshold = self.config.get("gsc_settings", {}).get("ctr_threshold", 0.01)
        high_imp_low_ctr = df[(df['ctr'] < ctr_threshold) & (df['impressions'] > 100)].copy()

        # Match with Tier 1 and Tier 2
        clinical = self.config.get("clinical", {})
        t1 = set(clinical.get("tier_1_medical", []))
        t2 = set(clinical.get("tier_2_systems", []))

        def get_tier(query):
            # C-M-08: the one canonical word-boundary matcher, so this agrees with
            # positioning.classify_query_tiers and with the relevance test. The old
            # `set(query.split()).intersection(...)` was whole-word but could not
            # match a multi-word Tier-2 term ("chronic anxiety") and missed anything
            # carrying punctuation ("anxiety?").
            from src.audit_universe import contains_term
            if any(contains_term(query, term) for term in t1):
                return "Tier 1 (Medical)"
            if any(contains_term(query, term) for term in t2):
                return "Tier 2 (Systems)"
            return "Other"

        high_imp_low_ctr['tier'] = high_imp_low_ctr['query'].apply(get_tier)
        target_gaps = high_imp_low_ctr[high_imp_low_ctr['tier'] != "Other"]

        # 2. Low-Hanging Fruit (Positions 11-20)
        low_hanging = df[(df['position'] > 10) & (df['position'] <= 20)].sort_values('impressions', ascending=False).head(10)
        # 3. Clinical Mismatch Check
        # Match Bowen pages receiving Medical hits
        mismatches = []
        unique_pages = df['page'].unique()
        
        print("🔍 Scanning local pages for clinical alignment...")
        page_scores = {}
        pages_considered = list(unique_pages[:20])  # Limit to top 20 pages for speed
        unreadable_pages = []
        for page in pages_considered:
            cached_audit = self.db.was_audited_recently(page)
            if cached_audit:
                page_scores[page] = cached_audit
                print(f"  ⚡ Using cached local audit for {page}")
                continue
                
            content = self.auditor.scrape_content(page)
            # C-C-09: branch on `extraction_status`, exactly as main.py does.
            # `scrape_content` returns a ScrapedPage and has not returned the string
            # "BLOCK" since the ScrapedPage refactor, so the old `content != "BLOCK"`
            # test was always true: a 429 or a timeout on the client's OWN page was
            # scored 0/0 and written to `semantic_audits` with run_id 0, where the
            # 7-day cache then served it for a week — suppressing the Clinical
            # Mismatch check (`systems_score > 5`) as a confident "no mismatches".
            status = getattr(content, "extraction_status", "error")
            if status in ("blocked", "error"):
                unreadable_pages.append(page)
                print(f"  ⚠️ Skipping unreadable own page ({status}): {page}")
                continue
            if content:
                scores = self.auditor.analyze_text(content)
                page_scores[page] = scores
                # Save to audit table for future GSC caching
                self.db.save_semantic_audit(page, scores['medical_score'], scores['systems_score'], run_id=0)

        # P2: a suppressed mismatch check must say so. "No mismatches" and "we could
        # not read 4 of your 20 pages" are different findings.
        if unreadable_pages:
            print(f"  ⚠️ Clinical alignment scanned {len(page_scores)} of "
                  f"{len(pages_considered)} pages — {len(unreadable_pages)} unreadable "
                  f"this run (retryable, NOT recorded as 'no systems language').")

        for _, row in df.head(100).iterrows():
            page = row['page']
            query = row['query']
            if page in page_scores:
                scores = page_scores[page]
                if scores['systems_score'] > 5 and get_tier(query) == "Tier 1 (Medical)":
                    mismatches.append({
                        'page': page,
                        'query': query,
                        'medical_hits': row['clicks'],
                        'reason': "Bowen page attracting Medical Model audience"
                    })

        return target_gaps, low_hanging, mismatches

    def generate_report(self, target_gaps, low_hanging, mismatches):
        report = [
            "# GSC Strategic Gap Report: The Reality Check",
            f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d')}",
            "\n## 1. High Impression / Low CTR Gaps (Tier 1 & 2)",
            "These keywords are being seen but not clicked. We need to reframe the Meta Titles with systemic depth."
        ]
        
        if not target_gaps.empty:
            report.append(target_gaps[['query', 'impressions', 'ctr', 'tier']].to_markdown(index=False))
        else:
            report.append("No significant gaps found.")

        report.append("\n## 2. Low-Hanging Fruit (Page 2 Targets)")
        report.append("These pages are ranking in positions 11-20. A small systemic boost could push them to Page 1.")
        if not low_hanging.empty:
            report.append(low_hanging[['query', 'page', 'position', 'impressions']].to_markdown(index=False))

        report.append("\n## 3. Clinical Mismatches")
        report.append("Detected instances where a Systems-heavy page is being found via Medical Model queries.")
        if mismatches:
            report.append(pd.DataFrame(mismatches).to_markdown(index=False))
        else:
            report.append("No clinical mismatches detected.")

        output_path = "gsc_strategic_gap.md"
        with open(output_path, 'w') as f:
            f.write("\n".join(report))
        print(f"✅ GSC Strategic Gap report generated: {output_path}")

if __name__ == "__main__":
    gsc = GSCManager()
    striking = gsc.get_striking_distance_keywords()
    gsc.generate_strike_report(striking)

