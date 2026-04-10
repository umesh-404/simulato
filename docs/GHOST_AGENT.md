# GHOST AGENT — Direct Screen Capture from Exam Laptop

**Status:** Implemented (controller integration complete, agent ready for build)  
**Version:** v1.0  
**Last Updated:** 2026-04-06

---

## 1. PROBLEM STATEMENT

Simulato currently uses a **physical phone camera** (Capture Phone, Node 4) mounted above the exam laptop to photograph the screen. This introduces fundamental, unfixable sources of error:

| Problem | Root Cause | Impact |
|---|---|---|
| **Coordinate mapping error** | Camera images are 4096×3072; screen is 1920×1080. An affine transform (`scale_x`, `scale_y`, `offset_x`, `offset_y`) maps between them. | ±15–30px click drift. Wrong option selected. |
| **Perspective distortion** | Camera views the laptop at an angle, producing trapezoidal warp. | Scale/offset corrections are approximations. Systematic vertical mis-clicks. |
| **Lighting artifacts** | Variable ambient light, reflections, shadows on screen surface. | HoughCircles detects false radio buttons from glare. Option detection degrades. |
| **Bezel contamination** | Physical laptop frame appears in captured images. | `header_anchor.py` was built to mask this but captured the plastic bezel itself as a template, corrupting detection. |
| **Capture latency** | Camera auto-focus + JPEG encode + Wi-Fi upload + WebSocket relay. | ~1–2 seconds per frame. Adds cumulative delay over 30+ questions. |
| **Calibration fragility** | Phone position shifts, angle changes, lighting changes between sessions. | Requires recalibration. `grid_map.json` transform drift. |

**The Ghost Agent eliminates all of these problems** by capturing the screen digitally from the exam laptop itself — pixel-perfect, zero distortion, zero latency.

---

## 2. SOLUTION OVERVIEW

A lightweight, headless Python agent runs directly on the exam laptop. It captures the screen at native resolution (1920×1080) using the **DXGI Desktop Duplication API** and streams JPEG frames to the Main Control PC over TCP on the same Wi-Fi network.

### Key Properties

- **Pixel-perfect capture**: 1920×1080 input = 1920×1080 screen. No transform needed.
- **Zero calibration**: Coordinates in the capture ARE screen coordinates. Identity transform.
- **Zero lighting artifacts**: Digital pixel readout. No reflections, no shadows, no camera noise.
- **Low latency**: ~50–100ms per frame (DXGI grab + JPEG encode + Wi-Fi TCP).
- **Invisible**: No window, no tray icon, no console. Disguised process name.
- **Zero footprint**: Single `.exe` file. No installation, no registry, no services.

---

## 3. ARCHITECTURE

```
┌──────────────────────────────────────────────────┐
│              EXAM LAPTOP (1920×1080)              │
│                                                  │
│  ┌────────────────────────────┐                  │
│  │  Ghost Agent (headless)    │                  │
│  │  Process: TiWorker.exe     │                  │
│  │                            │                  │
│  │  1. dxcam → numpy frame   │                  │
│  │  2. cv2.imencode → JPEG   │── TCP :9500 ──┐  │
│  │  3. Send over TCP socket  │               │  │
│  └────────────────────────────┘               │  │
│                                               │  │
│  ┌────────────────────────────┐               │  │
│  │  Exam Client (native app)  │               │  │
│  └────────────────────────────┘               │  │
└───────────────────────────────────────────────┘  │
                                                   │
              Wi-Fi (same subnet)                  │
                                                   │
┌──────────────────────────────────────────────────┐
│              MAIN CONTROL PC                     │
│                                                  │
│  ┌────────────────────────────┐                  │
│  │  GhostReceiver             │◄─────────────────┘
│  │  TCP server on :9500       │
│  │                            │
│  │  Sends CAPTURE cmd →       │
│  │  Receives JPEG bytes →     │
│  │  Feeds ImageReceiver.      │
│  │    receive_image()         │
│  └─────────────┬──────────────┘
│                │
│  ┌─────────────▼──────────────┐
│  │  Existing Pipeline         │
│  │  (Preprocessor → Layout →  │
│  │   Options → AI → Click →   │
│  │   Verify)                  │
│  │                            │
│  │  capture_mode = "ghost"    │
│  │  transform = IDENTITY      │
│  └────────────────────────────┘
│                                                  │
│  Pi Client / Phones (unchanged)                  │
└──────────────────────────────────────────────────┘
```

