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
    OLLAMA_TARGET_TIMEOUT_SECONDS,
    OLLAMA_COOLDOWN_SECONDS,
    OLLAMA_TIMEOUT_COOLDOWN_SECONDS,
    OLLAMA_KEEP_ALIVE,
    OCR_LAYOUT_PRIMARY_ENABLED,
)
from controller.ai_pipeline.aux_prompts import (
    SCROLL_CHECK_PROMPT,
    ANSWER_VERIFICATION_PROMPT,
    SCREEN_STATE_PROMPT,
    NEXT_BUTTON_PROMPT,
    OPTION_TARGET_PROMPT,
    NEXT_BUTTON_TARGET_PROMPT,
)
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("ollama_client")
_OLLAMA_UNAVAILABLE_UNTIL = 0.0


def _check_needs_scroll_ocr_heuristic(image_path: Path) -> tuple[bool, float]:
    """
    OCR-based truncation heuristic (no Ollama call).

    Idea:
      - Ignore bottom bar words by only considering words whose center is
        above the bottom-panel end.
      - If the lowest detected text bounding box in the question panel
        reaches close to the bottom end of the panel, assume the content
        is truncated and scrolling is needed.

    Returns:
        (needs_scroll, confidence) where confidence in [0,1].
    """
    if not OCR_LAYOUT_PRIMARY_ENABLED:
        return (False, 0.0)

    try:
        from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer

        ocr = OCRLayoutAnalyzer()
        result = ocr.analyze(image_path)
        if result is None or not result.words:
            return (False, 0.0)

        # --- Option-completeness veto ---
        # If the OptionDetector already found 3+ radio buttons, the answer
        # panel is fully visible and scrolling is almost certainly unnecessary.
        # This prevents false-positive scroll when option text sits near the
        # bottom of the image but all content is actually visible.
        try:
            from controller.capture_pipeline.option_detector import OptionDetector
            from controller.capture_pipeline.exam_layout import ExamLayoutDetector

            layout_det = ExamLayoutDetector()
            import cv2
            img = cv2.imread(str(image_path))
            if img is not None:
                layout_res = layout_det.detect(img)
                if layout_res is not None and layout_res.answer_panel is not None:
                    opt_det = OptionDetector()
                    opt_map = opt_det.crop_and_detect(img, layout_res.answer_panel)
                    if opt_map is not None and len(opt_map.options) >= 3:
                        logger.info(
                            "OCR scroll heuristic VETOED: %d options already detected — no scroll needed",
                            len(opt_map.options),
                        )
                        return (False, 0.95)
        except Exception:
            pass   # If option detection fails, continue with OCR heuristic.

        # Exclude bottom-bar area (NEXT/CLEAR/Prev buttons) from truncation
        # scoring.  Use a generous 12% to avoid counting the navigation bar
        # and bottom-most whitespace as clipped content.
        bottom_bar_frac = 0.12
        panel_end_y = int(result.image_h * (1.0 - bottom_bar_frac))
        question_words = [w for w in result.words if w.cy < panel_end_y]
        if len(question_words) < 5:
            return (False, 0.1)

        lowest_y2 = max(w.y + w.h for w in question_words)

        # How close lowest text is to the panel end determines confidence.
        band_px = max(10, int(result.image_h * 0.06))
        band_start = max(0, panel_end_y - band_px)

        if lowest_y2 < band_start:
            # Significant whitespace remains at the bottom of the question panel.
            return (False, 0.9 * max(0.0, (band_start - lowest_y2) / max(1, band_px)))

        # Content reaches the bottom band => likely truncation.
        conf = (lowest_y2 - band_start) / max(1, band_px)
        conf = max(0.0, min(1.0, float(conf)))

        # Optional strengthening: count words inside the bottom band.
        bottom_band_words = [w for w in question_words if (w.y + w.h) >= band_start]
        if len(bottom_band_words) >= 6:
            conf = min(1.0, conf + 0.15)

        return (True, conf)
    except Exception:
        return (False, 0.0)


class OllamaAPIError(Exception):
    """Raised when the Ollama API returns a non-recoverable error."""
    pass


