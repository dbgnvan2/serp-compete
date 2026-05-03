#!/bin/bash
# Serp-Compete Audit Runner
# Finds latest competitor_handoff from Serp-Discover and runs full analysis

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERP_COMPETE_DIR="$SCRIPT_DIR/Serp-compete"
HANDOFF_SOURCE="$SCRIPT_DIR/../serp-discover/output"

echo "🛡️ Living Systems: Serp-Compete Audit Runner"
echo "---"

# 1. Find latest handoff file
echo "📦 Looking for competitor handoff file..."
HANDOFF_FILE=$(find "$HANDOFF_SOURCE" -name "competitor_handoff_*.json" -type f 2>/dev/null | sort -r | head -1)

if [ -z "$HANDOFF_FILE" ]; then
    echo "❌ No competitor_handoff file found in $HANDOFF_SOURCE"
    echo "   Please run Serp-Discover first to generate competitor data."
    exit 1
fi

echo "✅ Found: $(basename "$HANDOFF_FILE")"

# 2. Copy handoff to project root
echo "📋 Copying handoff to Serp-Compete..."
cp "$HANDOFF_FILE" "$SCRIPT_DIR/"
echo "✅ Copied"

# 3. Run audit
echo "---"
echo "🔥 Starting audit (this may take 2-5 minutes)..."
echo ""

cd "$SERP_COMPETE_DIR"
export PYTHONPATH=.
python3 src/main.py

# 4. Show results
echo ""
echo "---"
echo "✅ Audit Complete!"
echo ""
echo "📊 Output files:"
ls -lh strategic_briefing_run_*.md audit_results_run_*.xlsx 2>/dev/null | tail -2 | awk '{print "   " $9 " (" $5 ")"}'
echo ""
echo "📖 To view results:"
echo "   open strategic_briefing_run_*.md"
echo "   or open audit_results_run_*.xlsx"
