# Implementation Plan

## AI‑Assisted Exam Simulation System

Version: 1.1\
Document Type: Implementation Plan\
Status: Final (Updated)

> **Note:** The phase descriptions (Sections 5–22) use the original design
> naming conventions (e.g. `state_manager.py`, `alarm_system.py`). The
> authoritative file names and project structure are defined in
> **REPOSITORY_STRUCTURE.md** and tracked in **IMPLEMENTATION_SUMMARY.md**.

------------------------------------------------------------------------

# 1. Purpose

This document defines the **step‑by‑step implementation plan** required
to build the AI‑Assisted Exam Simulation System described in the
previous documents (BRD, TRD, Architecture Specification).

The goal of this plan is to ensure:

-   zero ambiguity during development
-   deterministic build order
-   minimal integration errors
-   predictable system behavior

This plan is structured so that **each subsystem is built independently
and then integrated**.

------------------------------------------------------------------------

# 2. Implementation Strategy

The system will be built using a **layered integration strategy**.

Subsystems will be implemented in the following order:

1.  Core PC Controller Framework
2.  Database & Question Matching Engine
3.  AI Integration Layer
4.  Raspberry Pi HID Injection System
5.  Image Processing Pipeline
6.  Single Android Application (Capture Mode + Remote Control Mode)
7.  Fail‑Safe Monitoring System
8.  Full System Integration
9.  Validation & Testing

Each stage must be fully validated before proceeding.

------------------------------------------------------------------------

# 3. Development Environment Setup

## 3.1 Main Control PC Setup

Install required tools:

Python 3.10+

Recommended environment manager:

    venv

Create project environment:

    python -m venv .venv
    .venv\Scripts\activate.bat   # Windows
    # or
    source .venv/bin/activate    # Linux

Install dependencies:

    pip install opencv-python
    pip install numpy
    pip install pillow
    pip install fastapi
    pip install uvicorn
    pip install sentence-transformers
    pip install imagehash
    pip install pydantic
    pip install requests
    pip install python-dotenv

------------------------------------------------------------------------

# 4. Project Folder Structure

The following structure is the authoritative project layout (see REPOSITORY_STRUCTURE.md for the full tree).

    simulato/

    controller/
        main.py
        config.py
        orchestrator/          (state_machine, system_controller, workflow_engine)
        capture_pipeline/      (image_receiver, stitcher, scroll_detector, screen_validator, change_detector, preprocessor)
        ai_pipeline/           (grok_client, response_parser, prompt_builder)
        question_engine/       (question_matcher, canonicalizer, hash_engine, embedding_matcher)
        answer_engine/         (option_matcher, decision_engine, conflict_handler)
        hardware_control/      (pi_client, click_dispatcher, verification_engine)
        alerts/                (alert_manager, sound_player)
        mobile_api/            (api_server)
        replay/                (replay_engine, run_loader)
        utils/                 (logger, text_normalizer, timer)

    database/
        schema.sql
        db_manager.py

    raspberry_pi/
        hid_controller.py
        command_listener.py
        device_config.py

    mobile_app/android_project/   (full Kotlin/Gradle Android project)

    calibration/
        grid_mapper.py
        coordinate_solver.py

    communication/message_schemas/ (JSON schemas)
    config/                        (grid_map_template.json)
    scripts/                       (start_controller.sh, start_pi.sh, setup_pi_hid.sh, replay_run.sh)
    tests/                         (unit/, integration/, system_tests/)
    logs/
    datasets/
    runs/
    docs/

------------------------------------------------------------------------

# 5. Phase 1 --- PC Controller Framework

Objective: Create the **central orchestration engine**.

## Tasks

Implement:

    state_manager.py

State machine must support:

    IDLE
    CALIBRATION
    RUNNING
    PAUSED
    ERROR
    STOPPED

The controller must expose functions:

    start_test()
    pause_test()
    stop_test()
    calibrate_system()

The controller loop will continuously:

1.  wait for capture image
2.  process image
3.  determine answer
4.  inject click
5.  log result

------------------------------------------------------------------------

# 6. Phase 2 --- Database Implementation

Create SQLite database.

Schema must match TRD.

Create schema.sql:

    CREATE TABLE tests (
     test_id INTEGER PRIMARY KEY,
     test_name TEXT,
     created_at TIMESTAMP,
     question_count INTEGER
    );

    CREATE TABLE questions (
     question_id INTEGER PRIMARY KEY,
     test_id INTEGER,
     canonical_text TEXT,
     sha256_hash TEXT,
     simhash TEXT,
     embedding_vector BLOB,
     option_a TEXT,
     option_b TEXT,
     option_c TEXT,
     option_d TEXT,
     correct_answer TEXT,
     timestamp TIMESTAMP
    );

Implement db_manager.py functions:

    create_test()
    get_test()
    store_question()
    lookup_by_hash()
    lookup_by_simhash()
    lookup_by_embedding()

------------------------------------------------------------------------

# 7. Phase 3 --- Question Canonicalization

Implement canonicalizer.py.

Processing pipeline:

1.  convert to lowercase
2.  remove punctuation
3.  collapse whitespace
4.  normalize numeric formatting

Example:

Input:

    "What is the age of John if his father is twice as old?"

Output:

    age john father twice old

Construct canonical string:

    question|A|B|C|D

------------------------------------------------------------------------

# 8. Phase 4 --- Hash Generation

Generate SHA256:

    hashlib.sha256(canonical_text.encode())

Generate SimHash for fuzzy comparison.

Store both in database.

------------------------------------------------------------------------

# 9. Phase 5 --- Embedding Engine

