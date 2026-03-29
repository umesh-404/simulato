#!/bin/bash
# Simulato — Start Main Control PC (Linux/macOS)
#
# Launches the FastAPI controller server.
#
# Usage: bash scripts/start_controller.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "========================================="
echo "      Starting Simulato Controller"
echo "========================================="

# -----------------------------------------------
# Step 1: Start Python backend
# -----------------------------------------------
echo ""
echo "[1/1] Starting Python backend..."

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "[*] No venv found — using system Python"
fi

echo ""
echo "========================================="
echo "  Simulato Controller is starting..."
echo "  API: http://localhost:8000"
echo "  Phones: connect to this IP on port 8000"
echo "========================================="
echo ""

python3 -m controller.main

# -----------------------------------------------
# Teardown
# -----------------------------------------------
echo ""
echo "Shutting down Simulato..."
echo "Done."
