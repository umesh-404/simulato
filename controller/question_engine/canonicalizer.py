"""
Question canonicalization engine.

Converts raw question text + options into a deterministic canonical form
for hashing and comparison.

Pipeline:
    1. Normalize question text
    2. Normalize each option text
    3. Construct canonical string: "question|optA|optB|optC|optD"

The canonical string is order-dependent on the CONTENT of options
sorted alphabetically, not on their original A/B/C/D position.
This ensures that shuffled options produce the same canonical form
(Canonical Law 8 — answer by content).
"""

from controller.utils.text_normalizer import normalize_text
from controller.utils.logger import get_logger

logger = get_logger("canonicalizer")


def canonicalize_question(question_text: str, options: dict[str, str]) -> str:
    """
    Produce a canonical string from question text and options.

    Args:
        question_text: Raw question text extracted by AI.
        options: Dict mapping letter -> option text, e.g. {"A": "10", "B": "12"}.

    Returns:
        Canonical string in the form:
        "normalized_question|sorted_opt1|sorted_opt2|sorted_opt3|sorted_opt4"
    """
    norm_question = normalize_text(question_text)
    norm_options = sorted(normalize_text(v) for v in options.values())
    canonical = "|".join([norm_question] + norm_options)
    logger.debug("Canonical form: %s", canonical)
    return canonical