def _encode_image(image_path: Path) -> str:
    """Read an image file and return its base64 encoding."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_ollama_task(
    image_path: Path,
    prompt: str,
    timeout_seconds: Optional[int] = None,
) -> dict:
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
            timeout = int(timeout_seconds or OLLAMA_TIMEOUT_SECONDS)
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return json.loads(data["message"]["content"])
        except requests.exceptions.ReadTimeout as e:
            logger.error("Ollama task timed out: %s", e)
            # Short cooldown for timeout-only cases; avoids disabling local AI for too long.
            _OLLAMA_UNAVAILABLE_UNTIL = time.monotonic() + OLLAMA_TIMEOUT_COOLDOWN_SECONDS
            raise OllamaAPIError(f"Ollama task timed out: {e}")
        except Exception as e:
            logger.error("Ollama task failed: %s", e)
            _OLLAMA_UNAVAILABLE_UNTIL = time.monotonic() + OLLAMA_COOLDOWN_SECONDS
            raise OllamaAPIError(f"Ollama task failed: {e}")


def check_needs_scroll(image_path: Path) -> bool:
    """
    Check if the question/options are cut off and need scrolling.
    """
    # Step 1: Fast OCR heuristic (deterministic; helps avoid slow Ollama calls).
    if OCR_LAYOUT_PRIMARY_ENABLED:
        needs_scroll, conf = _check_needs_scroll_ocr_heuristic(image_path)
        if conf >= 0.80:
            logger.info("OCR scroll heuristic used: needs_scroll=%s conf=%.2f", needs_scroll, conf)
            return needs_scroll
        if conf > 0.0:
            logger.info("OCR scroll heuristic low confidence (%.2f) — falling back to Ollama", conf)

    # Step 2: Existing Ollama scroll-check prompt (fallback / safety).
    try:
        result = _call_ollama_task(image_path, SCROLL_CHECK_PROMPT)
        needs_scroll = result.get("needs_scroll", False)
        logger.info("Local AI scroll check (Ollama): %s", needs_scroll)
        return needs_scroll
    except Exception:
        return False  # Fail-safe to False (assume no scroll if AI fails)


def check_is_answered(image_path: Path) -> tuple[bool, Optional[str]]:
    """
    Check if an option is visually selected.
    Returns (is_answered, selected_letter).
    """
    try:
        result = _call_ollama_task(
            image_path,
            ANSWER_VERIFICATION_PROMPT,
            timeout_seconds=OLLAMA_TARGET_TIMEOUT_SECONDS,
        )
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


def _parse_normalized_target(result: dict) -> Optional[tuple[float, float]]:
    """Validate and extract normalized (x, y) target coordinates from a model result."""
    if not bool(result.get("found", False)):
        return None
    cx = result.get("center_x")
    cy = result.get("center_y")
    if cx is None or cy is None:
        return None
    try:
        x = float(cx)
        y = float(cy)
    except (TypeError, ValueError):
        return None
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return (x, y)
    return None


def locate_option_target(image_path: Path, letter: str) -> Optional[tuple[float, float]]:
    """
    Locate precise clickable target for a specific option letter.
    Returns normalized coordinates (x, y) in [0,1], or None.
    """
    try:
        prompt = OPTION_TARGET_PROMPT.format(LETTER=letter.strip().upper())
        result = _call_ollama_task(
            image_path,
            prompt,
            timeout_seconds=OLLAMA_TARGET_TIMEOUT_SECONDS,
        )
        target = _parse_normalized_target(result)
        if target is not None:
            logger.info("Local AI option locator (%s): normalized=(%.4f, %.4f)", letter, target[0], target[1])
        else:
            logger.info("Local AI option locator (%s): not found", letter)
        return target
    except Exception:
        return None


def locate_next_button_target(image_path: Path) -> Optional[tuple[float, float]]:
    """
    Locate precise clickable target for NEXT button.
    Returns normalized coordinates (x, y) in [0,1], or None.
    """
    try:
        result = _call_ollama_task(
            image_path,
            NEXT_BUTTON_TARGET_PROMPT,
            timeout_seconds=OLLAMA_TARGET_TIMEOUT_SECONDS,
        )
        target = _parse_normalized_target(result)
        if target is not None:
            logger.info("Local AI NEXT locator: normalized=(%.4f, %.4f)", target[0], target[1])
        else:
            logger.info("Local AI NEXT locator: not found")
        return target
    except Exception:
        return None
