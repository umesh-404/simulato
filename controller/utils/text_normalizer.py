"""
Text normalization utilities.

Used by the canonicalizer and option matcher to produce
deterministic, comparable text representations.
"""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison.

    Steps:
        1. Unicode NFC normalization
        2. Lowercase
        3. Strip leading/trailing whitespace
        4. Collapse internal whitespace to single spaces
        5. Remove non-alphanumeric characters except spaces
        6. Normalize numeric formats (remove leading zeros)
    """
    text = unicodedata.normalize("NFC", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\b0+(\d)", r"\1", text)
    return text.strip()


def normalize_for_matching(text: str) -> str:
    """
    Aggressive normalization for option-text matching.
    Removes ALL whitespace so that trivial formatting differences
    don't prevent content matches (Canonical Law 8).
    """
    base = normalize_text(text)
    return re.sub(r"\s", "", base)
