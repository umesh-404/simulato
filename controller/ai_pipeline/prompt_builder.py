"""
Prompt builder for Gemini Vision API.

Constructs the system and user prompts used when sending
exam question images to the AI model.

The AI returns ONLY the answer letter (A-E) in a minimal
JSON object: {"answer": "C"}. This minimises output tokens
for maximum speed.
"""

from controller.utils.logger import get_logger

logger = get_logger("prompt_builder")

# ---------------------------------------------------------------------------
# System prompt — reasoning + letter-only output
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert exam-question solver with deep knowledge across all academic subjects.

INPUT: A screenshot of an exam question. The image may be a single capture or a vertically stitched composite of two overlapping frames. If it appears taller than usual or contains repeated content, treat it as ONE continuous question and deduplicate.

LAYOUT: The exam screen has two panels:
- LEFT PANEL: Question text
- RIGHT PANEL: Answer options, each preceded by a round radio circle/bubble stacked top to bottom. Map them A, B, C, D, E from top to bottom.

PROCESS (execute in this order):
STEP 1 — READ: Read the full question from the left panel and all options from the right panel.
STEP 2 — REASON AND SOLVE: Apply your expert knowledge to solve the question:
   - Understand what is being asked.
   - Evaluate each option using facts, logic, or calculation.
   - Eliminate wrong options one by one.
   - Select the ONE option that is objectively correct.
   - DO NOT guess. THINK IT THROUGH.
STEP 3 — OUTPUT: Return ONLY the raw JSON object with JUST the answer letter.

REQUIRED JSON OUTPUT:
{"answer": "<A/B/C/D/E>"}

CRITICAL RULES:
• "answer" MUST be exactly one letter: A, B, C, D, or E.
• Output ONLY the raw JSON object. No explanations, no markdown, no codeblocks.
"""

# System prompt variant when a cropped answer panel is also provided.
SYSTEM_PROMPT_WITH_PANEL = """\
You are an expert exam-question solver with deep knowledge across all academic subjects.

INPUT: You are given TWO images:
1. FIRST IMAGE — The full exam screenshot with question on the LEFT panel and options on the RIGHT panel.
2. SECOND IMAGE — A zoomed-in crop of ONLY the answer options panel (right side). Use this to read option texts more clearly.

LAYOUT: Options are stacked top to bottom, each preceded by a round radio circle. Map them A, B, C, D, E from top to bottom.

PROCESS (execute in this order):
STEP 1 — READ: Read the question from the FIRST image (left panel). Read option texts from the SECOND image (zoomed answer panel) for maximum clarity.
STEP 2 — REASON AND SOLVE: Apply your expert knowledge to solve the question:
   - Understand what is being asked.
   - Evaluate each option using facts, logic, or calculation.
   - Eliminate wrong options one by one.
   - Select the ONE option that is objectively correct.
   - DO NOT guess. THINK IT THROUGH.
STEP 3 — OUTPUT: Return ONLY the raw JSON object with JUST the answer letter.

REQUIRED JSON OUTPUT:
{"answer": "<A/B/C/D/E>"}

CRITICAL RULES:
• "answer" MUST be exactly one letter: A, B, C, D, or E.
• Output ONLY the raw JSON object. No explanations, no markdown, no codeblocks.
"""

# ---------------------------------------------------------------------------
# User prompt — kept minimal; the image carries the context
# ---------------------------------------------------------------------------

USER_PROMPT = "Solve this exam question. Return ONLY valid JSON with just the answer letter."

USER_PROMPT_STITCHED = (
    "This image is a vertically stitched composite of two overlapping captures "
    "(the exam screen was scrolled to reveal more content). Treat it as a single "
    "continuous question. Deduplicate any repeated text or options. "
    "Return ONLY valid JSON with just the answer letter."
)

USER_PROMPT_WITH_PANEL = (
    "The FIRST image is the full exam screenshot. "
    "The SECOND image is a zoomed-in crop of the answer options panel for easier reading. "
    "Solve the question. Return ONLY valid JSON with just the answer letter."
)


def build_ai_messages(
    image_base64: str,
    ocr_context: str = "",
    is_stitched: bool = False,
    panel_image_base64: str = "",
) -> list[dict]:
    """
    Build the messages array for the Gemini Vision API request.

    Args:
        image_base64: Base64-encoded image string.
        ocr_context: Ignored — kept for call-site compatibility.
        is_stitched: True if the image is a multi-frame stitched composite.
        panel_image_base64: Optional base64-encoded cropped answer panel image.
            When provided, both images are sent in a single call for improved
            option readability (especially through watermarks).

    Returns:
        List of message dicts ready for the API payload.
    """
    # Choose prompt based on whether we have a panel crop
    if panel_image_base64:
        prompt_text = USER_PROMPT_WITH_PANEL
        system_prompt = SYSTEM_PROMPT_WITH_PANEL
    elif is_stitched:
        prompt_text = USER_PROMPT_STITCHED
        system_prompt = SYSTEM_PROMPT
    else:
        prompt_text = USER_PROMPT
        system_prompt = SYSTEM_PROMPT

    user_content = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
            },
        },
    ]

    # Append cropped answer panel as second image
    if panel_image_base64:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{panel_image_base64}",
            },
        })

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]
    logger.debug(
        "Built AI messages (image size: %d chars, stitched: %s, panel_crop: %s)",
        len(image_base64), is_stitched, bool(panel_image_base64),
    )
    return messages


# Backward-compatible alias
build_grok_messages = build_ai_messages
