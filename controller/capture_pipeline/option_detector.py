"""
Option detector for exam answer panel (v3 — crop-first approach).

Given the answer panel sub-image (right pane of the exam screen),
detects individual answer options by:

    1. Cropping the answer panel from the full image.
    2. Removing the fixed "Answer here" header zone geometrically.
    3. Running HoughCircles on a left-edge strip of the options zone.
    4. Clustering circle candidates by Y → one cluster per radio row.
    5. Sorting top-to-bottom → assigning A, B, C, D, E.
    6. OCR on the text region to the right of each radio button.

The header is removed by cropping, not by post-hoc filtering.
If we detect N circles, we have N options. No recovery or synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayout, Rect
from controller.utils.logger import get_logger

logger = get_logger("option_detector")

OPTION_LABELS = ["A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectedOption:
    """A single detected answer option."""
    label: str
    text: str
    circle_x: int
    circle_y: int
    circle_r: int
    click_x: int
    click_y: int
    bounds: Rect
    text_confidence: float = 0.0


@dataclass
class OptionMap:
    """Complete map of all detected options on the answer panel."""
    options: list[DetectedOption]
    panel_bounds: Optional[Rect] = None
    detection_method: str = ""
    image_w: int = 0
    image_h: int = 0
    debug_meta: dict | None = None

    @property
    def count(self) -> int:
        return len(self.options)

    def get(self, label: str) -> Optional[DetectedOption]:
        """Get option by label (e.g., 'A', 'B')."""
        label = label.strip().upper()
        for opt in self.options:
            if opt.label == label:
                return opt
        return None

    def norm(self, x: int, y: int) -> tuple[float, float]:
        """Convert absolute pixel coords to normalized [0, 1] coords.

        Uses (dimension - 1) as denominator to match the click pipeline:
        OCRLayoutResult._norm and ClickDispatcher._absolute_for_normalized
        both use this convention so pixel 0 maps to 0.0 and the last pixel
        maps to 1.0.
        """
        nx = max(0.0, min(1.0, float(x) / float(max(1, self.image_w - 1))))
        ny = max(0.0, min(1.0, float(y) / float(max(1, self.image_h - 1))))
        return (nx, ny)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class OptionDetector:
    """
    Detects answer options in the right panel of the exam screen.

    Uses a crop-first strategy: isolate the options zone by removing the
    header geometrically, then detect radio circles in the clean crop.
    """

    # Header skip: fraction of answer panel height occupied by the
    # "Answer here" header and the shared top bar (Internet Status,
    # student name, etc.).  The answer panel Rect starts at the same
    # Y as the question panel, so the top ~25% is all header/chrome.
    HEADER_SKIP_FRAC = 0.28
    HEADER_SKIP_MIN_FRAC = 0.15
    HEADER_SKIP_MAX_FRAC = 0.38

    # Bottom margin: fraction of answer panel to skip (footer buttons).
    # The footer contains Clear/Prev/Next buttons whose circular shapes
    # can be misdetected as radio buttons (e.g. Clear button at y=2536).
    # 12% excludes the footer bar while keeping option D/E visible.
    BOTTOM_SKIP_FRAC = 0.12

    # Radio strip: left portion of the answer panel where circles live.
    # On wider panels (divider further left), the radio circles can be
    # 150-200px from the panel edge. Use 300px max to cover all layouts.
    # The X-column filter later discards text-circle noise from the
    # wider area, keeping only the radio-button column.
    RADIO_STRIP_WIDTH_FRAC = 0.25
    RADIO_STRIP_MAX_PX = 300

    # Primary HoughCircles parameters.
    HOUGH_DP = 1.2
    HOUGH_MIN_DIST = 20
    HOUGH_PARAM1 = 80
    HOUGH_PARAM2 = 15
    HOUGH_MIN_RADIUS = 5
    HOUGH_MAX_RADIUS = 30

    # Fallback (relaxed) HoughCircles parameters.
    HOUGH_FALLBACK_DP = 1.0
    HOUGH_FALLBACK_MIN_DIST = 12
    HOUGH_FALLBACK_PARAM1 = 50
    HOUGH_FALLBACK_PARAM2 = 8
    HOUGH_FALLBACK_MIN_RADIUS = 3
    HOUGH_FALLBACK_MAX_RADIUS = 35

    # Y-clustering gap: circles within this vertical distance are one row.
    # Real radio buttons are typically 150-200px apart on a 3072px image.
    # This gap must be large enough to merge noise near a real circle,
    # but small enough to keep separate options distinct.
    Y_CLUSTER_GAP = 75

    # Min circles in a cluster to count as a real row.
    MIN_CLUSTER_SIZE = 1

    MAX_EXPECTED_OPTIONS = 5

    # --- Post-detection validation thresholds ---

    # Radius consistency: reject circles whose radius differs from the
    # median by more than this factor (e.g. 2.0 means allow [median/2, median*2]).
    RADIUS_TOLERANCE_FACTOR = 2.5

    # X-alignment: reject clusters whose center_x differs from the
    # median cluster X by more than this many pixels.
    X_ALIGNMENT_MAX_DEVIATION_PX = 40

    # Spacing regularity: reject outlier clusters where the gap to
    # the nearest neighbour is < MIN_RATIO or > MAX_RATIO of the median gap.
    # Relaxed ratios to handle non-uniform option heights.
    # Multi-line answers can create 2.5x+ normal spacing between rows.
    SPACING_MIN_RATIO = 0.25
    SPACING_MAX_RATIO = 3.0

    # OCR text crop starts this many pixels right of the circle edge.
    TEXT_OFFSET_X_PX = 20

    # --- Ghost-mode specific HoughCircles parameters ---
    # Ghost captures are pixel-perfect 1920x1080 screenshots via DXGI.
    # Radio circles are thin, low-contrast, r=5–7px.  Smaller blur kernel,
    # lower accumulator threshold, tighter radius range.
    GHOST_HOUGH_DP = 1.0
    GHOST_HOUGH_MIN_DIST = 50
    GHOST_HOUGH_PARAM1 = 50
    GHOST_HOUGH_PARAM2 = 8
    GHOST_HOUGH_MIN_RADIUS = 3
    GHOST_HOUGH_MAX_RADIUS = 12
    GHOST_BLUR_KERNEL = (5, 5)
    GHOST_BLUR_SIGMA = 1.5
    # In ghost mode the header is much smaller relative to the panel.
    # The "Answer here" text ends ~70px below panel top, options start ~100px.
    GHOST_HEADER_SKIP_FRAC = 0.08

    def _is_ghost_mode(self) -> bool:
        """Check if the system is running in ghost capture mode."""
        try:
            from controller.config import CAPTURE_MODE
            return CAPTURE_MODE == "ghost"
        except Exception:
            return False

    def detect(
        self,
        image_path: Path,
        layout: ExamLayout,
        max_options: int | None = None,
    ) -> OptionMap:
        """
        Detect option radio buttons and their text in the answer panel.

        Strategy: crop to the options zone (below the fixed header),
        detect circles, cluster, label, OCR.

        In ghost mode (pixel-perfect screenshots), uses tuned parameters
        for thin, low-contrast radio circles and skips the edge quality
        filter (no camera noise to reject).
        """
        logger.info("Detecting options for: %s", image_path.name)
        ghost_mode = self._is_ghost_mode()

        empty = lambda: OptionMap(
            options=[], image_w=layout.image_w, image_h=layout.image_h
        )

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available")
            return empty()

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return empty()

        if layout.answer_panel is None:
            logger.warning("No answer panel in layout")
            return empty()

        ap = layout.answer_panel
        img_h, img_w = img.shape[:2]

        # ------------------------------------------------------------------
        # Step 1: Determine the options zone by removing the header.
        # ------------------------------------------------------------------
        if ghost_mode:
            # Ghost mode: use a much smaller header skip.  The "Answer here"
            # header is compact on the 1080p screen; the large fractional
            # skip designed for phone photos eats the first option row.
            header_bottom_y = ap.y + max(1, int(ap.h * self.GHOST_HEADER_SKIP_FRAC))
            logger.info("Ghost mode: header_bottom_y=%d (%.0f%% of panel)",
                        header_bottom_y, self.GHOST_HEADER_SKIP_FRAC * 100)
        else:
            header_bottom_y = self._determine_header_bottom(img, ap)
        footer_top_y = ap.y2 - max(1, int(ap.h * self.BOTTOM_SKIP_FRAC))

        options_y1 = max(ap.y, min(header_bottom_y, footer_top_y - 1))
        options_y2 = min(ap.y2, footer_top_y)

        logger.info(
            "Options zone: Y=[%d, %d] within panel Y=[%d, %d] (header_bottom=%d)",
            options_y1, options_y2, ap.y, ap.y2, header_bottom_y,
        )

        if options_y2 - options_y1 < 50:
            logger.warning("Options zone too small (%d px)", options_y2 - options_y1)
            return OptionMap(
                options=[], panel_bounds=ap, detection_method="none",
                image_w=img_w, image_h=img_h,
            )

        # ------------------------------------------------------------------
        # Step 2: Detect radio circles in a left strip of the options zone.
        # ------------------------------------------------------------------
        if ghost_mode:
            # Ghost mode: use a narrow 100px strip — radio buttons are at
            # a known fixed X column (~11px from panel edge).  The narrow
            # strip avoids picking up text circles further right.
            strip_w = 100
        else:
            strip_w = max(
                min(int(ap.w * self.RADIO_STRIP_WIDTH_FRAC), self.RADIO_STRIP_MAX_PX),
                40,
            )
            # Ensure the strip covers at least 15% of the panel width,
            # which is enough to capture the radio button column even
            # on wider answer panels where buttons are further indented.
            strip_w = max(strip_w, int(ap.w * 0.15))
        strip_x1 = ap.x
        strip_x2 = min(ap.x2, ap.x + strip_w)

        strip_img = img[options_y1:options_y2, strip_x1:strip_x2]
        if strip_img.size == 0:
            logger.warning("Empty radio strip crop")
            return OptionMap(
                options=[], panel_bounds=ap, detection_method="none",
                image_w=img_w, image_h=img_h,
            )

        gray = cv2.cvtColor(strip_img, cv2.COLOR_BGR2GRAY)

        if ghost_mode:
            # Ghost mode: smaller Gaussian kernel for thin circles.
            blurred = cv2.GaussianBlur(gray, self.GHOST_BLUR_KERNEL, self.GHOST_BLUR_SIGMA)
            circles = self._find_circles_ghost(cv2, blurred)
        else:
            blurred = cv2.GaussianBlur(gray, (9, 9), 2)
            circles = self._find_circles(cv2, blurred)

        if circles is None or len(circles) == 0:
            logger.warning("No radio circles detected in options zone")
            return OptionMap(
                options=[], panel_bounds=ap, detection_method="none",
                image_w=img_w, image_h=img_h,
                debug_meta={
                    "strip_x1": strip_x1, "strip_x2": strip_x2,
                    "options_y1": options_y1, "options_y2": options_y2,
                    "raw_candidates": 0,
                },
            )

        raw_count = len(circles)

        # Layer 1: Radius consistency — reject circles with outlier radii.
        circles = self._filter_by_radius(circles)
        after_radius = len(circles)

        if ghost_mode:
            # Ghost mode: skip edge quality filter.  Ghost screenshots
            # are pixel-perfect with no camera noise; the thin, clean
            # radio circles have low contrast by design and the edge
            # filter incorrectly rejects them.
            after_edge = after_radius
            logger.debug("Ghost mode: edge quality filter skipped")
        else:
            # Layer 1b: Edge quality — reject circles without clear radio-button edges.
            circles = self._filter_by_edge_quality(circles, gray)
            after_edge = len(circles)

        # Layer 1c: X-column filter — identify the radio button column and
        # discard circles that are too far from it. Radio buttons sit in a
        # narrow vertical band. Watermark/text circles scatter across X.
        circles = self._filter_by_x_column(circles, strip_w)
        after_x_col = len(circles)

        # Convert circle coords from strip-local to absolute image coords.
        abs_circles = [
            (strip_x1 + int(cx), options_y1 + int(cy), int(cr))
            for cx, cy, cr in circles
        ]

        # Cluster by Y with the base gap (not adaptive — the X-column
        # filter already removed the watermark chains that caused merging).
        clusters = self._cluster_by_y(abs_circles, gap=self.Y_CLUSTER_GAP)
        clusters.sort(key=lambda c: c["center_y"])
        cluster_count_raw = len(clusters)

        # Layer 2: X-alignment — reject clusters misaligned horizontally.
        clusters = self._filter_clusters_by_x_alignment(clusters)

        # Layer 3: Spacing regularity — reject outlier phantom clusters.
        clusters = self._filter_clusters_by_spacing(clusters)

        # Cap to max options (final safety net).
        effective_max = max_options if max_options is not None else self.MAX_EXPECTED_OPTIONS
        if len(clusters) > effective_max:
            clusters = self._trim_to_count(clusters, effective_max)

        logger.info(
            "%d raw > %d radius > %d edge > %d x-col > %d clusters > "
            "%d validated (cap %d)%s",
            raw_count, after_radius, after_edge, after_x_col,
            cluster_count_raw, len(clusters), effective_max,
            " [ghost]" if ghost_mode else "",
        )

        # ------------------------------------------------------------------
        # Step 3: Estimate label offset for missed top options.
        # ------------------------------------------------------------------
        # When HoughCircles misses option A's circle (e.g. due to contrast),
        # the first detected circle is actually option B. Without correction,
        # every label shifts down by one, causing clicks to land one option
        # below the intended target.
        #
        # Detection: if the gap from header_bottom to the first detected
        # circle is significantly larger than the median inter-option step,
        # it means one or more options are missing above.
        #
        # Example (live capture bug):
        #   header_bottom=1056, first_circle=1446, step=203
        #   gap=390, gap/step=1.92 → 1 option missing → label_offset=1
        #   Labels shift: A→B, B→C (correct mapping)
        #
        # Example (test images, working correctly):
        #   header_bottom=1032, first_circle=1172, step=260
        #   gap=140, gap/step=0.54 → 0 missing → label_offset=0
        #   Labels unchanged: A, B, C, D (correct)
        # ------------------------------------------------------------------
        label_offset = 0
        if len(clusters) >= 2:
            ys = [c["center_y"] for c in clusters]
            steps = [ys[j + 1] - ys[j] for j in range(len(ys) - 1)]
            median_step = sorted(steps)[len(steps) // 2]
            if median_step > 30:
                top_gap = ys[0] - header_bottom_y
                if top_gap > 0:
                    # int(ratio - 0.3) gives 0 when ratio < 1.3 (no missing),
                    # 1 when ratio is ~1.3–2.3 (1 missing), etc.
                    label_offset = max(0, int(top_gap / median_step - 0.3))
                    label_offset = min(label_offset, 2)  # Safety cap
                    if label_offset > 0:
                        logger.info(
                            "Label offset=%d: top_gap=%d, median_step=%d (%.1fx) "
                            "— %d option(s) likely missed above first detected circle",
                            label_offset, top_gap, median_step,
                            top_gap / median_step, label_offset,
                        )

        # ------------------------------------------------------------------
        # Step 4: Build options — OCR text, assign labels, set click coords.
        # ------------------------------------------------------------------
        options: list[DetectedOption] = []

        for i, cluster in enumerate(clusters):
            label_idx = i + label_offset
            if label_idx >= len(OPTION_LABELS):
                break

            label = OPTION_LABELS[label_idx]
            cx = cluster["center_x"]
            cy = cluster["center_y"]
            cr = cluster["median_r"]

            row_top, row_bottom = self._compute_option_row(
                i, clusters, ap.h, cy - ap.y,
            )
            row_top_abs = ap.y + row_top
            row_bottom_abs = ap.y + row_bottom

            text_x1 = cx + cr + self.TEXT_OFFSET_X_PX
            text_x2 = min(ap.x2, text_x1 + min(int(ap.w * 0.70), 600))
            pad_y = 10
            crop_y1 = max(0, row_top_abs - pad_y)
            crop_y2 = min(img_h, row_bottom_abs + pad_y)
            text_region = img[crop_y1:crop_y2, text_x1:text_x2]

            text, text_conf = self._ocr_text(text_region)

            option_bounds = Rect(
                x=ap.x, y=row_top_abs,
                w=ap.w, h=row_bottom_abs - row_top_abs,
            )

            options.append(DetectedOption(
                label=label,
                text=text,
                circle_x=cx,
                circle_y=cy,
                circle_r=cr,
                click_x=cx,
                click_y=cy,
                bounds=option_bounds,
                text_confidence=text_conf,
            ))

            logger.info(
                "Option %s: circle=(%d,%d) r=%d click=(%d,%d) text='%s' conf=%.1f",
                label, cx, cy, cr, cx, cy,
                text[:60] if text else "", text_conf,
            )

        method = "crop_and_detect" if options else "none"
        logger.info("Detected %d options via %s (%d raw candidates)",
                     len(options), method, raw_count)

        return OptionMap(
            options=options,
            panel_bounds=ap,
            detection_method=method,
            image_w=img_w,
            image_h=img_h,
            debug_meta={
                "strip_x1": strip_x1,
                "strip_x2": strip_x2,
                "options_y1": options_y1,
                "options_y2": options_y2,
                "header_bottom": header_bottom_y,
                "raw_candidates_count": raw_count,
                "after_radius_filter": after_radius,
                "after_edge_filter": after_edge,
                "after_x_column_filter": after_x_col,
                "clusters_before_validation": cluster_count_raw,
                "cluster_count": len(clusters),
            },
        )

    # ------------------------------------------------------------------
    # Header detection
    # ------------------------------------------------------------------

    def _determine_header_bottom(self, img: np.ndarray, ap: Rect) -> int:
        """Find where the header ends and options begin.

        Two-phase approach:
          1. OCR scan for "Answer here" in the top 30% of the panel.
             Accept only if the match is in the top 30% (reject false
             positives from option text containing "answer").
          2. Brightness-band detection: scan downward from the OCR
             anchor (or from the fractional fallback) to find the
             first option-band boundary — the point where alternating
             white/gray option rows begin.
          3. Clamp to [HEADER_SKIP_MIN_FRAC, HEADER_SKIP_MAX_FRAC].
        """
        import cv2

        min_y = ap.y + int(ap.h * self.HEADER_SKIP_MIN_FRAC)
        max_y = ap.y + int(ap.h * self.HEADER_SKIP_MAX_FRAC)

        ocr_bottom = self._find_answer_here_bottom(img, ap)

        if ocr_bottom is not None:
            band_y = self._find_first_option_band(img, ap, ocr_bottom)
            if band_y is not None:
                result = band_y
            else:
                gap = max(int(ap.h * 0.02), 20)
                result = ocr_bottom + gap
            return max(min_y, min(max_y, result))

        # Fallback: use fraction-based estimate, then refine with band detection
        is_stitched = img.shape[0] >= img.shape[1] * 1.4
        frac = 0.18 if is_stitched else self.HEADER_SKIP_FRAC
        fallback_y = ap.y + int(ap.h * frac)

        band_y = self._find_first_option_band(img, ap, fallback_y - 50)
        if band_y is not None:
            return max(min_y, min(max_y, band_y))

        return max(min_y, min(max_y, fallback_y))

    def _find_answer_here_bottom(self, img: np.ndarray, ap: Rect) -> int | None:
        """Use OCR to locate the 'Answer here' header text.

        Scans ONLY the top 30% of the answer panel. Accepts only matches
        where both "answer" and "here" appear on the same text line,
        and only if the matched text is within the top 30% of the panel
        (to reject false positives from option text like "answer the question").
        """
        try:
            import cv2
            import pytesseract
            from controller.config import TESSERACT_CMD, OCR_TIMEOUT_SECONDS

            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()
        except Exception:
            return None

        scan_frac = 0.30
        scan_h = min(int(ap.h * scan_frac), 800)
        crop = img[ap.y:ap.y + scan_h, ap.x:ap.x2]
        if crop.size == 0:
            return None

        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(
                gray,
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 6",
                timeout=OCR_TIMEOUT_SECONDS,
            )
        except Exception:
            return None

        n = len(data.get("text", []))

        # Group words by line (block_num, par_num, line_num)
        lines: dict[tuple, list[dict]] = {}
        for i in range(n):
            word = str(data["text"][i]).strip()
            if not word:
                continue
            key = (
                int(data.get("block_num", [0])[i]),
                int(data.get("par_num", [0])[i]),
                int(data.get("line_num", [0])[i]),
            )
            lines.setdefault(key, []).append({
                "text": word.lower(),
                "top": int(data["top"][i]),
                "height": int(data["height"][i]),
            })

        # Find a line containing both "answer" and "here"
        for key in sorted(lines.keys()):
            words = lines[key]
            line_text = " ".join(w["text"] for w in words)
            cleaned = "".join(c for c in line_text if c.isalpha() or c == " ")

            has_answer = "answer" in cleaned
            has_here = "here" in cleaned

            if has_answer and has_here:
                bottom = max(w["top"] + w["height"] for w in words)
                abs_bottom = ap.y + bottom
                # Sanity check: must be in the top 30% of the panel
                local_frac = bottom / max(1, ap.h)
                if local_frac < scan_frac:
                    logger.debug(
                        "Found 'Answer here' at local Y=%d (abs %d, %.1f%% of panel)",
                        bottom, abs_bottom, local_frac * 100,
                    )
                    return abs_bottom

        # Fallback: accept a single "answer" or "here" if it's very near the top
        for key in sorted(lines.keys()):
            words = lines[key]
            line_text = " ".join(w["text"] for w in words)
            cleaned = "".join(c for c in line_text if c.isalpha())

            if cleaned in ("answer", "here", "answerhere"):
                bottom = max(w["top"] + w["height"] for w in words)
                local_frac = bottom / max(1, ap.h)
                if local_frac < 0.15:
                    return ap.y + bottom

        return None

    def _find_first_option_band(
        self, img: np.ndarray, ap: Rect, search_from_y: int,
    ) -> int | None:
        """Find where the first option band starts below search_from_y.

        The exam options area has alternating white (~248-255) and light
        gray (~235-245) horizontal bands. Each band corresponds to one
        option row. We scan downward from the given Y to find the first
        transition into these bands.

        Returns the absolute Y where the first option band begins, or None.
        """
        import cv2

        # Work on a single column strip near the center of the answer panel
        # to avoid edge effects
        strip_x1 = ap.x + int(ap.w * 0.3)
        strip_x2 = ap.x + int(ap.w * 0.7)

        local_start = max(0, search_from_y - ap.y)
        local_end = min(ap.h, local_start + int(ap.h * 0.25))

        if local_end - local_start < 30:
            return None

        crop = img[ap.y + local_start:ap.y + local_end, strip_x1:strip_x2]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        row_means = np.mean(gray, axis=1)

        # Option bands have brightness > 230. The header/separator area
        # may be different (colored bar, thin line, etc).
        # Find the first row where brightness consistently stays > 230
        # for at least 20 consecutive rows (one option band is typically
        # 50-120px tall on a 3072px image).
        MIN_BAND_LEN = 15
        run_start = None
        run_len = 0

        for y_local in range(len(row_means)):
            if row_means[y_local] > 230:
                if run_start is None:
                    run_start = y_local
                run_len += 1
            else:
                if run_len >= MIN_BAND_LEN and run_start is not None:
                    abs_y = ap.y + local_start + run_start
                    # Only accept if it's above the max header boundary
                    if abs_y <= ap.y + int(ap.h * self.HEADER_SKIP_MAX_FRAC):
                        return abs_y
                run_start = None
                run_len = 0

        if run_len >= MIN_BAND_LEN and run_start is not None:
            abs_y = ap.y + local_start + run_start
            if abs_y <= ap.y + int(ap.h * self.HEADER_SKIP_MAX_FRAC):
                return abs_y

        return None

    # ------------------------------------------------------------------
    # Circle detection
    # ------------------------------------------------------------------

    def _find_circles(self, cv2, blurred: np.ndarray) -> list[tuple[int, int, int]]:
        """Run HoughCircles: primary pass first, fallback supplement if sparse.

        The primary pass provides clean, high-confidence detections for most
        images. If it returns fewer than 4 circles, the fallback pass runs
        with more sensitive parameters and adds only circles at NEW Y
        positions (not near any primary result) — this catches small/
        low-contrast radio buttons at the bottom of the camera frame
        without flooding the pipeline with watermark noise.
        """
        # Primary pass (higher selectivity)
        raw = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=self.HOUGH_DP,
            minDist=self.HOUGH_MIN_DIST,
            param1=self.HOUGH_PARAM1,
            param2=self.HOUGH_PARAM2,
            minRadius=self.HOUGH_MIN_RADIUS,
            maxRadius=self.HOUGH_MAX_RADIUS,
        )

        if raw is not None:
            result = np.round(raw[0]).astype(int).tolist()
            logger.debug("Primary HoughCircles: %d circles", len(result))
        else:
            result = []
            logger.debug("Primary HoughCircles found nothing")

        # Only try fallback if primary returned few results (< 4 viable
        # circles suggest some options are being missed). Cap fallback
        # additions to avoid overwhelming filters with noise.
        MAX_FALLBACK_ADD = 6
        if len(result) < 4:
            raw_fb = cv2.HoughCircles(
                blurred, cv2.HOUGH_GRADIENT,
                dp=self.HOUGH_FALLBACK_DP,
                minDist=self.HOUGH_FALLBACK_MIN_DIST,
                param1=self.HOUGH_FALLBACK_PARAM1,
                param2=self.HOUGH_FALLBACK_PARAM2,
                minRadius=self.HOUGH_FALLBACK_MIN_RADIUS,
                maxRadius=self.HOUGH_FALLBACK_MAX_RADIUS,
            )
            if raw_fb is not None:
                fallback = np.round(raw_fb[0]).astype(int).tolist()
                added = 0
                for fc in fallback:
                    if added >= MAX_FALLBACK_ADD:
                        break
                    is_dup = any(
                        abs(fc[0] - rc[0]) < 30 and abs(fc[1] - rc[1]) < 30
                        for rc in result
                    )
                    if not is_dup:
                        result.append(fc)
                        added += 1
                if added > 0:
                    logger.debug(
                        "Fallback added %d circles (total %d)", added, len(result),
                    )

        return result

    def _find_circles_ghost(
        self, cv2, blurred: np.ndarray,
    ) -> list[tuple[int, int, int]]:
        """Find radio circles in a ghost-mode (pixel-perfect) screenshot.

        Ghost captures produce thin, low-contrast circles at r=5–7px.
        A single pass with tuned parameters is sufficient because there
        is no camera noise, watermark distortion, or perspective warping.
        The min_dist is set high (50px) to avoid duplicate detections in
        the same option row.
        """
        raw = cv2.HoughCircles(
            blurred, cv2.HOUGH_GRADIENT,
            dp=self.GHOST_HOUGH_DP,
            minDist=self.GHOST_HOUGH_MIN_DIST,
            param1=self.GHOST_HOUGH_PARAM1,
            param2=self.GHOST_HOUGH_PARAM2,
            minRadius=self.GHOST_HOUGH_MIN_RADIUS,
            maxRadius=self.GHOST_HOUGH_MAX_RADIUS,
        )

        if raw is not None:
            result = np.round(raw[0]).astype(int).tolist()
            logger.debug("Ghost HoughCircles: %d circles", len(result))
        else:
            result = []
            logger.debug("Ghost HoughCircles found nothing")

        return result

    # ------------------------------------------------------------------
    # Circle validation filters
    # ------------------------------------------------------------------

    def _filter_by_x_column(
        self,
        circles: list[tuple[int, int, int]],
        strip_width: int,
    ) -> list[tuple[int, int, int]]:
        """Identify the radio-button X column and discard circles outside it.

        Radio buttons form a vertical column at a consistent X position.
        Watermark/text circles are scattered across the strip width.
        We find the dominant X band by histogramming circle X positions
        and keeping only circles near the densest bin.

        Tie-breaking: when two X-bands have similar circle counts, we
        evaluate both and prefer the band whose circles form a more
        regular vertical spacing pattern (real radio buttons are evenly
        spaced, watermark noise is randomly scattered).
        """
        if len(circles) < 4:
            return circles

        xs = np.array([c[0] for c in circles])

        # Create histogram bins of 30px width across the strip
        bin_width = 30
        n_bins = max(1, strip_width // bin_width)
        hist, bin_edges = np.histogram(xs, bins=n_bins, range=(0, strip_width))

        # Find top-2 histogram peaks for tie-breaking
        sorted_bins = sorted(range(len(hist)), key=lambda i: hist[i], reverse=True)

        def _y_spacing_cv(candidate_circles: list[tuple[int, int, int]]) -> float:
            """Coefficient of variation of Y-gaps — lower is more regular."""
            if len(candidate_circles) < 3:
                return 999.0
            ys = sorted(c[1] for c in candidate_circles)
            gaps = [ys[i+1] - ys[i] for i in range(len(ys) - 1)]
            if not gaps:
                return 999.0
            mean_gap = sum(gaps) / len(gaps)
            if mean_gap < 1:
                return 999.0
            variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
            return (variance ** 0.5) / mean_gap

        # Accept circles within 50px of a peak center
        tolerance = 50
        best_kept = circles  # fallback: no filter
        best_cv = 999.0

        for bin_idx in sorted_bins[:3]:  # check top-3 peaks
            if hist[bin_idx] < 3:
                continue
            peak_center = (bin_edges[bin_idx] + bin_edges[bin_idx + 1]) / 2
            kept = [c for c in circles if abs(c[0] - peak_center) <= tolerance]
            if len(kept) < 3:
                continue
            cv = _y_spacing_cv(kept)
            if cv < best_cv:
                best_cv = cv
                best_kept = kept

        if len(best_kept) < 3:
            return circles

        removed = len(circles) - len(best_kept)
        if removed:
            logger.debug(
                "X-column filter: kept %d/%d (best_cv=%.2f, "
                "strip_w=%d)",
                len(best_kept), len(circles), best_cv, strip_width,
            )
        return best_kept

    def _filter_by_radius(
        self, circles: list[tuple[int, int, int]],
    ) -> list[tuple[int, int, int]]:
        """Reject circles whose radius deviates too far from the median.

        Real radio buttons on the exam have consistent radii. Noise and
        watermark artifacts produce circles with wildly different sizes.
        """
        if len(circles) < 3:
            return circles

        radii = [c[2] for c in circles]
        median_r = float(np.median(radii))
        if median_r < 1:
            return circles

        lo = median_r / self.RADIUS_TOLERANCE_FACTOR
        hi = median_r * self.RADIUS_TOLERANCE_FACTOR
        kept = [c for c in circles if lo <= c[2] <= hi]

        if len(kept) < 2:
            return circles

        removed = len(circles) - len(kept)
        if removed:
            logger.debug(
                "Radius filter: kept %d/%d (median_r=%.1f, range=[%.1f, %.1f])",
                len(kept), len(circles), median_r, lo, hi,
            )
        return kept

    def _filter_by_edge_quality(
        self,
        circles: list[tuple[int, int, int]],
        gray: np.ndarray,
    ) -> list[tuple[int, int, int]]:
        """Reject circles that don't look like real radio button outlines.

        Real radio buttons have high contrast between the circle edge
        (dark) and both the interior and exterior (light background).
        We sample pixels along the circle perimeter and inside and
        compute the contrast ratio. Low-contrast circles are likely
        watermark artifacts or noise.
        """
        import cv2

        if len(circles) < 3:
            return circles

        h, w = gray.shape[:2]
        scores = []

        for cx, cy, cr in circles:
            if cr < 3 or cx - cr - 2 < 0 or cy - cr - 2 < 0:
                scores.append(0.0)
                continue
            if cx + cr + 2 >= w or cy + cr + 2 >= h:
                scores.append(0.0)
                continue

            # Sample perimeter pixels (12 points around the circle)
            angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
            edge_vals = []
            for a in angles:
                px = int(round(cx + cr * np.cos(a)))
                py = int(round(cy + cr * np.sin(a)))
                if 0 <= px < w and 0 <= py < h:
                    edge_vals.append(float(gray[py, px]))

            # Sample interior pixels (center region, ~50% radius)
            inner_vals = []
            inner_r = max(1, cr // 2)
            for a in angles[:6]:
                px = int(round(cx + inner_r * np.cos(a)))
                py = int(round(cy + inner_r * np.sin(a)))
                if 0 <= px < w and 0 <= py < h:
                    inner_vals.append(float(gray[py, px]))
            inner_vals.append(float(gray[min(cy, h - 1), min(cx, w - 1)]))

            if not edge_vals or not inner_vals:
                scores.append(0.0)
                continue

            mean_edge = np.mean(edge_vals)
            mean_inner = np.mean(inner_vals)
            contrast = abs(mean_inner - mean_edge)
            scores.append(contrast)

        if not scores or max(scores) < 5:
            return circles

        median_score = float(np.median(scores))
        threshold = max(median_score * 0.18, 2.5)

        kept = [c for c, s in zip(circles, scores) if s >= threshold]

        if len(kept) < 2:
            return circles

        removed = len(circles) - len(kept)
        if removed:
            all_scores = [f"{s:.0f}" for s in scores]
            logger.debug(
                "Edge quality filter: kept %d/%d (median_score=%.1f, "
                "threshold=%.1f, scores=%s)",
                len(kept), len(circles), median_score, threshold,
                all_scores,
            )
        return kept

    def _filter_clusters_by_x_alignment(
        self, clusters: list[dict],
    ) -> list[dict]:
        """Reject clusters whose X-position is too far from the median.

        Radio buttons are vertically aligned. Watermark artifacts or
        noise circles often appear at different horizontal positions.
        """
        if len(clusters) < 3:
            return clusters

        xs = [c["center_x"] for c in clusters]
        median_x = float(np.median(xs))
        threshold = self.X_ALIGNMENT_MAX_DEVIATION_PX

        kept = [c for c in clusters if abs(c["center_x"] - median_x) <= threshold]

        if len(kept) < 2:
            return clusters

        removed = len(clusters) - len(kept)
        if removed:
            logger.debug(
                "X-alignment filter: kept %d/%d (median_x=%.0f, threshold=%d)",
                len(kept), len(clusters), median_x, threshold,
            )
        return kept

    def _filter_clusters_by_spacing(
        self, clusters: list[dict],
    ) -> list[dict]:
        """Reject outlier clusters that break the regular spacing pattern.

        Two-phase approach:
          Phase 1 (ratio-based): reject clusters whose gap to neighbours
                  deviates too far from the median gap.  Requires at least
                  5 clusters to act — with only 3--4, a single missed circle
                  creates irregular gaps that cascade into false removals.
          Phase 2 (leave-one-out): if we still have more clusters than
                  expected and removing one cluster dramatically improves
                  regularity, remove it.
        """
        if len(clusters) < 3:
            return clusters

        working = sorted(clusters, key=lambda c: c["center_y"])

        # --- Phase 1: Ratio-based outlier rejection ---
        MAX_ITERATIONS = 3
        for iteration in range(MAX_ITERATIONS):
            # Never drop below 3 clusters — with fewer, the ratio-based
            # filter has insufficient data to distinguish phantoms from
            # real options with irregular spacing.
            if len(working) <= 3:
                break

            ys = [c["center_y"] for c in working]
            gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            median_gap = float(np.median(gaps))

            if median_gap < 10:
                break

            lo = median_gap * self.SPACING_MIN_RATIO
            hi = median_gap * self.SPACING_MAX_RATIO

            all_regular = all(lo <= g <= hi for g in gaps)
            if all_regular:
                break

            worst_idx = None
            worst_deviation = 0.0
            for i, g in enumerate(gaps):
                if g < lo:
                    dev = lo - g
                elif g > hi:
                    dev = g - hi
                else:
                    continue
                if dev > worst_deviation:
                    worst_deviation = dev
                    worst_idx = i

            if worst_idx is None:
                break

            c_left = working[worst_idx]
            c_right = working[worst_idx + 1]

            xs = [c["center_x"] for c in working]
            median_x = float(np.median(xs))
            dev_left = abs(c_left["center_x"] - median_x)
            dev_right = abs(c_right["center_x"] - median_x)

            if dev_left > dev_right + 5:
                to_remove = c_left
            elif dev_right > dev_left + 5:
                to_remove = c_right
            elif worst_idx == 0:
                to_remove = c_left
            elif worst_idx == len(gaps) - 1:
                to_remove = c_right
            else:
                to_remove = c_right

            logger.debug(
                "Spacing filter phase 1 iter %d: removing cluster Y=%d "
                "(gap=%.0f, median_gap=%.0f, range=[%.0f, %.0f])",
                iteration, to_remove["center_y"], gaps[worst_idx],
                median_gap, lo, hi,
            )
            working = [c for c in working if c is not to_remove]

        # --- Phase 2: Leave-one-out regularity improvement ---
        # If we have 5+ clusters, check whether removing any single cluster
        # produces dramatically more regular spacing.  This catches phantom
        # options that happen to fall within the ratio thresholds but still
        # degrade regularity.
        working = self._leave_one_out_filter(working)

        removed = len(clusters) - len(working)
        if removed:
            logger.debug(
                "Spacing filter: kept %d/%d clusters",
                len(working), len(clusters),
            )
        return working

    def _leave_one_out_filter(self, clusters: list[dict]) -> list[dict]:
        """If removing one cluster dramatically improves spacing regularity,
        remove it.  Only acts when there are 5+ clusters.
        """
        if len(clusters) < 5:
            return clusters

        ordered = sorted(clusters, key=lambda c: c["center_y"])

        def _gap_cv(cs: list[dict]) -> float:
            """Coefficient of variation of inter-cluster gaps."""
            if len(cs) < 3:
                return 0.0
            ys = [c["center_y"] for c in cs]
            gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            mean = float(np.mean(gaps))
            if mean < 1:
                return 999.0
            return float(np.std(gaps)) / mean

        full_cv = _gap_cv(ordered)
        if full_cv < 0.15:
            return clusters

        best_removal_idx = None
        best_cv = full_cv

        for i in range(len(ordered)):
            subset = ordered[:i] + ordered[i + 1:]
            cv = _gap_cv(subset)
            if cv < best_cv:
                best_cv = cv
                best_removal_idx = i

        improvement_ratio = (full_cv - best_cv) / max(full_cv, 0.001)
        if best_removal_idx is not None and improvement_ratio > 0.20:
            removed = ordered[best_removal_idx]
            logger.debug(
                "Leave-one-out: removing cluster Y=%d (CV %.3f → %.3f, "
                "improvement=%.0f%%)",
                removed["center_y"], full_cv, best_cv,
                improvement_ratio * 100,
            )
            ordered = ordered[:best_removal_idx] + ordered[best_removal_idx + 1:]
            return self._leave_one_out_filter(ordered)

        return clusters

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster_by_y(
        self,
        circles: list[tuple[int, int, int]],
        gap: int | None = None,
    ) -> list[dict]:
        """Cluster circles by Y-coordinate proximity.

        Returns list of cluster dicts with center_x, center_y,
        median_r, and count.
        """
        if not circles:
            return []

        effective_gap = gap if gap is not None else self.Y_CLUSTER_GAP
        sorted_circles = sorted(circles, key=lambda c: c[1])
        clusters: list[list[tuple[int, int, int]]] = []
        current_cluster = [sorted_circles[0]]

        for i in range(1, len(sorted_circles)):
            if sorted_circles[i][1] - sorted_circles[i - 1][1] <= effective_gap:
                current_cluster.append(sorted_circles[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_circles[i]]
        clusters.append(current_cluster)

        result = []
        for cluster in clusters:
            if len(cluster) < self.MIN_CLUSTER_SIZE:
                continue
            xs = [c[0] for c in cluster]
            ys = [c[1] for c in cluster]
            rs = [c[2] for c in cluster]
            result.append({
                "center_x": int(np.median(xs)),
                "center_y": int(np.median(ys)),
                "median_r": int(np.median(rs)),
                "count": len(cluster),
            })

        return result

    def _trim_to_count(self, clusters: list[dict], target: int) -> list[dict]:
        """Select the best `target`-sized contiguous subset by spacing regularity."""
        if target <= 0 or len(clusters) <= target:
            return clusters

        ordered = sorted(clusters, key=lambda c: c["center_y"])
        best_subset = ordered[:target]
        best_std = float("inf")

        for start in range(len(ordered) - target + 1):
            subset = ordered[start: start + target]
            ys = [c["center_y"] for c in subset]
            if len(ys) < 2:
                return subset
            gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            std = float(np.std(gaps))
            if std < best_std:
                best_std = std
                best_subset = subset

        return best_subset

    # ------------------------------------------------------------------
    # Row bounds
    # ------------------------------------------------------------------

    def _compute_option_row(
        self,
        index: int,
        clusters: list[dict],
        panel_height: int,
        cy_local: int,
    ) -> tuple[int, int]:
        """Compute top and bottom Y for a row, panel-relative.

        Uses midpoints between consecutive cluster centers as boundaries.
        """
        n = len(clusters)
        if n <= 1:
            half = panel_height // 6
            return (max(0, cy_local - half), min(panel_height, cy_local + half))

        panel_y = clusters[index]["center_y"] - cy_local

        def to_local(abs_y: int) -> int:
            return abs_y - panel_y

        if index == 0:
            row_top = max(0, to_local(clusters[0]["center_y"]) - 40)
        else:
            mid = (clusters[index - 1]["center_y"] + clusters[index]["center_y"]) // 2
            row_top = max(0, to_local(mid))

        if index >= n - 1:
            row_bottom = min(panel_height, to_local(clusters[-1]["center_y"]) + 80)
        else:
            mid = (clusters[index]["center_y"] + clusters[index + 1]["center_y"]) // 2
            row_bottom = min(panel_height, to_local(mid))

        return (row_top, row_bottom)

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_color_watermark(bgr: np.ndarray) -> np.ndarray:
        """Remove colored watermark text (red/pink/orange) from an option crop."""
        import cv2

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        red_lo1 = cv2.inRange(hsv, np.array([0, 40, 80]), np.array([15, 255, 255]))
        red_lo2 = cv2.inRange(hsv, np.array([160, 40, 80]), np.array([180, 255, 255]))
        pink = cv2.inRange(hsv, np.array([140, 30, 80]), np.array([170, 255, 255]))
        orange = cv2.inRange(hsv, np.array([10, 50, 80]), np.array([25, 255, 255]))

        watermark_mask = red_lo1 | red_lo2 | pink | orange
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        watermark_mask = cv2.dilate(watermark_mask, kernel, iterations=1)

        cleaned = bgr.copy()
        cleaned[watermark_mask > 0] = (255, 255, 255)
        return cleaned

    def _ocr_text(self, text_region: np.ndarray) -> tuple[str, float]:
        """Run OCR on a cropped text region. Returns (text, confidence).

        Pipeline: watermark removal → grayscale → denoise → adaptive
        threshold → upscale if small → tesseract PSM 6.
        """
        if text_region.size == 0:
            return ("", 0.0)

        try:
            import cv2
            import pytesseract
            from controller.config import TESSERACT_CMD, OCR_TIMEOUT_SECONDS

            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()

            # Watermark removal on colour image.
            if len(text_region.shape) == 3 and text_region.shape[2] == 3:
                cleaned_bgr = self._remove_color_watermark(text_region)
                gray = cv2.cvtColor(cleaned_bgr, cv2.COLOR_BGR2GRAY)
            elif len(text_region.shape) == 3:
                gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
            else:
                gray = text_region

            denoised = cv2.fastNlMeansDenoising(gray, h=10)

            thresh = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 15,
            )

            ih, iw = thresh.shape[:2]
            if ih < 60:
                scale = max(2, 80 // max(ih, 1))
                thresh = cv2.resize(
                    thresh, (iw * scale, ih * scale),
                    interpolation=cv2.INTER_CUBIC,
                )

            thresh = cv2.copyMakeBorder(
                thresh, 10, 10, 10, 10,
                cv2.BORDER_CONSTANT, value=255,
            )

            cfg = "--oem 3 --psm 6"
            data = pytesseract.image_to_data(
                thresh,
                output_type=pytesseract.Output.DICT,
                config=cfg,
                timeout=OCR_TIMEOUT_SECONDS,
            )

            words = []
            confidences = []
            for i in range(len(data.get("text", []))):
                txt = str(data["text"][i]).strip()
                if not txt:
                    continue
                try:
                    conf = float(data["conf"][i])
                except (ValueError, TypeError):
                    conf = -1.0
                if conf >= 0:
                    words.append(txt)
                    confidences.append(conf)

            text = " ".join(words)
            avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
            return (text, avg_conf)

        except Exception as e:
            logger.debug("OCR failed: %s", e)
            return ("", 0.0)