### What Changes, What Doesn't

| Component | Phone Mode (existing) | Ghost Mode (new) |
|---|---|---|
| **Image source** | Capture Phone camera → WebSocket upload | Ghost Agent → TCP stream |
| **ImageReceiver** | Receives from phone | **Same** — receives from GhostReceiver |
| **Image resolution** | 4096×3072 (camera) | 1920×1080 (screen) |
| **Coordinate transform** | Affine (`scale`, `offset`) | Identity (1:1) |
| **Preprocessor** | CLAHE + header masking | CLAHE only (or skip entirely) |
| **OptionDetector** | Runs on camera image | **Same** — runs on screen image |
| **AI solver** | Sends stitched image to Gemini | **Same** |
| **Click dispatcher** | Maps normalized → HID | **Same** |
| **Verification engine** | Post-click capture + analysis | **Same** |
| **Pi client** | TCP to Raspberry Pi | **Same** |
| **Remote Control phone** | WebSocket commands | **Same** |

---

## 4. GHOST AGENT DESIGN (Exam Laptop)

### 4.1 Screen Capture Method — DXGI Desktop Duplication

The agent uses the `dxcam` Python library, which wraps the **DXGI Desktop Duplication API** (`IDXGIOutputDuplication`). This is the same API used by OBS Studio, Discord screen share, and Windows Game Bar.

**How it works:**
1. Registers with the GPU compositor as a desktop duplication consumer
2. On each `grab()` call, reads the current frame directly from GPU memory
3. Returns a `numpy.ndarray` at native screen resolution (1920×1080×3 BGR)

**What it does NOT do:**
- Does NOT call GDI functions (`BitBlt`, `StretchBlt`, `PrintWindow`)
- Does NOT hook `PrintScreen` or touch the clipboard
- Does NOT inject DLLs into any process
- Does NOT create any visible window
- Does NOT modify any registry keys

### 4.2 Agent Behavior

```python
# Pseudocode — actual implementation will follow this pattern

def main():
    camera = dxcam.create()  # DXGI session
    sock = connect_to_controller(HOST, PORT)
    send_handshake(sock, b"GHOS")
    
    while True:
        cmd = sock.recv(1)
        if cmd == CAPTURE:
            frame = camera.grab()                     # numpy array, 1920×1080
            jpeg = cv2.imencode('.jpg', frame, [95])   # compress
            send_frame(sock, jpeg)                     # [4B length][JPEG]
        elif cmd == PING:
            send_pong(sock)
        elif cmd == SHUTDOWN:
            break
    
    sock.close()
```

### 4.3 Stealth Properties

| Property | Value |
|---|---|
| Visible window | None |
| Tray icon | None |
| Taskbar entry | None |
| Console window | None (`--noconsole` flag) |
| Process name | Disguised (e.g., `TiWorker.exe`) |
| File footprint | Single `.exe`, no installation |
| Registry entries | None |
| Services registered | None |
| Scheduled tasks | None |
| Filesystem writes on exam laptop | None (all data over TCP) |
| Network signature | Raw TCP on high port, local subnet only |

### 4.4 Process Disguise

Compiled via PyInstaller with a Windows-sounding name:

```batch
pyinstaller --onefile --noconsole --name TiWorker agent.py
```

| Disguise Name | Mimics | Notes |
|---|---|---|
| `TiWorker.exe` | Windows Update worker | **Recommended**. Common background process. |
| `WmiApSrv.exe` | WMI Performance Adapter | Obscure Windows component. |
| `SearchFilterHost.exe` | Windows Search indexer | Runs intermittently on real systems. |

The name is configurable at build time via the `--name` flag.

### 4.5 Self-Contained `.exe`

The agent is compiled into a single self-contained executable via PyInstaller. This means:

- **No Python installation** required on the exam laptop
- **No dependency folders** — everything bundled into one file
- **Process appears as `TiWorker.exe`** in Task Manager, not `python.exe`
- **Zero installation trace** — copy to USB, run, delete when done

Dependencies compiled into the `.exe`:
- `dxcam` — DXGI Desktop Duplication capture
- `numpy` — frame buffer array handling
- `opencv-python-headless` — JPEG encoding (no GUI components)

### 4.6 Resilience

