# AI-Assisted Exam Simulation System --- Master Architecture (Final)

## 1. Objective

Design a distributed system to simulate how a student could use AI
assistance to complete MCQ tests.\
The system must:

-   Capture questions from the exam screen using a camera
-   Reconstruct full questions (including scrolling areas)
-   Extract question and options via a multimodal AI model
-   Automatically determine answers
-   Store questions locally for reuse
-   Reuse answers from a local database when questions repeat
-   Restrict search scope to the **active test context**
-   Automate mouse/keyboard input using a hardware injector
-   Provide remote control and monitoring
-   Include fail‑safe detection for abnormal screens
-   Produce a dataset of questions and results

------------------------------------------------------------------------

# 2. System Topology

Five devices participate in the architecture.

    Exam Laptop (Secure Browser)
            ↑
    Raspberry Pi (USB HID Injector)
            ↑
    Main Control PC (Orchestrator + AI + Database)
            ↑
    Capture Phone (Camera Device)
            ↑
    Remote Control Phone (Operator Interface)

The **Main Control PC acts as the central orchestrator**.\
All other devices communicate only with it.

------------------------------------------------------------------------

# 3. Device Responsibilities

## 3.1 Exam Laptop

Runs the secure exam browser.

Receives: - Mouse events - Keyboard events

The exam system remains isolated and unaware of the automation
framework.

------------------------------------------------------------------------

## 3.2 Raspberry Pi (Input Injector)

Connected to the exam laptop via USB.

Configured as a **USB Human Interface Device (HID)**.

Functions: - Receives commands from PC - Converts commands into
mouse/keyboard actions

Supported commands:

    CLICK_A
    CLICK_B
    CLICK_C
    CLICK_D
    CLICK_NEXT
    SCROLL_LEFT
    SCROLL_RIGHT

The Pi performs **no AI or vision tasks**.

------------------------------------------------------------------------

## 3.3 Main Control PC (System Brain)

The PC orchestrates the entire system.

Responsibilities:

-   Receive screenshots from capture phone
-   Use Local AI (Ollama/Qwen) to detect if scrolling is required
-   Capture additional frames if necessary
-   Stitch frames into a composite question image
-   Send images to primary AI Vision API (Cloud Grok) for solving
-   Receive structured JSON response (enforced via JSON Schema for Grok)
-   Normalize question text
-   Compute question hashes
-   Run similarity matching
-   Query local SQLite database
-   Manage test context
-   Dispatch input commands to Raspberry Pi
-   Verify answer clicks
-   Detect abnormal screens
-   Maintain system state
-   Log all operations

------------------------------------------------------------------------

## 3.4 Capture Phone

Runs the Android application in **Capture Mode**.

Functions:

-   Displays camera preview
-   Allows zoom adjustment
-   Captures screenshots of exam screen
-   Saves captured images to phone gallery
-   Uploads captured image to PC

Images use the phone's **native camera processing pipeline** (HDR,
sharpening, noise reduction).

------------------------------------------------------------------------

## 3.5 Remote Control Phone

Runs the Android app in **Remote Mode**.

Provides operator controls:

    CALIBRATE
    START
    PAUSE
    STOP
    STATUS

STOP prompts user:

-   Pause system
-   Cancel run

The phone sends commands to the PC controller.

------------------------------------------------------------------------

# 4. Android Application Design

Both phones run the same application.

## Home Screen

    Capture Mode
    Remote Control Mode

------------------------------------------------------------------------

## Capture Mode Interface

Displays:

-   Camera preview
-   Zoom control
-   Connection status
-   Capture indicator

Image capture events are triggered by the PC.

------------------------------------------------------------------------

## Remote Mode Interface

Displays:

Controls:

    CALIBRATE
    START
    PAUSE
    STOP
    STATUS

System information:

-   Active test
-   Question number
-   System state
-   API calls used
-   Cache hits
-   Error alerts

------------------------------------------------------------------------

# 5. Calibration Phase

Calibration is required before starting a session.

Steps:

1.  Operator presses **CALIBRATE**
2.  Capture phone captures screenshot
3.  Screenshot sent to PC
4.  PC detects UI layout
5.  PC generates screen coordinate grid
6.  Coordinates saved

Configuration file:

    grid_map.json

Example coordinates:

    option_A
    option_B
    option_C
    option_D
    next_button
    scroll_left
    scroll_right

------------------------------------------------------------------------

# 6. Screen Grid Mapping

The screen is mapped to a logical grid.

Example:

Resolution: 1920 × 1080\
Grid: 20 × 20

Each grid cell:

96 × 54 pixels

Example grid coordinates:

    A -> (15,8)
    B -> (15,10)
    C -> (15,12)
    D -> (15,14)
    NEXT -> (18,19)

PC converts grid coordinates to pixel coordinates before sending
commands to Pi.

------------------------------------------------------------------------

# 7. Test Context Manager

When the operator presses **START**, the system asks for a test name.

Example:

    Enter Test Name:
    KLU_2027_M1_Ages

The PC queries the database.

## If test exists

-   Load test context
-   Load stored questions
-   Activate cache mode

## If test does not exist

-   Create new test entry
-   Initialize empty question set

------------------------------------------------------------------------

