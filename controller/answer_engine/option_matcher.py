"""
Option text matcher.

Determines which on-screen option (A/B/C/D) corresponds to the
stored correct answer text.

Uses normalized text comparison (Canonical Law 8 — answer by content,
not position). This handles option shuffling between exam attempts.
"""

from typing import Optional

from controller.utils.text_normalizer import normalize_for_matching
from controller.utils.logger import get_logger

logger = get_logger("option_matcher")


class OptionMatchResult:
    """Result of matching a correct answer text against current options."""

    def __init__(
        self,
        matched_letter: Optional[str],
        matched_text: Optional[str],
        confidence: str,
    ) -> None:
        self.matched_letter = matched_letter
        self.matched_text = matched_text
        self.confidence = confidence

    @property
    def found(self) -> bool:
        return self.matched_letter is not None


def match_option_by_content(
    correct_answer_text: str,
    current_options: dict[str, str],
) -> OptionMatchResult:
    """
    Find which current option matches the stored correct answer text.

    Args:
        correct_answer_text: The stored correct answer (text content).
        current_options: Dict of letter -> text for current on-screen options.

    Returns:
        OptionMatchResult with the matched letter, or no match.
    """
    norm_answer = normalize_for_matching(correct_answer_text)
    logger.debug("Matching answer text (normalized): '%s'", norm_answer[:60])

    # Pass 1: Exact normalized match
    for letter, text in current_options.items():
        norm_option = normalize_for_matching(text)
        if norm_option == norm_answer:
            logger.info("Exact content match: %s = '%s'", letter, text[:60])
            return OptionMatchResult(
                matched_letter=letter,
                matched_text=text,
                confidence="exact",
            )

    # Pass 2: Substring containment (one contains the other)
    for letter, text in current_options.items():
        norm_option = normalize_for_matching(text)
        if norm_answer in norm_option or norm_option in norm_answer:
            logger.info("Substring content match: %s = '%s'", letter, text[:60])
            return OptionMatchResult(
                matched_letter=letter,
                matched_text=text,
                confidence="substring",
            )

    logger.warning("No option content match found for: '%s'", correct_answer_text[:60])
    return OptionMatchResult(
        matched_letter=None,
        matched_text=None,
        confidence="none",
    )
