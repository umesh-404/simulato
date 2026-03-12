"""
Embedding-based semantic similarity engine.

Uses bge-small-en-v1.5 (via sentence-transformers) to compute
dense vector embeddings for question text. Supports cosine
similarity lookup against stored embeddings.

Threshold: cosine_similarity > 0.92 (configurable in config.py).
Used as Stage 3 in the question identification pipeline.
"""

from typing import Optional

import numpy as np

from controller.config import EMBEDDING_MODEL_NAME, EMBEDDING_SIMILARITY_THRESHOLD
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("embedding_matcher")

_model = None


def _get_model():
    """Lazy-load the sentence-transformers model to avoid startup cost."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info("Embedding model loaded")
    return _model


def compute_embedding(text: str) -> np.ndarray:
    """Compute a dense embedding vector for the given text."""
    model = _get_model()
    with ExecutionTimer("compute_embedding"):
        vector = model.encode(text, normalize_embeddings=True)
    return vector


def embedding_to_bytes(vector: np.ndarray) -> bytes:
    """Serialize a numpy float32 vector to bytes for SQLite BLOB storage."""
    return vector.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes from SQLite BLOB back to a numpy float32 vector."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.
    Both vectors are assumed to be L2-normalized (from bge-small-en),
    so dot product equals cosine similarity.
    """
    return float(np.dot(vec_a, vec_b))


def find_best_match(
    query_embedding: np.ndarray,
    candidates: list[dict],
    threshold: Optional[float] = None,
) -> Optional[dict]:
    """
    Find the best embedding match among candidate question records.

    Args:
        query_embedding: The embedding of the new question.
        candidates: List of question dicts, each with 'embedding_vector' (bytes).
        threshold: Minimum cosine similarity. Defaults to config value.

    Returns:
        The best-matching question dict with '_similarity' score added,
        or None if no candidate exceeds the threshold.
    """
    if threshold is None:
        threshold = EMBEDDING_SIMILARITY_THRESHOLD

    best_match = None
    best_score = -1.0

    for candidate in candidates:
        raw = candidate.get("embedding_vector")
        if raw is None:
            continue
        stored_vec = bytes_to_embedding(raw)
        score = cosine_similarity(query_embedding, stored_vec)

        if score > best_score:
            best_score = score
            best_match = candidate

    if best_match is not None and best_score >= threshold:
        result = dict(best_match)
        result["_similarity"] = best_score
        logger.debug(
            "Embedding match found: question_id=%d, similarity=%.4f",
            result["question_id"], best_score,
        )
        return result

    logger.debug("No embedding match above threshold %.4f (best=%.4f)", threshold, best_score)
    return None
