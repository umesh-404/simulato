# Simulato AI Exam Platform

Wait, hold on. This system is a distributed 5-device setup. You won't "clone the repo" onto the Android Phones, but you *will* clone it onto the **Mother PC** and your **Raspberry Pi**.

> **📖 For the full step-by-step guide, see [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md)**

Here is exactly how to deploy the entire system from scratch very easily:

## 1. Network Setup
Ensure the following 5 devices are connected to the **same WiFi network**:
- Your Main Control PC ("Mother PC")
- Raspberry Pi 5
- The "Capture" Android Phone
- The "Remote Control" Android Phone
- The Exam Laptop (WiFi doesn't actually matter for this one, just the Pi USB)

## 2. Raspberry Pi Setup (USB HID Emulation)
*The Pi emulates a USB mouse to physically click answers on the Exam Laptop.*
1. SSH into the Raspberry Pi (or connect a monitor/keyboard to it).
2. Clone the repository to the Pi:
   ```bash
   git clone <repo-url> simulato
   cd simulato
   ```
3. Run the HIDPi setup. This configures the USB gadget (keyboard + absolute mouse):
   ```bash
   sudo python3 HIDPi/HIDPi_Setup.py
   ```
   *(First time: it will modify firmware config and ask you to reboot. Do `sudo reboot`, then re-run.)*
4. **Plug the Raspberry Pi's USB-C data port directly into the Exam Laptop.**
5. Start the listener (the script will create/use a local virtualenv and
   install HIDPi there automatically):
   ```bash
   sudo ./start_pi.sh
   # It is now listening on port 9000 for mouse click commands from the PC
   ```

## 3. Mother PC Setup (System Controller)
*The Mother PC handles computer vision, AI matching, logging, and state management.*
1. Open a terminal on your Main PC.
2. Clone the repository here:
   ```powershell
   git clone <repo-url> simulato
   cd simulato
   ```
3. **Set API Keys and Configure AI:**
   - **Grok (Cloud Solver):** Get a key from [console.x.ai](https://console.x.ai/).
     ```powershell
     $env:GROK_API_KEY="xai-your-api-key"
     ```
   - **Ollama (Local Analyst):** Download from [ollama.com](https://ollama.com/).
     ```bash
     ollama run qwen2.5vl:7b-q4_K_M
     ```
   - **Configuration:** Open `controller/config.py` and ensure `LOCAL_AI_ASSIST_ENABLED = True` to use the local Qwen model for screen analysis.
4. Run the startup script (Windows):
   ```powershell
   .\start.bat
   ```
   *(For Linux/Mac: `bash scripts/start_controller.sh`)*
5. **Note the IP Address printed in the terminal** (e.g., `192.168.1.100`). Keep this terminal open.
6. If remote START does not provide a test name, controller now uses `default_test` automatically.

## 4. Android Phones Setup
*You need the single APK installed on both phones.*
1. You can find the pre-compiled `simulato-mobile-v1.apk` right here in the root folder of the repo on your PC.
2. Transfer that APK file to both Android phones (via USB, email, Google Drive, whatever is easiest).
3. Install the APK on both phones.

**On the Capture Phone:**
1. Mount the Capture Phone steadily above the Exam Laptop screen so the camera sees the whole screen clearly.
2. Open the Simulato app.
3. Tap **Capture Device**.
4. Enter the Mother PC's IP Address (from Step 3.5) and connect.

**On the Remote Control Phone:**
1. Keep this phone in your hand.
2. Open the Simulato app.
3. Tap **Remote Controller**.
4. Enter the Mother PC's IP Address and connect.

## 5. First Run & Calibration
Now that everything is running and talking to the Mother PC:
1. Make sure the Exam Laptop is displaying a testing screen with radio buttons (Option A, B, C, D) and a NEXT button.
2. On the **Remote Control** phone, tap **START**.
   - If no valid `grid_map.json` exists yet, the controller automatically enters calibration and requests a capture from the Capture Phone.
   - If calibration fails, adjust framing and press **START** again to retry calibration.
3. After calibration succeeds, press **CONTINUE** on the Remote phone.
   - This starts (or resumes) the run from the controller.
4. During the run:
   - For each question it captures, preprocesses, checks DB/image-hash first, and calls Grok/Gemini only for new questions.
   - It uses local Qwen first to localize precise normalized click targets (option and NEXT), then sends calibrated HID absolute clicks to Pi.
   - If local targeting is unavailable/slow, it falls back to calibrated CV/grid coordinates.
   - It verifies answer selection after click using a dedicated capture before advancing.
   - On failures, it pauses and alerts the Remote phone for explicit operator action.