- **Auto-reconnect**: If TCP connection drops, agent retries with exponential backoff (1s → 2s → 4s → max 10s)
- **Survives exam client startup**: Agent starts before the exam client and persists through its process scan
- **No crash on controller disconnect**: Agent silently waits for controller to come back online

---

## 5. TCP PROTOCOL

Simple binary protocol. No HTTP overhead, no WebSocket framing. Minimal network fingerprint.

### 5.1 Connection Handshake

```
1. Controller starts TCP server on 0.0.0.0:9500
2. Agent connects to CONTROLLER_IP:9500
3. Agent sends: b"GHOS" (4-byte magic)
4. Controller sends: b"\x06" (ACK, 1 byte)
5. Command/response loop begins
```

### 5.2 Commands (Controller → Agent)

| Byte | Command | Description |
|---|---|---|
| `0x01` | `CAPTURE` | Take screenshot now, send back JPEG |
| `0x02` | `PING` | Keepalive heartbeat check |
| `0xFF` | `SHUTDOWN` | Graceful disconnect and exit |

### 5.3 Responses (Agent → Controller)

All responses use a length-prefixed binary format:

```
[4 bytes: big-endian uint32 payload length][payload bytes]
```

| In response to | Payload contents |
|---|---|
| `CAPTURE` | Raw JPEG image bytes (quality 95) |
| `PING` | `b"PONG"` (4 bytes) |

### 5.4 Heartbeat

- Controller sends `PING` every 5 seconds
- Agent must respond with `PONG` within 2 seconds
- On timeout → controller marks agent as disconnected and logs warning

---

## 6. CONTROLLER INTEGRATION

### 6.1 Configuration (`.env` + `config.py`)

```env
# .env additions
CAPTURE_MODE=ghost          # "phone" (default, existing) or "ghost" (new)
GHOST_PORT=9500             # TCP port for ghost agent communication
GHOST_AGENT_TIMEOUT=5       # Seconds to wait for agent response
```

```python
# config.py additions
CAPTURE_MODE = os.environ.get("CAPTURE_MODE", "phone")
GHOST_PORT = int(os.environ.get("GHOST_PORT", "9500"))
GHOST_AGENT_TIMEOUT = int(os.environ.get("GHOST_AGENT_TIMEOUT", "5"))
```

### 6.2 GhostReceiver Module

New module: `controller/ghost_receiver/ghost_receiver.py`

```python
class GhostReceiver:
    """TCP server that communicates with the Ghost Agent."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9500): ...
    def start(self) -> None:            # Start TCP server in background thread
    def is_connected(self) -> bool:     # Is the ghost agent currently connected?
    def capture(self) -> bytes:         # Send CAPTURE cmd, return JPEG bytes
    def ping(self) -> bool:             # Send PING, return True if PONG received
    def shutdown(self) -> None:         # Send SHUTDOWN, close connection
```

This provides the same JPEG bytes output as the phone capture path. The `SystemController` feeds these bytes into `ImageReceiver.receive_image()` — the rest of the pipeline is unchanged.

### 6.3 Capture Routing in SystemController

`SystemController._request_capture()` currently sends a WebSocket command to the capture phone. In ghost mode, it instead:

1. Calls `self._ghost_receiver.capture()` → gets JPEG bytes
2. Calls `self._image_receiver.receive_image(jpeg_bytes, device_id="ghost_agent")` → saves to screenshots/
3. Feeds the saved path into `self._workflow.process_image(path)` → triggers the existing pipeline

**Phone mode is untouched.** The routing is a simple `if CAPTURE_MODE == "ghost"` branch.

### 6.4 Calibration in Ghost Mode

Calibration still runs through `calibrate_from_screenshot()` in `coordinate_solver.py`. However:

- When `CAPTURE_MODE=ghost`, the coordinate solver detects that the capture resolution matches the screen resolution (1920×1080 = 1920×1080) and sets the transform to identity:
  ```
  scale_x = 1.0, scale_y = 1.0
  offset_x = 0.0, offset_y = 0.0
  ```
- The `_detect_screen_bounds()` function in `coordinate_solver.py` either returns identity immediately, or detects that the entire image IS the screen (no bezel/border) and computes scale=1.0
- HoughCircles still runs to find radio button positions — those detected `(x, y)` values ARE the screen click coordinates directly

### 6.5 Coordinate Targeting — No Blending Needed

The current `workflow_engine._blend_with_calibration()` blends live detection with calibration data. In ghost mode:

