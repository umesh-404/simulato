# Technical Requirements Document (TRD)

## AI‑Assisted Exam Simulation System

Version: 1.0\
Status: Final Technical Specification

------------------------------------------------------------------------

# 1. Purpose

This document defines the **complete technical requirements** for
building the AI‑Assisted Exam Simulation System.

The system simulates a student using AI assistance to complete MCQ‑based
exams while interacting with a secure exam browser.

The platform captures exam questions via camera, reconstructs the full
question context, uses an AI model to determine answers, and injects
inputs through a hardware device.

------------------------------------------------------------------------

# 2. System Scope

The system includes the following components:

-   Exam laptop running the secure browser
-   Raspberry Pi HID device
-   Main Control PC
-   Capture Phone (camera device)
-   Remote Control Phone (operator interface)

The Main Control PC orchestrates the entire system.

------------------------------------------------------------------------

# 3. System Architecture

    Exam Laptop (Secure Browser)
            ↑
    Raspberry Pi (USB HID Injector)
            ↑
    Main Control PC (AI + Database + Controller)
            ↑
    Capture Phone (Camera Device)
            ↑
    Remote Control Phone (Operator Interface)

All communication routes through the **Main Control PC**.

------------------------------------------------------------------------

# 4. Hardware Requirements

## 4.1 Main Control PC

Minimum specifications:

  Component       Requirement
  --------------- ----------------------------------
  CPU             Intel Core Ultra 7 or equivalent
  RAM             32 GB
  GPU             NVIDIA RTX 5060 8GB VRAM
  Secondary GPU   Intel Arc 140T
  NPU             Intel NPU (shared memory)
  Storage         1 TB SSD
  Network         Gigabit Ethernet or WiFi 6

The PC runs all AI processing, database operations, and system
orchestration.

------------------------------------------------------------------------

## 4.2 Raspberry Pi

Recommended model:

-   Raspberry Pi 4 or Raspberry Pi Zero 2 W

Requirements:

  Component   Requirement
  ----------- ----------------------------------
  USB         Must support USB gadget/HID mode
  RAM         ≥ 2GB
  Network     WiFi or Ethernet
  OS          Raspberry Pi OS Lite

Purpose:

-   emulate keyboard
-   emulate mouse
-   receive commands from PC

------------------------------------------------------------------------

## 4.3 Capture Phone

The capture phone runs the **Simulato Android Application** in **Capture Mode**.

Requirements:

  Feature               Requirement
  --------------------- -------------
  Camera                ≥ 12 MP
  Video stabilization   Required
  Manual zoom           Required
  HDR processing        Supported
  Storage               ≥ 5 GB free
  Connectivity          WiFi
  Android OS            Android 10+

Camera must capture high resolution images of the exam screen.

------------------------------------------------------------------------

## 4.4 Remote Control Phone

The remote control phone runs the **Simulato Android Application** in **Remote Control Mode**.

Requirements:

  Feature         Requirement
  --------------- -------------
  Android OS      Android 10+
  Connectivity    WiFi
  UI capability   required

Used to control system operations.

------------------------------------------------------------------------

## 4.5a Mobile Application Requirements

Both phones (Capture and Remote Control) run a **single Android
application** with **two operational modes**:

1.  **Capture Mode** — camera-based screen capture and image upload
2.  **Remote Control Mode** — operator control interface and alert handling

The application must allow switching between modes **without reinstalling
or restarting**.

The mode is selected from the home screen at startup.

Required Android permissions:

    CAMERA
    INTERNET
    ACCESS_WIFI_STATE
    WRITE_EXTERNAL_STORAGE

The application must allow cleartext HTTP traffic for local network
communication (`android:usesCleartextTraffic="true"` in manifest).

------------------------------------------------------------------------

## 4.5 Exam Laptop

Requirements:

  Feature          Requirement
  ---------------- -------------
  Secure Browser   Installed
  USB Ports        Available
  Display          ≥ 1920×1080

The exam laptop must allow USB input devices.

------------------------------------------------------------------------

# 5. Software Requirements

## 5.1 Operating Systems

  Device            OS
  ----------------- -----------------
  Main Control PC   Linux / Windows
  Raspberry Pi      Raspberry Pi OS
  Phones            Android
  Exam Laptop       Windows

------------------------------------------------------------------------

## 5.2 Programming Languages

Primary language:

-   Python 3.10+

Additional technologies:

-   Kotlin / Java (Single Android Application — Capture Mode + Remote Control Mode)
-   Bash (device scripts)

------------------------------------------------------------------------

## 5.3 Required Libraries

Python libraries:

-   OpenCV
-   NumPy
-   Pillow
-   SQLite3
-   FastAPI or Flask
-   PyTorch
-   sentence-transformers
-   imagehash
-   python-dotenv

------------------------------------------------------------------------

# 6. AI Model Requirements

## 6.1 Vision Model

AI models used (Tiered Strategy):

-   **Primary Solver (selectable at runtime):**
    -   Cloud AI (Gemini 2.5 Flash) -> Default. OpenAI-compatible endpoint.
    -   Cloud AI (Grok Vision API) -> Enforced JSON Schema via `response_format`.
