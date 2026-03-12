"""
Question change detector.

Detects when the exam screen has changed to a new question
by comparing consecutive screenshots using perceptual hashing.

Used to determine when the next question is ready for processing
after a CLICK_NEXT command (Architecture Spec Section 17 — Question Change Detection).

Approach:
    1. Crop the question region from both screenshots
    2. Compute perceptual hash (pHash) of each
    3. Compare hash distance
    4. If distance exceeds threshold → new question detected
"""

from pathlib import Path
from typing import Optional

import numpy as np

from controller.utils.logger import get_logger

logger = get_logger("change_detector")


class ChangeDetectionResult:
    def __init__(self, changed: bool, hash_distance: int = 0, confidence: float = 0.0) -> None:
        self.changed = changed
        self.hash_distance = hash_distance
        self.confidence = confidence


class QuestionChangeDetector:
    """
    Detects question changes by comparing perceptual hashes of
    the question region across consecutive screenshots.
    """

    PHASH_CHANGE_THRESHOLD = 10
    QUESTION_REGION_TOP_RATIO = 0.05
    QUESTION_REGION_BOTTOM_RATIO = 0.50
    QUESTION_REGION_LEFT_RATIO = 0.02
    QUESTION_REGION_RIGHT_RATIO = 0.98

    def __init__(self) -> None:
        self._previous_hash: Optional[np.ndarray] = None
        self._previous_path: Optional[Path] = None

    def reset(self) -> None:
        self._previous_hash = None
        self._previous_path = None

    def detect_change(self, image_path: Path) -> ChangeDetectionResult:
        """
        Compare the current screenshot with the previous one.

        Returns ChangeDetectionResult indicating whether the question has changed.
        On first call, always returns changed=True (no previous frame).
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — assuming changed")
            return ChangeDetectionResult(changed=True)

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Cannot read image: %s", image_path)
            return ChangeDetectionResult(changed=True)

        question_region = self._crop_question_region(img)
        current_hash = self._compute_phash(question_region)

        if self._previous_hash is None:
            self._previous_hash = current_hash
            self._previous_path = image_path
            logger.info("First frame — assuming new question")
            return ChangeDetectionResult(changed=True, hash_distance=64, confidence=1.0)

        distance = self._hash_distance(self._previous_hash, current_hash)

        old_hash = self._previous_hash
        self._previous_hash = current_hash
        self._previous_path = image_path

        changed = distance > self.PHASH_CHANGE_THRESHOLD
        confidence = min(distance / (self.PHASH_CHANGE_THRESHOLD * 2), 1.0) if changed else 1.0 - (distance / self.PHASH_CHANGE_THRESHOLD)

        if changed:
            logger.info("Question CHANGED (hash_distance=%d, threshold=%d)", distance, self.PHASH_CHANGE_THRESHOLD)
        else:
            logger.debug("Question unchanged (hash_distance=%d)", distance)

        return ChangeDetectionResult(changed=changed, hash_distance=distance, confidence=confidence)

    def _crop_question_region(self, img: np.ndarray) -> np.ndarray:
        """Crop the question text region from the full screenshot."""
        h, w = img.shape[:2]
        y1 = int(h * self.QUESTION_REGION_TOP_RATIO)
        y2 = int(h * self.QUESTION_REGION_BOTTOM_RATIO)
        x1 = int(w * self.QUESTION_REGION_LEFT_RATIO)
        x2 = int(w * self.QUESTION_REGION_RIGHT_RATIO)
        return img[y1:y2, x1:x2]

    def _compute_phash(self, img: np.ndarray, hash_size: int = 8) -> np.ndarray:
        """
        Compute perceptual hash (pHash) of an image.

        Steps:
            1. Resize to (hash_size*4) x (hash_size*4)
            2. Convert to grayscale
            3. Apply DCT
            4. Take top-left hash_size x hash_size coefficients
            5. Threshold at median
        """
        import cv2

        resized = cv2.resize(img, (hash_size * 4, hash_size * 4))
        if len(resized.shape) == 3:
            resized = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

        dct = cv2.dct(resized.astype(np.float32))
        dct_low = dct[:hash_size, :hash_size]
        median = float(np.median(dct_low))
        return (dct_low > median).astype(np.uint8)

    def _hash_distance(self, hash_a: np.ndarray, hash_b: np.ndarray) -> int:
        """Compute Hamming distance between two perceptual hashes."""
        return int(np.count_nonzero(hash_a != hash_b))
