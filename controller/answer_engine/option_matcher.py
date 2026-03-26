"""
Option text matcher.

Determines which on-screen option (A/B/C/D) corresponds to the
stored correct answer text.

Uses normalized text comparison (Canonical Law 8 — answer by content,
not position). This handles option shuffling between exam attempts.
"""

import re
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

    # Pass 1.5: Stripped-raw match — compare with only whitespace removed
    # from the raw input (no lowering of math chars like / ^ . - +).
    # This handles short numeric options like "3/2", "1/3" where
    # normalize_text might over-strip.
    raw_answer = re.sub(r"\s+", "", correct_answer_text.strip())
    for letter, text in current_options.items():
        raw_option = re.sub(r"\s+", "", text.strip())
        if raw_answer and raw_option and raw_answer == raw_option:
            logger.info("Raw exact match: %s = '%s'", letter, text[:60])
            return OptionMatchResult(
                matched_letter=letter,
                matched_text=text,
                confidence="exact_raw",
            )
    # Case-insensitive raw match
    raw_answer_lower = raw_answer.lower()
    for letter, text in current_options.items():
        raw_option_lower = re.sub(r"\s+", "", text.strip()).lower()
        if raw_answer_lower and raw_option_lower and raw_answer_lower == raw_option_lower:
            logger.info("Raw case-insensitive match: %s = '%s'", letter, text[:60])
            return OptionMatchResult(
                matched_letter=letter,
                matched_text=text,
                confidence="exact_raw_ci",
            )

    # Pass 1.7: Digit-focused match for numeric options where OCR may
    # confuse similar characters (l/1, O/0, I/1).  Extract only digits and
    # decimal/math symbols, then compare.
    _DIGIT_KEEP = re.compile(r"[^0-9./\-+^]")
    digit_answer = _DIGIT_KEEP.sub("", correct_answer_text.strip())
    if len(digit_answer) >= 2:
        for letter, text in current_options.items():
            digit_option = _DIGIT_KEEP.sub("", text.strip())
            if digit_option and digit_answer == digit_option:
                logger.info("Digit-focused match: %s = '%s'", letter, text[:60])
                return OptionMatchResult(
                    matched_letter=letter,
                    matched_text=text,
                    confidence="digit_exact",
                )

    # Pass 2: Substring containment — only safe for longer strings where a
    # partial overlap is meaningful.  For short numeric options like "3", "2",
    # "3/2" the substring check produces false positives (e.g. "2" in "32").
    # Guard: shorter side must be >= 4 chars and >= 60 % of longer side.
    for letter, text in current_options.items():
        norm_option = normalize_for_matching(text)
        if not norm_option or not norm_answer:
            continue
        shorter_len = min(len(norm_answer), len(norm_option))
        longer_len = max(len(norm_answer), len(norm_option))
        if shorter_len < 4 or shorter_len / longer_len < 0.6:
            continue
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

    logger.warning(
        "No option content match found for: '%s' among options: %s",
        correct_answer_text[:60],
        {k: v[:40] for k, v in current_options.items()},
    )
    return OptionMatchResult(
        matched_letter=None,
        matched_text=None,
        confidence="none",
    )
