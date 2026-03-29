"""
Grok Vision API client.

Sends stitched exam screenshots to the Grok API and returns
structured responses. Handles retries on transient failures
and malformed JSON.

When the model can read the question text but fails to read
option texts (common with heavy watermarks on fast models),
a panel-crop focused retry sends a zoomed-in answer panel image.

Network usage: Internet (Canonical Law 15 — only AI API calls use internet).
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

import requests

from controller.config import (
    GROK_API_URL,
    GROK_API_KEY,
    GROK_MODEL,
    AI_API_MAX_RETRIES,
    AI_API_BACKOFF_BASE_SECONDS,
)
from controller.ai_pipeline.prompt_builder import (
    build_grok_messages,
    build_grok_messages_with_panel_crop,
    get_grok_response_schema,
)
from controller.ai_pipeline.response_parser import parse_grok_response, GrokResponse, ParseError
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("grok_client")

MAX_RETRIES = AI_API_MAX_RETRIES


class GrokAPIError(Exception):
    """Raised when the Grok API returns a non-recoverable error."""
    pass


def _encode_image(image_path: Path) -> str:
    """Read an image file and return its base64 encoding."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_api(messages: list[dict]) -> str:
    """
    Make a single API call to Grok Vision.

    Returns the raw text content from the response.
    Raises GrokAPIError on HTTP errors.
    """
    if not GROK_API_KEY:
        raise GrokAPIError("GROK_API_KEY environment variable is not set")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROK_API_KEY}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    payload = {
        "model": GROK_MODEL,
        "messages": messages,
        "temperature": 0,
        "response_format": get_grok_response_schema(),
    }

    try:
        with ExecutionTimer("grok_api_request"):
            resp = requests.post(
                GROK_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
    except requests.RequestException as e:
        logger.error("Grok API request failed: %s", e)
        raise GrokAPIError(f"Grok API request failed: {e}") from e

    if resp.status_code != 200:
        logger.error("Grok API HTTP %d: %s", resp.status_code, resp.text[:300])
        raise GrokAPIError(f"Grok API returned HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as e:
        logger.error("Grok API returned invalid JSON: %s", resp.text[:300])
        raise GrokAPIError(f"Grok API returned invalid JSON: {e}") from e
    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error("Unexpected Grok response structure: %s", json.dumps(data)[:300])
        raise GrokAPIError(f"Unexpected response structure: {e}") from e

    return raw_text


def _crop_answer_panel(image_path: Path) -> Optional[str]:
    """
    Detect the answer panel region and return a base64-encoded cropped image.

    Uses ExamLayoutDetector to find the right (answer) panel, then crops
    it out and encodes as JPEG base64.  Returns None if detection fails.
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

    panel_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    logger.info(
        "Cropped answer panel for retry: region=(%d,%d,%d,%d), crop_size=%dx%d",
        x1, y1, x2, y2, x2 - x1, y2 - y1,
    )
    return panel_b64


def query_grok(image_path: Path, ocr_context: str = "", is_stitched: bool = False) -> GrokResponse:
    """
    Send an image to Grok Vision and return a validated structured response.

    Retries up to MAX_RETRIES times on parse failures.
    If the model reads the question but returns empty options, performs
    a focused retry with a cropped answer-panel image.

    Args:
        image_path: Path to the stitched question image.
        ocr_context: Optional OCR text to guide the model.
        is_stitched: True if the image is a multi-frame stitched composite.

    Returns:
        Validated GrokResponse with question, options, answer, answer_content.

    Raises:
        GrokAPIError: On HTTP-level failures after retries.
        ParseError: If all retry attempts produce unparseable responses.
    """
    image_b64 = _encode_image(image_path)
    messages = build_grok_messages(image_b64, ocr_context, is_stitched=is_stitched)

    last_error: Optional[Exception] = None
    # Track whether the model could read the question but not options,
    # so we can try a panel-crop focused retry.
    extracted_question: Optional[str] = None
    last_raw_text: str = ""
    # If we get a valid but sparse response (few options populated),
    # keep it as fallback while attempting a panel-crop retry.
    sparse_response: Optional[GrokResponse] = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Grok API call attempt %d/%d for %s", attempt, MAX_RETRIES, image_path.name)
        try:
            raw_text = _call_api(messages)
            last_raw_text = raw_text
            logger.info("Grok raw response (attempt %d): %s", attempt, raw_text[:500])
            response = parse_grok_response(raw_text)
            logger.info(
                "Grok query successful on attempt %d: answer=%s",
                attempt, response.answer,
            )

            # Check option extraction quality.
            # If fewer than 3 options have text, the model struggled with
            # the image (common with heavy watermarks on the answer panel).
            # Save this response as fallback and attempt a panel-crop retry.
            opts = response.options
            non_empty = sum(
                1 for k in ("A", "B", "C", "D", "E")
                if getattr(opts, k, "").strip()
            )
            if non_empty < 3 and response.question and len(response.question) > 20:
                logger.info(
                    "Sparse option extraction (%d of 5 non-empty) — will attempt panel-crop retry",
                    non_empty,
                )
                extracted_question = response.question
                sparse_response = response
                # Don't return yet — try panel-crop below
                break

            return response
        except ParseError as e:
            logger.warning("Parse error on attempt %d: %s", attempt, e)
            last_error = e
            # Check if model extracted a question but options were empty.
            # If so, save the question text for the panel-crop retry.
            if "unreadable" in str(e).lower() or "empty" in str(e).lower():
                try:
                    raw_data = json.loads(last_raw_text)
                    q = raw_data.get("question", "")
                    if q and len(q) > 20:
                        extracted_question = q
                except Exception:
                    pass
        except GrokAPIError as e:
            logger.error("API error on attempt %d: %s", attempt, e)
            last_error = e

        if attempt < MAX_RETRIES:
            backoff = max(0.0, AI_API_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            logger.info("Grok retry backoff: %.2fs", backoff)
            time.sleep(backoff)

    # -----------------------------------------------------------------------
    # Panel-crop focused retry: if the model read the question but couldn't
    # read options (or read very few), crop the answer panel and retry with
    # a two-image prompt.  This gives the model a zoomed-in view of the
    # option texts, which dramatically improves readability through watermarks.
    # -----------------------------------------------------------------------
    if extracted_question:
        logger.info(
            "Attempting panel-crop retry — model read question (%d chars) but options were sparse/empty",
            len(extracted_question),
        )
        panel_b64 = _crop_answer_panel(image_path)
        if panel_b64 is not None:
            retry_messages = build_grok_messages_with_panel_crop(
                full_image_base64=image_b64,
                panel_image_base64=panel_b64,
                question_text=extracted_question,
                ocr_context=ocr_context,
            )
            try:
                raw_text = _call_api(retry_messages)
                logger.info("Grok panel-crop retry response: %s", raw_text[:500])
                response = parse_grok_response(raw_text)
                logger.info(
                    "Grok panel-crop retry successful: answer=%s",
                    response.answer,
                )
                return response
            except (ParseError, GrokAPIError) as e:
                logger.warning("Panel-crop retry also failed: %s", e)
                last_error = e
        else:
            logger.warning("Could not crop answer panel — skipping panel-crop retry")

    # If we had a sparse but valid response, return it as a fallback.
    # The answer letter is likely correct even if option texts are missing.
    if sparse_response is not None:
        logger.info(
            "Returning sparse response as fallback (answer=%s, %d options populated)",
            sparse_response.answer,
            sum(1 for k in ("A", "B", "C", "D", "E")
                if getattr(sparse_response.options, k, "").strip()),
        )
        return sparse_response

    if last_error is not None:
        raise last_error
    raise GrokAPIError("No API attempts made (MAX_RETRIES=0?)")
