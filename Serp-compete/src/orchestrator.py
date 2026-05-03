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

st.set_page_config(page_title="Serp-Compete Audit Orchestrator", layout="wide")

st.title("🛡️ Serp-Compete: Competitor Analysis Orchestrator")
st.markdown("Analyze competitor pages and generate strategic briefings using Bowen Family Systems reframing.")
st.markdown("---")

# --- SIDEBAR: CONTROLS ---
st.sidebar.header("🛠️ Handoff File Configuration")

# Allow user to configure handoff directory
handoff_dir = st.sidebar.text_input(
    "📂 Competitor Handoff Directory",
    value=default_handoff_dir,
    help="Path to directory containing competitor_handoff_*.json files (usually from Serp-Discover output)"
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
        selected_handoff = st.sidebar.selectbox(
            "📦 Select Handoff File",
            handoff_names,
            help="Latest competitor data from Serp-Discover"
        )
        selected_handoff_path = os.path.join(handoff_dir, selected_handoff)
    else:
        st.sidebar.error(f"❌ No competitor_handoff files found in {handoff_dir}")
        selected_handoff_path = None
else:
    st.sidebar.error(f"❌ Directory not found: {handoff_dir}")
    selected_handoff_path = None

st.sidebar.markdown("---")
st.sidebar.header("🚀 Audit Configuration")

# Copy handoff to project root
copy_handoff = st.sidebar.checkbox("Copy handoff to Serp-Compete root", value=True,
                                   help="Makes file available for offline runs")

run_button = st.sidebar.button("🔥 RUN AUDIT", disabled=(selected_handoff_path is None))

# --- MAIN EXECUTION ---
if run_button and selected_handoff_path:
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

            # 3. Display results
            st.header("📊 Results")

            # Find latest briefing files
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
                    briefing_content = f.read()

                st.markdown("### 📄 Strategic Briefing")
                st.markdown(briefing_content)

                st.download_button(
                    label="⬇️ Download Briefing (MD)",
                    data=briefing_content,
                    file_name=os.path.basename(latest_briefing),
                    mime="text/markdown"
                )

            if xlsx_files:
                with open(xlsx_files[0], 'rb') as f:
                    xlsx_data = f.read()
                st.download_button(
                    label="⬇️ Download Results (Excel)",
                    data=xlsx_data,
                    file_name=os.path.basename(xlsx_files[0]),
                    mime="application/vnd.ms-excel"
                )
        else:
            st.error(f"❌ Audit Failed (Exit Code: {process.returncode})")

    except Exception as e:
        st.error(f"❌ Error running audit: {e}")

else:
    st.info("👈 Configure handoff directory and select a file in the sidebar, then click 'RUN AUDIT'.")

    st.header("ℹ️ How to Use")
    st.markdown("""
    1. **Set Handoff Directory**: Enter the path to your Serp-Discover output folder (saves as default)
    2. **Select File**: Choose the competitor_handoff_*.json file you want to analyze
    3. **Run**: Click "RUN AUDIT" to start the analysis
    4. **View Results**: See the strategic briefing and download files
    """)