-   **Auxiliary Analyst:** Local AI (Ollama / qwen2.5vl:7b) -> Vision-language classification for screen state.

Capabilities:

-   read screenshots
-   extract question text
-   extract options
-   determine correct answer

Expected output format:

``` json
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
```

------------------------------------------------------------------------

## 6.2 Embedding Model

Local embedding model:

bge-small-en

Purpose:

-   semantic similarity matching

Similarity threshold:

0.92 cosine similarity.

------------------------------------------------------------------------

# 7. Database Requirements

Database type:

SQLite

Location:

    /database/questions.db

------------------------------------------------------------------------

## 7.1 Tests Table

  Field            Type
  ---------------- -----------
  test_id          integer
  test_name        text
  created_at       timestamp
  question_count   integer

------------------------------------------------------------------------

## 7.2 Questions Table

  Field              Type
  ------------------ -----------
  question_id        integer
  test_id            integer
  canonical_text     text
  sha256_hash        text
  simhash            text
  embedding_vector   blob
  option_a           text
  option_b           text
  option_c           text
  option_d           text
  correct_answer     text
  timestamp          timestamp

------------------------------------------------------------------------

# 8. File Storage Requirements

Questions must also be stored as JSON files.

Directory structure:

    database/
      <test_name>/
         question_01.json
         question_02.json

JSON format:

``` json
{
 "test_name":"KLU_2027_M1_Ages",
 "question_number":1,
 "question":"...",
 "options":{
   "A":"...",
   "B":"...",
   "C":"...",
   "D":"..."
 },
 "answer":"B",
 "answer_content":"..."
}
```

------------------------------------------------------------------------

# 9. Image Processing Requirements

Image capture pipeline:

1.  Capture image
2.  Detect scroll
3.  Capture additional frames
4.  Stitch images
5.  Send composite image to AI

Image format:

JPEG

Recommended resolution:

1600px width minimum.

------------------------------------------------------------------------

# 10. Grid Mapping Requirements

Screen grid mapping required.

Example configuration:

    resolution: 1920×1080
    grid: 20×20
    cell size: 96×54

Example coordinates:

    A (15,8)
    B (15,10)
    C (15,12)
    D (15,14)
    NEXT (18,19)

------------------------------------------------------------------------

# 11. Communication Requirements

All devices communicate with the Main Control PC.

Protocols:

-   HTTP API
-   WebSocket

------------------------------------------------------------------------

## 11.1 Capture Phone → PC

Endpoint:

    POST /upload_image

Payload:

-   image file
-   timestamp

------------------------------------------------------------------------

## 11.2 Remote Phone → PC

Endpoints:

    POST /start
    POST /pause
    POST /stop
    POST /calibrate

------------------------------------------------------------------------

## 11.3 PC → Raspberry Pi

Communication via socket or serial.

Commands:

    CLICK_A
    CLICK_B
    CLICK_C
    CLICK_D
    CLICK_NEXT
    SCROLL_LEFT
    SCROLL_RIGHT

------------------------------------------------------------------------

# 12. Question Identification Requirements

Question lookup pipeline:

1.  Normalize text
2.  Generate SHA256 hash
3.  Compare hash within active test
4.  Compare SimHash
5.  Run embedding similarity search
6.  If no match → call Grok API (using `response_format: json_schema`) or Local Ollama.

------------------------------------------------------------------------

# 13. Fail‑Safe Requirements

System must detect unexpected screens.

Checks include:

-   missing question panel
-   missing options panel
-   login screen
-   error screen

If detected:

-   play alarm sound
-   pause automation
-   notify remote phone

------------------------------------------------------------------------

# 14. Logging Requirements

All events must be logged.

Log fields:

-   timestamp
-   test name
-   question id
-   api usage
-   cache hit
-   answer selected
-   execution time

Logs stored in:

    /logs/system.log

------------------------------------------------------------------------

# 15. Performance Requirements

Expected performance:

  Operation          Time
  ------------------ ---------
  Image capture      0.5 s
  Scroll detection   0.2 s
  Database lookup    \<1 ms
  AI inference       2‑3 s
  Input injection    \<0.1 s

Average question processing time:

\~3 seconds.

Cached questions:

\~0.2 seconds.

------------------------------------------------------------------------

# 16. System States

System must support the following states:

    IDLE
    CALIBRATION
    RUNNING
    PAUSED
    ERROR
    STOPPED

State transitions controlled by remote commands.

------------------------------------------------------------------------

# 17. Implementation Order

Development order:

1.  PC controller backend
2.  AI integration
3.  Database + hashing system
4.  Raspberry Pi HID injector
5.  Single Android application (Capture Mode + Remote Control Mode)
6.  Fail‑safe system
7.  Full integration testing

------------------------------------------------------------------------

# 18. Acceptance Criteria

The system is considered complete when:

-   All devices communicate correctly
-   Questions are captured reliably
-   AI responses are parsed correctly
-   Inputs are injected successfully
-   Database stores questions
-   Cached questions bypass API
-   Fail‑safe triggers on abnormal screens
-   Remote interface controls system

------------------------------------------------------------------------

# End of Technical Requirements Document
