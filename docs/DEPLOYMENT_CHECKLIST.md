# Simulato — Deployment Checklist

Use this checklist before every exam session to verify all components are ready.

> Current checkmarks reflect latest validated project/session behavior as of 2026-03-28. Re-verify before each live exam.

---

## 1. Hardware

- [ ] Main Control PC powered on and connected to WiFi
- [ ] Raspberry Pi powered on and connected to WiFi
- [ ] Raspberry Pi USB cable connected to exam laptop
- [ ] Capture Phone charged (> 80%)
- [ ] Remote Control Phone charged (> 80%)
- [ ] All devices on the same WiFi network

## 2. Raspberry Pi (HIDPi)

- [x] `/dev/hidg0` exists (HIDPi keyboard gadget)
- [x] `/dev/hidg1` exists (HIDPi mouse gadget)
- [x] Command listener running (`sudo ./start_pi.sh` using project venv)
- [x] PC can reach Pi on port 9000 (or configured PI_PORT)
- [x] Test HID click works (exam laptop moves cursor)

Optional quick smoke-test (recommended after changing cables/USB ports):

```powershell
# From the Mother PC (Windows):
python scripts/pi_smoke_test.py --host <PI_IP> --pattern center
python scripts/pi_smoke_test.py --host <PI_IP> --pattern corners
python scripts/pi_smoke_test.py --host <PI_IP> --pattern grid --steps 5
```

```bash
# First-time setup (run once, then reboot):
sudo python3 HIDPi/HIDPi_Setup.py
sudo reboot

# After reboot, start the listener:
sudo ./start_pi.sh
```

## 3. Main Control PC

- [x] Ollama installed (https://ollama.com/download)
- [x] Tesseract OCR installed and on PATH (or `TESSERACT_CMD` set in `.env`)
- [x] `.env` file configured with `GCP_PROJECT_ID` and `GCP_LOCATION`, and `PI_HOST`
- [x] Python virtual environment activated
- [x] Dependencies installed (`pip install -r requirements.txt`)
- [x] Controller running via `start.bat` (auto-starts Ollama + auto-pulls model + starts server)
- [x] API responds on port 8000

```bash
# Verify Tesseract:
tesseract --version

# Start everything (Ollama + model + controller):
.\start.bat

# Verify:
curl http://localhost:8000/api/status
```

## 4. Database

- [x] SQLite database initialized (`database/questions.db` exists)
- [x] Schema applied (tables: tests, questions, question_snapshots)
- [ ] Test data loaded (if pre-populated question bank available)

## 5. Capture Phone

- [x] Simulato app installed
- [x] App configured with Controller IP address
- [x] Camera permissions granted
- [x] Device registered with controller (check `/api/status`)
- [x] Test image upload successful

## 6. Remote Control Phone

- [x] Simulato app installed
- [x] App configured with Controller IP address
- [x] Device registered as remote controller
- [x] WebSocket alert connection active
- [x] Test alert received

## 7. Calibration

- [x] Capture Phone app open and in Capture Mode
- [x] Tap **CALIBRATE SCREEN MAP** button on Capture Phone
- [x] Controller log shows: `Calibration successful: N positions mapped`
- [x] `config/grid_map.json` saved and loaded (includes `transform` for capture→screen; v1.4.1+ preserves non-naive transform on re-calibration)
- [x] Capture Phone shows "Calibration successful" toast
- [x] Test click on each visible option row verified (3-5 rows, virtual letters A..E); if clicks land systematically one row off, adjust `transform` in `grid_map.json` or see `docs/SETUP_GUIDE.md`
- [x] NEXT button click verified
- [x] NEXT does not double-click after successful navigation (passive re-check + combined-signal verification confirms change before retry)
- [x] Scroll action verified (if applicable)

Optional CV pipeline calibration (validates scroll/option detection across 30-image dataset):

```powershell
python scripts/calibrate_cv_pipeline.py
python scripts/calibrate_scroll.py
```

## 8. Network

- [ ] All devices connected to the same WiFi network
- [ ] PC → Pi ping OK
- [ ] Phone → PC ping OK
- [ ] Cloud AI API reachable from PC (Gemini or Gemini, depending on active provider) OR Local AI running (if using Ollama)

## 9. Pre-Run Verification

- [x] Controller status shows all devices registered
- [x] System state is IDLE
- [x] Pi listener reachable from PC (if not, START will be rejected with INPUT_FAILURE)
- [x] Send CALIBRATE command → state transitions to CALIBRATION
- [x] Perform calibration → state transitions to IDLE
- [x] Send START command → state transitions to RUNNING
- [x] First question captured and processed successfully
- [x] Question number (`N / total`) appears in status/logs when visible in capture header
- [x] Send PAUSE command → state transitions to PAUSED
- [x] Send STOP command → state transitions to STOPPED

## 10. Logging

- [x] Logs directory created (`logs/`)
- [x] Event log writing confirmed
- [x] Run artifacts directory created (`runs/`)
- [x] Screenshot storage working

---

## Quick Start Sequence

1. Power on all devices
2. Connect all devices to the same WiFi network
3. On Pi: `sudo ./start_pi.sh`
4. On PC: Double-click `start.bat` (Starts Ollama, then Python backend)
5. On Capture Phone: Open app → Connect → Capture Mode
6. On Remote Phone: Open app → Connect → Remote Mode
7. On Capture Phone: Tap **CALIBRATE SCREEN MAP** → verify success toast
8. On Remote Phone: Tap START → system begins processing

---

## Emergency Procedures

| Situation | Action |
|-----------|--------|
| System alert sounds | Check Remote Phone for details |
| Click verification fails | System auto-pauses — verify exam screen |
| AI/DB conflict | Choose answer on Remote Phone |
| Network drops | System pauses — reconnect and resume |
| Unexpected screen | System pauses — manually navigate to question |
| Total failure | STOP system, collect logs, restart |

## Shutting Down

- To stop the system, close the `start.bat` command prompt window or press `Ctrl+C`.
- `start.bat` will automatically stop the Python server and kill the background Ollama process.
- On Windows, you can also use `scripts\stop_controller.bat` to kill the controller process.

## Android APK Install

To install or reinstall the APK on a connected Android phone:

```powershell
cd mobile_app\android_project
.\install-and-run.bat
```

This builds a release APK, installs it via ADB, and launches the app.
