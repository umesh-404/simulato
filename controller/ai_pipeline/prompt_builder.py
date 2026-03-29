"""
Prompt builder for AI Vision API (Grok / Gemini).

Constructs the system and user prompts used when sending
stitched question images to the AI model.

Enforces a JSON system prompt explicitly to avoid reliance on
strict structured outputs API decoding (which currently breaks
OCR nested fields on some fast models like Grok-4-fast).
"""

from controller.utils.logger import get_logger

logger = get_logger("prompt_builder")

# ---------------------------------------------------------------------------
# System prompt — format + behavioural rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert exam-question solver capable of reading text and unstructured layouts perfectly.

INPUT: A screenshot of an exam question. The image may be a single capture or a vertically stitched composite of two overlapping frames (scrolled to reveal more content). If the image appears taller than usual or contains repeated/overlapping sections, treat it as one continuous question — extract the full text once and ignore any duplicated regions.

LAYOUT: The exam screen is split into two panels:
- LEFT PANEL: Contains the question text.
- RIGHT PANEL: Contains the answer options, each marked by a round radio circle/bubble. The options are stacked vertically from top to bottom.
Look for the radio circles in the right panel to locate each option's text.

TASK:
1. Extract the full question text verbatim from the LEFT panel.
2. Find ALL answer options in the RIGHT panel (look for radio circles/bubbles).
3. Map these options to letters (A, B, C, D, E) in order from top to bottom.
   - The first option from the top is A, the second is B, the third is C, etc.
   - Even if the letters A/B/C/D are not physically written on the screen, you MUST assign them based on their visual order.
4. Determine the single correct answer to the question.
5. Return your response purely as a valid JSON object matching the exact structure below.

REQUIRED JSON STRUCTURE:
{
  "question": "<full question text over multiple lines if needed>",
  "options": {
    "A": "<option A text>",
    "B": "<option B text>",
    "C": "<option C text>",
    "D": "<option D text>",
    "E": "<option E text>"
  },
  "answer": "<A/B/C/D/E>",
  "answer_content": "<exact winning option text>"
}

CRITICAL RULES — follow every one without exception:
• Extract the EXACT text from the image for both the question and the options. Do not paraphrase. Look closely past any diagonal watermarks or visual noise. Do NOT invent or auto-complete math problems.
• If text is partially obscured by watermarks, extract what you CAN read. NEVER return an empty option if there is ANY visible text next to a radio circle.
• If the image is a stitched composite with overlapping frames, deduplicate the content. Extract each option only once.
• Map the options to keys "A", "B", "C", "D", "E" in order from top to bottom.
• If there are fewer than 5 options (e.g., only 2 or 3 exist), assign the ones that exist to A, B, etc., and set the remaining unused keys to "".
• Your "answer" MUST be a single letter whose corresponding option text is NOT empty.
  — NEVER select an option that you set to "".
