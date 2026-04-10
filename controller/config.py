"""
Simulato system configuration.

All configuration constants are centralized here.
Runtime values (e.g. grid_map) are loaded from files at startup.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_DIR = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "questions.db"
DATASETS_DIR = PROJECT_ROOT / "datasets"
RUNS_DIR = PROJECT_ROOT / "runs"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
GRID_MAP_PATH = CONFIG_DIR / "grid_map.json"

# ---------------------------------------------------------------------------
# Network / API configuration
# All devices connect to the same WiFi network.
# PI_HOST and PI_PORT identify the Raspberry Pi on that network.
# CONTROLLER_HOST 0.0.0.0 means the PC listens on all interfaces.
# Phones discover the controller by IP entered in the app.
# ---------------------------------------------------------------------------
CONTROLLER_HOST = "0.0.0.0"
CONTROLLER_PORT = int(os.environ.get("CONTROLLER_PORT", "8000"))

PI_HOST = os.environ.get("PI_HOST", "192.168.1.101")
PI_PORT = int(os.environ.get("PI_PORT", "9000"))

# Gemini AI via Vertex AI (sole AI provider — Gemini 2.5 Flash, non-reasoning)
# Authentication: uses Application Default Credentials (ADC)
#   Run: gcloud auth application-default login
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
AI_API_MAX_RETRIES = int(os.environ.get("AI_API_MAX_RETRIES", "2"))
AI_API_BACKOFF_BASE_SECONDS = float(os.environ.get("AI_API_BACKOFF_BASE_SECONDS", "1.0"))

# Legacy — kept for backward compatibility (not used with Vertex AI)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_URL = os.environ.get("GEMINI_API_URL", "")


# OCR-first layout targeting (option/NEXT localization)
OCR_LAYOUT_PRIMARY_ENABLED = os.environ.get("OCR_LAYOUT_PRIMARY_ENABLED", "True").lower() == "true"
OCR_MIN_WORD_CONFIDENCE = float(os.environ.get("OCR_MIN_WORD_CONFIDENCE", "45"))
OCR_TIMEOUT_SECONDS = int(os.environ.get("OCR_TIMEOUT_SECONDS", "6"))
OCR_PSM = int(os.environ.get("OCR_PSM", "6"))
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "")

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
COMMAND_ACK_TIMEOUT = 3
COMMAND_MAX_RETRIES = 3
IMAGE_UPLOAD_TIMEOUT = 10
VERIFY_FRAME_TIMEOUT_SECONDS = int(os.environ.get("VERIFY_FRAME_TIMEOUT_SECONDS", "18"))

# ---------------------------------------------------------------------------
# Question matching thresholds
# ---------------------------------------------------------------------------
EMBEDDING_SIMILARITY_THRESHOLD = 0.92
SIMHASH_MAX_DISTANCE = 3

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------
MIN_IMAGE_WIDTH = 1600

# ---------------------------------------------------------------------------
# Ghost Agent — direct screen capture from exam laptop
# When CAPTURE_MODE="ghost", the controller uses a TCP-connected agent on
# the exam laptop instead of the capture phone.  See docs/GHOST_AGENT.md.
# ---------------------------------------------------------------------------
CAPTURE_MODE = os.environ.get("CAPTURE_MODE", "phone")  # "phone" or "ghost"
GHOST_PORT = int(os.environ.get("GHOST_PORT", "9500"))
GHOST_AGENT_TIMEOUT = int(os.environ.get("GHOST_AGENT_TIMEOUT", "5"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = LOGS_DIR / "system.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
