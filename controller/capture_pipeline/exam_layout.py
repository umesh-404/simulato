"""
Exam screen layout detector.

Detects the fixed-layout exam UI structure from a captured screenshot
and returns pixel coordinates for every significant region:

    - Question panel (left)
    - Answer panel (right)
    - Vertical divider between panels
    - Bottom bar (Clear / Prev / Next buttons)
    - Question navigation sidebar (numbered buttons on far left)

The exam uses a split-pane layout with a draggable vertical divider
(a thin line with a '⁞' dot-handle).  The divider position is treated
as FIXED for a given exam session.

Detection strategy:
    1. Convert image to grayscale.
    2. Find the "Answer here" header via template matching / OCR to
       anchor the right-panel origin.
    3. Find the vertical divider using edge + column-projection analysis
       in the expected region (~40-55 % of width).
    4. Find bottom bar by locating "Clear" / "Next" text near the bottom.
    5. Find the nav sidebar as the narrow strip left of the question panel
       that contains numbered colored boxes.

All coordinates are in absolute pixels of the source image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from controller.utils.logger import get_logger

logger = get_logger("exam_layout")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rect:
    """Axis-aligned bounding rectangle in absolute pixels."""
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass
class ExamLayout:
    """Complete layout of the exam screen with all detected regions."""

    # Core panels
    question_panel: Optional[Rect] = None       # Left panel (question text)
    answer_panel: Optional[Rect] = None         # Right panel (answer options)
    divider_x: int = 0                          # X-coordinate of the vertical divider

    # Bottom bar buttons
    bottom_bar: Optional[Rect] = None
    next_button: Optional[Rect] = None
    prev_button: Optional[Rect] = None
    clear_button: Optional[Rect] = None
    is_last_question: bool = False

    # Navigation sidebar (far left numbered buttons)
    nav_sidebar: Optional[Rect] = None

    # Header region (contains exam info, timer, submit button)
    header: Optional[Rect] = None

    # Image dimensions for normalized coordinate conversion
    image_w: int = 0
    image_h: int = 0

    # Detection confidence
    confidence: float = 0.0
    detection_notes: list[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Layout is valid if we found at least the two main panels."""
        return (
            self.question_panel is not None
            and self.answer_panel is not None
            and self.divider_x > 0
        )

    def norm(self, x: int, y: int) -> tuple[float, float]:
        """Convert absolute pixel coords to normalized [0, 1] coords."""
        nx = max(0.0, min(1.0, x / max(1, self.image_w)))
        ny = max(0.0, min(1.0, y / max(1, self.image_h)))
        return (nx, ny)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class ExamLayoutDetector:
    """
    Detects the exam screen layout from a screenshot.

    Tunable thresholds are class-level constants.  Override them for
    calibration by subclassing or mutating the instance.

    Results are cached per image path (deterministic — same image always
    produces the same layout), which eliminates redundant detections when
    multiple subsystems (OCR, scroll, validation) request the layout for
    the same captured frame.
    """

    # Per-path result cache.  Shared across ALL instances so OCRLayoutAnalyzer,
    # ScreenValidator, ScrollDetector, etc. all benefit from a single detection.
    # Max 10 entries to avoid unbounded memory growth.
    _layout_cache: dict[str, "ExamLayout"] = {}
    _CACHE_MAX = 10

    # --- Tunable thresholds -------------------------------------------

    # Divider search region as fraction of image width.
    # We expect the divider at around 40-55 % of image width.
    DIVIDER_SEARCH_LEFT_FRAC = 0.38
    DIVIDER_SEARCH_RIGHT_FRAC = 0.58

    # Minimum vertical span (fraction of image height) for a column
    # to be considered a divider.
    DIVIDER_MIN_SPAN_FRAC = 0.45

    # Header is assumed to occupy the top N% of the image.
    HEADER_HEIGHT_FRAC = 0.12

    # Bottom bar is assumed to occupy the bottom N% of the image.
    BOTTOM_BAR_HEIGHT_FRAC = 0.08

    # Navigation sidebar is assumed to be within the left N% of the image.
    NAV_SIDEBAR_WIDTH_FRAC = 0.10

    # Grayscale intensity range for the divider line (light gray).
    DIVIDER_GRAY_MIN = 150
    DIVIDER_GRAY_MAX = 230

    def detect(self, image_path: Path) -> ExamLayout:
        """
        Analyze an exam screenshot and return the detected layout.

        Results are cached per resolved image path so that multiple
        subsystems requesting the layout for the same frame get an
        instant result (layout detection takes ~1s per call).

        Parameters
        ----------
        image_path : Path
            Path to the screenshot image.

        Returns
        -------
        ExamLayout
            Detected layout with pixel coordinates for all regions.
        """
        cache_key = str(image_path.resolve())

        # Fast path: return cached result
        if cache_key in self._layout_cache:
            cached = self._layout_cache[cache_key]
            logger.debug("Layout cache HIT for %s (divider_x=%d)", image_path.name, cached.divider_x)
            return cached

        logger.info("Detecting exam layout for: %s", image_path.name)

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — layout detection disabled")
            return ExamLayout()

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return ExamLayout()

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        layout = ExamLayout(image_w=w, image_h=h)
        notes: list[str] = []

        # Step 1: Detect header (top bar with exam info + timer)
        header_h = int(h * self.HEADER_HEIGHT_FRAC)
        layout.header = Rect(0, 0, w, header_h)

        # Step 2: Detect bottom bar
        bottom_bar_h = int(h * self.BOTTOM_BAR_HEIGHT_FRAC)
        bottom_bar_y = h - bottom_bar_h
        layout.bottom_bar = Rect(0, bottom_bar_y, w, bottom_bar_h)
        self._detect_bottom_buttons(gray, layout, bottom_bar_y, h, w, color_img=img)

        # Step 3: Detect navigation sidebar
        nav_w = int(w * self.NAV_SIDEBAR_WIDTH_FRAC)
        content_top = header_h
        content_bottom = bottom_bar_y
        layout.nav_sidebar = Rect(0, content_top, nav_w, content_bottom - content_top)

        # Step 4: Detect the vertical divider
        divider_x = self._detect_divider(gray, content_top, content_bottom, nav_w, w)
        if divider_x > 0:
            layout.divider_x = divider_x
            notes.append(f"divider found at x={divider_x}")
        else:
            # Fallback: assume divider at ~46% of width (observed default)
            divider_x = int(w * 0.46)
            layout.divider_x = divider_x
            notes.append(f"divider FALLBACK at x={divider_x}")

        # Step 5: Define the question and answer panels
        panel_top = content_top
        panel_bottom = content_bottom

        layout.question_panel = Rect(
            x=nav_w,
            y=panel_top,
            w=divider_x - nav_w,
            h=panel_bottom - panel_top,
        )

        layout.answer_panel = Rect(
            x=divider_x,
            y=panel_top,
            w=w - divider_x,
            h=panel_bottom - panel_top,
        )

        # Confidence based on whether we found a real divider
        layout.confidence = 0.9 if "divider found" in notes[0] else 0.5
        layout.detection_notes = notes

        logger.info(
            "Layout detected: divider_x=%d, q_panel=%s, a_panel=%s, confidence=%.2f",
            layout.divider_x,
            f"({layout.question_panel.x},{layout.question_panel.y},{layout.question_panel.w},{layout.question_panel.h})"
            if layout.question_panel else "None",
            f"({layout.answer_panel.x},{layout.answer_panel.y},{layout.answer_panel.w},{layout.answer_panel.h})"
            if layout.answer_panel else "None",
            layout.confidence,
        )

        # Cache the result.  Evict oldest entries if cache is full.
        if len(self._layout_cache) >= self._CACHE_MAX:
            oldest_key = next(iter(self._layout_cache))
            del self._layout_cache[oldest_key]
        self._layout_cache[cache_key] = layout

        return layout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_divider(
        self, gray: np.ndarray, content_top: int, content_bottom: int, nav_w: int, img_w: int
    ) -> int:
        """
        Dynamically find the vertical divider between the question and answers.
        1. Limit search to the middle region of the page
        2. Detect strongest vertical edge (Sobel-X)
        3. Check for drag handle dot pattern as fallback
        4. Validate the candidate has a continuous vertical span.
        """
        import cv2

        # Ghost captures are direct screenshots of a CSS split-view.
        # The split has no visible gray border or structural drag-handle dots,
        # but bounding it is strict. Visual scan will falsely trip on text.
        try:
            from controller.config import CAPTURE_MODE
            if CAPTURE_MODE == "ghost":
                return int(img_w * 0.46)
        except Exception:
            pass

        content_region = gray[content_top:content_bottom, :]
        c_h, c_w = content_region.shape[:2]

        search_x1 = max(nav_w, int(img_w * self.DIVIDER_SEARCH_LEFT_FRAC))
        search_x2 = min(c_w, int(img_w * self.DIVIDER_SEARCH_RIGHT_FRAC))

        if search_x2 <= search_x1:
            return 0

        search_strip = content_region[:, search_x1:search_x2]

        # Sobel-X to find vertical edges
        sobel_x = cv2.Sobel(search_strip, cv2.CV_64F, 1, 0, ksize=3)
        sobel_abs = np.abs(sobel_x).astype(np.uint8)

        # Column projection: sum of edge intensity per column
        col_projection = np.sum(sobel_abs, axis=0)

        if len(col_projection) == 0:
            return 0

        # Find the column with the maximum edge projection
        peak_col_local = int(np.argmax(col_projection))
        peak_col_global = search_x1 + peak_col_local

        # Validate: the candidate column should have a long continuous vertical span
        candidate_col = gray[content_top:content_bottom, peak_col_global]
        # The divider line is typically a light gray line
        in_range = (candidate_col >= self.DIVIDER_GRAY_MIN) & (candidate_col <= self.DIVIDER_GRAY_MAX)

        # Find longest continuous run of gray pixels
        longest_run = 0
        current_run = 0
        for val in in_range:
            if val:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0

        span_frac = longest_run / max(c_h, 1)
        if span_frac >= self.DIVIDER_MIN_SPAN_FRAC:
            return peak_col_global

        # Second attempt: look for the drag handle dots (⁞).
        # The drag handle has 6 small dark dots stacked vertically near
        # the center of the divider.  We search for a narrow column region
        # with small, repeating dark blobs roughly centered vertically.
        midpoint_y = c_h // 2
        handle_search = gray[
            content_top + midpoint_y - int(c_h * 0.15):content_top + midpoint_y + int(c_h * 0.15),
            search_x1:search_x2,
        ]

        # Threshold to find dark dots (the drag handle dots are darker than background)
        _, binary = cv2.threshold(handle_search, 140, 255, cv2.THRESH_BINARY_INV)
        col_sums = np.sum(binary > 0, axis=0)

        if len(col_sums) == 0:
            return 0

        # The column with the most dark pixels in the handle region
        handle_peak_local = int(np.argmax(col_sums))
        handle_peak_global = search_x1 + handle_peak_local

        # Only accept if the dot pattern has a minimum density
        if col_sums[handle_peak_local] > int(c_h * 0.03):
            return handle_peak_global

        return 0

    def _detect_bottom_buttons(
        self,
        gray: np.ndarray,
        layout: ExamLayout,
        bar_top: int,
        img_h: int,
        img_w: int,
        color_img: Optional[np.ndarray] = None,
    ) -> None:
        """
        Locate Clear, Prev, and Next buttons in the bottom bar using OCR.

        Falls back to color-based detection, then fixed positions.
        """
        try:
            import pytesseract
            from controller.config import TESSERACT_CMD, OCR_TIMEOUT_SECONDS

            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()

            bar_region = gray[bar_top:img_h, :]
            data = pytesseract.image_to_data(
                bar_region,
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 6",
                timeout=OCR_TIMEOUT_SECONDS,
            )

            n = len(data.get("text", []))
            has_next = False
            has_prev = False
            
            for i in range(n):
                txt = str(data["text"][i]).strip().lower()
                if not txt:
                    continue
                
                # Check for last-question keywords even if confidence is low, 
                # but only trust for buttons if confidence is ok.
                if "next" in txt:
                    has_next = True
                if "prev" in txt:
                    has_prev = True
                    
                conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0
                if conf < 30:
                    continue

                bx = int(data["left"][i])
                by = bar_top + int(data["top"][i])
                bw = max(1, int(data["width"][i]))
                bh = max(1, int(data["height"][i]))

                if "next" in txt:
                    layout.next_button = Rect(bx, by, bw, bh)
                elif "prev" in txt:
                    layout.prev_button = Rect(bx, by, bw, bh)
                elif "clear" in txt:
                    layout.clear_button = Rect(bx, by, bw, bh)

            if has_prev and not has_next:
                layout.is_last_question = True
                logger.info("ExamLayoutDetector: detected last question (Prev but no Next)")

        except Exception as e:
            logger.debug("Bottom button OCR failed, using fallback: %s", e)

        # Color-based button detection fallback before geometric guess.
        if layout.next_button is None and color_img is not None:
            self._detect_next_button_by_color(color_img, layout, bar_top, img_h, img_w)

        # Geometric fallback if all else failed.
        if layout.next_button is None:
            btn_w, btn_h = int(img_w * 0.05), int(img_h * 0.04)
            layout.next_button = Rect(
                img_w - btn_w - int(img_w * 0.02),
                bar_top + int((img_h - bar_top - btn_h) // 2),
                btn_w,
                btn_h,
            )
            logger.debug("Next button geometric fallback: %s", layout.next_button)

        if layout.prev_button is None:
            # Prev button: just left of Next
            if layout.next_button is not None:
                btn_w = layout.next_button.w
                btn_h = layout.next_button.h
                layout.prev_button = Rect(
                    layout.next_button.x - btn_w - int(img_w * 0.01),
                    layout.next_button.y,
                    btn_w,
                    btn_h,
                )

        if layout.clear_button is None:
            # Clear button: bottom-center-left area
            btn_w, btn_h = int(img_w * 0.05), int(img_h * 0.04)
            layout.clear_button = Rect(
                int(img_w * 0.46),
                bar_top + int((img_h - bar_top - btn_h) // 2),
                btn_w,
                btn_h,
            )

    def _detect_next_button_by_color(
        self,
        color_img: np.ndarray,
        layout: ExamLayout,
        bar_top: int,
        img_h: int,
        img_w: int,
    ) -> None:
        """Detect the NEXT button by finding blue/green colored rectangles
        in the bottom bar.  Assigns to layout.next_button / prev_button
        if successful.
        """
        try:
            import cv2

            bar_x1 = int(img_w * 0.50)
            bar_region = color_img[bar_top:img_h, bar_x1:img_w]
            if bar_region.size == 0:
                return
            hsv = cv2.cvtColor(bar_region, cv2.COLOR_BGR2HSV)

            blue_mask = cv2.inRange(hsv, np.array([90, 50, 50]), np.array([130, 255, 255]))
            green_mask = cv2.inRange(hsv, np.array([35, 50, 50]), np.array([85, 255, 255]))
            combined = cv2.bitwise_or(blue_mask, green_mask)

            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 6))
            combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return

            min_area = max(200, int(img_w * 0.02) * int(img_h * 0.015))
            buttons = []
            for c in contours:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bw * bh < min_area or bh < 8 or bw < 15:
                    continue
                abs_x = bar_x1 + bx
                abs_y = bar_top + by
                buttons.append((abs_x, abs_y, bw, bh))

            if not buttons:
                return

            # Sort by X descending — rightmost is "Next", second is "Prev".
            buttons.sort(key=lambda b: b[0], reverse=True)
            nx, ny, nw, nh = buttons[0]
            layout.next_button = Rect(nx, ny, nw, nh)
            logger.debug("NEXT button via color detection: %s", layout.next_button)

            if len(buttons) >= 2 and layout.prev_button is None:
                px, py, pw, ph = buttons[1]
                layout.prev_button = Rect(px, py, pw, ph)
                logger.debug("PREV button via color detection: %s", layout.prev_button)

        except Exception as e:
            logger.debug("Color-based button detection failed: %s", e)
