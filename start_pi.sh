#!/bin/bash
# Simulato — Start Raspberry Pi HID listener
# Uses HIDPi for USB gadget setup (keyboard + absolute mouse)

set -euo pipefail

echo "=== Simulato Raspberry Pi Node ==="

# Check if script is running as root (needed for HID gadgets)
if [ "$EUID" -ne 0 ]; then
  echo "[!] Please run as root (use sudo)"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Ensure python3 is available for venv creation.
if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 not found. Installing python3 + venv support..."
    apt-get update
    apt-get install -y python3 python3-venv
fi

# Always run from a project-local virtualenv to avoid Debian PEP668 restrictions.
if [ -d "$PROJECT_DIR/venv" ]; then
    VENV_DIR="$PROJECT_DIR/venv"
elif [ -d "$PROJECT_DIR/.venv" ]; then
    VENV_DIR="$PROJECT_DIR/.venv"
else
    VENV_DIR="$PROJECT_DIR/.venv"
    echo "[+] Creating project virtualenv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

PYTHON_BIN="$VENV_DIR/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "[!] Virtualenv python not found at $PYTHON_BIN"
    exit 1
fi

# Ensure pip exists inside venv (some images omit it by default).
"$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
echo "[+] Using Python: $PYTHON_BIN"

# 1. Check if HIDPi gadget is already active
if [ -e "/dev/hidg0" ] && [ -e "/dev/hidg1" ]; then
    echo "[+] HID gadget devices found (/dev/hidg0, /dev/hidg1)"
else
    echo "[!] HID gadget devices NOT found."
    echo "[+] Running HIDPi setup..."
    "$PYTHON_BIN" HIDPi/HIDPi_Setup.py

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
if ! "$PYTHON_BIN" -c "import hidpi" 2>/dev/null; then
    echo "[+] Installing HIDPi Python library..."
    cd HIDPi/library
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install .
    cd "$PROJECT_DIR"
fi

echo "[+] Starting Raspberry Pi Command Listener on port 9000..."
PYTHONPATH="$PROJECT_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" -m raspberry_pi.command_listener
