# Simulato — Complete Setup Guide

This guide takes you from zero to a fully running system.

---

## Prerequisites

| Device | Required | Notes |
|--------|----------|-------|
| Main Control PC | Windows 10/11 | Python 3.11+, internet for API calls |
| Raspberry Pi 5 | Raspberry Pi OS | Connected to exam laptop via USB-C |
| Capture Phone | Android 8.0+ | Camera pointed at exam screen |
| Remote Control Phone | Android 8.0+ | Operator uses this to control the system |
| Exam Laptop | Any | The device being automated |

---

## Part 1: Mother PC Setup

### 1.1 Clone & Install Dependencies
```powershell
git clone <repo-url> simulato
cd simulato
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 1.2 Install Ollama (Local AI)
1. Download from **https://ollama.com/download**
2. Run the installer
3. That's it — `start.bat` will auto-pull the model on first run

> **What does Ollama do?** It runs a small vision AI model (Qwen 2.5 VL) locally on your PC for auxiliary tasks: detecting if scrolling is needed, verifying clicks landed correctly, and checking if the screen shows a question or an error page. This is NOT the AI that answers questions — that's Grok/Gemini in the cloud.

### 1.3 Configure API Keys
Edit the `.env` file in the project root:
```env
# Pick one or both cloud AI providers:
GROK_API_KEY=your-grok-api-key-here
GEMINI_API_KEY=your-gemini-api-key-here

# Which one to use by default:
DEFAULT_AI_PROVIDER=gemini

# Pi's IP on your WiFi network:
PI_HOST=192.168.1.xxx

# Local AI model (auto-pulled by start.bat):
OLLAMA_MODEL=qwen2.5-vl:7b
LOCAL_AI_ASSIST_ENABLED=True
```

### 1.4 Start the Controller
```powershell
.\start.bat
```

**What happens automatically:**
1. ✅ Checks if Ollama is installed
2. ✅ Starts the Ollama server
3. ✅ Auto-pulls the AI model (first run: ~4GB download, takes 5-10 min)
4. ✅ Starts the FastAPI controller on port 8000
5. ✅ On exit, kills Ollama cleanly

You should see:
```
[1/3] Starting local AI server (Ollama)...
    -> Ollama server started successfully!
[2/3] Checking local AI model...
    -> Model "qwen2.5-vl:7b" already available.
[3/3] Starting Python backend...
=========================================
  Simulato Controller is starting...
  API: http://localhost:8000
=========================================
```

---

## Part 2: Raspberry Pi Setup

> ✅ **Already tested and working on your Pi 5.**

### 2.1 First-Time Setup (Already Done)
```bash
cd ~/simulato
sudo python3 HIDPi/HIDPi_Setup.py    # configures USB gadget
sudo reboot                            # activates gadget firmware
```

### 2.2 Install HIDPi Library (Already Done)
```bash
cd ~/simulato
python3 -m venv venv
source venv/bin/activate
cd HIDPi/library && pip install . && cd ~/simulato
```

### 2.3 Start the Listener (Every Session)
```bash
cd ~/simulato
source venv/bin/activate
sudo ./start_pi.sh
```

### 2.4 Physical Connection
- **USB-C cable** from Pi → Exam Laptop (for HID mouse/keyboard)
- **WiFi** connects Pi to the same network as the Mother PC

---

## Part 3: Android Phones Setup

> ✅ **APK built and installed on both phones.**

### 3.1 Capture Phone
1. Open the Simulato app
2. Enter the Mother PC's IP address (e.g., `192.168.1.100`)
3. Enter port: `8000`
4. Select role: **Capture**
5. Point the camera at the exam laptop screen
6. Tap **CALIBRATE SCREEN MAP** (one-time; maps where A/B/C/D/NEXT buttons are)

### 3.2 Remote Control Phone
1. Open the Simulato app
2. Enter the same PC IP and port
3. Select role: **Remote Control**
4. Use the buttons: **START**, **PAUSE**, **STOP**, **STATUS**
5. Alerts appear here with vibration when conflicts arise

---

## Part 4: Running a Session

### Step-by-Step
1. **Pi:** SSH in → `sudo ./start_pi.sh` → plug USB-C into exam laptop
2. **PC:** Double-click `start.bat` → wait for "Controller is starting..."
3. **Capture Phone:** Open app → enter PC IP → select Capture → aim at screen
4. **Remote Phone:** Open app → enter PC IP → select Remote Control
5. **Capture Phone:** Tap **CALIBRATE SCREEN MAP** (only needed once per exam layout)
6. **Remote Phone:** Tap **START**

### What Happens Automatically
```
Capture Phone captures screenshot
        ↓
Mother PC receives image via HTTP
        ↓
Local AI checks: is this a question screen? → if not, skip
        ↓
Local AI checks: does the question need scrolling?
        ↓
If scroll needed → Pi scrolls → phone recaptures → stitch frames
        ↓
Check DB: have we seen this question before?
        ↓
If DB hit → use cached answer (skip cloud AI call)
If new → send to Grok/Gemini AI → get answer
        ↓
Match answer text to option letter (A/B/C/D)
        ↓
Pi clicks the correct option on exam laptop
        ↓
Local AI verifies click was registered
        ↓
Pi clicks NEXT → auto-advance to next question
        ↓
Repeat
```

### Handling Conflicts
When the AI gives a different answer than what's in the database:
1. System **pauses** and plays an alarm
2. Remote phone shows an alert with both answers
3. Operator picks: **USE_AI_ANSWER**, **USE_DATABASE_ANSWER**, **SKIP**, or **REQUERY**

---

## Part 5: Troubleshooting

| Problem | Solution |
|---------|----------|
| `start.bat` says "Ollama is NOT installed" | Download from https://ollama.com/download |
| Model pull is slow | First pull is ~4GB. Subsequent starts are instant |
| Phone can't connect to PC | Ensure same WiFi network. Check firewall: allow port 8000 |
| Pi `BrokenPipeError` | USB cable isn't connected to exam laptop, or cable is charge-only |
| "HID devices not found" on Pi | Run `sudo python3 HIDPi/HIDPi_Setup.py` then `sudo reboot` |
| Click lands on wrong option | Re-run calibration (CALIBRATE button on Capture phone) |
| Local AI responses are slow | Normal for first query (~5s). Subsequent queries are faster |
| Cloud AI fails | Check API key in `.env`. Check internet on PC |

---

## File Reference

| File | Purpose |
|------|---------|
| `start.bat` | Start everything on PC (Ollama + model + controller) |
| `start_pi.sh` | Start everything on Pi (HIDPi check + listener) |
| `.env` | API keys, Pi IP, model config |
| `config/grid_map.json` | Calibration data (auto-generated) |
| `runs/` | Session logs, screenshots, AI responses |
| `database/questions.db` | Question cache (grows over sessions) |
