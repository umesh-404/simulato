#!/bin/bash
# Simulato — Start Raspberry Pi Command Listener
#
# Starts the TCP command listener that receives HID commands
# from the Main Control PC and executes them.
#
# Usage: bash start_pi.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Simulato Pi Command Listener ==="
echo "Project: $PROJECT_DIR"

# Check HID device
if [ ! -e /dev/hidg0 ]; then
    echo "[!] /dev/hidg0 not found. Run setup_pi_hid.sh first and reboot."
    exit 1
fi

echo "[+] HID device found: /dev/hidg0"
echo "[+] Starting command listener..."

cd "$PROJECT_DIR"
python3 -m raspberry_pi.command_listener
