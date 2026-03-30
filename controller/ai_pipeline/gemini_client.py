"""
Gemini Vision API client  (sole AI provider for Simulato).

Sends exam screenshots to Gemini 2.5 Flash (non-reasoning mode) via
the Google Gen AI SDK using Vertex AI and Application Default Credentials.

Authentication: uses ADC from `gcloud auth application-default login`.
Billing: consumes GCP free credits → promotional credits → real billing.

When an answer panel crop is available, both the full image and the
zoomed-in crop are sent in a single API call for improved readability
through watermarks.

Non-reasoning mode (thinking_budget=0) is used because testing showed
it achieves 100% accuracy on exam questions while being 2x faster and
using 2.5x fewer tokens than the reasoning variant.

Network usage: Internet (Canonical Law 15 — only AI API calls use internet).
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from controller.config import (
    GEMINI_MODEL,
    GCP_PROJECT_ID,
    GCP_LOCATION,
    AI_API_MAX_RETRIES,
    AI_API_BACKOFF_BASE_SECONDS,
)
from controller.ai_pipeline.prompt_builder import SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_PANEL, USER_PROMPT, USER_PROMPT_STITCHED, USER_PROMPT_WITH_PANEL
from controller.ai_pipeline.response_parser import AIResponse, parse_ai_response, ParseError
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("gemini_client")

MAX_RETRIES = AI_API_MAX_RETRIES

# Lazy-initialized Vertex AI client (created on first API call)
_client: Optional[genai.Client] = None


class GeminiAPIError(Exception):
    """Raised when the Gemini API returns a non-recoverable error."""
    pass


def _get_client() -> genai.Client:
    """Get or create the Vertex AI Gemini client (singleton)."""
    global _client
    if _client is not None:
        return _client

    client_kwargs = {"vertexai": True}
    if GCP_PROJECT_ID:
        client_kwargs["project"] = GCP_PROJECT_ID
    if GCP_LOCATION:
        client_kwargs["location"] = GCP_LOCATION

    logger.info(
        "Initializing Vertex AI Gemini client (project=%s, location=%s)",
        GCP_PROJECT_ID or "(auto)", GCP_LOCATION or "(auto)",
    )
    _client = genai.Client(**client_kwargs)
    return _client


def _crop_answer_panel(image_path: Path) -> Optional[bytes]:
    """
    Detect the answer panel region and return cropped image bytes.

    Uses ExamLayoutDetector to find the right (answer) panel, then crops
    it out and encodes as JPEG bytes. Returns None if detection fails.
    """
    try:
        import cv2
        from controller.capture_pipeline.exam_layout import ExamLayoutDetector
    except ImportError:
        logger.debug("Cannot crop answer panel — missing cv2 or exam_layout")
        return None

    detector = ExamLayoutDetector()
    layout = detector.detect(image_path)
    if layout is None or not layout.is_valid() or layout.answer_panel is None:
        logger.debug("Cannot crop answer panel — layout detection failed for %s", image_path.name)
        return None

    img = cv2.imread(str(image_path))
    if img is None:
        return None

    ap = layout.answer_panel
    # Add some left padding to capture radio circles fully
    pad_left = min(50, ap.x)
    x1 = max(0, ap.x - pad_left)
    y1 = max(0, ap.y)
    x2 = min(img.shape[1], ap.x + ap.w)
    y2 = min(img.shape[0], ap.y + ap.h)

    cropped = img[y1:y2, x1:x2]
    if cropped.size == 0:
        return None

    success, buf = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        return None

    logger.info(
        "Cropped answer panel: region=(%d,%d,%d,%d), crop_size=%dx%d",
        x1, y1, x2, y2, x2 - x1, y2 - y1,
    )
    return buf.tobytes()


# ---------------------------------------------------------------------------
# Image compression for AI upload
# ---------------------------------------------------------------------------
# With MEDIA_RESOLUTION_MEDIUM, Gemini uses exactly 256 tokens for the image
# regardless of source file size. So compressing locally before upload has
# zero impact on accuracy or token cost, but saves significant network
# upload time (~1s per question for typical home connections).
# ---------------------------------------------------------------------------

# Max dimension (longest edge) for the image sent to AI.
# Gemini internally downscales further to 256-token tiles, so anything
# above ~768px is wasted pixels. We use 1024 for a small safety margin.
AI_IMAGE_MAX_DIM = 1024

# JPEG quality for the compressed AI payload (80 is visually indistinguishable
# at these resolutions and yields ~200-400KB files).
AI_IMAGE_JPEG_QUALITY = 80


def _compress_for_ai(image_bytes: bytes) -> bytes:
    """
    Resize and compress image bytes for AI upload.

    Shrinks the longest edge to AI_IMAGE_MAX_DIM and re-encodes as JPEG
    at AI_IMAGE_JPEG_QUALITY. If the input is already small or OpenCV is
    unavailable, returns the original bytes unchanged.

    This function is ONLY used for the bytes sent to the Gemini API.
    The local CV pipeline always uses full-resolution images.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return image_bytes

    # Decode from bytes
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    h, w = img.shape[:2]
    original_size = len(image_bytes)

    # Compute scale factor based on longest edge
    max_side = max(h, w)
    if max_side <= AI_IMAGE_MAX_DIM:
        # Already small enough — just re-encode at lower quality
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, AI_IMAGE_JPEG_QUALITY])
        if ok:
            compressed = buf.tobytes()
            logger.info(
                "AI image compressed (no resize): %dKB -> %dKB (%.0f%% reduction)",
                original_size // 1024, len(compressed) // 1024,
                (1 - len(compressed) / original_size) * 100,
            )
            return compressed
        return image_bytes

    scale = AI_IMAGE_MAX_DIM / max_side
    new_w = int(w * scale)
    new_h = int(h * scale)

    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, AI_IMAGE_JPEG_QUALITY])
    if not ok:
        return image_bytes

    compressed = buf.tobytes()
    logger.info(
        "AI image compressed: %dx%d -> %dx%d, %dKB -> %dKB (%.0f%% reduction)",
        w, h, new_w, new_h,
        original_size // 1024, len(compressed) // 1024,
        (1 - len(compressed) / original_size) * 100,
    )
    return compressed


