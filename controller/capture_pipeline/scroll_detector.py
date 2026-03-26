"""
Scroll detector (v4) -- structural exam-UI-aware detection.

Determines whether the question panel (left) and/or the answer panel
(right) of the exam screen require scrolling.

Detection approach (v4):
    1.  Isolate the actual exam UI content area by finding the sharp
        brightness transition between white exam background and dark
        photo border.  The phone-captured screenshots have a dark
        bezel/desk region that extends into the panel bounding boxes,
        especially on the right side of the answer panel.
    2.  Within the isolated UI content area, detect a scrollbar as a
        narrow vertical strip (2-8px wide) that is distinctly darker
        than the white background on both sides, spanning a significant
        fraction of the panel height.
    3.  As a secondary heuristic, check for content cutoff at the
        bottom of the exam UI content area using edge density.

Given identical inputs, this module produces identical outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayout, Rect
from controller.utils.logger import get_logger

logger = get_logger("scroll_detector")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PanelScrollResult:
    """Scroll result for a single panel."""
    needs_scroll: bool
    confidence: float
    scrollbar_score: float = 0.0
    cutoff_score: float = 0.0
    method: str = ""          # Which heuristic triggered

    @property
    def reasons(self) -> list[str]:
        """Human-readable list of why scroll was detected."""
        r = []
        if self.scrollbar_score > 0.3:
            r.append(f"scrollbar({self.scrollbar_score:.2f})")
        if self.cutoff_score > 0.3:
            r.append(f"cutoff({self.cutoff_score:.2f})")
        return r


@dataclass
class DualPanelScrollResult:
    """Scroll results for both panels."""
    question: PanelScrollResult
    answer: PanelScrollResult

    @property
    def any_scroll_needed(self) -> bool:
        return self.question.needs_scroll or self.answer.needs_scroll


# Keep old result class for backward compatibility
@dataclass(frozen=True)
class ScrollDetectionResult:
    """Legacy result -- kept for backward compatibility."""
    needs_scroll: bool
    direction: Optional[str] = None
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class ScrollDetector:
    """
    Analyzes a screenshot to determine if scrolling is required
    on the question panel, the answer panel, or both.

    v4: Structural approach that first isolates the exam UI from the
    photo border, then searches for scrollbar within the UI content only.
    """

    # --- Tunable thresholds -------------------------------------------

    # UI boundary detection: a column is "exam UI background" if its
    # mean brightness exceeds this AND its std is below UI_BG_MAX_STD.
    # Exam UI white background: mean ~240-255, std ~5-15.
    # Photo border/bezel: mean ~30-80, std ~25-40.
    # Transition zone (watermarks on white): mean ~170-200, std ~60-70.
    UI_BG_MIN_BRIGHTNESS = 200
    UI_BG_MAX_STD = 40

    # How many consecutive columns must pass the UI bg test to be
    # considered real exam UI (filters out thin bright streaks in borders).
    UI_BG_MIN_RUN = 15

    # Scrollbar detection within the exam UI content area
    # The scrollbar is a thin (2-12px) gray strip on white background.
    # We look for columns where: the column has a significantly darker
    # region (a contiguous vertical run) compared to the median column
    # brightness in the surrounding area.
    SCROLLBAR_SEARCH_MARGIN = 40   # Search within N pixels from the UI right edge
    SCROLLBAR_MIN_WIDTH = 2        # Min width of scrollbar strip in pixels
    SCROLLBAR_MAX_WIDTH = 15       # Max width of scrollbar strip
    SCROLLBAR_RELATIVE_DARK = 40   # Column must be this much darker than neighbors
    SCROLLBAR_MIN_SPAN_FRAC = 0.08 # Min contiguous dark span as fraction of UI height
    SCROLLBAR_MAX_SPAN_FRAC = 0.85 # Max span (reject full-height dark bands)

    # Content cutoff detection
    CUTOFF_BOTTOM_FRAC = 0.10     # Bottom N% of UI content area to analyze
    CUTOFF_EDGE_DENSITY_THRESHOLD = 0.04  # Edge density above this = content cutoff

    # Overall decision threshold
    SCROLL_DECISION_THRESHOLD = 0.40

    def __init__(self, grid_map: Optional[object] = None) -> None:
        self._grid_map = grid_map

    def set_grid_map(self, grid_map: object) -> None:
        self._grid_map = grid_map

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_dual(
        self,
        image_path: Path,
        layout: ExamLayout,
    ) -> DualPanelScrollResult:
        """Detect scroll independently for both panels."""
        logger.info("Dual-panel scroll check for: %s", image_path.name)

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available")
            no_scroll = PanelScrollResult(needs_scroll=False, confidence=0.0)
            return DualPanelScrollResult(question=no_scroll, answer=no_scroll)

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            no_scroll = PanelScrollResult(needs_scroll=False, confidence=0.0)
            return DualPanelScrollResult(question=no_scroll, answer=no_scroll)

        q_result = self._analyze_panel(img, layout.question_panel, "question")
        a_result = self._analyze_panel(img, layout.answer_panel, "answer")

        result = DualPanelScrollResult(question=q_result, answer=a_result)

        logger.info(
            "Scroll result: question=%s (%.2f), answer=%s (%.2f)",
            "SCROLL" if q_result.needs_scroll else "no-scroll",
            q_result.confidence,
            "SCROLL" if a_result.needs_scroll else "no-scroll",
            a_result.confidence,
        )
        return result

    def detect(self, image_path: Path) -> ScrollDetectionResult:
        """Legacy detect method -- backward compatible."""
        logger.info("Legacy scroll check for: %s", image_path.name)

        try:
            import cv2
        except ImportError:
            return ScrollDetectionResult(needs_scroll=False)

        img = cv2.imread(str(image_path))
        if img is None:
            return ScrollDetectionResult(needs_scroll=False)

        h, w = img.shape[:2]
        full_rect = Rect(0, 0, w, h)
        result = self._analyze_panel(img, full_rect, "full")

        if result.needs_scroll:
            return ScrollDetectionResult(
                needs_scroll=True,
                direction="down",
                confidence=result.confidence,
            )
        return ScrollDetectionResult(needs_scroll=False, confidence=result.confidence)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_panel(
        self,
        img: np.ndarray,
        panel: Optional[Rect],
        panel_name: str,
    ) -> PanelScrollResult:
        """Analyze a single panel for scroll indicators."""
        import cv2

        if panel is None:
            return PanelScrollResult(needs_scroll=False, confidence=0.0)

        panel_img = img[panel.y:panel.y2, panel.x:panel.x2]
        if panel_img.size == 0:
            return PanelScrollResult(needs_scroll=False, confidence=0.0)

        p_h, p_w = panel_img.shape[:2]
        gray = cv2.cvtColor(panel_img, cv2.COLOR_BGR2GRAY)

        # Step 1: Find the actual exam UI content boundaries within this panel.
        # The panel bounding box from layout detection may extend into the
        # dark photo border (especially the answer panel, which goes to the
        # right edge of the photo).
        ui_left, ui_right, ui_top, ui_bottom = self._find_ui_bounds(gray, p_h, p_w)

        ui_w = ui_right - ui_left
        ui_h = ui_bottom - ui_top

        logger.debug(
            "Panel '%s' [%dx%d]: UI bounds [%d:%d, %d:%d] = [%dx%d]",
            panel_name, p_w, p_h, ui_left, ui_right, ui_top, ui_bottom, ui_w, ui_h,
        )

        if ui_w < 50 or ui_h < 50:
            logger.debug("Panel '%s': UI content area too small", panel_name)
            return PanelScrollResult(needs_scroll=False, confidence=0.0)

        # Extract the UI content region
        ui_gray = gray[ui_top:ui_bottom, ui_left:ui_right]

        # Step 2: Scrollbar detection within the UI content area
        scrollbar_score = self._detect_scrollbar_structural(ui_gray, ui_h, ui_w)

        # Step 3: Content cutoff detection at bottom of UI content area
        cutoff_score = self._detect_cutoff_structural(ui_gray, ui_h, ui_w, cv2)

        # Combined decision
        max_score = max(scrollbar_score, cutoff_score)
        needs_scroll = max_score > self.SCROLL_DECISION_THRESHOLD

        method = ""
        if needs_scroll:
            if scrollbar_score >= cutoff_score:
                method = "scrollbar"
            else:
                method = "cutoff"

        logger.debug(
            "Panel '%s': scrollbar=%.2f, cutoff=%.2f -> %s",
            panel_name, scrollbar_score, cutoff_score,
            "SCROLL" if needs_scroll else "no-scroll",
        )

        return PanelScrollResult(
            needs_scroll=needs_scroll,
            confidence=max_score,
            scrollbar_score=scrollbar_score,
            cutoff_score=cutoff_score,
            method=method,
        )

    def _find_ui_bounds(
        self,
        gray: np.ndarray,
        p_h: int,
        p_w: int,
    ) -> tuple[int, int, int, int]:
        """
        Find the actual exam UI content region within the panel.

        The phone-captured image includes dark photo borders (laptop bezel,
        desk) around the exam UI.  This function finds where the white
        exam UI background starts and ends.

        Returns (ui_left, ui_right, ui_top, ui_bottom) in panel-local coords.
        """
        # Compute column-level statistics
        col_means = np.mean(gray, axis=0)
        col_stds = np.std(gray, axis=0)

        # A column is "UI background" if it's bright enough and has moderate std.
        # The white background has high mean and low std.
        # Text content on white has high mean but higher std.
        # We consider both as "inside UI" — we want to find the boundary
        # between UI (mean > 200) and photo border (mean < 80).
        #
        # Use a more relaxed threshold: column mean > 130 indicates we are
        # inside the exam UI (even with watermarks/text, mean stays above 130).
        # Photo border columns have mean ~30-80.
        UI_COLUMN_THRESHOLD = 130

        # Find UI left edge: scan from left, find first run of bright columns
        ui_left = 0
        run = 0
        for i in range(p_w):
            if col_means[i] > UI_COLUMN_THRESHOLD:
                run += 1
                if run >= self.UI_BG_MIN_RUN:
                    ui_left = i - self.UI_BG_MIN_RUN + 1
                    break
            else:
                run = 0

        # Find UI right edge: scan from right, find first run of bright columns
        ui_right = p_w
        run = 0
        for i in range(p_w - 1, -1, -1):
            if col_means[i] > UI_COLUMN_THRESHOLD:
                run += 1
                if run >= self.UI_BG_MIN_RUN:
                    ui_right = i + self.UI_BG_MIN_RUN
                    break
            else:
                run = 0

        # Similarly for rows (top/bottom)
        row_means = np.mean(gray, axis=1)

        ui_top = 0
        run = 0
        for i in range(p_h):
            if row_means[i] > UI_COLUMN_THRESHOLD:
                run += 1
                if run >= 10:
                    ui_top = i - 9
                    break
            else:
                run = 0

        ui_bottom = p_h
        run = 0
        for i in range(p_h - 1, -1, -1):
            if row_means[i] > UI_COLUMN_THRESHOLD:
                run += 1
                if run >= 10:
                    ui_bottom = i + 10
                    break
            else:
                run = 0

        # Clamp
        ui_left = max(0, ui_left)
        ui_right = min(p_w, ui_right)
        ui_top = max(0, ui_top)
        ui_bottom = min(p_h, ui_bottom)

        return (ui_left, ui_right, ui_top, ui_bottom)

    def _detect_scrollbar_structural(
        self,
        ui_gray: np.ndarray,
        ui_h: int,
        ui_w: int,
    ) -> float:
        """
        Detect scrollbar within the isolated UI content area.

        In phone-captured exam screenshots, the scrollbar appears as a
        gradual brightness decline in the column-mean profile near the
        right edge of the UI content area.  Because the camera optics
        blur the thin scrollbar across ~30-60 pixels, we cannot look for
        a thin column or V-shaped dip.  Instead we detect:

        1. Profile range: in the rightmost 100 columns of the UI content,
           compute column means across the middle 60% of the panel height.
           Scroll panels show a range > 15 (brightness drops from ~170 to
           ~145 due to the scrollbar track blending into the background).
           No-scroll panels show a range < 10 (flat profile).

        2. Dip-column std: at the column with the lowest mean, compute
           the pixel std.  Scrollbar regions have LOW std (< 15) because
           they are uniform gray.  Text regions have HIGH std (> 25)
           because they mix dark text with bright background.

        Both conditions must be met for a positive scroll detection.
        """
        if ui_w < 50 or ui_h < 50:
            return 0.0

        # Use the middle 60% of the panel height to avoid header/footer.
        mid_start = ui_h // 5
        mid_end = 4 * ui_h // 5
        mid_gray = ui_gray[mid_start:mid_end, :]
        mid_h = mid_end - mid_start

        if mid_h < 30:
            return 0.0

        # Compute column means across the middle band
        col_means = np.mean(mid_gray, axis=0).astype(np.float64)

        # Search the rightmost portion of the UI content
        search_width = min(100, ui_w // 3)
        search_start = max(0, ui_w - search_width)
        profile = col_means[search_start:]
        n = len(profile)

        if n < 15:
            return 0.0

        # Smooth the profile to reduce noise
        kernel_size = min(5, n // 3)
        if kernel_size >= 2:
            kernel = np.ones(kernel_size) / kernel_size
            smoothed = np.convolve(profile, kernel, mode='same')
        else:
            smoothed = profile.copy()

        # Compute profile range (ignore the first and last 3 cols to
        # avoid edge artifacts from UI-to-border transitions)
        edge_margin = 3 if n > 10 else 0
        inner = smoothed[edge_margin:n - edge_margin] if edge_margin > 0 else smoothed
        profile_range = float(np.max(inner)) - float(np.min(inner))

        # Find the column with the minimum brightness in the INNER profile
        # (not the full profile, since the min at the edge is just the
        # UI-to-border gradient, not a scrollbar)
        inner_min_idx = int(np.argmin(inner)) + edge_margin
        inner_min_val = float(smoothed[inner_min_idx])
        max_val = float(np.max(smoothed))

        # Compute column std at the inner minimum location
        # The scrollbar region has low std (uniform gray), text areas
        # have high std (mix of black text and white background)
        dip_col_abs = search_start + inner_min_idx
        if 0 <= dip_col_abs < ui_w:
            dip_col = mid_gray[:, dip_col_abs]
            dip_std = float(np.std(dip_col))
        else:
            dip_std = 999.0

        logger.debug(
            "Scrollbar profile: range=%.1f, inner_min=%.1f (col %d), "
            "max=%.1f, dip_std=%.1f, n=%d",
            profile_range, inner_min_val, search_start + inner_min_idx,
            max_val, dip_std, n,
        )

        # Decision criteria (tuned empirically against 30-image calibration set):
        #   Answer-scroll panels: profile_range 14-27, dip_std 2-15
        #   No-scroll panels:     profile_range 2-8, dip_std 2-40
        #   Key separator: range combined with low std
        RANGE_THRESHOLD = 10.0    # Min range to suspect scrollbar
        STD_THRESHOLD = 20.0      # Max dip-column std for scrollbar

        if profile_range < RANGE_THRESHOLD:
            return 0.0

        if dip_std > STD_THRESHOLD:
            return 0.0

        # Score: combine range strength and std confidence
        # Use smaller denominator to give stronger signal for moderate ranges
        range_score = min((profile_range - RANGE_THRESHOLD) / 12.0, 1.0)
        std_score = max(0.0, 1.0 - dip_std / STD_THRESHOLD)
        score = range_score * (0.3 + 0.7 * std_score)

        # Boost confidence if the profile shows a clear monotonic decline
        # (scrollbar gradient) rather than random fluctuation
        if n >= 10:
            # Check if the second half of the profile is consistently
            # lower than the first half
            first_half_mean = float(np.mean(smoothed[:n // 2]))
            second_half_mean = float(np.mean(smoothed[n // 2:]))
            if first_half_mean > second_half_mean + 5:
                score = min(score * 1.3, 1.0)

        if score > 0.1:
            logger.debug(
                "Scrollbar detected: range=%.1f, dip_std=%.1f, "
                "range_score=%.2f, std_score=%.2f, final=%.2f",
                profile_range, dip_std, range_score, std_score, score,
            )

        return score

    def _detect_cutoff_structural(
        self,
        ui_gray: np.ndarray,
        ui_h: int,
        ui_w: int,
        cv2_module: object,
    ) -> float:
        """
        Detect if content is cut off at the bottom of the UI content area.

        Checks for high edge density near the bottom boundary -- if text
        is clipped mid-line, there will be many horizontal edges right
        at the bottom.
        """
        bottom_h = max(10, int(ui_h * self.CUTOFF_BOTTOM_FRAC))
        bottom_strip = ui_gray[max(0, ui_h - bottom_h):ui_h, :]

        if bottom_strip.size == 0:
            return 0.0

        edges = cv2_module.Canny(bottom_strip, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)

        if edge_density > self.CUTOFF_EDGE_DENSITY_THRESHOLD:
            return min(edge_density / (self.CUTOFF_EDGE_DENSITY_THRESHOLD * 2), 1.0)
        return edge_density / max(self.CUTOFF_EDGE_DENSITY_THRESHOLD, 0.001) * 0.3
