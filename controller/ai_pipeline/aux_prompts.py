"""
Simulato task-specific prompts for Local AI (Auxiliary tasks).
"""

# Prompt for verifying if a question requires more scrolling
SCROLL_CHECK_PROMPT = """
You are a screen analyzer for an exam system.
Look at this screenshot of an exam question.
Does the question text or the options list appear to be vertically cut off at the bottom?
Return a JSON object: {"needs_scroll": true/false}
"""

# Prompt for verifying if an option is visually selected (highlighted)
ANSWER_VERIFICATION_PROMPT = """
You are a screen analyzer for an exam system.
Look at this screenshot of an exam question.
Is any of the multiple choice options (A, B, C, D) currently highlighted or selected (look for blue/purple circles or boxes)?
Return a JSON object: {"is_answered": true/false, "selected_letter": "A" or "B" or "C" or "D" or null}
"""

# Prompt for verifying the type of screen
SCREEN_STATE_PROMPT = """
You are a screen analyzer for an exam system.
Identify the current state of the screen.
Return a JSON object: {"screen_type": "QUESTION" or "LOGIN" or "ERROR" or "OTHER"}
"""

# Prompt for finding the NEXT button location in calibrated grid coordinates.
NEXT_BUTTON_PROMPT = """
You are a screen analyzer for an exam system.
Look at this screenshot and locate the NEXT/Next button used to move to the next question.
Return STRICT JSON in this format:
{
  "next_visible": true or false,
  "grid_col": integer 0..19 or null,
  "grid_row": integer 0..19 or null
}
If NEXT is not visible, return next_visible=false and null coordinates.
"""
