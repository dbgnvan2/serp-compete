import sys
import datetime
import os
import json
import glob
import warnings
import jsonschema
from src.api_clients import DataForSEOClient, MozClient
from src.semantic import SemanticAuditor
from src.geo_profiler import GeoProfiler
from src.eeat_scorer import EEATScorer
from src.cluster_detector import ClusterDetector
from src.enrichment import (
    new_enrichment_stats, enrich_scraped_page,
    carry_forward_cached_page, finalize_domain_cluster,
)
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

    # Load shared config early for all checks
    shared_config = load_shared_config()

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
        reframe = ReframeEngine(shared_config)
        if reframe.client:
            reframe.client.models.retrieve(reframe.model)
            print(f"✅ OpenAI Model Ready: {reframe.model}")
    except Exception as e:
        print(f"❌ OpenAI Connectivity Error: {e}")
        return None

    # 3. Check GSC Connectivity (Mandatory - Hard Fail)
    gsc = None
    try:
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
    reframe_engine = ReframeEngine(shared_config)
    
    # 3. Engines
    auditor = SemanticAuditor()
    geo_profiler = GeoProfiler(shared_config)  # SC-1: competitor GEO/extractability
    eeat_scorer = EEATScorer(shared_config)           # wire-up fix: built but never called
    cluster_detector = ClusterDetector(shared_config)  # wire-up fix: built but never called
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

    # Finding 1/4 (P8/P2): make enrichment coverage provable, so an empty EEAT/GEO/
    # cluster report section is never silently indistinguishable from "competitors
    # had no signals". Counts fresh scores, cache-served carry-forwards, cache hits
    # with no prior profile to carry, and outright failures. See src/enrichment.py.
    enrich = new_enrichment_stats()

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

        # C2/C4: persist this competitor's Domain Authority (avg Moz PA) so positioning
        # (authority axis) and feasibility use the same DA basis as the client. Without
        # this the competitors table stays empty and both features degrade silently.
        if moz_metrics_map:
            db.save_competitor_summary(domain, int(round(avg_pa)))

        domain_medical_total = 0
        domain_t2_total = 0
        domain_t3_total = 0
        domain_traffic_total = 0
        domain_keywords = set()
        processed_urls = set() # Track URLs processed for this domain
        domain_blocked = False
        domain_scraped_pages = []  # wire-up fix: retain pages for cluster detection
        domain_had_cache_hit = False  # Finding 1: track cache hits for cluster carry-forward

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
                    domain_had_cache_hit = True
                    # Finding 1 (P8): page served from the 7-day semantic cache — not
                    # re-scraped, so carry the URL's latest prior EEAT/GEO profile into
                    # this run rather than blank the report sections. See enrichment.py.
                    carry_forward_cached_page(db, run_id, url, enrich)
                else:
                    # scrape_content returns a ScrapedPage (never a "BLOCK"/"" string,
                    # as the pre-ScrapedPage code assumed). Branch on extraction_status
                    # so the 429 circuit-breaker actually fires and failed fetches are
                    # not saved as zero-score traffic magnets / false systemic vacuums.
                    content = auditor.scrape_content(url)
                    status = getattr(content, "extraction_status", "error")
                    if status == "blocked":
                        print(f"  🛑 Circuit Breaker: Domain {domain} is blocking us (429). Skipping remaining pages.")
                        domain_blocked = True
                        continue
                    elif status == "error":
                        print(f"  ⚠️ Skipping unreadable page: {url}")
                        continue
                    scores = auditor.analyze_text(content)
                    db.save_semantic_audit(url, scores['medical_score'], scores['systems_score'], run_id=run_id, label=scores.get('systemic_label', 'Standard'))
                    domain_scraped_pages.append(content)
                    # Wire-up fix + SC-1: score EEAT and profile GEO for the freshly-
                    # scraped page (both were built but never called). See enrichment.py.
                    enrich_scraped_page(db, run_id, content, pa, eeat_scorer, geo_profiler, enrich)

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

        # Wire-up fix (built but never called) + Finding 1 mixed-domain fix: compute
        # cluster detection only when the whole domain was freshly scraped; otherwise
        # carry the latest complete result forward rather than under-count hubs on a
        # partial page set. See src/enrichment.py::finalize_domain_cluster.
        finalize_domain_cluster(
            db, run_id, domain, domain_scraped_pages, domain_had_cache_hit,
            cluster_detector, enrich,
        )

        db.tag_competitor_position(domain, domain_medical_total, domain_t2_total, domain_t3_total, domain_traffic_total)
        competitor_keywords[domain] = domain_keywords

    # Finding 1/4 (P8/P2): surface enrichment coverage. An empty EEAT/GEO/cluster
    # section must never be silently mistaken for "no signals" — report exactly how
    # many were computed fresh, served from cache, or failed.
    print("\n📊 Enrichment coverage  (fresh / carried-forward / cache-hit-no-prior / failed):")
    print(f"   EEAT:    {enrich['eeat_fresh']} / {enrich['eeat_carried']} / {enrich['eeat_no_prior']} / {enrich['eeat_failed']}")
    print(f"   GEO:     {enrich['geo_fresh']} / {enrich['geo_carried']} / {enrich['geo_no_prior']} / {enrich['geo_failed']}")
    print(f"   Cluster: {enrich['cluster_fresh']} / {enrich['cluster_carried']} / {enrich['cluster_no_prior']} / {enrich['cluster_failed']}")
    if enrich["eeat_failed"] or enrich["geo_failed"] or enrich["cluster_failed"]:
        print("   ⚠️ Some enrichment steps FAILED (not merely cache-served) — investigate the warnings above.")
    if enrich["eeat_no_prior"] or enrich["geo_no_prior"] or enrich["cluster_no_prior"]:
        print("   ℹ️ Some cache-served URLs had no prior profile to carry forward; they populate once re-scraped.")

    if all_metrics_to_save:
        db.save_competitor_metrics(all_metrics_to_save, run_id=run_id)

    # Client's own GSC positions — shared by C4 (SERP overlap) and C2 (positioning).
    # get_query_position_map catches its own fetch errors (returns {}), so this is
    # safe to compute once outside the per-feature guards.
    client_positions = gsc.get_query_position_map() if gsc else {}

    # C4 / SC-6: SERP Overlap & Differentiation Gap — the single wired who-ranks-
    # where matrix + the previously-unwired AnalysisEngine keyword-intersection gap
    # and feasibility. Competitor positions come from competitor_metrics; the
    # client's own positions from first-party GSC (the handoff is competitor-only).
    try:
        from src.serp_overlap import analyze_serp_overlap
        overlap = analyze_serp_overlap(
            competitor_positions=db.get_competitor_positions(run_id),
            client_positions=client_positions,
            competitor_keywords=competitor_keywords,
            client_keywords=set(client_positions.keys()),
            client_domain=client_domain,
            client_da=shared_config.get("client", {}).get("da", 0),
            competitor_das=db.get_competitor_das(),
            config=shared_config.get("serp_overlap", {}),
            snapshot_date=datetime.datetime.now().strftime("%Y-%m-%d"),
            keyword_volumes=db.get_keyword_volumes(run_id),
        )
        db.save_serp_overlap(run_id, overlap["rows"])
        db.save_competitor_feasibility(
            run_id, shared_config.get("client", {}).get("da", 0), overlap["feasibility"])
        if not overlap["client_positions_available"]:
            print("   ⚠️ SERP overlap: client GSC positions unavailable this run — "
                  "self-presence UNKNOWN; exclusive-competitor/self claims withheld.")
        print(f"   🗺️  SERP overlap: {len(overlap['rows'])} keywords classified — "
              f"{len(overlap['action_exclusive_competitor'])} exclusive-competitor, "
              f"{len(overlap['action_shared_commodity'])} shared-commodity, "
              f"{len(overlap['gap_keywords'])} all-competitor gaps; "
              f"{len(overlap['feasibility'])} competitors scored for feasibility.")
    except Exception as overlap_err:
        print(f"⚠️ SERP overlap analysis skipped: {overlap_err}")

    # C2 / SC-4: Barbell Positioning Diagnostic — authority x focus 2x2 over the
    # competitors (authority from Moz DA + top-10 rankings, focus from tier identity)
    # plus the client (always plotted; its authority from config DA + GSC top-10, its
    # focus from classifying its GSC queries into tiers, since Compete doesn't audit it).
    # get_positioning_inputs now includes moz_da so competitors use the client's formula.
    try:
        from src.positioning import compute_positioning, classify_query_tiers
        pos_cfg = shared_config.get("positioning", {})
        comp_inputs = db.get_positioning_inputs(run_id)
        client_med, client_sys = classify_query_tiers(
            list(client_positions.keys()), shared_config.get("clinical", {}))
        client_inputs = {
            "moz_da": shared_config.get("client", {}).get("da"),
            "top10_count": sum(1 for p in client_positions.values() if p <= 10),
            "medical_total": client_med, "systems_total": client_sys,
        }
        pos_rows = compute_positioning(comp_inputs, client_domain, client_inputs, pos_cfg)
        db.save_positioning(run_id, pos_rows,
                            computed_at=datetime.datetime.now().strftime("%Y-%m-%d"))
        quads = {}
        for r in pos_rows:
            quads[r["quadrant"]] = quads.get(r["quadrant"], 0) + 1
        print("   🧭 Positioning: " + ", ".join(f"{q}: {n}" for q, n in sorted(quads.items())))
    except Exception as pos_err:
        print(f"⚠️ Positioning analysis skipped: {pos_err}")

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
