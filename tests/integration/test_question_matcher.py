"""
Integration tests for the question matcher pipeline.

Tests the full 4-stage lookup pipeline:
    Stage 1: SHA256 exact match
    Stage 2: SimHash fuzzy match
    Stage 3: Embedding similarity match
    Stage 4: New question (AI fallback)

Uses an in-memory SQLite database.
"""

import pytest
import tempfile
from pathlib import Path

try:
    import sentence_transformers
    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    _HAS_SENTENCE_TRANSFORMERS = False

from controller.question_engine.question_matcher import (
    match_question,
    MatchSource,
)
from controller.question_engine.embedding_matcher import embedding_to_bytes
from database.db_manager import DatabaseManager

pytestmark = pytest.mark.skipif(
    not _HAS_SENTENCE_TRANSFORMERS,
    reason="sentence-transformers not installed",
)


@pytest.fixture
def db():
    """Create a temporary in-memory database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        manager = DatabaseManager(db_path=db_path)
        yield manager
        manager.close()


@pytest.fixture
def test_id(db):
    """Create a test context and return its ID."""
    test = db.get_or_create_test("integration_test")
    return test["test_id"]


class TestStage1ExactHash:

    def test_exact_match_returns_hash_exact(self, db, test_id):
        """First insert, then lookup the same question — should hit Stage 1."""
        q_text = "What is the capital of France?"
        options = {"A": "Paris", "B": "London", "C": "Berlin", "D": "Madrid"}

        first = match_question(db, test_id, q_text, options)
        assert first.source == MatchSource.AI_NEW

        from controller.question_engine.embedding_matcher import compute_embedding
        db.store_question(
            test_id=test_id,
            canonical_text=first.canonical_text,
            sha256_hash=first.sha256_hash,
            simhash=first.simhash,
            embedding_vector=embedding_to_bytes(first.embedding),
            option_a="Paris", option_b="London",
            option_c="Berlin", option_d="Madrid",
            correct_answer="Paris", answer_letter="A",
        )

        second = match_question(db, test_id, q_text, options)
        assert second.source == MatchSource.HASH_EXACT
        assert second.is_cached
        assert second.correct_answer == "Paris"


class TestStage4NewQuestion:

    def test_new_question_returns_ai_new(self, db, test_id):
        """A question with no match should return AI_NEW."""
        result = match_question(
            db, test_id,
            "What is quantum entanglement?",
            {"A": "A phenomenon", "B": "A theory", "C": "A particle", "D": "A wave"},
        )
        assert result.source == MatchSource.AI_NEW
        assert not result.is_cached
        assert result.question_record is None

    def test_different_questions_are_different(self, db, test_id):
        """Two distinct questions should both be AI_NEW."""
        q1 = match_question(db, test_id, "What is 1+1?",
                            {"A": "1", "B": "2", "C": "3", "D": "4"})
        q2 = match_question(db, test_id, "What is 2+2?",
                            {"A": "2", "B": "3", "C": "4", "D": "5"})
        assert q1.source == MatchSource.AI_NEW
        assert q2.source == MatchSource.AI_NEW
        assert q1.sha256_hash != q2.sha256_hash


class TestCanonicalConsistency:

    def test_shuffled_options_same_canonical(self, db, test_id):
        """Options in different order should produce same canonical form."""
        q = "Which element has symbol O?"
        opts1 = {"A": "Oxygen", "B": "Gold", "C": "Silver", "D": "Iron"}
        opts2 = {"A": "Gold", "B": "Iron", "C": "Oxygen", "D": "Silver"}

        r1 = match_question(db, test_id, q, opts1)
        r2 = match_question(db, test_id, q, opts2)

        assert r1.canonical_text == r2.canonical_text
        assert r1.sha256_hash == r2.sha256_hash

    def test_case_variation_same_hash(self, db, test_id):
        """Case differences should produce the same hash."""
        opts = {"A": "Yes", "B": "No", "C": "Maybe", "D": "Never"}
        opts_upper = {"A": "YES", "B": "NO", "C": "MAYBE", "D": "NEVER"}

        r1 = match_question(db, test_id, "Is this correct?", opts)
        r2 = match_question(db, test_id, "IS THIS CORRECT?", opts_upper)

        assert r1.sha256_hash == r2.sha256_hash


class TestMatchResultProperties:

    def test_ai_new_is_not_cached(self, db, test_id):
        result = match_question(db, test_id, "A new question",
                                {"A": "a", "B": "b", "C": "c", "D": "d"})
        assert not result.is_cached
        assert result.correct_answer is None

    def test_cached_result_has_answer(self, db, test_id):
        q = "Stored question"
        opts = {"A": "opt1", "B": "opt2", "C": "opt3", "D": "opt4"}

        first = match_question(db, test_id, q, opts)
        db.store_question(
            test_id=test_id,
            canonical_text=first.canonical_text,
            sha256_hash=first.sha256_hash,
            simhash=first.simhash,
            embedding_vector=embedding_to_bytes(first.embedding),
            option_a="opt1", option_b="opt2",
            option_c="opt3", option_d="opt4",
            correct_answer="opt1", answer_letter="A",
        )

        second = match_question(db, test_id, q, opts)
        assert second.is_cached
        assert second.correct_answer == "opt1"

    def test_hashes_are_populated(self, db, test_id):
        result = match_question(db, test_id, "Some question",
                                {"A": "a", "B": "b", "C": "c", "D": "d"})
        assert len(result.sha256_hash) == 64
        assert len(result.simhash) == 16
        assert result.embedding is not None
        assert len(result.canonical_text) > 0
