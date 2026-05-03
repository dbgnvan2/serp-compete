import streamlit as st
import os
import subprocess
import glob
import json
from datetime import datetime

# --- CONFIGURATION ---
ST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERP_COMPETE_DIR = os.path.join(ST_ROOT, "Serp-compete")
SHARED_CONFIG_PATH = os.path.join(ST_ROOT, "shared_config.json")

# Load shared config
def load_config():
    if os.path.exists(SHARED_CONFIG_PATH):
        with open(SHARED_CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(SHARED_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

shared_config = load_config()
default_handoff_dir = shared_config.get("orchestrator", {}).get("handoff_source_dir",
                                                                  os.path.join(ST_ROOT, "..", "serp-discover", "output"))
default_reports_dir = shared_config.get("orchestrator", {}).get("reports_dir",
                                                                 SERP_COMPETE_DIR)

st.set_page_config(page_title="Serp-Compete Audit Orchestrator", layout="wide")

st.title("🛡️ Serp-Compete: Competitor Analysis Orchestrator")
st.markdown("Analyze competitor pages and generate strategic briefings using Bowen Family Systems reframing.")
st.markdown("---")

# Initialize session state for report display
if "show_report" not in st.session_state:
    st.session_state.show_report = False
if "report_content" not in st.session_state:
    st.session_state.report_content = None
if "report_xlsx" not in st.session_state:
    st.session_state.report_xlsx = None
if "report_filename" not in st.session_state:
    st.session_state.report_filename = None

# --- SIDEBAR: CONTROLS ---
st.sidebar.header("🛠️ Configuration")

# Tabs for configuration
config_tab1, config_tab2 = st.sidebar.tabs(["🔍 New Audit", "📂 Settings"])

with config_tab1:
    st.subheader("Run New Audit")

    # Allow user to configure handoff directory
    handoff_dir = st.text_input(
        "📦 Competitor Handoff Directory",
        value=default_handoff_dir,
        help="Path to directory containing competitor_handoff_*.json files (from Serp-Discover output)"
    )

    # Save as default if different
    if handoff_dir != default_handoff_dir:
        config = load_config()
        if "orchestrator" not in config:
            config["orchestrator"] = {}
        config["orchestrator"]["handoff_source_dir"] = handoff_dir
        save_config(config)

    # Find handoff files in selected directory
    if os.path.exists(handoff_dir):
        handoff_files = sorted(glob.glob(os.path.join(handoff_dir, "competitor_handoff_*.json")),
                              key=os.path.getmtime, reverse=True)
        handoff_names = [os.path.basename(f) for f in handoff_files]

        if handoff_names:
            selected_handoff = st.selectbox(
                "📋 Select Handoff File",
                handoff_names,
                help="Latest competitor data from Serp-Discover"
            )
            selected_handoff_path = os.path.join(handoff_dir, selected_handoff)
        else:
            st.error(f"❌ No competitor_handoff files found in {handoff_dir}")
            selected_handoff_path = None
    else:
        st.error(f"❌ Directory not found: {handoff_dir}")
        selected_handoff_path = None

    # Copy handoff to project root
    copy_handoff = st.checkbox("Copy handoff to Serp-Compete root", value=True,
                              help="Makes file available for offline runs")

    run_button = st.button("🔥 RUN AUDIT", disabled=(selected_handoff_path is None), use_container_width=True)

with config_tab2:
    st.subheader("Settings")

    reports_dir = st.text_input(
        "📁 Reports Directory",
        value=default_reports_dir,
        help="Where to save generated briefing files"
    )

    if reports_dir != default_reports_dir:
        config = load_config()
        if "orchestrator" not in config:
            config["orchestrator"] = {}
        config["orchestrator"]["reports_dir"] = reports_dir
        save_config(config)

st.sidebar.markdown("---")

# Load previous reports section
st.sidebar.header("📚 Previous Reports")

if os.path.exists(default_reports_dir):
    briefing_files = sorted(
        glob.glob(os.path.join(default_reports_dir, "strategic_briefing_run_*.md")),
        key=os.path.getmtime, reverse=True
    )

    if briefing_files:
        briefing_names = [os.path.basename(f) for f in briefing_files]
        selected_report = st.sidebar.selectbox(
            "📖 Load Previous Report",
            briefing_names,
            help="Open a previously generated report"
        )

        if st.sidebar.button("📖 Open Report", use_container_width=True):
            report_path = os.path.join(default_reports_dir, selected_report)
            try:
                with open(report_path, 'r') as f:
                    st.session_state.report_content = f.read()

                # Try to find corresponding Excel file
                xlsx_name = selected_report.replace("strategic_briefing_", "audit_results_").replace(".md", ".xlsx")
                xlsx_path = os.path.join(default_reports_dir, xlsx_name)
                if os.path.exists(xlsx_path):
                    with open(xlsx_path, 'rb') as f:
                        st.session_state.report_xlsx = f.read()
                else:
                    st.session_state.report_xlsx = None

                st.session_state.report_filename = selected_report
                st.session_state.show_report = True
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"❌ Failed to load report: {e}")
    else:
        st.sidebar.info("No previous reports found")
else:
    st.sidebar.warning(f"Reports directory not found: {default_reports_dir}")

# --- MAIN CONTENT ---

# Report display section (persistent until closed)
if st.session_state.show_report and st.session_state.report_content:
    st.header("📊 Report")

    col1, col2 = st.columns([1, 10])
    with col1:
        if st.button("❌ Close Report"):
            st.session_state.show_report = False
            st.session_state.report_content = None
            st.session_state.report_xlsx = None
            st.rerun()

    with col2:
        st.markdown(f"*Report: {st.session_state.report_filename}*")

    st.markdown("---")

    # Display briefing content
    st.markdown(st.session_state.report_content)

    st.markdown("---")

    # Download buttons
    col1, col2 = st.columns(2)

    with col1:
        if st.session_state.report_content:
            st.download_button(
                label="⬇️ Download Briefing (MD)",
                data=st.session_state.report_content,
                file_name=st.session_state.report_filename or "strategic_briefing.md",
                mime="text/markdown"
            )

    with col2:
        if st.session_state.report_xlsx:
            st.download_button(
                label="⬇️ Download Results (Excel)",
                data=st.session_state.report_xlsx,
                file_name=st.session_state.report_filename.replace(".md", ".xlsx").replace("strategic_briefing_", "audit_results_"),
                mime="application/vnd.ms-excel"
            )

# Audit execution
elif run_button and selected_handoff_path:
    # 1. Copy handoff file if requested
    if copy_handoff:
        import shutil
        try:
            dest_path = os.path.join(ST_ROOT, os.path.basename(selected_handoff_path))
            shutil.copy(selected_handoff_path, dest_path)
            st.info(f"✅ Copied {os.path.basename(selected_handoff_path)} to project root")
        except Exception as e:
            st.error(f"❌ Failed to copy handoff: {e}")

    # 2. Run audit
    st.header("🔄 Running Competitor Analysis...")

    cmd = ["python3", "src/main.py"]
    st.info(f"Running: {' '.join(cmd)} in {SERP_COMPETE_DIR}")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=SERP_COMPETE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONPATH": "."}
        )

        with st.expander("📋 Audit Logs", expanded=True):
            log_placeholder = st.empty()
            full_log = ""
            for line in process.stdout:
                full_log += line
                log_placeholder.code(full_log)

        process.wait()

        if process.returncode == 0:
            st.balloons()
            st.success("✅ Audit Completed Successfully!")

            # 3. Load and display results
            briefing_files = sorted(
                glob.glob(os.path.join(SERP_COMPETE_DIR, "strategic_briefing_run_*.md")),
                key=os.path.getmtime, reverse=True
            )
            xlsx_files = sorted(
                glob.glob(os.path.join(SERP_COMPETE_DIR, "audit_results_run_*.xlsx")),
                key=os.path.getmtime, reverse=True
            )

            if briefing_files:
                latest_briefing = briefing_files[0]
                with open(latest_briefing, 'r') as f:
                    st.session_state.report_content = f.read()

                if xlsx_files:
                    with open(xlsx_files[0], 'rb') as f:
                        st.session_state.report_xlsx = f.read()

                st.session_state.report_filename = os.path.basename(latest_briefing)
                st.session_state.show_report = True
                st.rerun()
        else:
            st.error(f"❌ Audit Failed (Exit Code: {process.returncode})")

    except Exception as e:
        st.error(f"❌ Error running audit: {e}")

else:
    st.info("👈 Click 'New Audit' tab to run analysis or 'Previous Reports' in sidebar to open an existing report.")

    st.header("ℹ️ How to Use")
    st.markdown("""
    ### Run a New Audit
    1. Click the **New Audit** tab
    2. Enter path to Serp-Discover output folder (saves as default)
    3. Select a `competitor_handoff_*.json` file
    4. Click "RUN AUDIT"
    5. Review results and download files

    ### Load a Previous Report
    1. Use **Previous Reports** sidebar to browse your reports
    2. Select a report and click "Open Report"
    3. Report stays open until you click "Close Report"
    4. Download files anytime from the report view

    ### Configure Settings
    1. Click **Settings** tab to change where reports are saved
    2. Reports directory saves automatically
    """)
