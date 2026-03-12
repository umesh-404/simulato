"""
Grok Vision API response parser.

Validates and extracts structured data from the AI response JSON.
Ensures conformance to the expected schema:

{
  "question": str,
  "options": {"A": str, "B": str, "C": str, "D": str},
  "answer": str,          # letter A-D
  "answer_content": str   # text of the chosen option
}

Returns a validated Pydantic model or raises on malformed responses.
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, field_validator

from controller.utils.logger import get_logger

logger = get_logger("response_parser")


class GrokResponseOptions(BaseModel):
    A: str
    B: str
    C: str
    D: str


class GrokResponse(BaseModel):
    question: str
    options: GrokResponseOptions
    answer: str
    answer_content: str

    @field_validator("answer")
    @classmethod
    def validate_answer_letter(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in ("A", "B", "C", "D"):
            raise ValueError(f"answer must be A, B, C, or D — got '{v}'")
        return v


class GrokErrorResponse(BaseModel):
    error: str


class ParseError(Exception):
    """Raised when the AI response cannot be parsed into valid structured data."""
    pass


def _extract_json_from_text(text: str) -> str:
    """
    Extract JSON object from text that may contain markdown fencing
    or surrounding prose.
    """
    text = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return brace_match.group(0)

    return text


def parse_grok_response(raw_text: str) -> GrokResponse:
    """
    Parse raw Grok API response text into a validated GrokResponse.

    Args:
        raw_text: The raw text content from the API response.

    Returns:
        Validated GrokResponse object.

    Raises:
        ParseError: If the response is malformed or fails validation.
    """
    json_str = _extract_json_from_text(raw_text)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s | raw: %s", e, raw_text[:200])
        raise ParseError(f"Invalid JSON from Grok: {e}") from e

    if "error" in data and len(data) == 1:
        error_resp = GrokErrorResponse(**data)
        logger.warning("Grok returned error response: %s", error_resp.error)
        raise ParseError(f"Grok error: {error_resp.error}")

    try:
        response = GrokResponse(**data)
    except Exception as e:
        logger.error("Schema validation failed: %s | data: %s", e, json.dumps(data)[:300])
        raise ParseError(f"Response schema validation failed: {e}") from e

    declared_content = getattr(response.options, response.answer)
    if response.answer_content.strip() != declared_content.strip():
        logger.warning(
            "answer_content mismatch: answer=%s, options[%s]='%s', answer_content='%s'. "
            "Using options[%s] as authoritative.",
            response.answer, response.answer, declared_content[:80],
            response.answer_content[:80], response.answer,
        )
        response.answer_content = declared_content

    logger.info(
        "Parsed Grok response: answer=%s, question_length=%d",
        response.answer, len(response.question),
    )
    return response