• "answer_content" MUST be identical to the exact text you placed in options[answer].
• Output ONLY the raw JSON object. Do NOT wrap it in ```json codeblocks.
"""

# ---------------------------------------------------------------------------
# User prompt — kept minimal; the image carries the context
# ---------------------------------------------------------------------------

USER_PROMPT = "Analyze this exam question screenshot. Return ONLY valid JSON."

USER_PROMPT_STITCHED = (
    "This image is a vertically stitched composite of two overlapping captures "
    "(the exam screen was scrolled to reveal more content). Treat it as a single "
    "continuous question. Deduplicate any repeated text or options. "
    "Return ONLY valid JSON."
)


def build_grok_messages(
    image_base64: str,
    ocr_context: str = "",
    is_stitched: bool = False,
) -> list[dict]:
    """
    Build the messages array for the Grok/Gemini Vision API request.

    Args:
        image_base64: Base64-encoded image string.
        ocr_context: Optional raw OCR text to inject as context to stop hallucination.
        is_stitched: True if the image is a multi-frame stitched composite.

    Returns:
        List of message dicts ready for the API payload.
    """
    prompt_text = USER_PROMPT_STITCHED if is_stitched else USER_PROMPT
    user_content = [
        {"type": "text", "text": prompt_text},
    ]

    if ocr_context:
        user_content.append({
            "type": "text",
            "text": f"--- RAW OCR TEXT FROM IMAGE (FOR CONTEXT) ---\n\n{ocr_context}"
        })

    user_content.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{image_base64}",
        },
    })

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]
    logger.debug("Built AI messages (image size: %d chars, stitched: %s)", len(image_base64), is_stitched)
    return messages


def get_grok_response_schema() -> dict:
    """
    Return the response_format setting.

    Due to a known capability bug in some fast models (e.g. grok-4-1-fast-non-reasoning) 
    where strict json_schema decoding breaks vision extraction of nested object fields 
    (resulting in empty option values), we fallback to standard "json_object" mode.
    """
    return {
        "type": "json_object"
    }


# ---------------------------------------------------------------------------
# Focused retry prompt — used when the model read the question but
# returned empty options.  We send the full image PLUS a cropped
# answer-panel image to give the model a zoomed-in view.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_OPTIONS_RETRY = """\
You are an expert exam-question solver. You previously read the question but could not extract the answer options.

You are now given TWO images:
1. FIRST IMAGE: The full exam screenshot (same as before).
2. SECOND IMAGE: A cropped, zoomed-in view of ONLY the RIGHT PANEL (answer options area).

LAYOUT: The answer options are in the RIGHT PANEL. Each option is marked by a round radio circle/bubble. The options are stacked vertically from top to bottom. Focus on the SECOND (cropped) image to read the option texts.

TASK:
1. Extract the full question text from the FIRST image (left panel).
2. Read ALL answer option texts from the SECOND image (the cropped right panel). Look for text next to each radio circle.
3. Map options to letters A, B, C, D, E in order from top to bottom.
4. Determine the correct answer.
5. Return ONLY a valid JSON object.

REQUIRED JSON STRUCTURE:
{
  "question": "<full question text>",
  "options": {
    "A": "<option A text>",
    "B": "<option B text>",
    "C": "<option C text>",
    "D": "<option D text>",
    "E": "<option E text>"
  },
  "answer": "<A/B/C/D/E>",
  "answer_content": "<exact winning option text>"
}

CRITICAL RULES:
• Extract option texts from the SECOND (cropped) image. Even if partially obscured by watermarks, extract what you CAN read. NEVER return empty options if there is ANY text visible near a radio circle.
• If there are fewer than 5 options, set unused keys to "".
• Your "answer" MUST be a single letter with non-empty option text.
• "answer_content" MUST match options[answer] exactly.
• Output ONLY the raw JSON object.
"""


def build_grok_messages_with_panel_crop(
    full_image_base64: str,
    panel_image_base64: str,
    question_text: str = "",
    ocr_context: str = "",
) -> list[dict]:
    """
    Build messages for the options-focused retry attempt.

    Sends both the full exam screenshot and a cropped answer panel image
    so the model gets a zoomed-in view of the option texts.

    Args:
        full_image_base64: Base64-encoded full exam image.
        panel_image_base64: Base64-encoded cropped answer panel image.
        question_text: The question text extracted from the first attempt.
        ocr_context: Optional raw OCR text for context.

    Returns:
        List of message dicts ready for the API payload.
    """
    user_content = [
        {
            "type": "text",
            "text": (
                f"The question from the exam is:\n\"{question_text}\"\n\n"
                "Focus on the SECOND image (cropped answer panel) to read the option texts. "
                "Return ONLY valid JSON."
            ),
        },
    ]

    if ocr_context:
        user_content.append({
            "type": "text",
            "text": f"--- RAW OCR TEXT FROM IMAGE (FOR CONTEXT) ---\n\n{ocr_context}",
        })

    # Full image first
    user_content.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{full_image_base64}",
        },
    })

    # Cropped answer panel second (zoomed in)
    user_content.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{panel_image_base64}",
        },
    })

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT_OPTIONS_RETRY,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]
    logger.debug("Built options-retry messages (full=%d chars, panel=%d chars)",
                 len(full_image_base64), len(panel_image_base64))
    return messages
