simulato/
│
├── requirements.txt
├── start.bat
├── .env
├── start_pi.sh
│
├── docs/
│   ├── ARCHITECTURE_SPEC.md
│   ├── BUSINESS_REQUIREMENTS_DOCUMENT.md
│   ├── CANONICAL_LAWS.md
│   ├── COMMUNICATION_PROTOCOLS.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── IMPLEMENTATION_SUMMARY.md
│   ├── MASTER PLAN.md
│   ├── REPOSITORY_STRUCTURE.md
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
│   │   ├── scroll_detector.py
│   │   ├── screen_validator.py
│   │   └── change_detector.py
│   │
│   ├── ai_pipeline/
│   │   ├── __init__.py
│   │   ├── grok_client.py
│   │   ├── gemini_client.py
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
│   ├── schema.sql
│   └── db_manager.py
│
├── datasets/
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
│
├── raspberry_pi/
│   ├── __init__.py
│   ├── hid_controller.py
│   ├── command_listener.py
│   └── device_config.py
│
├── mobile_app/
│   └── android_project/
│       ├── build.gradle.kts
│       ├── settings.gradle.kts
│       ├── gradle.properties
│       ├── gradle/wrapper/
│       │   └── gradle-wrapper.properties
│       │
│       └── app/
│           ├── build.gradle.kts
│           ├── proguard-rules.pro
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
│   └── message_schemas/
│       ├── ai_response_schema.json
│       ├── question_schema.json
│       └── command_schema.json
│
├── calibration/
│   ├── __init__.py
│   ├── grid_mapper.py
│   └── coordinate_solver.py
│
├── config/
│   └── grid_map_template.json
│
├── scripts/
│   ├── start_controller.sh
│   ├── start_pi.sh
│   └── replay_run.sh
│
├── logs/
│   └── system.log
│
├── experiments/
│
└── tests/
    ├── __init__.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_canonicalizer.py
    │   ├── test_hash_engine.py
    │   ├── test_option_matcher.py
    │   └── test_state_machine.py
    ├── integration/
    │   ├── __init__.py
    │   ├── test_question_matcher.py
    │   └── test_workflow_engine.py
    └── system_tests/
        └── __init__.py
