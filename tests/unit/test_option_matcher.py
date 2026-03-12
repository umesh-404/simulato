"""
Unit tests for the option text matcher.

Validates:
    - Exact content matching (Canonical Law 8)
    - Substring matching
    - No match scenario
    - Case / whitespace insensitivity
    - Matching by content, not position
"""

import pytest

from controller.answer_engine.option_matcher import (
    match_option_by_content,
    OptionMatchResult,
)


class TestExactMatch:

    def test_exact_match_option_a(self):
        result = match_option_by_content("Photosynthesis", {
            "A": "Photosynthesis",
            "B": "Respiration",
            "C": "Osmosis",
            "D": "Diffusion",
        })
        assert result.found
        assert result.matched_letter == "A"
        assert result.confidence == "exact"

    def test_exact_match_option_d(self):
        result = match_option_by_content("Diffusion", {
            "A": "Photosynthesis",
            "B": "Respiration",
            "C": "Osmosis",
            "D": "Diffusion",
        })
        assert result.found
        assert result.matched_letter == "D"

    def test_case_insensitive_match(self):
        result = match_option_by_content("PHOTOSYNTHESIS", {
            "A": "photosynthesis",
            "B": "respiration",
            "C": "osmosis",
            "D": "diffusion",
        })
        assert result.found
        assert result.matched_letter == "A"

    def test_whitespace_insensitive_match(self):
        result = match_option_by_content("  Photo  synthesis  ", {
            "A": "Photosynthesis",
            "B": "Respiration",
            "C": "Osmosis",
            "D": "Diffusion",
        })
        assert result.found
        assert result.matched_letter == "A"


class TestSubstringMatch:

    def test_answer_is_substring_of_option(self):
        result = match_option_by_content("42", {
            "A": "42 meters",
            "B": "15 meters",
            "C": "30 meters",
            "D": "60 meters",
        })
        assert result.found
        assert result.matched_letter == "A"
        assert result.confidence == "substring"

    def test_option_is_substring_of_answer(self):
        result = match_option_by_content("The answer is 42 meters per second", {
            "A": "42 meters per second",
            "B": "15 meters per second",
            "C": "30 meters per second",
            "D": "60 meters per second",
        })
        assert result.found
        assert result.matched_letter == "A"


class TestNoMatch:

    def test_no_match_returns_none(self):
        result = match_option_by_content("Magnetism", {
            "A": "Photosynthesis",
            "B": "Respiration",
            "C": "Osmosis",
            "D": "Diffusion",
        })
        assert not result.found
        assert result.matched_letter is None
        assert result.confidence == "none"


class TestContentNotPosition:
    """Verify that matching uses text content, not option letter (Canonical Law 8)."""

    def test_shuffled_options_same_answer(self):
        answer_text = "Oxygen"
        opts_v1 = {"A": "Oxygen", "B": "Nitrogen", "C": "Carbon", "D": "Hydrogen"}
        opts_v2 = {"A": "Carbon", "B": "Hydrogen", "C": "Nitrogen", "D": "Oxygen"}

        r1 = match_option_by_content(answer_text, opts_v1)
        r2 = match_option_by_content(answer_text, opts_v2)

        assert r1.found and r2.found
        assert r1.matched_letter == "A"
        assert r2.matched_letter == "D"
        assert r1.matched_text == r2.matched_text == "Oxygen"

    def test_never_relies_on_letter(self):
        result = match_option_by_content("Nitrogen", {
            "A": "Oxygen",
            "B": "Nitrogen",
            "C": "Carbon",
            "D": "Hydrogen",
        })
        assert result.matched_letter == "B"
        assert result.matched_text == "Nitrogen"
