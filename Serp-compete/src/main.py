import sys
import datetime
import os
import json
import glob
import warnings
import jsonschema
from src.api_clients import (DataForSEOClient, MozClient, domain_authority_map,
                              page_authority_map)
from src.semantic import SemanticAuditor
from src import briefing_messages
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
from src.brand_utils import normalise_domain
from src import audit_universe
from src.reporting import ReportGenerator
from src.reframe_engine import ReframeEngine
from src.velocity_module import VelocityTracker
from src.gsc_performance import GSCManager
from src import config_io
from src import db_connect

# Paths relative to the project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED_CONFIG_PATH = config_io.SHARED_CONFIG_PATH  # review chunk Y16
MANUAL_TARGETS_PATH = os.path.join(PROJECT_ROOT, "manual_targets.json")
HANDOFF_SCHEMA_PATH = os.path.join(PROJECT_ROOT, "handoff_schema.json")
KEYWORD_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "serp-keyword", "output")

# One reader for this file (review chunk Y16): `src.database.load_shared_config`,
# which is `config_io.load_config`. This module had its own copy.
from src.database import load_shared_config  # noqa: E402

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

def convert_handoff_to_targets(handoff_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], List[str]]:
    """Convert handoff format to internal targets format.

    Returns `(targets, paa_map, client_brand_names)`. The third element used to be
    dropped on the floor while `comparison_features` read a `client.brand_names`
    key that does not exist in shared_config.json, so the client's branded-demand
    query was the bare stem 'livingsystems' (C-C-13).

    `est_traffic` is 0 because the handoff carries no traffic estimate — it means
    "not measured", and src/audit_universe.py fills it from DataForSEO's `etv`
    only when DataForSEO reports the same url AND keyword.
    """
    targets = []
    for target in handoff_data.get("targets", []):
        targets.append({
            "domain": target["domain"],
            "url": target["url"],
            "primary_keyword": target["primary_keyword_for_url"],
            "est_traffic": 0,  # Handoff doesn't include traffic; 0 = not measured
            "rank": target["rank"],
            "entity_type": target["entity_type"],
            "content_type": target["content_type"],
            "title": target["title"],
            "source_keyword": target["source_keyword"]
        })
    return targets, {}, list(handoff_data.get("client_brand_names") or [])

def convert_legacy_to_targets(legacy_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], List[str]]:
    """Convert legacy market_analysis format to internal targets format.

    Third element (client brand names) is always [] — the legacy format has no
    such field; the caller falls back to shared_config `client.name`.
    """
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

    return targets, paa_data, []

