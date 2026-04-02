import streamlit as st
import os
import subprocess
import glob
import yaml
import re
from datetime import datetime

# --- CONFIGURATION ---
ST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERP_KEYWORD_DIR = os.path.join(ST_ROOT, "serp-keyword")
SERP_COMPETE_DIR = os.path.join(ST_ROOT, "Serp-compete")
CONFIG_PATH = os.path.join(SERP_KEYWORD_DIR, "config.yml")

st.set_page_config(page_title="SERP Intelligence Orchestrator", layout="wide")

st.title("🛡️ Living Systems: SERP Intelligence Orchestrator")
st.markdown("---")

# --- SIDEBAR: CONTROLS ---
st.sidebar.header("🛠️ Workflow Settings")

# 1. Keyword File Dropdown
csv_files = glob.glob(os.path.join(SERP_KEYWORD_DIR, "*.csv"))
csv_names = sorted([os.path.basename(f) for f in csv_files])
selected_csv = st.sidebar.selectbox("🎯 Select Keyword File", csv_names)

st.sidebar.markdown("---")
st.sidebar.header("🚀 Selected Steps")

step_mine = st.sidebar.checkbox("Step 1: Competitor Keyword Mining (Module I)", value=True)
step1 = st.sidebar.checkbox("Step 2: SERP Audit & Enrichment (serp_audit.py)", value=False)
step2 = st.sidebar.checkbox("Step 3: Systematic Scoring (run_pipeline.py)", value=True)
step3 = st.sidebar.checkbox("Step 4: GSC Performance Pull (gsc_performance.py)", value=True)
step4 = st.sidebar.checkbox("Step 5: Strike-Mapping & Publication Prep (strike_mapper.py)", value=True)

st.sidebar.warning("Note: Step 3 includes Step 2 internally.")

run_button = st.sidebar.button("🔥 RUN SELECTED STEPS")

# --- HELPERS ---
def run_script(script_path, cwd, args=None):
    cmd = [os.sys.executable, os.path.basename(script_path)]
    if args:
        cmd.extend(args)
    
    st.info(f"Running: {' '.join(cmd)} in {cwd}")
    process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    with st.expander(f"Logs: {os.path.basename(script_path)}", expanded=True):
        log_placeholder = st.empty()
        full_log = ""
        for line in process.stdout:
            full_log += line
            log_placeholder.code(full_log)
    
    process.wait()
    if process.returncode == 0:
        st.success(f"✅ {os.path.basename(script_path)} Completed")
    else:
        st.error(f"❌ {os.path.basename(script_path)} Failed (Exit Code: {process.returncode})")
    return process.returncode == 0

def update_config(csv_file):
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            
            if 'files' not in config:
                config['files'] = {}
            config['files']['input_csv'] = csv_file
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f)
            st.sidebar.success(f"Config updated: {csv_file}")
            return True
        except Exception as e:
            st.sidebar.error(f"Failed to update config: {e}")
            return False
    return False

def get_latest_md_reports():
    """Find the most recent market analysis MD files in serp-keyword/output/"""
    output_dir = os.path.join(SERP_KEYWORD_DIR, "output")
    md_files = glob.glob(os.path.join(output_dir, "market_analysis_*.md"))
    if not md_files:
        return []
    # Sort by modification time
    md_files.sort(key=os.path.getmtime, reverse=True)
    return md_files[:2] # Return latest 2

# --- MAIN EXECUTION ---
if run_button:
    if update_config(selected_csv):
        success = True
        
        if step_mine and success:
            success = run_script(os.path.join(SERP_COMPETE_DIR, "src", "competitor_mining.py"), ST_ROOT)

        if step1 and success:
            success = run_script(os.path.join(SERP_KEYWORD_DIR, "serp_audit.py"), SERP_KEYWORD_DIR)
            
        if step2 and success:
            success = run_script(os.path.join(SERP_KEYWORD_DIR, "run_pipeline.py"), SERP_KEYWORD_DIR)
            
        if step3 and success:
            success = run_script(os.path.join(SERP_COMPETE_DIR, "src", "gsc_performance.py"), ST_ROOT)
            
        if step4 and success:
            success = run_script(os.path.join(SERP_COMPETE_DIR, "src", "strike_mapper.py"), ST_ROOT)

        if success:
            st.balloons()
            st.header("📄 Generated Reports")
            
            # Display latest market analysis
            latest_mds = get_latest_md_reports()
            
            # List of specific reports to check
            reports = latest_mds + [
                os.path.join(SERP_KEYWORD_DIR, "domain_override_candidates.md"),
                os.path.join(ST_ROOT, "gsc_strike_list.md"),
                os.path.join(ST_ROOT, "new_content_opportunities.md"),
                os.path.join(ST_ROOT, "publication", "pillar_north_shore.md"),
                os.path.join(ST_ROOT, "publication", "neighborhood_pivots.md"),
                os.path.join(ST_ROOT, "directory_interception_bio.md")
            ]
            
            # Use a set to avoid duplicates (latest_mds might contain some of these)
            seen = set()
            for r in reports:
                if r in seen: continue
                seen.add(r)
                if os.path.exists(r):
                    with st.expander(f"Report: {os.path.basename(r)}", expanded=True):
                        with open(r, 'r', encoding='utf-8') as f:
                            st.markdown(f.read())
                else:
                    st.warning(f"Report not found: {r}")
    else:
        st.error("Could not update config.yml. Check file permissions.")

else:
    st.info("👈 Select your steps and keyword file in the sidebar and click 'RUN'.")
    
    # Display current state of reports if they exist
    st.header("📄 Existing Publication Drafts")
    col1, col2 = st.columns(2)
    
    with col1:
        if os.path.exists(os.path.join(ST_ROOT, "publication", "pillar_north_shore.md")):
            st.subheader("Pillar Page")
            st.caption("publication/pillar_north_shore.md")
        if os.path.exists(os.path.join(ST_ROOT, "directory_interception_bio.md")):
            st.subheader("Directory Bio")
            st.caption("directory_interception_bio.md")
            
    with col2:
        if os.path.exists(os.path.join(ST_ROOT, "publication", "neighborhood_pivots.md")):
            st.subheader("Neighborhood Pivots")
            st.caption("publication/neighborhood_pivots.md")
        if os.path.exists(os.path.join(ST_ROOT, "new_content_opportunities.md")):
            st.subheader("New Content Opportunities")
            st.caption("new_content_opportunities.md")
        if os.path.exists(os.path.join(ST_ROOT, "gsc_strike_list.md")):
            st.subheader("GSC Strike List")
            st.caption("gsc_strike_list.md")
