#!/bin/bash
# Simulato — Start Raspberry Pi Command Listener (scripts/ variant)
#
# This is the scripts/ directory variant. The main startup script
# is at the repo root: start_pi.sh
#
# Usage: bash scripts/start_pi.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Simulato Pi Command Listener ==="
echo "Project: $PROJECT_DIR"

# Check HID devices (HIDPi registers keyboard=hidg0, mouse=hidg1)
if [ ! -e /dev/hidg0 ] || [ ! -e /dev/hidg1 ]; then
    echo "[!] HID devices not found. Run HIDPi setup first:"
    echo "    sudo python3 $PROJECT_DIR/HIDPi/HIDPi_Setup.py"
    echo "    sudo reboot"
    exit 1
fi

echo "[+] HID devices found: /dev/hidg0 (keyboard), /dev/hidg1 (mouse)"
echo "[+] Starting command listener..."

cd "$PROJECT_DIR"
python3 -m raspberry_pi.command_listener
