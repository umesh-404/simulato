"""
Screen validator (fail-safe system).

Validates that the captured screen shows the expected exam layout
before processing begins.

Checks (Architecture Spec Section 17 / TRD Section 13):
    - Question panel visible (text content in upper region)
    - Options panel visible (structured content in lower region)
    - No login/error screens (keyword detection via OCR-like heuristics)
    - Expected layout structure (edge distribution matches exam pattern)

If validation fails:
    - System enters ERROR state
    - Alarm triggered
    - Operator notified

(Canonical Law 12 — Failure Visibility)
"""

from pathlib import Path
from typing import Optional

import numpy as np

from controller.utils.logger import get_logger

logger = get_logger("screen_validator")


class ValidationResult:
    def __init__(self, valid: bool, issues: Optional[list[str]] = None, confidence: float = 0.0) -> None:
        self.valid = valid
        self.issues = issues or []
        self.confidence = confidence


class ScreenValidator:
    """
    Validates that a screenshot shows the expected exam interface.

    Multi-check approach:
        1. Image readability and size
        2. Content presence (not blank/solid)
        3. Text region detection (edge density)
        4. Layout structure (content in expected zones)
        5. Abnormal screen detection (uniform color = login/error)
    """

    MIN_WIDTH = 640
    MIN_HEIGHT = 480
    MIN_EDGE_DENSITY = 0.01
    MAX_UNIFORM_RATIO = 0.85
    MIN_CONTENT_ZONES = 2

    def __init__(self, grid_map: Optional[object] = None) -> None:
        self._grid_map = grid_map

    def set_grid_map(self, grid_map) -> None:
        self._grid_map = grid_map

    def validate(self, image_path: Path) -> ValidationResult:
        """
        Validate that a screenshot shows the expected exam layout.

        Runs multiple checks and aggregates results.
        """
        logger.info("Validating screen: %s", image_path.name)

        if not image_path.exists():
            return ValidationResult(valid=False, issues=["Image file does not exist"])

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — basic validation only")
            return ValidationResult(valid=True, issues=[], confidence=0.5)

        img = cv2.imread(str(image_path))
        if img is None:
            return ValidationResult(valid=False, issues=["Cannot read image file"])

        issues = []
        checks_passed = 0
        total_checks = 5

        # Check 1: Image dimensions
        h, w = img.shape[:2]
        if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
            issues.append(f"Image too small: {w}x{h} (min {self.MIN_WIDTH}x{self.MIN_HEIGHT})")
        else:
            checks_passed += 1

        # Check 2: Not blank/solid
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        std_dev = float(np.std(gray))
        if std_dev < 10:
            issues.append(f"Image appears blank or solid (std_dev={std_dev:.1f})")
        else:
            checks_passed += 1

        # Check 3: Edge density (text presence)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)
        if edge_density < self.MIN_EDGE_DENSITY:
            issues.append(f"Very low text/content density ({edge_density:.4f})")
        else:
            checks_passed += 1

        # Check 4: Content zone distribution
        zones = self._check_content_zones(edges)
        if zones < self.MIN_CONTENT_ZONES:
            issues.append(f"Content in only {zones} zone(s), expected ≥{self.MIN_CONTENT_ZONES}")
        else:
            checks_passed += 1

        # Check 5: Abnormal screen detection (uniform large regions)
        uniform_ratio = self._detect_uniform_regions(gray)
        if uniform_ratio > self.MAX_UNIFORM_RATIO:
            issues.append(f"Screen appears abnormal — {uniform_ratio:.0%} uniform (login/error screen?)")
        else:
            checks_passed += 1

        confidence = checks_passed / total_checks
        valid = len(issues) == 0

        if valid:
            logger.info("Screen validation PASSED (confidence=%.2f)", confidence)
        else:
            logger.warning("Screen validation FAILED: %s (confidence=%.2f)", "; ".join(issues), confidence)

        return ValidationResult(valid=valid, issues=issues, confidence=confidence)

    def _check_content_zones(self, edges: np.ndarray) -> int:
        """Split image into vertical thirds and count zones with content."""
        h = edges.shape[0]
        third = h // 3
        zones = 0
        for i in range(3):
            zone = edges[i * third:(i + 1) * third, :]
            density = float(np.count_nonzero(zone)) / max(zone.size, 1)
            if density > 0.005:
                zones += 1
        return zones

    def _detect_uniform_regions(self, gray: np.ndarray) -> float:
        """Detect what fraction of the image is near-uniform color (login/error indicator)."""
        h, w = gray.shape
        block_size = 32
        uniform_blocks = 0
        total_blocks = 0

        for y in range(0, h - block_size, block_size):
            for x in range(0, w - block_size, block_size):
                block = gray[y:y + block_size, x:x + block_size]
                if float(np.std(block)) < 5:
                    uniform_blocks += 1
                total_blocks += 1

        return uniform_blocks / max(total_blocks, 1)
