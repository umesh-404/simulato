"""
Prompt builder for Grok Vision API.

Constructs the system and user prompts used when sending
stitched question images to the AI model.

The prompt is engineered to produce structured JSON output
matching the Simulato AI response schema.
"""

from controller.utils.logger import get_logger

logger = get_logger("prompt_builder")

SYSTEM_PROMPT = """You are an expert exam question analyzer. You will be given a screenshot of an exam question with multiple choice options.

Your task:
1. Read the question text carefully and completely.
2. Read all answer options (A, B, C, D).
3. Determine the correct answer.
4. Return your response as a JSON object with this exact structure:

{
  "question": "<full question text>",
  "options": {
    "A": "<option A text>",
    "B": "<option B text>",
    "C": "<option C text>",
    "D": "<option D text>"
  },
  "answer": "<letter of correct answer>",
  "answer_content": "<full text of the correct answer option>"
}

Rules:
- Extract the EXACT text shown in the image. Do not paraphrase.
- The "answer" field must be a single letter: A, B, C, or D.
- The "answer_content" field must contain the exact text of the option you selected.
- Return ONLY the JSON object. No explanation, no markdown, no extra text.
- If you cannot read the image clearly, return: {"error": "unreadable"}
"""

USER_PROMPT = "Analyze this exam question screenshot and return the structured JSON response."


def build_grok_messages(image_base64: str) -> list[dict]:
    """
    Build the messages array for the Grok Vision API request.

    Args:
        image_base64: Base64-encoded image string.

    Returns:
        List of message dicts ready for the API payload.
    """
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": USER_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                    },
                },
            ],
        },
    ]
    logger.debug("Built Grok messages (image size: %d chars)", len(image_base64))
    return messages


def get_grok_response_schema() -> dict:
    """
    Return the JSON Schema for structured Grok outputs.
    Used with the 'response_format' API parameter.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "exam_question",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "object",
                        "properties": {
                            "A": {"type": "string"},
                            "B": {"type": "string"},
                            "C": {"type": "string"},
                            "D": {"type": "string"},
                        },
                        "required": ["A", "B", "C", "D"],
                        "additionalProperties": False,
                    },
                    "answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "answer_content": {"type": "string"},
                },
                "required": ["question", "options", "answer", "answer_content"],
                "additionalProperties": False,
            },
        },
    }
