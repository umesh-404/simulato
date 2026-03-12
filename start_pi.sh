#!/bin/bash
# Simulato — Start Raspberry Pi HID listener
# Uses HIDPi for USB gadget setup (keyboard + absolute mouse)

set -e

echo "=== Simulato Raspberry Pi Node ==="

# Check if script is running as root (needed for HID gadgets)
if [ "$EUID" -ne 0 ]; then
  echo "[!] Please run as root (use sudo)"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# 1. Check if HIDPi gadget is already active
if [ -e "/dev/hidg0" ] && [ -e "/dev/hidg1" ]; then
    echo "[+] HID gadget devices found (/dev/hidg0, /dev/hidg1)"
else
    echo "[!] HID gadget devices NOT found."
    echo "[+] Running HIDPi setup..."
    python3 HIDPi/HIDPi_Setup.py

    # If devices still don't exist, a reboot is needed
    if [ ! -e "/dev/hidg0" ] || [ ! -e "/dev/hidg1" ]; then
        echo ""
        echo "[*] HIDPi applied firmware config. You MUST reboot now."
        echo "    Type: sudo reboot"
        echo "    After reboot, run this script again."
        exit 0
    fi
fi

echo "[+] USB HID Gadget is active."

# 2. Install HIDPi Python library if not already installed
if ! python3 -c "import hidpi" 2>/dev/null; then
    echo "[+] Installing HIDPi Python library..."
    cd HIDPi/library && pip install . && cd "$PROJECT_DIR"
fi

# 3. Check for python dependencies
if ! command -v python3 &> /dev/null; then
    echo "[!] Python3 not found! Installing..."
    apt-get update && apt-get install -y python3
fi

echo "[+] Starting Raspberry Pi Command Listener on port 9000..."
python3 -m raspberry_pi.command_listener
