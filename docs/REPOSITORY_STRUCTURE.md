simulato/
│
├── requirements.txt
├── start.bat
├── .env
├── start_pi.sh
├── clean_imports.py
├── restore_imports.py
├── Local                          # GPU/compute model selection notes
├── Model
├── Ollama
│
├── docs/
│   ├── ARCHITECTURE_SPEC.md
│   ├── BUSINESS_REQUIREMENTS_DOCUMENT.md
│   ├── CANONICAL_LAWS.md
│   ├── COMMUNICATION_PROTOCOLS.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── HIDPI_INTEGRATION_GUIDE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── IMPLEMENTATION_SUMMARY.md
│   ├── MASTER PLAN.md
│   ├── REPOSITORY_STRUCTURE.md
│   ├── SETUP_GUIDE.md
│   ├── TECHNICAL_REQUIREMENTS_DOCUMENT.md
│   └── WIFI_SETUP_GUIDE.md
│
├── controller/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── system_controller.py
│   │   ├── state_machine.py
│   │   └── workflow_engine.py
│   │
│   ├── capture_pipeline/
│   │   ├── __init__.py
│   │   ├── image_receiver.py
│   │   ├── image_stitcher.py
│   │   ├── image_preprocessor.py
│   │   ├── scroll_detector.py          # v4: structural UI-aware scroll detection
│   │   ├── screen_validator.py
│   │   ├── change_detector.py
│   │   ├── ocr_layout_analyzer.py     # [NEW] OCR-based click targeting (Tesseract)
│   │   ├── exam_layout.py             # [NEW] Split-pane exam UI layout detector
│   │   └── option_detector.py         # [NEW] Radio-button option detector (HoughCircles Y-clustering)
│   │
│   ├── ai_pipeline/
│   │   ├── __init__.py
│   │   ├── grok_client.py
│   │   ├── gemini_client.py
│   │   ├── ollama_client.py           # [NEW] Dedicated Local AI (Qwen) task client
│   │   ├── aux_prompts.py            # [NEW] Task-specific prompts for Ollama auxiliary tasks
│   │   ├── response_parser.py
│   │   └── prompt_builder.py
│   │
│   ├── question_engine/
│   │   ├── __init__.py
│   │   ├── question_matcher.py
│   │   ├── canonicalizer.py
│   │   ├── hash_engine.py
│   │   └── embedding_matcher.py
│   │
│   ├── answer_engine/
│   │   ├── __init__.py
│   │   ├── option_matcher.py
│   │   ├── decision_engine.py
│   │   └── conflict_handler.py
│   │
│   ├── hardware_control/
│   │   ├── __init__.py
│   │   ├── pi_client.py
│   │   ├── click_dispatcher.py
│   │   └── verification_engine.py
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── alert_manager.py
│   │   └── sound_player.py
│   │
│   ├── mobile_api/
│   │   ├── __init__.py
│   │   └── api_server.py
│   │
│   ├── replay/
│   │   ├── __init__.py
│   │   ├── replay_engine.py
│   │   └── run_loader.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── text_normalizer.py
│       └── timer.py
│
├── database/
│   ├── __init__.py
│   ├── schema.sql
│   ├── db_manager.py
│   ├── questions.db                   # SQLite database (auto-created)
│   ├── migrations/
│   └── seed_data/
│
├── datasets/
│   ├── calibration/
│   │   ├── no-scroll/                 # 24 reference images (no scroll needed)
│   │   ├── answer-scroll/             # 4 reference images (answer panel scrolled)
│   │   ├── question-scroll/           # 1 reference image (question panel scrolled)
│   │   └── answer-and-question-scroll/ # 1 reference image (both panels scrolled)
│   ├── embeddings/
│   └── tests/
│       └── <test_name>/
│           └── questions/
│               └── question_NNNN.json
│
├── runs/
│   └── <run_id>/
│       ├── screenshots/
│       ├── ai_responses/
│       └── events.jsonl
│   └── pipeline_debug/                # CV pipeline diagnostic output (debug images + JSON report)
│
├── raspberry_pi/
│   ├── __init__.py
│   ├── hid_controller.py
│   ├── command_listener.py
│   └── device_config.py
│
├── HIDPi/                             # Third-party HIDPi library (submodule)
│   ├── HIDPi_Setup.py
│   ├── HIDPi_Analysis.md
│   ├── README.md
│   ├── library/                       # Python package (pip install .)
│   └── assets/
│
├── mobile_app/
│   └── android_project/
│       ├── build.gradle.kts
│       ├── settings.gradle.kts
│       ├── gradle.properties
│       ├── install-and-run.bat        # One-click APK install + launch
│       ├── gradle/wrapper/
│       │   └── gradle-wrapper.properties
│       │
│       └── app/
│           ├── build.gradle.kts
│           ├── proguard-rules.pro
│           ├── simulato.keystore      # Release signing keystore
│           └── src/main/
│               ├── AndroidManifest.xml
│               ├── java/com/simulato/app/
│               │   ├── HomeActivity.kt
│               │   ├── capture/
│               │   │   └── CaptureActivity.kt
│               │   ├── remote/
│               │   │   └── RemoteControlActivity.kt
│               │   ├── networking/
│               │   │   ├── ApiClient.kt
│               │   │   ├── WebSocketClient.kt
│               │   │   └── MessageParser.kt
│               │   ├── service/
│               │   │   ├── HeartbeatManager.kt
│               │   │   └── HeartbeatService.kt
│               │   └── shared/
│               │       ├── SimulatoApp.kt
│               │       ├── AppConfig.kt
│               │       ├── Constants.kt
│               │       └── Logger.kt
│               └── res/
│                   ├── layout/
│                   │   ├── activity_home.xml
│                   │   ├── activity_capture.xml
│                   │   └── activity_remote_control.xml
│                   └── values/
│                       ├── colors.xml
│                       ├── strings.xml
│                       └── themes.xml
│
├── communication/
│   ├── message_schemas/
│   │   ├── ai_response_schema.json
│   │   ├── question_schema.json
│   │   └── command_schema.json
│   └── protocols/
│
├── calibration/
│   ├── __init__.py
│   ├── grid_mapper.py
│   └── coordinate_solver.py
│
├── config/
│   ├── grid_map.json                  # Auto-generated: grid, pixel_positions, capture_resolution, transform
│   └── grid_map_template.json         # Minimal schema reference (full maps include transform block)
│
├── scripts/
│   ├── start_controller.sh
│   ├── start_controller.bat
│   ├── stop_controller.bat
│   ├── start_pi.sh
│   ├── replay_run.sh
│   ├── pi_smoke_test.py               # HID click smoke test from PC
│   ├── calibrate_cv_pipeline.py       # CV pipeline calibration over 30-image dataset
│   ├── calibrate_scroll.py            # Scroll detection calibration
│   ├── debug_scroll.py                # Scroll detection debugging tool
│   ├── scroll_diagnosis.py            # Scroll analysis diagnostics
│   ├── measure_radio.py               # Radio button measurement tool
│   ├── measure_scroll.py              # Scroll bar measurement tool
│   └── pipeline_diagnosis.py          # [NEW] Full CV pipeline diagnostic (layout+options+scroll vs 30-image dataset)
│
├── logs/
│   └── system.log
│
├── experiments/
│   ├── latency_tests/
│   ├── model_tests/
│   └── reliability_tests/
│
└── .agent/                            # AI assistant configuration
    └── workflows/