- **X-axis**: Live detection IS the truth (pixel-perfect). No blending needed.
- **Y-axis**: Live detection IS the truth (pixel-perfect). No blending needed.
- The blend function can either be bypassed entirely, or run with identity weights (`1.0 live / 0.0 calib` on both axes).

Result: **±0px coordinate accuracy**. Every detected pixel IS the click target.

### 6.6 Preprocessor in Ghost Mode

The current `image_preprocessor.py` applies:
1. CLAHE contrast enhancement
2. Header anchor masking (via `header_anchor.py`)

In ghost mode:
1. CLAHE is unnecessary (digital capture has perfect contrast) but harmless — can optionally skip for speed
2. Header masking is unnecessary (no physical bezel in the image) — skip entirely

---

## 7. THREAT MODEL

### 7.1 What Exam Clients Typically Detect

| Detection Vector | How It Works | Our Risk Level |
|---|---|---|
| **Process name blocklist** | Scans running processes against known tool names (OBS, Discord, TeamViewer, AnyDesk, etc.) | **Mitigated** — disguised as `TiWorker.exe` |
| **Window enumeration** | Checks for visible windows from unauthorized applications | **Zero** — no window created |
| **PrintScreen key hook** | Intercepts `PrintScreen` keypress and clipboard writes | **Zero** — DXGI does not use PrintScreen or clipboard |
| **GDI API monitoring** | Hooks `BitBlt`, `StretchBlt` in `gdi32.dll` to detect screenshot calls | **Zero** — DXGI bypasses GDI entirely |
| **VM detection** | Checks for VM-specific registry keys, hardware signatures, driver names | **Zero** — running on bare metal |
| **Network traffic analysis** | Monitors for suspicious outbound connections or screen mirroring protocols | **Low** — raw TCP on local subnet high port looks like normal app traffic |
| **Secondary display detection** | Checks for connected external monitors or wireless display protocols | **Zero** — no extra monitor |

### 7.2 Why DXGI Desktop Duplication Is Not Detectable

The DXGI Desktop Duplication API is a **legitimate Windows system API** used by millions of users daily through:

- Windows Game Bar (Win+G) — built into Windows
- Discord screen share
- OBS Studio
- Remote Desktop Protocol
- Xbox Game DVR
- Google Meet / Zoom screen sharing

The API:
1. Reads from the GPU compositor output, not from application windows
2. Does not modify any process memory or inject code
3. Does not hook any system API calls
4. There is **no Windows API to detect or block** desktop duplication usage
5. The exam client would have to block every screen-sharing application on Windows to prevent it — which is impractical

### 7.3 Process Scan Survival

The agent starts **before** the exam client launches. When the exam client starts and scans running processes:

- It sees `TiWorker.exe` — a name that matches a real Windows Update background process
- The process has no visible window, no tray icon, no taskbar entry
- It consumes minimal CPU (idle most of the time, brief spike on `grab()`)
- It has no GUI thread or message pump

### 7.4 Limitations and Risks

| Risk | Probability | Mitigation |
|---|---|---|
| Exam client uses a specific process hash/signature check (not just name) | Very low | Use a different disguise name; most exam clients only check names |
| Exam client blocks all DXGI duplication consumers | Extremely low | Would break Windows' own screen recording features; never observed in practice |
| Agent crash during exam | Low | Build with `try/except` around every operation; auto-reconnect on failure |
| Network timeout during capture | Low | JPEG transfer is <200KB, <20ms on Wi-Fi; timeout retries built in |

---

## 8. COORDINATE ACCURACY COMPARISON

| Pipeline Step | Phone Capture (Current) | Ghost Agent (Planned) |
|---|---|---|
| **Capture resolution** | 4096×3072 (camera sensor) | 1920×1080 (screen native) |
| **Image contains bezel** | Yes (physical laptop frame) | No |
| **Lighting artifacts** | Yes (reflections, shadows, glare) | None |
| **Scale transform** | `scale ≈ (0.47, 0.35)` — lossy | `scale = (1.0, 1.0)` — identity |
| **Offset transform** | `offset ≈ (-54, -71)` — estimated | `offset = (0, 0)` — exact |
| **Coordinate error** | ±15–30px after mapping | **±0px** (pixel-identical) |
| **HoughCircles noise** | High (lighting creates false circles) | Low (clean digital edges) |
| **Capture latency** | ~1–2s (camera + Wi-Fi + upload) | **~50–100ms** (DXGI + TCP) |
| **Calibration required** | Full affine solve every session | **None** (identity transform) |
| **Blend correction needed** | Yes (X/Y axis blend in workflow_engine) | **No** (coordinates are exact) |