Install model:

    bge-small-en

Load using sentence-transformers.

Compute embeddings:

    model.encode(question)

Store embedding vectors.

Similarity threshold:

    cosine similarity > 0.92

------------------------------------------------------------------------

# 10. Phase 6 --- Grok Vision Integration

Create grok_client.py.

Responsibilities:

1.  send stitched image
2.  receive JSON
3.  validate JSON structure

Expected format:

    {
     "question": "...",
     "options": {
       "A": "...",
       "B": "...",
       "C": "...",
       "D": "..."
     },
     "answer": "A",
     "answer_content": "..."
    }

Implement retry if JSON malformed.

------------------------------------------------------------------------

# 11. Phase 7 --- Image Capture Receiver

Create FastAPI server.

Endpoint:

    POST /upload_image

Payload:

    image file
    timestamp

Save image temporarily for processing.

------------------------------------------------------------------------

# 12. Phase 8 --- Scroll Detection

Implement scroll_detector.py.

Algorithm:

1.  detect bottom boundary of question text
2.  detect presence of scroll bar
3.  detect clipped text

If scrolling required:

send command:

    SCROLL_LEFT
    SCROLL_RIGHT

------------------------------------------------------------------------

# 13. Phase 9 --- Image Stitching

Using OpenCV.

Steps:

1.  load captured frames
2.  align vertically
3.  concatenate images

Output:

    stitched_question.png

------------------------------------------------------------------------

# 14. Phase 10 --- Raspberry Pi Interface

Install Raspberry Pi OS Lite.

Enable USB HID gadget mode.

Implement pi_client.py.

Communication protocol:

TCP socket connection.

Commands supported:

    CLICK_A
    CLICK_B
    CLICK_C
    CLICK_D
    CLICK_NEXT
    SCROLL_LEFT
    SCROLL_RIGHT

Each command mapped to mouse action.

------------------------------------------------------------------------

# 15. Phase 11 --- Single Android Application

Build a **single Android application** providing two operational modes.

The mode is selected from the **home screen** at startup:

    Select Device Role

    [ Capture Device ]
    [ Remote Controller ]

The application must allow switching between modes **without reinstalling
or restarting**.

------------------------------------------------------------------------

## 15.1 Capture Mode

Capture Mode features:

-   camera preview
-   zoom control
-   upload captured images
-   auto capture on request

Use Android Camera2 API.

------------------------------------------------------------------------

## 15.2 Remote Control Mode

Interface buttons:

    CALIBRATE
    START
    PAUSE
    STOP
    STATUS

Commands sent to PC via REST API.

------------------------------------------------------------------------

## 15.3 APK Build Requirements

The application must be packaged as a **release APK**.

Final artifact:

    simulato-mobile-v1.apk

Install via:

    adb install simulato-mobile-v1.apk

Android build configuration:

-   minSdkVersion: Android 8.0 (API 26)
-   targetSdkVersion: Android 14 (API 34)

Required permissions:

    CAMERA
    INTERNET
    ACCESS_WIFI_STATE
    WRITE_EXTERNAL_STORAGE

Signing:

-   Generate keystore: `keytool -genkey -v -keystore simulato.keystore`
-   Configure Gradle signing for release builds

Network:

-   Android Manifest must include: `android:usesCleartextTraffic="true"`
    to allow local HTTP communication

------------------------------------------------------------------------

# 17. Phase 13 --- Screen Validation

Implement screen_validator.py.

Checks:

-   question panel visible
-   option panel visible
-   correct layout detected

If invalid:

trigger alarm.

------------------------------------------------------------------------

# 18. Phase 14 --- Alarm System

alarm_system.py must:

1.  play sound
2.  pause automation
3.  notify remote device

------------------------------------------------------------------------

# 19. Phase 15 --- Logging System

Logs must include:

    timestamp
    test_name
    question_id
    scroll_detected
    api_used
    answer
    execution_time

Logs written to:

    logs/system.log

------------------------------------------------------------------------

# 20. Phase 16 --- Full Integration

Integration sequence:

1.  start controller
2.  start API server
3.  connect Raspberry Pi
4.  connect capture phone
5.  connect remote phone

Test calibration.

Test question processing.

------------------------------------------------------------------------

# 21. Validation Testing

Testing scenarios:

1.  question without scrolling
2.  question requiring scrolling
3.  repeated question lookup
4.  unexpected screen detection
5.  API response validation

------------------------------------------------------------------------

# 22. Deployment Procedure

Steps:

1.  install software on PC
2.  configure Raspberry Pi (run `scripts/setup_pi_hid.sh`)
3.  install Simulato Android APK on both phones
4.  connect all five devices to the same WiFi network
5.  create `.env` configuration file on PC with `PI_HOST` and `GROK_API_KEY`
6.  start Pi listener (`scripts/start_pi.sh`)
7.  start controller (`start.bat` on Windows or `scripts/start_controller.sh` on Linux)
8.  enter PC IP in both phone apps, assign device roles (one Capture, one Remote Control)
9.  run calibration
10. start test

------------------------------------------------------------------------

# 23. Risk Mitigation

Potential issues:

Camera misalignment\
AI misinterpretation\
Network latency\
UI layout changes

Mitigation:

Calibration checks\
Fail‑safe detection\
Logging and diagnostics

------------------------------------------------------------------------

# 24. Completion Criteria

The system is considered fully implemented when:

-   all subsystems communicate correctly
-   AI answers are processed
-   inputs are injected reliably
-   database caching works
-   fail‑safe triggers correctly
-   full test cycle completes automatically

------------------------------------------------------------------------

# End of Implementation Plan
