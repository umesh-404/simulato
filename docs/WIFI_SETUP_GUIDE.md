# Simulato — WiFi Network Setup Guide

## Overview

Simulato requires all five devices to be connected to the **same WiFi network**. Any network will work — home router, mobile hotspot, campus WiFi, or portable router. There is no requirement for DHCP configuration, static IPs, or a dedicated network.

The only external connection is outbound HTTPS from the Main Control PC to the Cloud Grok API (if using Cloud AI instead of Local Ollama).

## Network Model

```
[Any WiFi Network]
      │
      ├── Main Control PC       (note its IP)
      ├── Raspberry Pi           (note its IP)
      ├── Capture Phone          (enters PC IP in app)
      ├── Remote Control Phone   (enters PC IP in app)
      └── Exam Laptop            (no network participation)
```

All that matters is:

1. **PC and Pi** know each other's IP addresses.
2. **Phones** know the PC's IP address (entered in the app on first launch).
3. All devices are on the **same subnet** (same WiFi network).

## Setup Steps

### Step 1: Connect all devices to the same WiFi

Connect the Main Control PC, Raspberry Pi, Capture Phone, and Remote Control Phone to any shared WiFi network. The Exam Laptop does not need WiFi — it connects to the Pi via USB only.

### Step 2: Find the PC's IP address

**Windows:**
```powershell
ipconfig
# Look for "IPv4 Address" under your WiFi adapter
```

**Linux/macOS:**
```bash
ip addr show wlan0    # Linux
ifconfig en0          # macOS
```

### Step 3: Find the Pi's IP address

```bash
hostname -I
# or
ip addr show wlan0
```

### Step 4: Configure the PC

Create a `.env` file in the project root with the following configuration:

```env
PI_HOST=<pi_ip_address>
PI_PORT=9000
GROK_API_KEY=your_key_here
OLLAMA_MODEL=qwen2.5-vl:7b
```

**Note:** For convenience, you can just run `start.bat` (Windows) or `bash scripts/start_controller.sh` (Linux) which will automatically load the `.env` file.

### Step 5: Configure the phones

When launching the Simulato app, enter the **PC's IP address** and port (default 8000) on the home screen. The app stores this for future sessions.

### Step 6: Verify connectivity

```bash
# From PC: ping Pi
ping <pi_ip_address>

# From PC: test Pi command listener
python -c "import socket; s=socket.socket(); s.connect(('<pi_ip_address>', 9000)); print('Pi OK'); s.close()"

# From phone browser: test PC API
# Navigate to: http://<pc_ip_address>:8000/status
```

## Ports Required

The following ports must be accessible on the local network:

| Device | Port | Protocol | Purpose |
|--------|------|----------|---------|
| Main Control PC | 8000 | TCP (HTTP + WebSocket) | FastAPI server for phones |
| Raspberry Pi | 9000 | TCP | Command listener from PC |

### Firewall Configuration

If your firewall blocks local traffic, allow these ports:

**Windows (PC):**
```powershell
New-NetFirewallRule -DisplayName "Simulato Controller" -Direction Inbound -Port 8000 -Protocol TCP -Action Allow
```

**Linux (Pi):**
```bash
sudo ufw allow 9000/tcp
```

Most home routers and mobile hotspots allow local device-to-device traffic by default.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Phone can't reach PC | Verify same WiFi network; check PC IP; check port 8000 |
| PC can't reach Pi | Verify same WiFi network; check Pi IP; check port 9000 |
| Image upload slow | Move devices closer to router; reduce WiFi interference |
| WebSocket drops | Check WiFi signal strength; reduce distance to router |
| Cloud AI API fails | Verify PC has internet access (only PC needs internet if using Cloud AI) |
| Pi unreachable after reboot | Pi's IP may have changed — re-check with `hostname -I` |

## Tips

- If IP addresses change between sessions (common on home routers), just re-check them before starting. 
- Use the **One-Click Scripts** (`start.bat` for Windows and `start_pi.sh` for Pi) to simplify the startup process.
- For more stable IPs, most routers allow you to "reserve" an IP for a device's MAC address via the router admin page — but this is optional, not required.
- The Exam Laptop never needs network access. It connects to the Pi via USB cable only.
