"""
Scroll detector.

Determines whether a captured question requires scrolling
to reveal the full content (question text or options may extend
beyond the visible area).

Detection methods:
    1. Scrollbar presence: detect vertical bar indicators on the right edge
    2. Clipped text at bottom: analyze text density near bottom boundary
    3. Option panel completeness: check if all 4 options are visible

If scrolling is required, the system issues scroll commands
via the Raspberry Pi before capturing additional frames.
"""

from pathlib import Path
from typing import Optional

import numpy as np

from controller.utils.logger import get_logger

logger = get_logger("scroll_detector")


class ScrollDetectionResult:
    def __init__(self, needs_scroll: bool, direction: Optional[str] = None, confidence: float = 0.0) -> None:
        self.needs_scroll = needs_scroll
        self.direction = direction
        self.confidence = confidence


class ScrollDetector:
    """
    Analyzes a screenshot to determine if scrolling is required.

    Uses multiple heuristics:
        - Right-edge scrollbar detection (thin vertical element)
        - Bottom-edge text density (clipped content indicator)
        - Content distribution analysis (text concentrated in top half)
    """

    SCROLLBAR_EDGE_WIDTH = 30
    SCROLLBAR_MIN_HEIGHT_RATIO = 0.3
    SCROLLBAR_COLOR_VARIANCE_THRESHOLD = 20
    BOTTOM_TEXT_DENSITY_THRESHOLD = 0.05
    TEXT_DISTRIBUTION_RATIO = 0.65

    def __init__(self, grid_map: Optional[object] = None) -> None:
        self._grid_map = grid_map

    def set_grid_map(self, grid_map) -> None:
        self._grid_map = grid_map

    def detect(self, image_path: Path) -> ScrollDetectionResult:
        """
        Analyze an image for scroll requirements.

        Returns ScrollDetectionResult with direction 'right' if scrolling needed.
        """
        logger.info("Analyzing scroll requirements for: %s", image_path.name)

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — scroll detection disabled")
            return ScrollDetectionResult(needs_scroll=False)

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return ScrollDetectionResult(needs_scroll=False)

        scores = []

        scrollbar_score = self._detect_scrollbar(img)
        scores.append(("scrollbar", scrollbar_score))

        text_clip_score = self._detect_clipped_text(img)
        scores.append(("text_clip", text_clip_score))

        distribution_score = self._detect_uneven_distribution(img)
        scores.append(("distribution", distribution_score))

        max_score = max(s[1] for s in scores)
        needs_scroll = max_score > 0.5

        if needs_scroll:
            best_indicator = max(scores, key=lambda s: s[1])
            logger.info(
                "Scroll DETECTED: best_indicator=%s (%.2f), all=%s",
                best_indicator[0], best_indicator[1],
                {k: f"{v:.2f}" for k, v in scores},
            )
            return ScrollDetectionResult(
                needs_scroll=True,
                direction="right",
                confidence=max_score,
            )

        logger.debug("No scroll required (max_score=%.2f)", max_score)
        return ScrollDetectionResult(needs_scroll=False, confidence=max_score)

    def _detect_scrollbar(self, img: np.ndarray) -> float:
        """Detect scrollbar on the right edge of the image."""
        import cv2

        h, w = img.shape[:2]
        right_strip = img[:, max(0, w - self.SCROLLBAR_EDGE_WIDTH):w]
        gray = cv2.cvtColor(right_strip, cv2.COLOR_BGR2GRAY)

        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        col_sums = np.sum(binary == 0, axis=1)
        continuous_dark = 0
        max_continuous = 0
        for val in col_sums:
            if val > self.SCROLLBAR_EDGE_WIDTH * 0.3:
                continuous_dark += 1
                max_continuous = max(max_continuous, continuous_dark)
            else:
                continuous_dark = 0

        ratio = max_continuous / max(h, 1)
        if ratio > self.SCROLLBAR_MIN_HEIGHT_RATIO and ratio < 0.9:
            return min(ratio * 1.5, 1.0)
        return ratio * 0.3

    def _detect_clipped_text(self, img: np.ndarray) -> float:
        """Detect if text appears clipped at the bottom of the image."""
        import cv2

        h, w = img.shape[:2]
        bottom_strip = img[int(h * 0.85):h, :]
        gray = cv2.cvtColor(bottom_strip, cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)

        if edge_density > self.BOTTOM_TEXT_DENSITY_THRESHOLD:
            return min(edge_density / (self.BOTTOM_TEXT_DENSITY_THRESHOLD * 2), 1.0)
        return edge_density / self.BOTTOM_TEXT_DENSITY_THRESHOLD * 0.3

    def _detect_uneven_distribution(self, img: np.ndarray) -> float:
        """Detect if content is concentrated in the top portion (suggesting more below)."""
        import cv2

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        h = edges.shape[0]

        top_half = edges[:h // 2, :]
        bottom_half = edges[h // 2:, :]

        top_density = float(np.count_nonzero(top_half)) / max(top_half.size, 1)
        bottom_density = float(np.count_nonzero(bottom_half)) / max(bottom_half.size, 1)

        if top_density > 0 and bottom_density > 0:
            ratio = top_density / (top_density + bottom_density)
            if ratio > self.TEXT_DISTRIBUTION_RATIO:
                return min((ratio - 0.5) * 2, 1.0)
        return 0.0
