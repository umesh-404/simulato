"""
AI Vision API response parser.

Extracts the answer letter (A-E) from the AI response.

The AI returns a minimal JSON object:  {"answer": "C"}

The parser handles edge cases:
- JSON wrapped in markdown fences
- Raw letter without JSON wrapping
- Extra fields returned by the model (silently ignored)

Returns a validated AIResponse or raises ParseError.
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, field_validator

from controller.utils.logger import get_logger

logger = get_logger("response_parser")


# ---------------------------------------------------------------------------
# Response model — kept with backward-compatible fields so downstream
# code that accesses .question / .options / .answer_content doesn't crash.
# Only .answer is actively populated by the parser.
# ---------------------------------------------------------------------------

class AIResponseOptions(BaseModel):
    A: str = ""
    B: str = ""
    C: str = ""
    D: str = ""
    E: str = ""


class AIResponse(BaseModel):
    question: str = ""
    options: AIResponseOptions = AIResponseOptions()
    answer: str
    answer_content: str = ""

    @field_validator("answer")
    @classmethod
    def validate_answer_letter(cls, v: str) -> str:
        v_stripped = v.strip()
        if not v_stripped:
            raise ValueError("answer is empty")
            
        # Support Fill-in-the-Blank textual responses natively
        if v_stripped.upper().startswith("FITB:"):
            return v_stripped
            
        v_upper = v_stripped.upper()
        # Take only the first character — models sometimes return "C - explanation"
        if len(v_upper) > 1 and not v_upper.startswith("FITB:"):
            first_char = v_upper[0]
            if first_char in ("A", "B", "C", "D", "E"):
                return first_char
                
        if v_upper not in ("A", "B", "C", "D", "E"):
            raise ValueError(f"answer must be A, B, C, D, E, or start with 'FITB:' — got '{v}'")
        return v_upper


# Backward-compatible aliases so existing imports don't break
GrokResponse = AIResponse
GrokResponseOptions = AIResponseOptions


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


def _extract_bare_letter(text: str) -> Optional[str]:
    """
    Try to extract a bare answer letter from text that isn't valid JSON.
    Handles cases like: "C", "The answer is B", "A\n", etc.
    """
    text_upper = text.strip().upper()
    
    # Check for Fill-in-the-Blank syntax
    if text_upper.startswith("FITB:"):
        return text.strip()  # preserve original casing for the typed answer
        
    # Exact single letter
    if text_upper in ("A", "B", "C", "D", "E"):
        return text_upper
    # First character is a valid letter followed by non-alpha
    if len(text_upper) >= 1 and text_upper[0] in ("A", "B", "C", "D", "E"):
        if len(text_upper) == 1 or not text_upper[1].isalpha():
            return text_upper[0]
    return None


def parse_ai_response(raw_text: str) -> AIResponse:
    """
    Parse raw AI API response text into a validated AIResponse.

    Expects minimal JSON: {"answer": "C"}
    Also handles extra fields (question, options, etc.) gracefully —
    they are accepted but not required.

    Args:
        raw_text: The raw text content from the API response.

    Returns:
        Validated AIResponse with answer letter.

    Raises:
        ParseError: If the response is malformed or fails validation.
    """
    json_str = _extract_json_from_text(raw_text)

    # Try JSON parse first
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Not valid JSON — try extracting a bare letter
        bare = _extract_bare_letter(raw_text)
        if bare:
            logger.info("Extracted bare answer letter from non-JSON response: %s", bare)
            return AIResponse(answer=bare)
        logger.error("JSON parse failed and no bare letter found | raw: %s", raw_text[:200])
        raise ParseError(f"Invalid JSON from AI and no bare letter found: {raw_text[:100]}")

    # Handle error responses
    if "error" in data and len(data) == 1:
        logger.warning("AI returned error response: %s", data["error"])
        raise ParseError(f"AI error: {data['error']}")

    # Ensure "answer" key exists
    if "answer" not in data:
        # Try to find letter in any field value
        for v in data.values():
            if isinstance(v, str):
                bare = _extract_bare_letter(v)
                if bare:
                    logger.warning("No 'answer' key — extracted letter '%s' from field value", bare)
                    return AIResponse(answer=bare)
        raise ParseError(f"No 'answer' key in AI response: {json.dumps(data)[:200]}")

    # Build response — extra fields (question, options, etc.) are accepted
    # by AIResponse's default values and won't cause errors
    try:
        response = AIResponse(**{k: v for k, v in data.items()
                                   if k in AIResponse.model_fields})
    except Exception as e:
        logger.error("Schema validation failed: %s | data: %s", e, json.dumps(data)[:300])
        raise ParseError(f"Response validation failed: {e}") from e

    logger.info("Parsed AI response: answer=%s", response.answer)
    return response


# Backward-compatible alias
parse_grok_response = parse_ai_response
