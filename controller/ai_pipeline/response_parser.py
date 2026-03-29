"""
AI Vision API response parser.

Validates and extracts structured data from the AI response JSON.
Ensures conformance to the expected schema:

{
  "question": str,
  "options": {"A": str, "B": str, "C": str, "D": str, "E": str},
  "answer": str,          # letter A-E
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
    C: str = ""
    D: str = ""
    E: str = ""


class GrokResponse(BaseModel):
    question: str
    options: GrokResponseOptions
    answer: str
    answer_content: str

    @field_validator("answer")
    @classmethod
    def validate_answer_letter(cls, v: str) -> str:
        v = v.strip().upper()
        # Allow empty string through — recovery logic in parse_grok_response
        # handles remapping when the model returns an empty answer.
        if v and v not in ("A", "B", "C", "D", "E"):
            raise ValueError(f"answer must be A, B, C, D, or E — got '{v}'")
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


def _get_non_empty_options(options: GrokResponseOptions) -> dict[str, str]:
    """Return only the options that have non-empty text."""
    all_opts = {"A": options.A, "B": options.B, "C": options.C, "D": options.D, "E": options.E}
    return {k: v for k, v in all_opts.items() if v.strip()}


def parse_grok_response(raw_text: str) -> GrokResponse:
    """
    Parse raw AI API response text into a validated GrokResponse.

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
        raise ParseError(f"Invalid JSON from AI: {e}") from e

    if "error" in data and len(data) == 1:
        error_resp = GrokErrorResponse(**data)
        logger.warning("AI returned error response: %s", error_resp.error)
        raise ParseError(f"AI error: {error_resp.error}")

    try:
        response = GrokResponse(**data)
    except Exception as e:
        logger.error("Schema validation failed: %s | data: %s", e, json.dumps(data)[:300])
        raise ParseError(f"Response schema validation failed: {e}") from e

    # -----------------------------------------------------------------------
    # Validate: answer letter must correspond to a non-empty option.
    # If the model picked a letter with empty text but provided non-empty
    # options, try to auto-correct by matching answer_content against them.
    # -----------------------------------------------------------------------
    declared_content = getattr(response.options, response.answer, "")
    non_empty = _get_non_empty_options(response.options)

    if not declared_content.strip():
        # Model chose an option it left empty — this is an error from the model.
        # Attempt recovery: if answer_content matches a non-empty option, remap.
        if response.answer_content.strip() and non_empty:
            for letter, text in non_empty.items():
                if text.strip() == response.answer_content.strip():
                    logger.warning(
                        "Auto-correcting answer from '%s' (empty) to '%s' based on answer_content match",
                        response.answer, letter,
                    )
                    response.answer = letter
                    declared_content = text
                    break
            else:
                # answer_content doesn't match any option text exactly — pick the
                # first non-empty option as a last-resort (we'll log the issue).
                first_letter = next(iter(non_empty))
                logger.warning(
                    "Answer '%s' has empty option text and answer_content '%s' "
                    "doesn't match any option. Remapping to first non-empty option '%s'.",
                    response.answer, response.answer_content[:60], first_letter,
                )
                response.answer = first_letter
                response.answer_content = non_empty[first_letter]
                declared_content = response.answer_content
        elif non_empty:
            # No answer_content provided but there are non-empty options
            first_letter = next(iter(non_empty))
            logger.warning(
                "Answer '%s' has empty option text. Remapping to first non-empty option '%s'.",
                response.answer, first_letter,
            )
            response.answer = first_letter
            response.answer_content = non_empty[first_letter]
            declared_content = response.answer_content
        else:
            # All options are empty — unreadable image
            raise ParseError(
                "All option texts are empty — image appears unreadable to AI"
            )

    # Ensure answer_content matches the authoritative option text
    if response.answer_content.strip() != declared_content.strip():
        logger.warning(
            "answer_content mismatch: answer=%s, options[%s]='%s', answer_content='%s'. "
            "Using options[%s] as authoritative.",
            response.answer, response.answer, declared_content[:80],
            response.answer_content[:80], response.answer,
        )
        response.answer_content = declared_content

    logger.info(
        "Parsed AI response: answer=%s, question_length=%d, non_empty_options=%d",
        response.answer, len(response.question), len(non_empty),
    )
    return response
