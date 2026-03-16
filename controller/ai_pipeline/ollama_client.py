"""
Ollama Local Vision API client for Auxiliary Tasks.

Sends screenshots to a local Ollama instance (e.g. qwen2.5vl:7b-q4_K_M) 
to perform screen understanding tasks like scroll verification 
and answer state checking.
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

import requests

from controller.config import (
    OLLAMA_API_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_COOLDOWN_SECONDS,
    OLLAMA_KEEP_ALIVE,
)
from controller.ai_pipeline.aux_prompts import (
    SCROLL_CHECK_PROMPT,
    ANSWER_VERIFICATION_PROMPT,
    SCREEN_STATE_PROMPT,
    NEXT_BUTTON_PROMPT,
)
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("ollama_client")
_OLLAMA_UNAVAILABLE_UNTIL = 0.0


class OllamaAPIError(Exception):
    """Raised when the Ollama API returns a non-recoverable error."""
    pass


def _encode_image(image_path: Path) -> str:
    """Read an image file and return its base64 encoding."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_ollama_task(image_path: Path, prompt: str) -> dict:
    """
    Internal helper to call Ollama with a specific prompt and image.
    Enforces JSON output.
    """
    image_b64 = _encode_image(image_path)
    
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64]
            }
        ],
        "options": {
            "temperature": 0.0,
            "seed": 42
        },
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }

    global _OLLAMA_UNAVAILABLE_UNTIL
    now = time.monotonic()
    if now < _OLLAMA_UNAVAILABLE_UNTIL:
        remaining = int(_OLLAMA_UNAVAILABLE_UNTIL - now)
        raise OllamaAPIError(f"Ollama temporarily disabled for {remaining}s")

    with ExecutionTimer("ollama_aux_task"):
        try:
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=OLLAMA_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            return json.loads(data["message"]["content"])
        except Exception as e:
            logger.error("Ollama task failed: %s", e)
            _OLLAMA_UNAVAILABLE_UNTIL = time.monotonic() + OLLAMA_COOLDOWN_SECONDS
            raise OllamaAPIError(f"Ollama task failed: {e}")


def check_needs_scroll(image_path: Path) -> bool:
    """
    Check if the question/options are cut off and need scrolling.
    """
    try:
        result = _call_ollama_task(image_path, SCROLL_CHECK_PROMPT)
        needs_scroll = result.get("needs_scroll", False)
        logger.info("Local AI scroll check: %s", needs_scroll)
        return needs_scroll
    except Exception:
        return False  # Fail-safe to False (assume no scroll if AI fails)


def check_is_answered(image_path: Path) -> tuple[bool, Optional[str]]:
    """
    Check if an option is visually selected.
    Returns (is_answered, selected_letter).
    """
    try:
        result = _call_ollama_task(image_path, ANSWER_VERIFICATION_PROMPT)
        is_answered = result.get("is_answered", False)
        letter = result.get("selected_letter")
        logger.info("Local AI answer check: %s (%s)", is_answered, letter)
        return is_answered, letter
    except Exception:
        return False, None


def check_screen_state(image_path: Path) -> str:
    """
    Identify current screen type (QUESTION, LOGIN, ERROR, etc.)
    """
    try:
        result = _call_ollama_task(image_path, SCREEN_STATE_PROMPT)
        state = result.get("screen_type", "OTHER")
        logger.info("Local AI screen state: %s", state)
        return state
    except Exception:
        return "OTHER"


def locate_next_button_grid(image_path: Path) -> tuple[bool, Optional[tuple[int, int]]]:
    """
    Locate NEXT button in 20x20 grid coordinates.
    Returns (next_visible, (grid_col, grid_row) or None).
    """
    try:
        result = _call_ollama_task(image_path, NEXT_BUTTON_PROMPT)
        visible = bool(result.get("next_visible", False))
        col = result.get("grid_col")
        row = result.get("grid_row")
        if not visible or col is None or row is None:
            logger.info("Local AI NEXT locator: not visible")
            return (False, None)
        col_i = int(col)
        row_i = int(row)
        if 0 <= col_i <= 19 and 0 <= row_i <= 19:
            logger.info("Local AI NEXT locator: grid=(%d,%d)", col_i, row_i)
            return (True, (col_i, row_i))
        logger.warning("Local AI NEXT locator returned out-of-range coords: %s", result)
        return (False, None)
    except Exception:
        return (False, None)