def _handoff_anchor_texts(run_domains=None, client_domain: str = "") -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Anchor texts and fetch coverage from the latest handoff's Moz block.

    Returns `(anchors_by_domain, coverage)`. Coverage travels with the anchors
    so a run where every Moz call failed cannot be reported as "no anchor
    risks found" (Spec: compete-spec.md#C6, SC-8.4).

    Thin wrapper so the import stays local and guarded — an optional signal
    must never stop the audit starting.
    """
    try:
        from src.handoff_moz import (anchor_coverage, anchor_texts_by_domain,
                                     moz_collected_at)  # noqa: F401
        # The block validated in get_latest_market_data, not a second raw read
        # of the same file: only the first was checked against the schema, so
        # re-reading meant the moz block bypassed validation entirely.
        from src.handoff_moz import validated_moz_block
        block = validated_moz_block()
        coverage = anchor_coverage(block, run_domains, client_domain)
        coverage["collected_at"] = moz_collected_at(block)
        return anchor_texts_by_domain(block), coverage
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Moz anchor texts unavailable: {exc}")
        # A distinguishable sentinel, not an empty dict: total failure of the
        # anchor path must not render identically to a run where nothing was
        # attempted, which is the one case where silence is correct (P2/P25).
        return {}, {"total": 0, "fetch_status": "unavailable", "reason": str(exc)}


def _remember_moz_block(handoff_data: Dict[str, Any]) -> None:
    """Retain the handoff's `moz` block and `schema_version` for later steps.

    The state and its guard live in src.handoff_moz, which is importable
    without the application's full dependency set and can therefore be tested.

    The version is retained here, with the block, because both are facts about
    the handoff that was actually validated and both are needed long after
    ingestion returns — the version decides whether the report must qualify
    `targets[].rank` as page-relative (Chunk X, rank semantics).
    """
    try:
        from src.handoff_moz import (remember_client_domain,
                                     remember_handoff_version,
                                     remember_moz_block)
        remember_moz_block(handoff_data)
        remember_handoff_version(handoff_data)
        # Review chunk Y1: the published client host, so a handoff produced
        # for a different client is reported rather than audited in silence.
        remember_client_domain(handoff_data)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Moz block not retained: {exc}")


def get_latest_market_data(handoff_path: str = None) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], List[str], str]:
    """
    Gap 1: Competitor handoff ingestion from Tool 1.

    With `handoff_path` that exact file is used (the orchestrator's selection, passed
    through as `--handoff`). Without it, sources are tried in order:
    1. competitor_handoff_*.json (Tool 1 Gap 3) — validated against handoff_schema.json
    2. market_analysis_*.json (legacy, deprecated) — with DeprecationWarning
    3. manual_targets.json (developer override) — fallback only

    Returns: (list of target entries, dict of keyword -> paa_questions,
              client brand names from the handoff — [] on the legacy/manual paths,
              the path or label of the source actually used)

    C-C-16: the GUI's handoff selection only reached this function when "Copy handoff
    to root" happened to be ticked, because the path was never passed and this
    function picked whichever `competitor_handoff_*.json` in the repo root was newest.
    Unticked, the owner could select an older handoff and silently get a report about
    a different file — and nothing in the report named the file it used.
    """
    schema = load_handoff_schema()
    # Cleared per ingestion: the legacy and manual paths never set it, so a
    # second run in one process would otherwise attribute the previous
    # handoff's anchors to it (P8).
    _remember_moz_block({})

    # 1. The explicitly selected handoff, else the newest in the project root.
    handoff_file = handoff_path or find_latest_handoff_file()
    if handoff_path and not os.path.exists(handoff_path):
        print(f"❌ Handoff not found: {handoff_path}")
        sys.exit(1)
    if handoff_file:
        print(f"📦 Loading competitor handoff from: {handoff_file}")
        try:
            with open(handoff_file, 'r') as f:
                handoff_data = json.load(f)

            # C-C-14: enforce `handoff.supported_versions`. README and USER_MANUAL
            # tell the owner this key lists "Tool 1 handoff formats accepted" and
            # nothing read it — so a future Tool 1 bump to 2.0 would have been
            # neither accepted nor rejected by version, only by the schema's
            # `additionalProperties: false`. The config also listed 2.0/2.1 while
            # every real handoff is 1.0 or 1.1; the values are corrected to the real
            # ones, because enforcing the wrong list would reject every file.
            version_error = _unsupported_handoff_version(handoff_data)
            if version_error:
                print(f"❌ {version_error}")
                sys.exit(1)

            # Validate against schema
            if schema:
                try:
                    jsonschema.validate(instance=handoff_data, schema=schema)
                    print(f"✅ Handoff validated against schema v{handoff_data.get('schema_version')}")
                    _remember_moz_block(handoff_data)
                    return (*convert_handoff_to_targets(handoff_data), handoff_file)
                except jsonschema.ValidationError as e:
                    print(f"❌ Handoff validation failed: {e.message}")
                    print(f"   Path: {list(e.path)}")
                    sys.exit(1)  # Hard fail per spec
            else:
                print("⚠️ Schema file not found; skipping validation. Using handoff data as-is.")
                _remember_moz_block(handoff_data)
                return (*convert_handoff_to_targets(handoff_data), handoff_file)
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
            return (*convert_legacy_to_targets(legacy_data), legacy_file)
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
                return targets, {}, [], MANUAL_TARGETS_PATH
        except Exception as e:
            print(f"❌ Error loading manual targets: {e}")
            return [], {}, [], MANUAL_TARGETS_PATH

    # No data sources found
    print(f"⚠️ No data sources found (checked: handoff, legacy, manual).")
    return [], {}, [], "none"

def _unsupported_handoff_version(handoff_data: Dict[str, Any]) -> str | None:
    """None when the handoff's `schema_version` is accepted, else why not (C-C-14).

    An empty or absent `handoff.supported_versions` means "accept any version", which
    is the pre-2026-11-15 behaviour — the key is a allowlist, not a requirement to
    configure one.
    """
    config = load_shared_config().get("handoff", {}) or {}
    supported = [str(v) for v in (config.get("supported_versions") or [])]
    if not supported:
        return None
    version = str(handoff_data.get("schema_version") or "")
    if version in supported:
        return None
    return (f"Handoff schema_version {version or '(absent)'} is not in "
            f"handoff.supported_versions {supported}. Either Tool 1 changed format or "
            f"the config is stale — this is a hard fail rather than a silent audit of "
            f"a file this tool does not understand.")


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
            auth=(dfs.login, dfs.password),
            # C-C-12: without a timeout this call could hang the pre-flight check
            # indefinitely — the one call in the run that had none.
            timeout=30
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
            # Normalised on load so the comparison cannot depend on which form
            # each side happens to use.
            from src.brand_utils import normalise_domain
            return {normalise_domain(line) for line in f if line.strip()}
    return set()

def parse_args(argv: List[str]) -> Dict[str, Any]:
    """`--handoff <path>` — the handoff the caller selected (C-C-16).

    Hand-rolled rather than argparse so the one flag stays trivially testable and
    `python3 src/main.py` with no arguments behaves exactly as before.
    """
    options: Dict[str, Any] = {"handoff": None}
    for i, arg in enumerate(argv):
        if arg == "--handoff" and i + 1 < len(argv):
            options["handoff"] = argv[i + 1]
        elif arg.startswith("--handoff="):
            options["handoff"] = arg.split("=", 1)[1]
    return options


def run_audit(handoff_path: str = None):
    """Run the audit, and say on the way out if a cleanup step failed.

    The briefing's coverage block carries the tally as it stood when the
    report was generated; the report itself then reads the database several
    more times, and `pre_flight_check` opens it before this function can
    return early. So the tally is also read in a `finally`, where an abort and
    the report's own reads are both still covered (P2, the cold review of
    chunk Y13).
    """
    # A tally left by an earlier run in this process would be reported as
    # this run's (P6, review chunk Y13). The same applies to the report
    # messages this process could not find (chunk Y17): the GUI runs twice in
    # one process, and the second briefing must count its own holes.
    db_connect.reset_cleanup_failures()
    briefing_messages.reset_misses()
    try:
        return _run_audit(handoff_path)
    finally:
        db_connect.report_cleanup_failures()


def _run_audit(handoff_path: str = None):
    gsc = pre_flight_check()
    if not gsc:
        print("🛑 Pre-flight check failed. Aborting run.")
        sys.exit(1)

    shared_config = load_shared_config()
    omitted_domains = load_omitted_domains(shared_config)
    client_domain = shared_config.get("client", {}).get("domain", "livingsystems.ca")

    # 1. Foundation: Dynamic Handover & Velocity Tracker
    targets_raw, paa_map, client_brand_names, handoff_file = get_latest_market_data(
        handoff_path)
    # Review chunk Y1: the handoff says which client it was produced for, and
    # nothing read it. This repo's config stays the authority — the audit is
    # configured here — but a disagreement is stated rather than left to be
    # discovered in the numbers. Checked before the no-targets abort: a handoff
    # for the wrong client is a likely reason for there to be no targets, and
    # behind the abort the run died without ever naming it (cold review of Y1).
    try:
        from src.handoff_moz import client_domain_mismatch
        client_mismatch = client_domain_mismatch(client_domain)
    except Exception:                               # never abort on a caveat
        client_mismatch = ""
    if client_mismatch:
        print(f"⚠️ Client mismatch: {client_mismatch}.")

    if not targets_raw:
        print("❌ No competitors identified. Aborting.")
        return

    # Optimization 1: Group by domain — by the CANONICAL form of it.
    #
    # Chunk X (canonical domain form): Tool 1 writes `targets[].domain` as
    # `netloc.lower()` with `www.` kept, while its own citation and brand paths
    # strip it. Grouping on the raw string therefore made one site two
    # competitors whenever a handoff carried both forms — two DataForSEO
    # enrichment calls, two `competitors` rows, two sets of keyword counts for
    # the barbell and positioning to divide between, and the same brand token
    # derived twice. The omit-list test two lines below already normalised, so
    # the two paths disagreed about what a domain is: an omitted `www.` host
    # was skipped while its bare twin was audited.
    #
    # The canonical form is the stripped one, because that is what the rest of
    # this repo already compares on: `load_omitted_domains`, `derive_brand_name`,
    # `sov_analyzer._norm_domain`, `cluster_detector._normalise` and
    # `youtube_presence._stem` all normalise first. Target URLs are untouched —
    # the URL is what gets fetched, and `https://www.x.com/a` is not
    # necessarily `https://x.com/a`.
    #
    # Decision 4 (which side owns canonical form) is still open and this does
    # not pre-empt it: the workplan's own note is that the fix belongs here
    # defensively either way, and if Tool 1 starts stripping at write time this
    # code keeps working unchanged.
    #
    # The grouping itself lives in src.audit_universe so that a test can reach
    # it — this loop was unreachable from any test, and the one test that
    # covered it re-implemented it instead.
    domain_groups = audit_universe.group_targets_by_domain(targets_raw)
    dropped_targets = len(targets_raw) - sum(len(v) for v in domain_groups.values())
    if dropped_targets:
        print(f"⚠️ {dropped_targets} handoff target(s) carried no domain and were "
              f"not attributed to a competitor.")

    # The domains this run is willing to audit: every ingested domain MINUS the
    # policy exclusions. Deliberately not minus the get_relevant_pages skip —
    # that is a DataForSEO call, and a 429 there is transient, which is what
    # scoping on competitor_keywords got wrong. But domain_groups alone
    # re-admits the omit list, so an omitted directory could collect an
    # anchor-spam finding in a client report (P3/P6).
    audited_domains = [d for d in domain_groups if d not in omitted_domains]

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

    # C-M-01 (owner decision 1(b), 2026-11-14): the handoff is the PRIMARY audit
    # universe — `url` / `primary_keyword_for_url` is what Tool 1 actually ranked and
    # what FEATURE_GUIDE §2.1 promises. DataForSEO `ranked_keywords` is kept only as an
    # additional enrichment, filtered by the relevance test below, with each keyword's
    # source carried into the report. See src/audit_universe.py.
    from src.brand_utils import derive_brand_name
    brand_suffixes = shared_config.get("brand", {}).get("name_suffixes")
    handoff_keywords = audit_universe.handoff_keyword_set(targets_raw)
    clinical_terms = audit_universe.clinical_term_set(shared_config.get("clinical", {}))
    universe_stats = audit_universe.new_universe_stats()
    # C-C-12 (P2): a domain that drops out of the run must leave a trace in the
    # ARTEFACT, not only in the console. The "Missing Data Alert" could never fire
    # for one, because it compared the set of domains that produced pages with
    # itself.
    skipped_domains: List[Tuple[str, str]] = []
    enrichment_failures: List[Tuple[str, str]] = []
    unmeasured_pa_domains: List[str] = []
    unmeasured_da_domains: List[str] = []
    # C-M-20: the Executive Summary must state run coverage, which until now reached
    # only the console — so a reader of the .md could not tell fresh from cached, nor
    # a blocked domain from one with nothing to report.
    blocked_domains: List[str] = []
    cached_domains: List[str] = []
    incomplete_tier_domains: List[str] = []
    print(f"🎯 Audit universe: {len(handoff_keywords)} keyword(s) handed over by Tool 1 "
          f"across {len(targets_raw)} target URL(s) in {len(domain_groups)} domain(s).")

    # Finding 1/4 (P8/P2): make enrichment coverage provable, so an empty EEAT/GEO/
    # cluster report section is never silently indistinguishable from "competitors
    # had no signals". Counts fresh scores, cache-served carry-forwards, cache hits
    # with no prior profile to carry, and outright failures. See src/enrichment.py.
    enrich = new_enrichment_stats()

    print(f"Starting audit for {client_domain}...")
    
    # 4. Ingestion & Expert Filtering
    for domain, group_targets in domain_groups.items():
        # Aggregator/Omitted Exclusion: Cross-reference the external omitted_domains list
        if normalise_domain(domain) in omitted_domains:
            print(f"Skipping omitted domain: {domain}")
            skipped_domains.append((domain, "on the omit list"))
            continue

        print(f"Analyzing competitor: {domain}")
        brand_token = derive_brand_name(domain, brand_suffixes)
        # Enrichment only now, never the universe itself: a DataForSEO failure here
        # costs this domain its keyword enrichment, not its audit. The call is also
        # guarded: an unhandled RequestException used to abort the whole run AFTER
        # create_run had written its row, leaving an orphan run and no report
        # (C-C-12). get_relevant_pages no longer raises, but the guard means a future
        # change there cannot resurrect that failure mode.
        try:
            enrichment_items = dfs_client.get_relevant_pages(domain)
        except Exception as dfs_err:  # noqa: BLE001 - recorded, never fatal
            enrichment_items = []
            enrichment_failures.append((domain, str(dfs_err)))
            print(f"  ⚠️ DataForSEO enrichment failed for {domain}: {dfs_err}")
        else:
            if not enrichment_items:
                reason = getattr(dfs_client, "last_error", None) or "no ranked keywords returned"
                enrichment_failures.append((domain, reason))
                print(f"  ℹ️ No DataForSEO ranked keywords for {domain} ({reason}) — "
                      f"auditing its handoff targets only.")
        pages = audit_universe.build_domain_universe(
            group_targets, enrichment_items, handoff_keywords, clinical_terms,
            brand_token, universe_stats)
        if not pages:
            print(f"  ⚠️ No auditable (url, keyword) rows for {domain} — skipped.")
            skipped_domains.append((domain, "no auditable (url, keyword) rows"))
            continue

        # Moz metrics for filtering
        urls = []
        for record in pages:
            if record["url"] not in urls:
                urls.append(record["url"])
        # C-C-03/C-C-04: a URL Moz had no record for is ABSENT from this map, never
        # present with 0, so `pa` below is None ("unknown") rather than a measured
        # authority of zero. The N-of-M line makes a shape mismatch (`page` vs `url`,
        # C-C-04) visible as 0-of-M on the next live run instead of silently mapping
        # one arbitrary URL.
        moz_metrics_map = {}
        moz_error = None
        domain_root = f"https://{normalise_domain(domain)}/"
        competitor_domain_authority = None
        try:
            # C-M-09: ask for the domain ROOT as well, so the barbell's authority
            # axis and the feasibility table can use a real Moz Domain Authority
            # instead of the average PAGE authority of the sampled URLs. It is the
            # same call and the same response — the domain figure was simply never
            # read.
            moz_results = moz_client.get_url_metrics(urls + [domain_root])
            moz_metrics_map = page_authority_map(moz_results, urls)
            root_da = domain_authority_map(moz_results, [domain_root])
            competitor_domain_authority = root_da.get(domain_root)
            print(f"  Moz returned {len(moz_metrics_map)} metrics for {len(urls)} URL(s)"
                  f"; domain authority "
                  f"{competitor_domain_authority if competitor_domain_authority is not None else 'unmeasured'}.")
        except Exception as e:
            moz_error = str(e)
            print(f"  Warning: Moz metrics failed: {e} — Page Authority is UNKNOWN for "
                  f"{domain} this run (stored NULL, not 0).")

        # Expert Filter: DA Threshold: Skip any domain where Domain Authority > 50.
        # With no measured PA the filter cannot be applied at all: say so rather than
        # let `avg_pa = 0` silently disable it (P2).
        if moz_metrics_map:
            avg_pa = sum(moz_metrics_map.values()) / len(moz_metrics_map)
            # C-M-18: the threshold is config, not a literal. FEATURE_GUIDE §3.1 says
            # "exact weights/thresholds live in shared_config.json ... editable
            # without code changes", and this one — which decides whether a
            # competitor is audited at all — was a `50` in the middle of the loop.
            high_authority_max_pa = float(
                (shared_config.get("technical", {}) or {}).get("high_authority_max_pa", 50))
            if avg_pa > high_authority_max_pa:
                print(f"  Skipping high-authority domain (Avg PA {avg_pa:.1f} > "
                      f"{high_authority_max_pa:g}): {domain}")
                skipped_domains.append(
                    (domain, f"PA filter (avg PA {avg_pa:.1f} > {high_authority_max_pa:g})"))
                continue
            # C2/C4: persist this competitor's authority figures. `avg_da` is the
            # average PAGE authority of the sampled URLs (the historic column);
            # `domain_authority` is the domain root's real Moz DA, or None when Moz
            # did not return one — positioning and feasibility read the latter
            # (C-M-09) and withhold a verdict rather than compare a DA with a PA.
            db.save_competitor_summary(
                domain, int(round(avg_pa)),
                domain_authority=(None if competitor_domain_authority is None
                                  else int(round(competitor_domain_authority))))
            if competitor_domain_authority is None:
                unmeasured_da_domains.append(domain)
        else:
            avg_pa = None
            unmeasured_pa_domains.append(domain)
            print(f"  ℹ️ Avg Page Authority unmeasured for {domain} "
                  f"({moz_error or 'Moz returned no metrics for these URLs'}) — the "
                  f"PA > 50 filter was NOT applied and no competitors row was written.")

        domain_medical_total = 0
        domain_t2_total = 0
        domain_t3_total = 0
        domain_traffic_total = 0
        domain_keywords = set()
        processed_urls = set() # Track URLs processed for this domain
        domain_blocked = False
        domain_scraped_pages = []  # wire-up fix: retain pages for cluster detection
        domain_had_cache_hit = False  # Finding 1: track cache hits for cluster carry-forward
        domain_tier_counts_complete = True  # C-C-08: False once a page's counts are unknown
        domain_pages_audited = 0

        for page in pages:
            if domain_blocked:
                break

            url = page["url"]
            keyword = page["keyword"]
            pos = page["position"]
            traffic = page["traffic"]
            keyword_source = page["keyword_source"]
            keyword_relevant = page["keyword_relevant"]

            if keyword:
                domain_keywords.add(keyword)

            all_metrics_to_save.append({
                "domain": domain,
                "url": url,
                "keyword": keyword,
                "position": pos,
                "traffic": traffic,
                "keyword_source": keyword_source
            })
            
            # C-C-03: None, not 0 — "Moz had no figure" is not "authority zero".
            pa = moz_metrics_map.get(url)
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
                    if status in ("blocked", "error"):
                        # C-C-06: record the ATTEMPT with rank NULL instead of omitting
                        # it. An omitted page used to shrink the visibility series,
                        # which read as the competitor losing visibility; a NULL rank
                        # says "we could not read this", which is what happened.
                        velocity.save_market_snapshot(
                            domain=domain, url=url, keyword=keyword, rank=None, da=pa,
                            systems_score=None, medical_score=None, run_id=run_id)
                    if status == "blocked":
                        print(f"  🛑 Circuit Breaker: Domain {domain} is blocking us (429). Skipping remaining pages.")
                        domain_blocked = True
                        continue
                    elif status == "error":
                        print(f"  ⚠️ Skipping unreadable page: {url}")
                        continue
                    scores = auditor.analyze_text(content)
                    db.save_semantic_audit(
                        url, scores['medical_score'], scores['systems_score'],
                        run_id=run_id, label=scores.get('systemic_label', 'Standard'),
                        # C-C-08: persist the real tier counts so a cache hit never
                        # has to guess them back out of the weighted score.
                        t2_count=scores.get('t2_count'), t3_count=scores.get('t3_count'),
                        scoring_window_words=scores.get('scoring_window_words'))
                    domain_scraped_pages.append(content)
                    # Wire-up fix + SC-1: score EEAT and profile GEO for the freshly-
                    # scraped page (both were built but never called). See enrichment.py.
                    enrich_scraped_page(db, run_id, content, pa, eeat_scorer,
                                        geo_profiler, enrich,
                                        # C-M-12: the DOMAIN's authority for the
                                        # authoritativeness component, not this URL's
                                        # page authority.
                                        domain_authority=competitor_domain_authority)

                db.save_traffic_magnet(run_id, domain, url, keyword, traffic,
                                       scores['medical_score'], scores['systems_score'],
                                       label=scores.get('systemic_label', 'Standard'),
                                       keyword_source=keyword_source,
                                       keyword_relevant=keyword_relevant,
                                       rank=pos,
                                       # C-C-08: the real counts travel with the row;
                                       # None for a pre-C3 cached page, never guessed.
                                       t2_count=scores.get('t2_count'),
                                       t3_count=scores.get('t3_count'),
                                       # C-M-19: the window the counts came from, so
                                       # the report can show a density.
                                       scoring_window_words=scores.get('scoring_window_words'))
                print(f"  Audit {url}: Medical {scores['medical_score']}, Systems {scores['systems_score']} "
                      f"({scores.get('systemic_label')}) — keyword '{keyword}' "
                      f"[{keyword_source}, rank {pos}, "
                      f"{'relevant' if keyword_relevant else 'not a magnet candidate'}]")
                
                # Spec 4: Save every audit result (DA, Rank, Scores) into market_history
                velocity.save_market_snapshot(
                    domain=domain,
                    url=url,
                    keyword=keyword,
                    rank=pos,
                    da=pa, # Using PA as proxy for DA at URL level (NULL when unknown)
                    systems_score=scores['systems_score'],
                    medical_score=scores['medical_score'],
                    run_id=run_id,  # C-C-05: alerts are scoped to the run
                )

                domain_medical_total += scores['medical_score']
                # C-C-08 / C-M-05: the tier counts are READ, never estimated. The
                # deleted estimate (`t3 = systems_score / 2.0 if >= 2.0`) turned a
                # page with four generic Tier-2 words into "one Tier-3 term" on a
                # cached re-run and re-labelled its domain *Direct Systemic*. A
                # cached row written before the counts were persisted has None, and
                # that is carried as UNKNOWN to tag_competitor_position rather than
                # silently counted as zero.
                t2_count, t3_count = scores.get('t2_count'), scores.get('t3_count')
                if t2_count is None or t3_count is None:
                    domain_tier_counts_complete = False
                else:
                    domain_t2_total += t2_count
                    domain_t3_total += t3_count
                domain_traffic_total += traffic
                domain_pages_audited += 1
                processed_urls.add(url)

        # Wire-up fix (built but never called) + Finding 1 mixed-domain fix: compute
        # cluster detection only when the whole domain was freshly scraped; otherwise
        # carry the latest complete result forward rather than under-count hubs on a
        # partial page set. See src/enrichment.py::finalize_domain_cluster.
        finalize_domain_cluster(
            db, run_id, domain, domain_scraped_pages, domain_had_cache_hit,
            cluster_detector, enrich,
        )

        db.tag_competitor_position(domain, domain_medical_total, domain_t2_total,
                                   domain_t3_total, domain_traffic_total,
                                   tier_counts_complete=domain_tier_counts_complete)
        if not domain_tier_counts_complete:
            print(f"  ℹ️ Tier counts incomplete for {domain} (cache-served pages "
                  f"audited before the counts were persisted) — the Direct Systemic / "
                  f"Generalist classification is withheld this run.")
            incomplete_tier_domains.append(domain)
        if domain_had_cache_hit:
            cached_domains.append(domain)
        if domain_blocked:
            blocked_domains.append(domain)
        competitor_keywords[domain] = domain_keywords

    # Finding 1/4 (P8/P2): surface enrichment coverage. An empty EEAT/GEO/cluster
    # section must never be silently mistaken for "no signals" — report exactly how
    # many were computed fresh, served from cache, or failed.
    # C-M-01 (P2): say how the keyword universe was assembled, so an enrichment
    # keyword in the report can never be mistaken for a handed-over ranked fact.
    print(f"\n🎯 Keyword universe: {audit_universe.universe_summary_line(universe_stats)}")

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

    # C-C-03 / C-C-12 (P2): run coverage, for the console AND the briefing. An absent
    # competitor and an unmeasured authority figure are facts about the run; until
    # now they reached only the console, so a reader of the .md could not tell a
    # competitor that was skipped from one that has nothing to report.
    pa_measured, pa_total = db.get_pa_coverage(run_id)
    run_coverage = {
        "handoff_file": handoff_file or "unknown",
        "domains_in_handoff": len(domain_groups),
        "domains_audited": len(competitor_keywords),
        "skipped_domains": skipped_domains,
        "enrichment_failures": enrichment_failures,
        "unmeasured_pa_domains": unmeasured_pa_domains,
        "unmeasured_da_domains": unmeasured_da_domains,
        "blocked_domains": blocked_domains,
        "cached_domains": cached_domains,
        "incomplete_tier_domains": incomplete_tier_domains,
        "pa_measured": pa_measured,
        "pa_total": pa_total,
        "universe": dict(universe_stats),
        # Carried into the report, not left in the console line above.
        "client_domain_mismatch": client_mismatch,
    }
    # Chunk X (rank semantics / H1): the handoff's ranks are page-relative
    # until serp-discover's D1 lands, so the magnet table's "rank" column is
    # not a SERP position. Carried as a fact about the ingested file rather
    # than hard-coded, so the caveat disappears by itself once a handoff
    # arrives on a version listed in `handoff.absolute_rank_versions`.
    try:
        from src.handoff_moz import handoff_rank_is_absolute, validated_handoff_version
        run_coverage["handoff_version"] = validated_handoff_version()
        # The run's OWN config, passed in rather than read again inside the
        # helper: a second read resolves the file relative to src/, so an
        # orchestrator- or test-supplied config was ignored and the report
        # could have described a rank convention the run was not using.
        run_coverage["rank_is_absolute"] = handoff_rank_is_absolute(
            absolute_versions=(shared_config.get("handoff", {}) or {}).get(
                "absolute_rank_versions") or [])
    except Exception as exc:  # noqa: BLE001
        # A caveat that fails silently is worse than no caveat: the rank column
        # would print unqualified and the report would look as though the ranks
        # had been checked. Record the failure so the coverage block says the
        # convention is unknown (P2/P25).
        print(f"⚠️ Handoff rank semantics not determined: {exc}")
        run_coverage["rank_semantics_error"] = str(exc)
    print(f"\n📋 Run coverage: audited {len(competitor_keywords)} of "
          f"{len(domain_groups)} handoff domain(s); "
          f"{len(skipped_domains)} skipped"
          + (f" ({', '.join(f'{d}: {r}' for d, r in skipped_domains)})"
             if skipped_domains else "")
          + f"; Page Authority measured for {pa_measured} of {pa_total} audited URL(s)."
          + (f" Enrichment unavailable for {len(enrichment_failures)} domain(s)."
             if enrichment_failures else ""))

    # Comparison layer (C4 SERP-overlap / C2 positioning / C1 AI share-of-voice /
    # C3 branded-demand / C6 reputation-risk) — extracted to src/comparison_features.py
    # so the assembly (read inputs → compute → persist) is unit-testable; each feature is
    # independently guarded there (see tests/test_comparison_features.py).
    from src.comparison_features import run_comparison_features
    # Unpacked explicitly: `**dict(zip(...))` truncates to the shorter side
    # without error, so a change in either list would silently drop a kwarg —
    # a silent drop inside the code added to stop silent drops (P2).
    _moz_anchors, _moz_coverage = _handoff_anchor_texts(
        audited_domains, client_domain)
    run_comparison_features(db, run_id, shared_config, client_domain, competitor_keywords,
                            gsc, dfs_client, PROJECT_ROOT,
                            anchor_texts_by_domain=_moz_anchors,
                            anchor_coverage=_moz_coverage,
                            run_domains=audited_domains,
                            client_brand_names=client_brand_names,
                            # C-M-09/C-M-11: the shared keyword universe, so the
                            # client's top-10 count and the overlap matrix are
                            # restricted to what Tool 1 handed over.
                            handoff_keywords=handoff_keywords)

    # Strategic Logic with PAA context from Handover.
    # C-M-02 (owner decision 2, 2026-11-14): a page is a reframe target only when it
    # clears the medical floor, ranks well on a handed-over keyword, and that keyword
    # passed the relevance test — not merely because its systems score is 0.
    from src.database import magnet_thresholds
    vacuum_min_medical, magnet_max_position = magnet_thresholds(shared_config)
    print("Identifying Strategic Openings...")
    openings = db.identify_strategic_openings(
        run_id, min_medical=vacuum_min_medical, max_position=magnet_max_position)
    audited_pages = db.count_audited_pages(run_id)
    print(f"   {len(openings)} reframe target(s) of {audited_pages} audited page(s) "
          f"(medical_score >= {vacuum_min_medical}, handoff rank <= "
          f"{magnet_max_position}, keyword passes the relevance test, no systemic "
          f"language).")
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

    # Spec 4: Get market velocity alerts — scoped to THIS run (C-C-05). Before this,
    # a URL that left the competitive set kept its last recorded drop in every later
    # briefing, forever.
    market_alerts = velocity.get_market_alerts(run_id=run_id)

    # P2 — a database cleanup step that failed is a fact this run has to
    # report. `db_connect._safely` logs each one so a failed close cannot
    # replace the exception that caused it (chunk Y11), but a log line is not
    # where the reader of the briefing looks, and the audit opens and closes a
    # connection per domain: one failed close is usually many. Read after the
    # audit's own work, not where run_coverage is built; `run_audit`'s
    # `finally` covers what the report generator then does.
    run_coverage["db_cleanup"] = db_connect.cleanup_failure_warning()

    reporter.generate_summary(
        client_domain, 
        expected_competitors=list(competitor_keywords.keys()), 
        run_id=run_id, 
        reframes=reframes,
        token_usage=total_usage,
        market_alerts=market_alerts,
        gsc_findings=gsc_findings,
        run_coverage=run_coverage,
    )

if __name__ == "__main__":
    run_audit(handoff_path=parse_args(sys.argv[1:])["handoff"])