def _call_api(image_bytes: bytes, is_stitched: bool, panel_crop_bytes: Optional[bytes] = None) -> str:
    """
    Make a single API call to Gemini via the google-genai SDK (Vertex AI).

    Uses non-reasoning mode (thinking_budget=0) for maximum speed.

    Args:
        image_bytes: Full exam screenshot JPEG bytes.
        is_stitched: True if image is a multi-frame stitched composite.
        panel_crop_bytes: Optional zoomed-in crop of the answer panel.

    Returns the raw text content from the response.
    Raises GeminiAPIError on errors.
    """
    client = _get_client()

    # Choose system prompt and user prompt based on available context
    if panel_crop_bytes is not None:
        system_prompt = SYSTEM_PROMPT_WITH_PANEL
        user_prompt = USER_PROMPT_WITH_PANEL
    elif is_stitched:
        system_prompt = SYSTEM_PROMPT
        user_prompt = USER_PROMPT_STITCHED
    else:
        system_prompt = SYSTEM_PROMPT
        user_prompt = USER_PROMPT

    # Build content parts: text prompt + full image + optional panel crop
    contents = [
        user_prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
    ]
    if panel_crop_bytes is not None:
        contents.append(
            types.Part.from_bytes(data=panel_crop_bytes, mime_type="image/jpeg"),
        )

    # Configure: non-reasoning + low-res image (matches AI Studio token usage) + JSON output
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {
                "answer": {"type": "STRING"}
            },
            "required": ["answer"],
        },
    )

    try:
        with ExecutionTimer("gemini_api_request"):
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
    except Exception as e:
        logger.error("Gemini API request failed: %s", e)
        raise GeminiAPIError(f"Gemini API request failed: {e}") from e

    if response.text is None:
        logger.error("Gemini returned empty response")
        raise GeminiAPIError("Gemini returned empty response")

    # Log usage metadata if available
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        um = response.usage_metadata
        logger.info(
            "Gemini usage: input=%s, output=%s, total=%s",
            getattr(um, 'prompt_token_count', '?'),
            getattr(um, 'candidates_token_count', '?'),
            getattr(um, 'total_token_count', '?'),
        )

    return response.text


def query_gemini(image_path: Path, ocr_context: str = "", is_stitched: bool = False) -> AIResponse:
    """
    Send an image to Gemini and return the answer letter.

    Retries up to MAX_RETRIES times on parse failures or API errors.

    Args:
        image_path: Path to the exam question image.
        ocr_context: Ignored — kept for call-site compatibility.
        is_stitched: True if the image is a multi-frame stitched composite.

    Returns:
        AIResponse with the answer letter.

    Raises:
        GeminiAPIError: On API-level failures after retries.
        ParseError: If all retry attempts produce unparseable responses.
    """
    # Read main image as bytes
    image_bytes = image_path.read_bytes()

    # Compress for AI upload — saves ~1s of network upload time per question.
    # Local CV pipeline uses full-resolution images (this only affects the API call).
    image_bytes = _compress_for_ai(image_bytes)

    # Best-effort: crop the answer panel for a zoomed-in view that
    # helps the AI read option text through watermarks/noise.
    panel_crop = _crop_answer_panel(image_path)
    if panel_crop is not None:
        panel_crop = _compress_for_ai(panel_crop)
        logger.info("Answer panel crop included (%d bytes)", len(panel_crop))

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Gemini API call attempt %d/%d for %s", attempt, MAX_RETRIES, image_path.name)
        try:
            raw_text = _call_api(image_bytes, is_stitched, panel_crop_bytes=panel_crop)
            logger.info("Gemini raw response (attempt %d): %s", attempt, raw_text[:200])
            response = parse_ai_response(raw_text)
            logger.info(
                "Gemini query successful on attempt %d: answer=%s",
                attempt, response.answer,
            )
            return response
        except ParseError as e:
            logger.warning("Parse error on attempt %d: %s", attempt, e)
            last_error = e
        except GeminiAPIError as e:
            logger.error("API error on attempt %d: %s", attempt, e)
            last_error = e

        if attempt < MAX_RETRIES:
            backoff = max(0.0, AI_API_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            logger.info("Gemini retry backoff: %.2fs", backoff)
            time.sleep(backoff)

    if last_error is not None:
        raise last_error
    raise GeminiAPIError("No API attempts made (MAX_RETRIES=0?)")