# 8. Database Design

SQLite database is used.

## Tests Table

  Field            Description
  ---------------- ----------------------------
  test_id          unique identifier
  test_name        name of the test
  created_at       timestamp
  question_count   number of stored questions

------------------------------------------------------------------------

## Questions Table

  Field              Description
  ------------------ ---------------------
  question_id        unique identifier
  test_id            reference to test
  canonical_text     normalized question
  sha256_hash        exact hash
  simhash            fuzzy hash
  embedding_vector   semantic vector
  option_a           option text
  option_b           option text
  option_c           option text
  option_d           option text
  correct_answer     correct option
  timestamp          stored time

------------------------------------------------------------------------

# 9. JSON Storage

Questions are also stored as JSON files.

Directory structure:

    database/
       KLU_2027_M1_Ages/
           question_01.json
           question_02.json

Example JSON:

``` json
{
  "test_name": "KLU_2027_M1_Ages",
  "question_number": 3,
  "question": "...",
  "options": {
    "A": "...",
    "B": "...",
    "C": "...",
    "D": "..."
  },
  "answer": "B",
  "answer_content": "..."
}
```

------------------------------------------------------------------------

# 10. Question Capture Pipeline

For each question:

1.  Capture screenshot
2.  Detect scrolling requirement
3.  Scroll using Raspberry Pi
4.  Capture additional frames
5.  Stitch frames into one composite image

------------------------------------------------------------------------

# 11. Image Stitching

Example input frames:

    question_part1
    question_part2
    options_part1

Result:

    stitched_question.png

This ensures the entire question is visible to the model.

------------------------------------------------------------------------

# 12. AI Vision Processing

The stitched image is sent to the configured AI API (Grok or Ollama).

Expected JSON response:

``` json
{
 "question": "...",
 "options": {
   "A": "...",
   "B": "...",
   "C": "...",
   "D": "..."
 },
 "answer": "C",
 "answer_content": "..."
}
```

For Cloud Grok API, the system uses **Structured Outputs** (JSON Schema) to guarantee valid results. For Local Ollama, JSON mode is enforced.

PC extracts structured data and performs validation before proceeding.

------------------------------------------------------------------------

# 13. Canonical Text Generation

Normalization steps:

-   Convert to lowercase
-   Remove punctuation
-   Remove extra spaces
-   Normalize numbers

Example canonical string:

    age john father twice old|10|12|15|20

------------------------------------------------------------------------

# 14. Question Identification

Lookup order:

1.  SHA256 exact hash
2.  SimHash similarity
3.  Embedding similarity
4.  AI Vision API fallback

------------------------------------------------------------------------

# 15. Semantic Similarity

Embeddings generated using **bge-small-en** model.

Threshold:

    cosine_similarity > 0.92

If matched, stored answer is used.

------------------------------------------------------------------------

# 16. Answer Execution

Once answer is determined:

1.  Map option → grid coordinate
2.  Convert grid → pixel
3.  Send command to Pi

Example:

    CLICK_C
    CLICK_NEXT

------------------------------------------------------------------------

# 17. Question Change Detection

Process:

1.  Capture screenshot
2.  Crop question region
3.  Compute perceptual hash
4.  Compare with previous question

If different → new question detected.

------------------------------------------------------------------------

# 18. Answer Verification

After clicking answer:

1.  Capture screenshot
2.  Detect highlighted option

If highlight not detected:

Retry click.

------------------------------------------------------------------------

# 19. Fail‑Safe System

Before answering each question:

System verifies:

-   Expected exam layout
-   Question panel visible
-   Options panel visible
-   No warning screens

If abnormal screen detected:

-   Enter ERROR state
-   Play alarm sound
-   Pause system
-   Notify remote phone

------------------------------------------------------------------------

# 20. System State Machine

States:

    IDLE
    CALIBRATION
    RUNNING
    PAUSED
    ERROR
    STOPPED

Transitions controlled via remote commands.

------------------------------------------------------------------------

# 21. Logging System

Each event recorded.

Example log entry:

    timestamp
    test_name
    question_id
    scroll_detected
    api_used
    answer_selected
    execution_time

Logs stored for analysis.

------------------------------------------------------------------------

# 22. Performance Expectations

Typical cycle:

Capture image → 0.5s\
Scroll detection → 0.2s\
Database lookup → \<1ms\
API inference → 2--3s\
Click action → \<0.1s

Average:

\~3 seconds per question

Cached questions:

\~0.2 seconds.

------------------------------------------------------------------------

# 23. Implementation Order

Recommended build sequence:

1.  PC controller
2.  AI Vision API integration (Ollama / Grok)
3.  Database + hashing + embeddings
4.  Raspberry Pi HID interface
5.  Capture phone app
6.  Remote control interface
7.  Fail‑safe detection
8.  End‑to‑end testing

------------------------------------------------------------------------

# Final System Summary

The completed platform consists of:

-   Camera-based question capture
-   Multimodal AI reasoning
-   Local question database
-   Semantic similarity engine
-   Hardware input injection
-   Remote control interface
-   Fail-safe monitoring
-   Dataset generation

Over time, the database accumulates questions and most answers are
retrieved locally rather than via API.
