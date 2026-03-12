#!/bin/bash
# Simulato — Start Main Control PC (Linux/macOS)
#
# Starts Ollama (local AI), auto-pulls the model, then launches
# the FastAPI controller server.
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
# Step 1: Check if Ollama is installed
# -----------------------------------------------
if ! command -v ollama &> /dev/null; then
    echo "[!] Ollama is NOT installed."
    echo "    Install from: https://ollama.com/download"
    echo "    Then re-run this script."
    exit 1
fi

# -----------------------------------------------
# Step 2: Start Ollama server
# -----------------------------------------------
echo ""
echo "[1/3] Starting local AI server (Ollama)..."
ollama serve &> /dev/null &
OLLAMA_PID=$!

# Wait max 10 seconds for Ollama to start
OLLAMA_STARTED=0
for i in $(seq 1 10); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        OLLAMA_STARTED=1
        break
    fi
    sleep 1
done

if [ "$OLLAMA_STARTED" -eq 0 ]; then
    echo "[WARNING] Ollama failed to respond within 10 seconds."
    echo "         Local AI features will be unavailable."
else
    echo "    -> Ollama server started successfully!"
fi

# -----------------------------------------------
# Step 3: Auto-pull model if not present
# -----------------------------------------------
echo ""
echo "[2/3] Checking local AI model..."

# Read model from .env or use default
MODEL="qwen2.5-vl:7b"
if [ -f ".env" ]; then
    ENV_MODEL=$(grep -i "^OLLAMA_MODEL=" .env 2>/dev/null | cut -d'=' -f2 | tr -d '[:space:]')
    if [ -n "$ENV_MODEL" ]; then
        MODEL="$ENV_MODEL"
    fi
fi

if ! ollama list 2>/dev/null | grep -qi "$MODEL"; then
    echo "    Model \"$MODEL\" not found locally. Pulling now..."
    echo "    (This may take several minutes on first run)"
    echo ""
    ollama pull "$MODEL" || echo "[WARNING] Failed to pull model."
else
    echo "    -> Model \"$MODEL\" already available."
fi

# -----------------------------------------------
# Step 4: Start Python backend
# -----------------------------------------------
echo ""
echo "[3/3] Starting Python backend..."

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
kill $OLLAMA_PID 2>/dev/null || true
echo "Done."
