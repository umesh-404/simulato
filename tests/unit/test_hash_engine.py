"""
Unit tests for the hash generation engine.

Validates:
    - SHA256 determinism and correctness
    - SimHash generation and distance calculation
    - Edge cases (empty strings, single tokens)
"""

import hashlib

import pytest

from controller.question_engine.hash_engine import (
    compute_sha256,
    compute_simhash,
    simhash_distance,
)


class TestSHA256:

    def test_deterministic(self):
        text = "what is 2 plus 2|3|4|5|6"
        assert compute_sha256(text) == compute_sha256(text)

    def test_matches_stdlib(self):
        text = "hello world"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_sha256(text) == expected

    def test_different_inputs_different_hashes(self):
        assert compute_sha256("abc") != compute_sha256("abd")

    def test_empty_string(self):
        result = compute_sha256("")
        assert len(result) == 64

    def test_returns_hex_string(self):
        result = compute_sha256("test")
        assert all(c in "0123456789abcdef" for c in result)
        assert len(result) == 64


class TestSimHash:

    def test_deterministic(self):
        text = "the quick brown fox jumps over the lazy dog"
        assert compute_simhash(text) == compute_simhash(text)

    def test_returns_hex_string(self):
        result = compute_simhash("hello world foo bar")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_similar_texts_small_distance(self):
        t1 = "what is the capital of france"
        t2 = "what is the capital of germany"
        h1 = compute_simhash(t1)
        h2 = compute_simhash(t2)
        dist = simhash_distance(h1, h2)
        assert dist < 20

    def test_different_texts_larger_distance(self):
        t1 = "the weather is nice today and the sun is shining brightly"
        t2 = "quantum mechanics describes the behavior of particles at atomic scale"
        h1 = compute_simhash(t1)
        h2 = compute_simhash(t2)
        dist = simhash_distance(h1, h2)
        assert dist > 5

    def test_empty_string(self):
        result = compute_simhash("")
        assert result == "0" * 16

    def test_single_token(self):
        result = compute_simhash("hello")
        assert len(result) == 16


class TestSimHashDistance:

    def test_identical_hashes_zero_distance(self):
        h = compute_simhash("test string")
        assert simhash_distance(h, h) == 0

    def test_distance_is_symmetric(self):
        h1 = compute_simhash("hello world")
        h2 = compute_simhash("goodbye world")
        assert simhash_distance(h1, h2) == simhash_distance(h2, h1)

    def test_max_distance_is_64(self):
        assert simhash_distance("0000000000000000", "ffffffffffffffff") == 64

    def test_known_distance(self):
        assert simhash_distance("0000000000000000", "0000000000000001") == 1

    def test_non_negative(self):
        h1 = compute_simhash("abc def ghi")
        h2 = compute_simhash("xyz uvw rst")
        assert simhash_distance(h1, h2) >= 0