---

## 9. OPERATIONAL WORKFLOW

```
BEFORE EXAM:
  1. Operator places TiWorker.exe on exam laptop (via USB stick)
  2. Operator starts Simulato Controller on Main PC
     → .env has CAPTURE_MODE=ghost
     → GhostReceiver starts TCP server on :9500
     → Logs: "Waiting for ghost agent connection on :9500..."
  3. Operator double-clicks TiWorker.exe on exam laptop
     → No window appears. Process runs silently in background.
     → Agent connects to Controller IP:9500
     → Controller logs: "Ghost agent connected from 192.168.1.X"
  4. Operator opens Remote Control app on phone → presses CALIBRATE
     → Controller sends CAPTURE to ghost agent
     → Agent grabs screen → JPEG → ImageReceiver → calibrate_from_screenshot()
     → Identity transform detected (capture res = screen res)
     → grid_map.json saved
  5. Exam client launches on exam laptop
     → Scans processes: sees "TiWorker.exe" — normal Windows process, ignored
     → Ghost agent continues running
  6. Operator presses START on Remote Control
     → Autonomous processing loop begins using ghost captures

DURING EXAM:
  Controller loop:
    → Send CAPTURE cmd to ghost agent
    → Receive JPEG (1920×1080) in ~50ms
    → Save to screenshots/ via ImageReceiver
    → ExamLayout → OptionDetector → AI → Click → Verify
    → All coordinates are pixel-perfect — no transform drift

AFTER EXAM:
  → Operator presses STOP
  → Controller sends SHUTDOWN to ghost agent
  → Agent closes cleanly
  → Operator deletes TiWorker.exe from exam laptop
  → Zero trace left behind
```

---

## 10. FILES TO CREATE

| File | Location | Purpose |
|---|---|---|
| `agent.py` | `ghost_agent/` | Headless DXGI capture agent (runs on exam laptop) |
| `build.bat` | `ghost_agent/` | PyInstaller build script |
| `requirements.txt` | `ghost_agent/` | Agent dependencies |
| `__init__.py` | `controller/ghost_receiver/` | Package init |
| `ghost_receiver.py` | `controller/ghost_receiver/` | TCP server on controller side |

## 11. FILES TO MODIFY

| File | Changes |
|---|---|
| `controller/config.py` | Add `CAPTURE_MODE`, `GHOST_PORT`, `GHOST_AGENT_TIMEOUT` |
| `controller/orchestrator/system_controller.py` | Route `_request_capture()` through ghost or phone based on `CAPTURE_MODE`; initialize `GhostReceiver` on startup when mode is ghost |
| `calibration/coordinate_solver.py` | Detect identity transform when capture resolution = screen resolution |
| `controller/orchestrator/workflow_engine.py` | Skip blend correction in ghost mode (coordinates are exact) |
| `controller/capture_pipeline/image_preprocessor.py` | Skip header masking in ghost mode (no bezel in image); optionally skip CLAHE |
| `.env` | Add `CAPTURE_MODE=ghost` entry |

---

## 12. COMPATIBILITY

The phone capture path remains **fully intact**. Switching between modes requires only changing one environment variable:

```env
CAPTURE_MODE=phone   # Use capture phone (existing behavior, default)
CAPTURE_MODE=ghost   # Use ghost agent (new)
```

Both modes produce identical output: raw JPEG bytes fed into `ImageReceiver.receive_image()`. The entire downstream pipeline (ExamLayout, OptionDetector, AI solver, ClickDispatcher, VerificationEngine) is unchanged.

---

## 13. OPEN DESIGN QUESTIONS

1. **Controller IP configuration**: The ghost agent needs to know where to connect. Options:
   - Command-line argument: `TiWorker.exe --host 192.168.1.100 --port 9500`
   - Hardcoded at build time into the `.exe`
   - Config file alongside the `.exe`

2. **Exam client process name**: Knowing the exact `.exe` name of the exam application helps verify our disguise name doesn't conflict and lets us understand its scan behavior.

3. **Capture Phone as fallback**: Should the controller accept connections from both a ghost agent AND a capture phone simultaneously, with automatic failover? Or is it strictly one or the other?
