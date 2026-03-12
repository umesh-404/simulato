# Simulato — Deployment Checklist

Use this checklist before every exam session to verify all components are ready.

---

## 1. Hardware

- [ ] Main Control PC powered on and connected to WiFi
- [ ] Raspberry Pi powered on and connected to WiFi
- [ ] Raspberry Pi USB cable connected to exam laptop
- [ ] Capture Phone charged (> 80%)
- [ ] Remote Control Phone charged (> 80%)
- [ ] All devices on the same WiFi network

## 2. Raspberry Pi (HIDPi)

- [ ] `/dev/hidg0` exists (HIDPi keyboard gadget)
- [ ] `/dev/hidg1` exists (HIDPi mouse gadget)
- [ ] Command listener running (`python3 -m raspberry_pi.command_listener`)
- [ ] PC can reach Pi on port 9000 (or configured PI_PORT)
- [ ] Test HID click works (exam laptop moves cursor)

```bash
# First-time setup (run once, then reboot):
sudo python3 HIDPi/HIDPi_Setup.py
sudo reboot

# After reboot, start the listener:
sudo ./start_pi.sh
```

## 3. Main Control PC

- [ ] Ollama installed (https://ollama.com/download)
- [ ] `.env` file configured with `GROK_API_KEY` or `GEMINI_API_KEY`, and `PI_HOST`
- [ ] Python virtual environment activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Controller running via `start.bat` (auto-starts Ollama + auto-pulls model + starts server)
- [ ] API responds on port 8000

```bash
# Start everything (Ollama + model + controller):
.\start.bat

# Verify:
curl http://localhost:8000/api/status
```

## 4. Database

- [ ] SQLite database initialized (`data/simulato.db` exists)
- [ ] Schema applied (tables: tests, questions, question_snapshots)
- [ ] Test data loaded (if pre-populated question bank available)

## 5. Capture Phone

- [ ] Simulato app installed
- [ ] App configured with Controller IP address
- [ ] Camera permissions granted
- [ ] Device registered with controller (check `/status`)
- [ ] Test image upload successful

## 6. Remote Control Phone

- [ ] Simulato app installed
- [ ] App configured with Controller IP address
- [ ] Device registered as remote controller
- [ ] WebSocket alert connection active
- [ ] Test alert received

## 7. Calibration

- [ ] Capture Phone app open and in Capture Mode
- [ ] Tap **CALIBRATE SCREEN MAP** button on Capture Phone
- [ ] Controller log shows: `Calibration successful: N positions mapped`
- [ ] `config/grid_map.json` saved and loaded
- [ ] Capture Phone shows "Calibration successful" toast
- [ ] Test click on each option (A, B, C, D) verified
- [ ] NEXT button click verified
- [ ] Scroll action verified (if applicable)

## 8. Network

- [ ] All devices connected to the same WiFi network
- [ ] PC → Pi ping OK
- [ ] Phone → PC ping OK
- [ ] Cloud AI API reachable from PC (Gemini or Grok, depending on active provider) OR Local AI running (if using Ollama)

## 9. Pre-Run Verification

- [ ] Controller status shows all devices registered
- [ ] System state is IDLE
- [ ] Send CALIBRATE command → state transitions to CALIBRATION
- [ ] Perform calibration → state transitions to IDLE
- [ ] Send START command → state transitions to RUNNING
- [ ] First question captured and processed successfully
- [ ] Send PAUSE command → state transitions to PAUSED
- [ ] Send STOP command → state transitions to STOPPED

## 10. Logging

- [ ] Logs directory created (`logs/`)
- [ ] Event log writing confirmed
- [ ] Run artifacts directory created (`data/runs/`)
- [ ] Screenshot storage working

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
