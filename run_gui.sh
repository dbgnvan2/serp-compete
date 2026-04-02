#!/bin/bash
# Living Systems SERP Orchestrator Launcher

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🛡️ Starting Living Systems SERP Orchestrator..."

# Check if streamlit is installed
if ! python3 -c "import streamlit" &> /dev/null; then
    echo "⚠️ Streamlit not found. Attempting to install..."
    pip3 install streamlit
fi

# Launch the orchestrator
streamlit run Serp-compete/src/orchestrator.py
