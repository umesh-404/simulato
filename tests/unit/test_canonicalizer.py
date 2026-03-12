"""
Unit tests for the question canonicalization engine.

Validates:
    - Deterministic canonical form generation
    - Option order independence (sorted by content, not letter)
    - Normalization consistency
    - Edge cases (empty text, special characters, unicode)
"""

import pytest

from controller.question_engine.canonicalizer import canonicalize_question


class TestCanonicalizeQuestion:

    def test_basic_canonical_form(self):
        question = "What is 2 + 2?"
        options = {"A": "3", "B": "4", "C": "5", "D": "6"}
        result = canonicalize_question(question, options)
        assert "|" in result
        parts = result.split("|")
        assert len(parts) == 5

    def test_deterministic_same_input(self):
        """Same inputs must always produce the same output (Canonical Law 1)."""
        q = "What color is the sky?"
        opts = {"A": "Blue", "B": "Red", "C": "Green", "D": "Yellow"}
        result1 = canonicalize_question(q, opts)
        result2 = canonicalize_question(q, opts)
        assert result1 == result2

    def test_option_order_independence(self):
        """Shuffled options must produce the same canonical form (Canonical Law 8)."""
        q = "Which is largest?"
        opts_original = {"A": "Elephant", "B": "Cat", "C": "Dog", "D": "Ant"}
        opts_shuffled = {"A": "Cat", "B": "Dog", "C": "Ant", "D": "Elephant"}
        assert canonicalize_question(q, opts_original) == canonicalize_question(q, opts_shuffled)

    def test_case_insensitive(self):
        q1 = "WHAT IS THE ANSWER?"
        q2 = "what is the answer?"
        opts = {"A": "YES", "B": "NO", "C": "MAYBE", "D": "NEVER"}
        opts_lower = {"A": "yes", "B": "no", "C": "maybe", "D": "never"}
        assert canonicalize_question(q1, opts) == canonicalize_question(q2, opts_lower)

    def test_whitespace_normalization(self):
        q1 = "What  is   the  answer?"
        q2 = "What is the answer?"
        opts = {"A": "  yes  ", "B": "no", "C": "maybe", "D": "never"}
        opts_clean = {"A": "yes", "B": "no", "C": "maybe", "D": "never"}
        assert canonicalize_question(q1, opts) == canonicalize_question(q2, opts_clean)

    def test_special_characters_removed(self):
        q = "What is the answer? (choose one)"
        opts = {"A": "Yes!", "B": "No.", "C": "Maybe...", "D": "Never!"}
        result = canonicalize_question(q, opts)
        assert "?" not in result
        assert "!" not in result
        assert "." not in result

    def test_empty_question(self):
        q = ""
        opts = {"A": "yes", "B": "no", "C": "maybe", "D": "never"}
        result = canonicalize_question(q, opts)
        assert result.startswith("|") or result == "|".join([""] + sorted(["yes", "no", "maybe", "never"]))

    def test_unicode_normalization(self):
        q1 = "caf\u00e9"
        q2 = "cafe\u0301"
        opts = {"A": "a", "B": "b", "C": "c", "D": "d"}
        assert canonicalize_question(q1, opts) == canonicalize_question(q2, opts)

    def test_numeric_normalization(self):
        q = "What is 007?"
        opts = {"A": "007", "B": "07", "C": "7", "D": "0"}
        result = canonicalize_question(q, opts)
        parts = result.split("|")
        assert "what is 7" == parts[0]

    def test_options_sorted_alphabetically(self):
        """Options are sorted by normalized content, not by letter."""
        q = "Pick one"
        opts = {"A": "Zebra", "B": "Apple", "C": "Mango", "D": "Banana"}
        result = canonicalize_question(q, opts)
        parts = result.split("|")
        option_parts = parts[1:]
        assert option_parts == sorted(option_parts)
