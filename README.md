# Simulato AI Exam Platform (v1.5.0)

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
   - **Vertex AI (Gemini):** Set up Application Default Credentials:
     ```bash
     gcloud auth application-default login
     ```
   - **Tesseract OCR:** Download from [github.com/UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki). Ensure `tesseract` is on PATH or set `TESSERACT_CMD` in `.env`.
   - **Configuration:** Edit `.env` in the project root:
     ```env
     GCP_PROJECT_ID=your-gcp-project-id
     GCP_LOCATION=us-central1
     GEMINI_MODEL=gemini-2.5-flash
     PI_HOST=192.168.1.xxx

     # Capture mode: "phone" (camera) or "ghost" (direct screen capture)
     CAPTURE_MODE=phone
     ```
4. Run the startup script (Windows):
   ```powershell
   .\start.bat
   ```
   *(For Linux/Mac: `bash scripts/start_controller.sh`)*
5. **Note the IP Address printed in the terminal** (e.g., `192.168.1.100`). Keep this terminal open.
6. If remote START does not provide a test name, controller now uses `default_test` automatically.

## 4. Android Phones Setup
*You need the single APK installed on both phones.*
1. Build and install using ADB (USB connected):
   ```powershell
   cd mobile_app\android_project
   .\install-and-run.bat
   ```
   Or manually transfer `simulato-release.apk` to both phones.
2. Install the APK on both phones.

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
1. Make sure the Exam Laptop is displaying a testing screen with radio buttons (3 to 5 options; virtual letters A..E) and a NEXT button.
2. On the **Remote Control** phone, tap **START**.
   - If no valid `grid_map.json` exists yet, the controller automatically enters calibration and requests a capture from the Capture Phone.
   - If calibration fails, adjust framing and press **START** again to retry calibration.
3. After calibration succeeds, press **CONTINUE** on the Remote phone.
   - This starts (or resumes) the run from the controller.
4. **Capture → screen coordinate mapping:** Option clicks use **normalized** targets from live detection (`click_at_normalized`). The mapping from capture pixels to exam-screen pixels uses the `transform` block in `config/grid_map.json` (`scale_x`, `scale_y`, `offset_x`, `offset_y`). A naive linear scale (`screen_resolution / capture_resolution`) is wrong when the phone photographs the laptop at an angle; a small affine-style correction (for example adjusted `scale_y` and `offset_y`) fixes systematic “one row below” mis-clicks. Re-running calibration **preserves** a non-naive transform already on disk so you do not lose a tuned mapping. See [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md) troubleshooting for details.
5. During the run:
   - For each question it captures, preprocesses, stitches frames if scrolling was needed, and **always sends the composite image directly to the cloud AI** (Vertex AI Gemini).
   - It uses OCR + adaptive radio-circle detection (HoughCircles with 8-strip scan up to 16% panel width) as primary option targeting, with calibration-anchored A..E mapping to prevent row-shift mistakes when only a subset of options is visible.
   - Calibration-guided filtering removes "Answer here" header phantoms using the actual calibrated option-A position, while upward Y-bias corrects for camera perspective.
   - NEXT targeting uses a layered strategy: layout `next_button` rect center (primary), bottom-bar color-shape detection (blue/green button), OCR "next" word anchor, then layout/grid fallback.
   - After AI returns an answer for a stitched question image, the controller requests a dedicated fresh post-AI mapping frame for live radio-row mapping before click dispatch.
   - It verifies answer selection after click using a dedicated capture around the exact click target, with panel-scan fallback for robustness; on failure it retries the same intended option once (fresh option detection on retry frame).
   - For NEXT verification, it uses multi-tier thresholds (q-panel diff, full-frame diff, pHash hamming, combined signals) with a passive re-check before deciding whether a retry click is required. Thresholds are tuned to avoid false-negative retries that skip questions.
   - Question number (`N / 30`) is read from the header OCR when available and used for status/log visibility.
   - On failures, it pauses and alerts the Remote phone for explicit operator action.

## Recent progress (v1.5.0)

- **AI-Direct Pipeline:** Database matching, image-hash lookups, and OCR pre-checks have been fully eliminated from the question-processing pipeline. Every stitched image is now sent directly to the cloud AI immediately after capture. This removes latency from DB queries and eliminates false cache hits that previously caused wrong answers to be reused.
- **False-Positive Scroll Fix (Structural Path):** The structural scroll detector's `_question_panel_text_truncated` heuristic now filters out navigation/status words ("Marks", "Negative", "View More", "Prev", "Next") and raised its threshold from 2 → 3 words. An option-completeness veto (3+ radio buttons visible → no scroll needed) was added to the structural path.
- **Stitched-Image AI Prompting:** The system prompt explicitly instructs the AI that stitched composite images may contain overlapping frames; a separate `USER_PROMPT_STITCHED` is used when the image spans multiple captures, telling the AI to deduplicate repeated content.
- **AI Anti-Hallucination via OCR Injection:** Tesseract's full-screen word transcript is automatically extracted and appended as context alongside the screenshot in all Vertex AI Gemini prompts.
- **Split-Axis Coordinate Targeting:** Clicks blend calibration data (X-axis) and live OCR detection (Y-axis) dynamically, with a fallback to pure calibration if live detection drifts >120 px.
- **Perspective-aware `grid_map.json` transform:** Runtime option clicks map normalized capture coordinates through `GridMap.capture_to_screen_pixel()` using `scale_*` and `offset_*`, correcting systematic vertical mis-clicks from angled camera photography.
