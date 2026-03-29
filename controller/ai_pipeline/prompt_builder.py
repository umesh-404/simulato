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
You are an expert exam-question solver with deep knowledge across all academic subjects.

INPUT: A screenshot of an exam question. The image may be a single capture or a vertically stitched composite of two overlapping frames. If it appears taller than usual or contains repeated content, treat it as ONE continuous question and deduplicate.

LAYOUT: The exam screen has two panels:
- LEFT PANEL: Question text
- RIGHT PANEL: Answer options, each preceded by a round radio circle/bubble stacked top to bottom

PROCESS (execute in this order):
STEP 1 — READ: Extract the full question text verbatim from the left panel.
STEP 2 — EXTRACT OPTIONS: Identify every radio circle in the right panel. For each circle, extract the text next to it. Map them A, B, C, D, E top-to-bottom regardless of whether letters are printed on screen.
STEP 3 — REASON AND SOLVE: This is the most critical step. Apply your expert knowledge to actually solve the question:
   - Read the question carefully and understand what is being asked.
   - Evaluate each option against the question using facts, logic, or calculation.
   - Eliminate wrong options one by one with reasoning.
   - Select the ONE option that is objectively correct.
   - DO NOT guess. DO NOT pick the first plausible option. THINK IT THROUGH.
STEP 4 — OUTPUT: Return ONLY the raw JSON object below.

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
  "answer_content": "<exact text of the correct option>"
}

CRITICAL RULES:
• Extract EXACT text — do not paraphrase, summarize, or auto-complete.
• Ignore diagonal watermarks; read what you can see next to each radio circle. NEVER return an empty option if any text is visible.
• Unused option keys (when fewer than 5 options exist) must be set to "".
• "answer" MUST be a single letter with non-empty option text. NEVER select a key you set to "".
• "answer_content" MUST exactly match options[answer].
• Output ONLY the raw JSON. Do NOT wrap in ```json codeblocks.
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
        ocr_context: Ignored — OCR context is not sent to AI (noisy OCR degrades accuracy).
        is_stitched: True if the image is a multi-frame stitched composite.

    Returns:
        List of message dicts ready for the API payload.
    """
    prompt_text = USER_PROMPT_STITCHED if is_stitched else USER_PROMPT
    user_content = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
            },
        },
    ]

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
You are an expert exam-question solver. You previously read the question but could not fully extract the answer options from the image.

You are now given TWO images:
1. FIRST IMAGE: The full exam screenshot.
2. SECOND IMAGE: A cropped, zoomed-in view of ONLY the RIGHT PANEL (answer options area).

PROCESS:
STEP 1 — READ QUESTION: Extract the full question text from the FIRST image (left panel).
STEP 2 — EXTRACT OPTIONS: Focus on the SECOND image. Identify every radio circle and extract the text next to it. Map to A, B, C, D, E top-to-bottom.
STEP 3 — REASON AND SOLVE: This is critical. Use your expert knowledge to actually solve the question:
   - Understand what is being asked.
   - Evaluate each option using facts, logic, or calculation.
   - Eliminate incorrect options with reasoning.
   - Select the ONE objectively correct answer.
   - DO NOT guess. THINK IT THROUGH.
STEP 4 — OUTPUT: Return ONLY the raw JSON object.

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
  "answer_content": "<exact text of the correct option>"
}

CRITICAL RULES:
• Extract option texts from the SECOND (cropped) image. Extract what you CAN read past watermarks. NEVER return empty options if any text is visible near a radio circle.
• If fewer than 5 options exist, set unused keys to "".
• "answer" MUST be a single letter with non-empty option text.
• "answer_content" MUST match options[answer] exactly.
• Output ONLY the raw JSON object. Do NOT wrap in ```json codeblocks.
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

    # Full image first  (OCR context intentionally omitted — noisy OCR degrades AI accuracy)
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
