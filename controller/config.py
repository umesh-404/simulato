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

GROK_API_URL = os.environ.get("GROK_API_URL", "https://api.x.ai/v1/chat/completions")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-2-vision-latest")

# Gemini Cloud AI (Primary Solver — alternative to Grok)
GEMINI_API_URL = os.environ.get("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Active AI provider for primary question solving ("grok" or "gemini")
DEFAULT_AI_PROVIDER = os.environ.get("DEFAULT_AI_PROVIDER", "gemini")

# Local AI Assist (Mother PC - Qwen/Ollama)
# Used for auxiliary tasks like scroll verification and state checking.
LOCAL_AI_ASSIST_ENABLED = os.environ.get("LOCAL_AI_ASSIST_ENABLED", "True").lower() == "true"
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-vl")

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
COMMAND_ACK_TIMEOUT = 3
COMMAND_MAX_RETRIES = 3
IMAGE_UPLOAD_TIMEOUT = 10

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
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = LOGS_DIR / "system.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
