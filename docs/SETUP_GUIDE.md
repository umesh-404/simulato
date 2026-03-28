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

### 1.2.1 Install OCR Engine (Tesseract)
OCR is used as the primary layout detector for click targeting.

1. Install Tesseract OCR for Windows.
2. Verify it works:
```powershell
tesseract --version
```
3. If `tesseract` is not in PATH, set `TESSERACT_CMD` in `.env` to the full executable path.

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
OLLAMA_MODEL=qwen2.5vl:7b-q4_K_M
LOCAL_AI_ASSIST_ENABLED=True
OLLAMA_TIMEOUT_SECONDS=20
OLLAMA_TARGET_TIMEOUT_SECONDS=25
OLLAMA_COOLDOWN_SECONDS=120
OLLAMA_TIMEOUT_COOLDOWN_SECONDS=6
OLLAMA_KEEP_ALIVE=30m
VERIFY_FRAME_TIMEOUT_SECONDS=18
AI_API_MAX_RETRIES=2
AI_API_BACKOFF_BASE_SECONDS=1.0
OCR_LAYOUT_PRIMARY_ENABLED=True
OCR_MIN_WORD_CONFIDENCE=45
OCR_TIMEOUT_SECONDS=6
OCR_PSM=6
# Optional if tesseract is not in PATH:
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
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
    -> Model "qwen2.5vl:7b-q4_K_M" already available.
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
sudo ./start_pi.sh
```

`start_pi.sh` automatically prefers `./venv/bin/python` or `./.venv/bin/python`
if present, so you do not need to manually activate venv before running it.

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
6. Keep the phone fixed on the stand; calibration can be triggered automatically from START.

### 3.2 Remote Control Phone
1. Open the Simulato app
2. Enter the same PC IP and port
3. Select role: **Remote Control**
4. Use the buttons: **START**, **PAUSE**, **STOP**, **STATUS**
5. Alerts appear here with vibration when conflicts arise

Background reliability note:
- The Android heartbeat layer now auto re-registers the device when the
  controller restarts or temporarily loses registration state.

---

## Part 4: Running a Session

### Step-by-Step
1. **Pi:** SSH in → `sudo ./start_pi.sh` → plug USB-C into exam laptop
2. **PC:** Double-click `start.bat` → wait for "Controller is starting..."
3. **Capture Phone:** Open app → enter PC IP → select Capture → aim at screen
4. **Remote Phone:** Open app → enter PC IP → select Remote Control
5. **Remote Phone:** Tap **START**
6. If calibration is required, system auto-enters calibration:
   - On failure: remote shows blocking **Retry Calibration**
   - On success: remote shows **CONTINUE** to start/resume

### What Happens Automatically
```
START command arrives on controller
        ↓
If no valid grid_map.json: auto calibration requested
        ↓
Capture phone captures calibration screenshot
        ↓
If calibration fails → remote blocks on Retry Calibration
If calibration succeeds → remote confirms CONTINUE
        ↓
Capture Phone captures question screenshot
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
Controller requests one fresh post-AI mapping frame for live option-row mapping
        ↓
Match answer text to option letter (A/B/C/D/E)
        ↓
Header OCR reads question number (`N / total`) when visible
        ↓
OCR scans whole screen and adaptive radio-circle detection localize option row target (primary)
        ↓
If OCR cannot localize confidently → Local Qwen targeting fallback
        ↓
Controller maps normalized target to calibrated HID absolute coordinates
        ↓
Pi clicks the correct option on exam laptop
        ↓
Local AI verifies click was registered
        ↓
NEXT target localization (layered):
  1) layout `next_button` rect center
  2) bottom-bar blue/green button color detection
  3) OCR "next" word anchor
  4) layout/grid fallback
        ↓
Pi clicks NEXT
        ↓
Controller verifies screen change
        ↓
If first verify fails → passive re-check (no second click yet)
        ↓
Only if still unchanged → one NEXT retry click
        ↓
When screen changed, process next question
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
| START shows Pi not connected | Start Pi listener (`sudo ./start_pi.sh`) and verify `.env` has correct `PI_HOST`/`PI_PORT` |
| OCR targeting not working | Install Tesseract OCR and set `TESSERACT_CMD` if not on PATH |
| Remote shows WebSocket 403 / heartbeat 404 | Device registration was lost (usually after controller restart). App now auto re-registers; if needed reopen app once |
| `ConnectionResetError 10054` during cloud AI call | Transient internet/provider reset. Controller now wraps it as AI provider failure and auto-falls back to alternate provider once |
| Cloud AI intermittently fails | Retries use exponential backoff (`AI_API_BACKOFF_BASE_SECONDS`: 1s, 2s, ...) before final failure |
| Local AI not active / timing out early | `start.bat` now enforces Ollama readiness and warmup when `LOCAL_AI_ASSIST_ENABLED=True`; increase `OLLAMA_TIMEOUT_SECONDS` only if needed |
| Click lands on wrong option | Keep full exam window in frame, rerun calibration. Calibration-anchored labels now use Y-proximity matching to prevent mislabeling when a radio button is missed. Verify `answer_panel_detected_options.png` debug image for correct A..E mapping. Keep `LOCAL_AI_ASSIST_ENABLED=True`. |
| Correct option clicked but system still says verification failed | Verification checks the exact click target and falls back to a panel-wide highlight scan. On failure it retries the same option once with fresh detection. If this persists, inspect the verification debug crop for highlight visibility and reduce glare/blur. |
| NEXT click skips a question | NEXT verification uses multi-tier thresholds (q-panel diff + pHash + combined signals). Fixed in v1.4.0 — if it recurs, check logs for `NEXT verify` threshold values. |
| Local AI responses are slow | Normal for first query (~5s). Subsequent queries are faster |
| Cloud AI fails | Check API keys in `.env` for both Gemini and Grok. Controller now auto-falls back to alternate cloud provider once before alerting |

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
