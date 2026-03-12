"""
Question matcher — staged lookup engine.

Implements the four-stage question identification pipeline
(Architecture Spec Section 8):

    Stage 1: SHA256 exact hash match
    Stage 2: SimHash similarity
    Stage 3: Embedding similarity (cosine > threshold)
    Stage 4: AI query fallback (no local match)

All lookups are scoped to the active test context.
"""

from enum import Enum
from typing import Optional

import numpy as np

from controller.config import SIMHASH_MAX_DISTANCE
from controller.question_engine.canonicalizer import canonicalize_question
from controller.question_engine.hash_engine import compute_sha256, compute_simhash
from controller.question_engine.embedding_matcher import (
    compute_embedding,
    embedding_to_bytes,
    find_best_match,
)
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer
from database.db_manager import DatabaseManager

logger = get_logger("question_matcher")


class MatchSource(str, Enum):
    HASH_EXACT = "hash_exact"
    SIMHASH = "simhash"
    EMBEDDING = "embedding"
    AI_NEW = "ai_new"


class MatchResult:
    """Encapsulates the outcome of a question lookup."""

    def __init__(
        self,
        source: MatchSource,
        question_record: Optional[dict],
        canonical_text: str,
        sha256_hash: str,
        simhash: str,
        embedding: np.ndarray,
    ) -> None:
        self.source = source
        self.question_record = question_record
        self.canonical_text = canonical_text
        self.sha256_hash = sha256_hash
        self.simhash = simhash
        self.embedding = embedding

    @property
    def is_cached(self) -> bool:
        return self.source != MatchSource.AI_NEW

    @property
    def correct_answer(self) -> Optional[str]:
        if self.question_record:
            return self.question_record.get("correct_answer")
        return None


def match_question(
    db: DatabaseManager,
    test_id: int,
    question_text: str,
    options: dict[str, str],
) -> MatchResult:
    """
    Run the staged lookup pipeline for a question.

    Args:
        db: Database manager instance.
        test_id: Active test context ID.
        question_text: Raw question text from AI extraction.
        options: Dict of option letter -> option text.

    Returns:
        MatchResult indicating the lookup outcome and source.
    """
    with ExecutionTimer("question_match_pipeline"):
        canonical = canonicalize_question(question_text, options)
        sha256 = compute_sha256(canonical)
        sim = compute_simhash(canonical)

        # Stage 1: Exact hash
        logger.info("Stage 1: SHA256 exact lookup (test_id=%d)", test_id)
        exact = db.lookup_by_hash(test_id, sha256)
        if exact:
            logger.info("Stage 1 HIT: question_id=%d", exact["question_id"])
            embedding = compute_embedding(canonical)
            return MatchResult(
                source=MatchSource.HASH_EXACT,
                question_record=exact,
                canonical_text=canonical,
                sha256_hash=sha256,
                simhash=sim,
                embedding=embedding,
            )

        # Stage 2: SimHash similarity
        logger.info("Stage 2: SimHash fuzzy lookup (max_distance=%d)", SIMHASH_MAX_DISTANCE)
        sim_matches = db.lookup_by_simhash(test_id, sim, SIMHASH_MAX_DISTANCE)
        if sim_matches:
            best = sim_matches[0]
            logger.info(
                "Stage 2 HIT: question_id=%d, distance=%d",
                best["question_id"], best["_simhash_distance"],
            )
            embedding = compute_embedding(canonical)
            return MatchResult(
                source=MatchSource.SIMHASH,
                question_record=best,
                canonical_text=canonical,
                sha256_hash=sha256,
                simhash=sim,
                embedding=embedding,
            )

        # Stage 3: Embedding similarity
        logger.info("Stage 3: Embedding similarity search")
        embedding = compute_embedding(canonical)
        all_questions = db.get_all_questions_for_test(test_id)
        emb_match = find_best_match(embedding, all_questions)
        if emb_match:
            logger.info(
                "Stage 3 HIT: question_id=%d, similarity=%.4f",
                emb_match["question_id"], emb_match["_similarity"],
            )
            return MatchResult(
                source=MatchSource.EMBEDDING,
                question_record=emb_match,
                canonical_text=canonical,
                sha256_hash=sha256,
                simhash=sim,
                embedding=embedding,
            )

        # Stage 4: No match — this is a new question
        logger.info("Stage 4: No local match found — question is new")
        return MatchResult(
            source=MatchSource.AI_NEW,
            question_record=None,
            canonical_text=canonical,
            sha256_hash=sha256,
            simhash=sim,
            embedding=embedding,
        )
