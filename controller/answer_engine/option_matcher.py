"""
Option text matcher.

Determines which on-screen option (A/B/C/D) corresponds to the
stored correct answer text.

Uses normalized text comparison (Canonical Law 8 — answer by content,
not position). This handles option shuffling between exam attempts.
"""

from typing import Optional
from difflib import SequenceMatcher

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

    # Pass 3: Fuzzy similarity (strict gate to avoid wrong remaps).
    # Deterministic tie-break: alphabetical order when scores equal.
    scored: list[tuple[float, str, str]] = []
    for letter in sorted(current_options.keys()):
        text = current_options[letter]
        norm_option = normalize_for_matching(text)
        if not norm_option or not norm_answer:
            continue
        score = SequenceMatcher(None, norm_answer, norm_option).ratio()
        scored.append((score, letter, text))

    if scored:
        scored.sort(key=lambda t: (-t[0], t[1]))
        best_score, best_letter, best_text = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        # Require very strong + unambiguous fuzzy match.
        if best_score >= 0.93 and (best_score - second_score) >= 0.08:
            logger.info(
                "Fuzzy content match: %s (score=%.3f, delta=%.3f) = '%s'",
                best_letter,
                best_score,
                best_score - second_score,
                (best_text or "")[:60],
            )
            return OptionMatchResult(
                matched_letter=best_letter,
                matched_text=best_text,
                confidence="fuzzy",
            )

    logger.warning("No option content match found for: '%s'", correct_answer_text[:60])
    return OptionMatchResult(
        matched_letter=None,
        matched_text=None,
        confidence="none",
    )
