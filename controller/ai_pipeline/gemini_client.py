"""
Gemini Vision API client.

Sends stitched exam screenshots to the Gemini API (OpenAI-compatible endpoint)
and returns structured responses. Handles retries on transient failures
and malformed JSON.

Network usage: Internet (Canonical Law 15 — only AI API calls use internet).
"""

import base64
import json
from pathlib import Path
from typing import Optional

import requests

from controller.config import GEMINI_API_URL, GEMINI_API_KEY, GEMINI_MODEL
from controller.ai_pipeline.prompt_builder import build_grok_messages
from controller.ai_pipeline.response_parser import parse_grok_response, GrokResponse, ParseError
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("gemini_client")

MAX_RETRIES = 2


class GeminiAPIError(Exception):
    """Raised when the Gemini API returns a non-recoverable error."""
    pass


def _encode_image(image_path: Path) -> str:
    """Read an image file and return its base64 encoding."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _call_api(messages: list[dict]) -> str:
    """
    Make a single API call to Gemini Vision (OpenAI-compatible endpoint).

    Returns the raw text content from the response.
    Raises GeminiAPIError on HTTP errors.
    """
    if not GEMINI_API_KEY:
        raise GeminiAPIError("GEMINI_API_KEY environment variable is not set")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}",
    }
    payload = {
        "model": GEMINI_MODEL,
        "messages": messages,
        "temperature": 0,
    }

    with ExecutionTimer("gemini_api_request"):
        resp = requests.post(
            GEMINI_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

    if resp.status_code != 200:
        logger.error("Gemini API HTTP %d: %s", resp.status_code, resp.text[:300])
        raise GeminiAPIError(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error("Unexpected Gemini response structure: %s", json.dumps(data)[:300])
        raise GeminiAPIError(f"Unexpected response structure: {e}") from e

    return raw_text


def query_gemini(image_path: Path) -> GrokResponse:
    """
    Send an image to Gemini Vision and return a validated structured response.

    Retries up to MAX_RETRIES times on parse failures.

    Args:
        image_path: Path to the stitched question image.

    Returns:
        Validated GrokResponse with question, options, answer, answer_content.

    Raises:
        GeminiAPIError: On HTTP-level failures after retries.
        ParseError: If all retry attempts produce unparseable responses.
    """
    image_b64 = _encode_image(image_path)
    messages = build_grok_messages(image_b64)

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Gemini API call attempt %d/%d for %s", attempt, MAX_RETRIES, image_path.name)
        try:
            raw_text = _call_api(messages)
            logger.debug("Gemini raw response (attempt %d): %s", attempt, raw_text[:200])
            response = parse_grok_response(raw_text)
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

    raise last_error
