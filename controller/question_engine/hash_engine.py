"""
Hash generation engine.

Produces:
    - SHA256 exact hash of canonical text
    - SimHash for fuzzy similarity comparison

Used in staged question lookup (Architecture Spec Section 8).
"""

import hashlib
from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("hash_engine")


def compute_sha256(canonical_text: str) -> str:
    """Compute SHA256 hex digest of the canonical question string."""
    digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    logger.debug("SHA256: %s (input length: %d)", digest[:16] + "...", len(canonical_text))
    return digest


def compute_simhash(canonical_text: str) -> str:
    """
    Compute a SimHash fingerprint for fuzzy matching.

    Uses a simple token-frequency based SimHash.
    Returns hex string representation of the 64-bit fingerprint.
    """
    tokens = canonical_text.split()
    if not tokens:
        return "0" * 16

    vector = [0] * 64
    for token in tokens:
        token_hash = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(64):
            if token_hash & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(64):
        if vector[i] > 0:
            fingerprint |= (1 << i)

    result = f"{fingerprint:016x}"
    logger.debug("SimHash: %s", result)
    return result


def simhash_distance(hash_a: str, hash_b: str) -> int:
    """
    Compute Hamming distance between two SimHash hex strings.
    Lower distance = more similar.
    """
    val_a = int(hash_a, 16)
    val_b = int(hash_b, 16)
    xor = val_a ^ val_b
    return bin(xor).count("1")
