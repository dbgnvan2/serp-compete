import sys
import datetime
import os
import json
import glob
import warnings
import jsonschema
from src.api_clients import DataForSEOClient, MozClient
from src.semantic import SemanticAuditor
from src.analysis import AnalysisEngine
from src.database import DatabaseManager
from typing import Dict, Set, List, Tuple, Any
from src.reporting import ReportGenerator
from src.reframe_engine import ReframeEngine
from src.velocity_module import VelocityTracker
from src.gsc_performance import GSCManager

# Paths relative to the project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED_CONFIG_PATH = os.path.join(PROJECT_ROOT, "shared_config.json")
MANUAL_TARGETS_PATH = os.path.join(PROJECT_ROOT, "manual_targets.json")
HANDOFF_SCHEMA_PATH = os.path.join(PROJECT_ROOT, "handoff_schema.json")
KEYWORD_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "serp-keyword", "output")

def load_shared_config():
    if os.path.exists(SHARED_CONFIG_PATH):
        with open(SHARED_CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def load_handoff_schema():
    """Load the JSON Schema for handoff validation."""
    if os.path.exists(HANDOFF_SCHEMA_PATH):
        with open(HANDOFF_SCHEMA_PATH, 'r') as f:
            return json.load(f)
    return None

def find_latest_handoff_file() -> str | None:
    """Find the most recently modified competitor_handoff_*.json file."""
    handoff_files = glob.glob(os.path.join(PROJECT_ROOT, "competitor_handoff_*.json"))
    if not handoff_files:
        return None
    return max(handoff_files, key=os.path.getmtime)

def find_latest_legacy_file() -> str | None:
    """Find the most recently modified market_analysis_*.json file (legacy)."""
    legacy_files = glob.glob(os.path.join(KEYWORD_OUTPUT_DIR, "market_analysis_*.json"))
    if not legacy_files:
        return None
    return max(legacy_files, key=os.path.getmtime)

def convert_handoff_to_targets(handoff_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """Convert handoff format to internal targets format."""
    targets = []
    for target in handoff_data.get("targets", []):
        targets.append({
            "domain": target["domain"],
            "url": target["url"],
            "primary_keyword": target["primary_keyword_for_url"],
            "est_traffic": 0,  # Handoff doesn't include traffic; it's deterministic audit data
            "rank": target["rank"],
            "entity_type": target["entity_type"],
            "content_type": target["content_type"],
            "title": target["title"],
            "source_keyword": target["source_keyword"]
        })
    return targets, {}

def convert_legacy_to_targets(legacy_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """Convert legacy market_analysis format to internal targets format."""
    targets = []
    if "organic_results" in legacy_data:
        for res in legacy_data["organic_results"]:
            url = res.get("Link")
            keyword = res.get("Source_Keyword")
            if url and keyword:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace('www.', '')
                targets.append({
                    "domain": domain,
                    "url": url,
                    "primary_keyword": keyword,
                    "est_traffic": res.get("Word_Count") if isinstance(res.get("Word_Count"), (int, float)) else 0
                })

    paa_data = {}
    if "paa_questions" in legacy_data:
        for paa in legacy_data["paa_questions"]:
            kw = paa.get("Source_Keyword")
            question = paa.get("Question")
            if kw and question:
                if kw not in paa_data:
                    paa_data[kw] = []
                paa_data[kw].append(question)

    return targets, paa_data

def get_latest_market_data() -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """
    Gap 1: Competitor handoff ingestion from Tool 1.

    Tries sources in order:
    1. competitor_handoff_*.json (Tool 1 Gap 3) — validated against handoff_schema.json
    2. market_analysis_*.json (legacy, deprecated) — with DeprecationWarning
    3. manual_targets.json (developer override) — fallback only

    Returns: (list of target entries, dict of keyword -> paa_questions)
    """
    schema = load_handoff_schema()

    # 1. Try competitor_handoff_*.json (Tool 1 Gap 3)
    handoff_file = find_latest_handoff_file()
    if handoff_file:
        print(f"📦 Loading competitor handoff from: {handoff_file}")
        try:
            with open(handoff_file, 'r') as f:
                handoff_data = json.load(f)

            # Validate against schema
            if schema:
                try:
                    jsonschema.validate(instance=handoff_data, schema=schema)
                    print(f"✅ Handoff validated against schema v{handoff_data.get('schema_version')}")
                    return convert_handoff_to_targets(handoff_data)
                except jsonschema.ValidationError as e:
                    print(f"❌ Handoff validation failed: {e.message}")
                    print(f"   Path: {list(e.path)}")
                    sys.exit(1)  # Hard fail per spec
            else:
                print("⚠️ Schema file not found; skipping validation. Using handoff data as-is.")
                return convert_handoff_to_targets(handoff_data)
        except Exception as e:
            print(f"❌ Error loading handoff: {e}")
            sys.exit(1)

    # 2. Try legacy market_analysis_*.json (deprecated)
    legacy_file = find_latest_legacy_file()
    if legacy_file:
        print(f"⚠️ DEPRECATED: Loading legacy market_analysis from: {legacy_file}")
        warnings.warn(
            "market_analysis_*.json format is deprecated. Please use competitor_handoff_*.json from Tool 1.",
            DeprecationWarning,
            stacklevel=2
        )
        try:
            with open(legacy_file, 'r') as f:
                legacy_data = json.load(f)
            return convert_legacy_to_targets(legacy_data)
        except Exception as e:
            print(f"❌ Error loading legacy file: {e}")
            # Continue to fallback

    # 3. Fallback to manual_targets.json (developer override)
    if os.path.exists(MANUAL_TARGETS_PATH):
        print(f"📦 Loading manual targets from {MANUAL_TARGETS_PATH}")
        try:
            with open(MANUAL_TARGETS_PATH, 'r') as f:
                data = json.load(f)
                targets = [{"domain": d, "url": f"https://{d}", "primary_keyword": "manual_audit", "est_traffic": 0}
                           for d in data.get("competitors", [])]
                return targets, {}
        except Exception as e:
            print(f"❌ Error loading manual targets: {e}")
            return [], {}

    # No data sources found
    print(f"⚠️ No data sources found (checked: handoff, legacy, manual).")
    return [], {}

def pre_flight_check():
    """
    Validate all credentials and API health before starting a costly run.
    """
    print("--- 🛠️ Pre-Flight Check ---")
    required_vars = [
        "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", 
        "OPENAI_API_KEY", "MOZ_TOKEN"
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return None

    # 1. Check DataForSEO Balance
    try:
        dfs = DataForSEOClient()
        import requests
        r = requests.get(
            'https://api.dataforseo.com/v3/appendix/user_data', 
            auth=(dfs.login, dfs.password)
        ).json()
        balance = r['tasks'][0]['result'][0]['money']['balance']
        if balance <= 0:
            print(f"❌ DataForSEO balance is too low: {balance}")
            return None
        print(f"✅ DataForSEO Balance: ${balance}")
    except Exception as e:
        print(f"❌ DataForSEO Connectivity Error: {e}")
        return None

    # 2. Check OpenAI connectivity
    try:
        reframe = ReframeEngine()
        if reframe.client:
            reframe.client.models.retrieve(reframe.model)
            print(f"✅ OpenAI Model Ready: {reframe.model}")
    except Exception as e:
        print(f"❌ OpenAI Connectivity Error: {e}")
        return None

    # 3. Check GSC Connectivity (Mandatory - Hard Fail)
    gsc = None
    try:
        shared_config = load_shared_config()
        secrets_path = shared_config.get("auth", {}).get("gsc_client_secrets")
        if not secrets_path or not os.path.exists(secrets_path):
            print("❌ GSC Credentials not found. Please provide path to GSC Client Secrets in shared_config.json.")
            return None
            
        gsc = GSCManager()
        success, message = gsc.test_connection()
        if not success:
            print(f"❌ GSC Connectivity Error: {message}")
            return None
        print(f"✅ GSC Connection Verified: {message}")
    except Exception as e:
        print(f"❌ GSC Check Error: {e}")
        return None

    print("✅ All systems go. Starting Audit...\n")
    return gsc

def load_omitted_domains(config):
    """
    Load domains to skip from the external text file.
    """
    path_rel = config.get("filtering", {}).get("omitted_domains_path", "omitted_domains.txt")
    # Path is relative to project root
    path = os.path.join(PROJECT_ROOT, path_rel)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()

def run_audit():
    gsc = pre_flight_check()
    if not gsc:
        print("🛑 Pre-flight check failed. Aborting run.")
        sys.exit(1)

    shared_config = load_shared_config()
    omitted_domains = load_omitted_domains(shared_config)
    client_domain = shared_config.get("client", {}).get("domain", "livingsystems.ca")

    # 1. Foundation: Dynamic Handover & Velocity Tracker
    targets_raw, paa_map = get_latest_market_data()
    if not targets_raw:
        print("❌ No competitors identified. Aborting.")
        return

    # Optimization 1: Group by domain
    domain_groups = {}
    for t in targets_raw:
        d = t["domain"]
        if d not in domain_groups:
            domain_groups[d] = []
        domain_groups[d].append(t)

    db = DatabaseManager()
    velocity = VelocityTracker(SHARED_CONFIG_PATH)
    run_id = db.create_run(client_domain)
    print(f"Created new Audit Run ID: {run_id}")
    
    # 2. API Clients
    dfs_client = DataForSEOClient()
    moz_client = MozClient()
    reframe_engine = ReframeEngine()
    
    # 3. Engines
    auditor = SemanticAuditor()
    reporter = ReportGenerator()

    # 4. Optional: Internal GSC Analysis
    gsc_findings = None
    try:
        print("🔍 Running Internal GSC Gap Analysis...")
        target_gaps, low_hanging, mismatches = gsc.analyze_gaps()
        if not target_gaps.empty or not low_hanging.empty or mismatches:
            gsc_findings = {
                "target_gaps": target_gaps,
                "low_hanging": low_hanging,
                "mismatches": mismatches
            }
            print(f"✅ GSC Analysis complete: {len(target_gaps)} gaps, {len(low_hanging)} low-hanging, {len(mismatches)} mismatches.")
        else:
            print("ℹ️ No significant GSC gaps found or access restricted.")
    except Exception as e:
        print(f"⚠️ GSC Analysis skipped: {e}")

    
    competitor_keywords: Dict[str, Set[str]] = {}
    all_metrics_to_save = []
    
    print(f"Starting audit for {client_domain}...")
    
    # 4. Ingestion & Expert Filtering
    for domain, group_targets in domain_groups.items():
        # Aggregator/Omitted Exclusion: Cross-reference the external omitted_domains list
        if domain in omitted_domains:
            print(f"Skipping omitted domain: {domain}")
            continue
            
        print(f"Analyzing competitor: {domain}")
        pages = dfs_client.get_relevant_pages(domain)
        if not pages:
            continue

        # Moz metrics for filtering
        urls = [p.get('ranked_serp_element', {}).get('serp_item', {}).get('url') for p in pages]
        urls = [u for u in urls if u]
        moz_metrics_map = {}
        try:
            moz_results = moz_client.get_url_metrics(urls)
            for res in moz_results:
                moz_metrics_map[res.get('url')] = res.get('page_authority') or res.get('pa') or 0
        except Exception as e:
            print(f"  Warning: Moz metrics failed: {e}")

        # Expert Filter: DA Threshold: Skip any domain where Domain Authority > 50
        avg_pa = sum(moz_metrics_map.values()) / len(moz_metrics_map) if moz_metrics_map else 0
        if avg_pa > 50:
            print(f"  Skipping high-authority domain (Avg PA {avg_pa:.1f} > 50): {domain}")
            continue

        domain_medical_total = 0
        domain_t2_total = 0
        domain_t3_total = 0
        domain_traffic_total = 0
        domain_keywords = set()
        processed_urls = set() # Track URLs processed for this domain
        domain_blocked = False

        for page in pages:
            if domain_blocked:
                break
                
            serp_item = page.get('ranked_serp_element', {}).get('serp_item', {})
            url = serp_item.get('url')
            if not url: continue
            
            keyword = page.get('keyword_data', {}).get('keyword') or page.get('keyword')
            pos = serp_item.get('rank_absolute')
            traffic = serp_item.get('etv') or 0
            
            if keyword:
                domain_keywords.add(keyword)
                
            all_metrics_to_save.append({
                "domain": domain,
                "url": url,
                "keyword": keyword,
                "position": pos,
                "traffic": traffic
            })
            
            pa = moz_metrics_map.get(url, 0)
            db.save_competitor_history(run_id, url, pos, pa, traffic)
            
            max_pages = shared_config.get("technical", {}).get("max_audit_pages_per_domain", 3)
            
            # Optimization 3: Only scrape if not audited in last 7 days
            if url not in processed_urls and len(processed_urls) < max_pages:
                processed_urls.add(url) # Mark as attempted IMMEDIATELY to avoid re-scrape loops
                
                cached_audit = db.was_audited_recently(url)
                if cached_audit:
                    scores = cached_audit
                    print(f"  ⚡ Using cached audit for {url} (fresh within 7 days)")
                else:
                    # Double check we don't scrape the same URL if it was already processed in this domain loop
                    content = auditor.scrape_content(url)
                    if content == "BLOCK":
                        print(f"  🛑 Circuit Breaker: Domain {domain} is blocking us (429). Skipping remaining pages.")
                        domain_blocked = True
                        continue
                    elif content:
                        scores = auditor.analyze_text(content)
                        db.save_semantic_audit(url, scores['medical_score'], scores['systems_score'], run_id=run_id, label=scores.get('systemic_label', 'Standard'))
                    else:
                        # Logic: If we hit a major error other than 429, scrape_content returns ""
                        continue

                db.save_traffic_magnet(run_id, domain, url, keyword, traffic, scores['medical_score'], scores['systems_score'], label=scores.get('systemic_label', 'Standard'))
                print(f"  Audit {url}: Medical {scores['medical_score']}, Systems {scores['systems_score']} ({scores.get('systemic_label')})")
                
                # Spec 4: Save every audit result (DA, Rank, Scores) into market_history
                velocity.save_market_snapshot(
                    domain=domain,
                    url=url,
                    keyword=keyword,
                    rank=pos,
                    da=pa, # Using PA as proxy for DA at URL level
                    systems_score=scores['systems_score'],
                    medical_score=scores['medical_score']
                )

                domain_medical_total += scores['medical_score']
                # Correctly handle potential missing T2/T3 in cached audit
                domain_t2_total += scores.get('t2_count', 0) if not cached_audit else (scores['systems_score'] / 0.5 if scores['systems_score'] < 2.0 else 0) # Rough estimate for cache
                domain_t3_total += scores.get('t3_count', 0) if not cached_audit else (scores['systems_score'] / 2.0 if scores['systems_score'] >= 2.0 else 0)
                domain_traffic_total += traffic
                processed_urls.add(url)

        db.tag_competitor_position(domain, domain_medical_total, domain_t2_total, domain_t3_total, domain_traffic_total)
        competitor_keywords[domain] = domain_keywords

    if all_metrics_to_save:
        db.save_competitor_metrics(all_metrics_to_save, run_id=run_id)

    # Strategic Logic with PAA context from Handover
    print("Identifying Strategic Openings...")
    openings = db.identify_strategic_openings(run_id)
    reframes = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    
    for opening in openings:
        # Pull paa_questions as reframe_context
        paa_questions = paa_map.get(opening['keyword'], [])
        
        # Integration: Reframe_Engine pull paa_questions as primary evidence
        reframe_result = reframe_engine.generate_bowen_reframe(
            opening['keyword'], opening['url'], opening['medical_score'], paa_questions=paa_questions
        )
        
        usage = reframe_result.get("usage", {})
        for key in total_usage:
            total_usage[key] += usage.get(key, 0)

        reframes.append({
            "keyword": opening['keyword'],
            "url": opening['url'],
            "paa": paa_questions,
            "reframe": reframe_result["reframe"]
        })

    # Spec 4: Get market velocity alerts
    market_alerts = velocity.get_market_alerts()

    reporter.generate_summary(
        client_domain, 
        expected_competitors=list(competitor_keywords.keys()), 
        run_id=run_id, 
        reframes=reframes,
        token_usage=total_usage,
        market_alerts=market_alerts,
        gsc_findings=gsc_findings
    )

if __name__ == "__main__":
    run_audit()
