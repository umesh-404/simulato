"""
Option detector for exam answer panel (v2 — Y-clustering approach).

Given the answer panel sub-image (right pane of the exam screen),
detects individual answer options by:

    1. Extracting a narrow vertical strip on the left edge of the
       answer panel where radio buttons live.
    2. Running HoughCircles on that strip → many noisy candidates.
    3. Clustering the candidates by Y-coordinate → each cluster = one
       radio button row.
    4. Picking the median X within each cluster = best circle center.
    5. Sorting clusters top-to-bottom → assigning A, B, C, D, E.
    6. OCR on the text region to the right of each radio button.

This approach is robust to watermark circles, noise, and variable
circle sizes because it leverages the fact that radio buttons are
the only circles that appear at regular vertical intervals in a
narrow left-edge strip.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayout, Rect
from controller.utils.logger import get_logger

logger = get_logger("option_detector")

# Labels assigned by vertical position (top to bottom)
OPTION_LABELS = ["A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectedOption:
    """A single detected answer option."""
    label: str                          # A, B, C, D, or E
    text: str                           # OCR-extracted option text
    circle_x: int                       # Radio button center X (absolute px)
    circle_y: int                       # Radio button center Y (absolute px)
    circle_r: int                       # Radio button radius in pixels
    click_x: int                        # Recommended click X (absolute px)
    click_y: int                        # Recommended click Y (absolute px)
    bounds: Rect                        # Full bounding rect of the option row
    text_confidence: float = 0.0        # OCR confidence for the text


@dataclass
class OptionMap:
    """Complete map of all detected options on the answer panel."""
    options: list[DetectedOption]
    panel_bounds: Optional[Rect] = None     # Answer panel region used
    detection_method: str = ""              # "y-cluster" / "contour" / "none"
    image_w: int = 0
    image_h: int = 0
    debug_meta: dict | None = None         # optional debug metadata (strip bounds etc.)

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
        """Convert absolute pixel coords to normalized [0, 1] coords."""
        nx = max(0.0, min(1.0, x / max(1, self.image_w)))
        ny = max(0.0, min(1.0, y / max(1, self.image_h)))
        return (nx, ny)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class OptionDetector:
    """
    Detects answer options in the right panel of the exam screen.

    Uses Y-clustering of HoughCircle candidates in a narrow left-edge
    strip to find radio buttons reliably despite watermark noise.
    """

    # --- Tunable thresholds -------------------------------------------

    # Width of each search strip (pixels from a candidate left anchor).
    SEARCH_STRIP_WIDTH = 80
    SEARCH_STRIP_MIN_WIDTH = 50
    SEARCH_STRIP_MAX_WIDTH = 140
    SEARCH_STRIP_WIDTH_FRAC = 0.06
    SEARCH_MAX_RIGHT_FRAC = 0.16
    SEARCH_TOP_MARGIN_FRAC = 0.10
    SEARCH_BOTTOM_MARGIN_FRAC = 0.06

    # Small upward correction (in capture-image pixels) applied to click_y.
    # Camera perspective causes a consistent ~5px downward bias in circle
    # centre detection; this shifts the click target slightly upward to
    # land on the radio button rather than just below it.
    CLICK_Y_UPWARD_BIAS_PX = 8

    # HoughCircles parameters (kept loose — we filter with clustering afterwards)
    HOUGH_DP = 1.2
    HOUGH_MIN_DIST = 20             # Pixels between circle centers
    HOUGH_PARAM1 = 80               # Canny upper threshold
    HOUGH_PARAM2 = 18               # Accumulator threshold (low → more circles)
    HOUGH_MIN_RADIUS = 5
    HOUGH_MAX_RADIUS = 25

    # Y-clustering: merge circles within this Y distance into one cluster
    Y_CLUSTER_GAP = 60              # Pixels
    MIN_ROW_GAP_PX = 28
    MAX_ROW_GAP_PX = 320

    # Minimum cluster size to be considered a real radio button row
    MIN_CLUSTER_SIZE = 1

    # Expected number of options (used for validation, not hard-coded)
    MIN_EXPECTED_OPTIONS = 3
    MAX_EXPECTED_OPTIONS = 5

    # How far right of the circle to start the OCR text crop
    TEXT_OFFSET_X_PX = 30           # Pixels right of the circle edge

    def detect(
        self,
        image_path: Path,
        layout: ExamLayout,
        max_options: int | None = None,
    ) -> OptionMap:
        """
        Detect option radio buttons and their text in the answer panel.

        Parameters
        ----------
        image_path : Path
            Path to the full exam screenshot.
        layout : ExamLayout
            Pre-detected layout with answer_panel bounds.

        Returns
        -------
        OptionMap
            All detected options with coordinates and OCR text.
        """
        logger.info("Detecting options for: %s", image_path.name)

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available")
            return OptionMap(options=[], image_w=layout.image_w, image_h=layout.image_h)

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return OptionMap(options=[], image_w=layout.image_w, image_h=layout.image_h)

        if layout.answer_panel is None:
            logger.warning("No answer panel in layout")
            return OptionMap(options=[], image_w=layout.image_w, image_h=layout.image_h)

        ap = layout.answer_panel

        #region agent log
        from controller.utils.debug_ndjson import dbg as _dbg
        _dbg(
            location="controller/capture_pipeline/option_detector.py:detect",
            message="option_detect start",
            data={
                "image": str(image_path),
                "ap": {"x": ap.x, "y": ap.y, "w": ap.w, "h": ap.h},
            },
            hypothesisId="H2",
        )
        #endregion agent log

        # Step 1: adaptive strip search across the left-to-mid answer panel.
        candidate_strips = self._candidate_strips(ap)
        best_clusters: list[dict] = []
        best_abs_candidates: list[tuple[int, int, int]] = []
        best_strip: tuple[int, int] | None = None
        best_search_y1 = ap.y
        best_search_y2 = ap.y2
        best_score = float("-inf")

        # Margin to skip "Answer here" header. Use fraction of panel
        # height but cap to an absolute max to prevent over-cutting on
        # tall stitched images.
        top_margin = min(int(ap.h * self.SEARCH_TOP_MARGIN_FRAC), 500)
        bottom_margin = min(int(ap.h * self.SEARCH_BOTTOM_MARGIN_FRAC), 300)
        search_y1 = ap.y + top_margin
        search_y2 = ap.y2 - bottom_margin
        search_y1 = max(ap.y, min(search_y1, ap.y2 - 1))
        search_y2 = max(search_y1 + 1, min(search_y2, ap.y2))

        for strip_x1, strip_x2 in candidate_strips:
            seq, seq_score, abs_candidates = self._detect_best_sequence_for_strip(
                img,
                strip_x1=strip_x1,
                strip_x2=strip_x2,
                strip_y1=search_y1,
                strip_y2=search_y2,
            )
            if seq_score > best_score:
                best_score = seq_score
                best_clusters = seq
                best_abs_candidates = abs_candidates
                best_strip = (strip_x1, strip_x2)
                best_search_y1 = search_y1
                best_search_y2 = search_y2

        clusters = best_clusters
        abs_candidates = best_abs_candidates
        if not clusters:
            logger.warning("No reliable radio-row sequence detected in adaptive strips")
            return OptionMap(
                options=[],
                panel_bounds=ap,
                detection_method="none",
                image_w=layout.image_w,
                image_h=layout.image_h,
                debug_meta={
                    "adaptive": True,
                    "best_strip_x1": None,
                    "best_strip_x2": None,
                    "search_y1": best_search_y1,
                    "search_y2": best_search_y2,
                    "best_score": best_score,
                    "raw_candidates_count": 0,
                },
            )

        # Remove obvious non-option rows (bottom-bar artefacts and header
        # phantoms above the real option area).
        #
        # Strategy: use the calibrated option-A Y position (transformed to
        # capture-image space) as the authoritative floor.  Any cluster
        # whose Y is more than half an inter-option step above calibrated-A
        # is almost certainly the "Answer here" header circle.  The bottom
        # cutoff is a simple absolute cap.
        original_clusters = list(clusters)
        max_row_y = ap.y + ap.h - min(int(ap.h * 0.03), 150)
        min_row_y = self._calibrated_min_row_y(img.shape[0])
        filtered_clusters = [
            c for c in clusters
            if min_row_y <= int(c.get("center_y", ap.y)) <= max_row_y
        ]
        if len(filtered_clusters) >= self.MIN_EXPECTED_OPTIONS:
            clusters = filtered_clusters
        else:
            clusters = original_clusters

        # Step 4: Build options from clusters
        # Sort clusters by Y (top to bottom)
        clusters.sort(key=lambda c: c["center_y"])

        # Trim to max expected options.
        # If caller specified max_options (from AI response), use that;
        # otherwise fall back to the class-level MAX_EXPECTED_OPTIONS.
        effective_max = max_options if max_options is not None else self.MAX_EXPECTED_OPTIONS
        if len(clusters) > effective_max:
            clusters = self._trim_to_expected_count(clusters, effective_max, img.shape[0])

        # Spacing regularity filter: real radio buttons are roughly evenly
        # spaced.  If the gap between the first and second row is more than
        # 2× the median of other inter-row gaps, the first row is almost
        # certainly a phantom header circle — drop it.
        clusters = self._drop_spacing_outliers(clusters)

        # Recovery pass: last-resort fallback when primary detection still
        # misses circles (unusual framing, extreme camera angle, etc.).
        # With the corrected search-strip range this should rarely trigger.
        if 2 <= len(clusters) <= 3 and best_strip is not None:
            pre_count = len(clusters)
            clusters = self._recover_missing_rows(
                img, clusters, best_strip, ap,
            )
            if len(clusters) > pre_count:
                logger.warning(
                    "Recovery pass activated (rare): %d → %d option rows. "
                    "Primary HoughCircles missed %d circles.",
                    pre_count, len(clusters), len(clusters) - pre_count,
                )

        options: list[DetectedOption] = []
        # Radio buttons lie on a stable left column; derive a shared anchor X
        # to avoid drifting into option-text circles (e.g., "o"/"e" glyph loops).
        stable_radio_x = self._stable_radio_anchor_x(clusters, ap)

        # Use calibration anchors to assign correct A-E labels even when
        # fewer than 5 clusters are found (avoids label shifting).
        label_assignment = self._assign_labels_from_calibration(
            clusters, layout.image_w, layout.image_h,
        )

        for i, cluster in enumerate(clusters):
            if i >= len(OPTION_LABELS):
                break

            label = label_assignment.get(i, OPTION_LABELS[i])
            cx = cluster["center_x"]
            cy = cluster["center_y"]
            cr = cluster["median_r"]

            # Compute option row bounds for OCR
            row_top, row_bottom = self._compute_option_row(
                i, clusters, ap.y2 - ap.y, cy - ap.y,
            )
            # Convert back to absolute
            row_top_abs = ap.y + row_top
            row_bottom_abs = ap.y + row_bottom

            # OCR text region: from right of circle to a focused area.
            # Cap width to avoid sweeping across watermarks that dominate
            # the wide answer panel.  Most option text sits within ~400px
            # of the radio button, but on lower-res crops it may be
            # narrower.  Use at most 40% of panel width or 500px.
            text_x = cx + cr + self.TEXT_OFFSET_X_PX
            max_text_w = min(int(ap.w * 0.40), 500)
            text_x2 = min(text_x + max_text_w, ap.x2)
            pad_y = 10
            crop_y1 = max(0, row_top_abs - pad_y)
            crop_y2 = min(img.shape[0], row_bottom_abs + pad_y)
            text_region = img[crop_y1:crop_y2, text_x:text_x2]

            text, text_conf = self._ocr_text(text_region)

            option_bounds = Rect(
                x=ap.x,
                y=row_top_abs,
                w=ap.w,
                h=row_bottom_abs - row_top_abs,
            )

            options.append(DetectedOption(
                label=label,
                text=text,
                circle_x=cx,
                circle_y=cy,
                circle_r=cr,
                click_x=stable_radio_x,
                click_y=max(0, cy - self.CLICK_Y_UPWARD_BIAS_PX),
                bounds=option_bounds,
                text_confidence=text_conf,
            ))

            logger.info(
                "Option %s: circle=(%d,%d) r=%d click=(%d,%d) text='%s' conf=%.1f",
                label, cx, cy, cr, stable_radio_x, cy,
                text[:60] if text else "", text_conf,
            )

        # Post-OCR filter: drop any option whose text is clearly the
        # "Answer here" header rather than real option content.
        options, dropped_header = self._filter_answer_here_options(options)

        # Post-filter recovery: if the "Answer here" drop (or other filters)
        # left us with fewer than 4 options, try to recover the missing row
        # by extrapolating from the remaining options' spacing.
        if dropped_header and 2 <= len(options) <= 3 and best_strip is not None:
            remaining_clusters = [
                {"center_x": o.circle_x, "center_y": o.circle_y,
                 "median_r": o.circle_r, "count": 1}
                for o in options
            ]
            recovered = self._recover_missing_rows(
                img, remaining_clusters, best_strip, ap,
            )
            if len(recovered) > len(options):
                logger.info(
                    "Post-filter recovery: %d → %d option rows",
                    len(options), len(recovered),
                )
                # Rebuild options from recovered clusters.
                recovered.sort(key=lambda c: c["center_y"])
                stable_rx = self._stable_radio_anchor_x(recovered, ap)
                new_options: list[DetectedOption] = []
                for ri, rc in enumerate(recovered):
                    if ri >= len(OPTION_LABELS):
                        break
                    rcx = rc["center_x"]
                    rcy = rc["center_y"]
                    rcr = rc["median_r"]
                    row_top, row_bottom = self._compute_option_row(
                        ri, recovered, ap.y2 - ap.y, rcy - ap.y,
                    )
                    row_top_abs = ap.y + row_top
                    row_bottom_abs = ap.y + row_bottom
                    max_text_w = min(int(ap.w * 0.40), 500)
                    text_region = img[
                        max(0, row_top_abs - 10) : min(img.shape[0], row_bottom_abs + 10),
                        min(img.shape[1], rcx + rcr + 8) : min(img.shape[1], rcx + rcr + 8 + max_text_w),
                    ]
                    ocr_text, ocr_conf = self._ocr_text(text_region)
                    click_x = stable_rx + max(10, rcr + 2)
                    adjusted_click_y = max(0, rcy - self.CLICK_Y_UPWARD_BIAS_PX)
                    new_options.append(DetectedOption(
                        label=OPTION_LABELS[ri],
                        text=ocr_text,
                        circle_x=rcx,
                        circle_y=rcy,
                        circle_r=rcr,
                        click_x=click_x,
                        click_y=adjusted_click_y,
                        bounds=(ap.x, row_top_abs, ap.w, row_bottom_abs - row_top_abs),
                        text_confidence=ocr_conf,
                    ))
                    logger.info(
                        "Option %s: circle=(%d,%d) r=%d click=(%d,%d) text=%r conf=%.1f",
                        OPTION_LABELS[ri], rcx, rcy, rcr, click_x, adjusted_click_y,
                        ocr_text[:40] if ocr_text else None, ocr_conf,
                    )
                options = new_options

        method = "adaptive_y_cluster" if options else "none"
        logger.info("Detected %d options via %s (%d raw candidates)",
                     len(options), method, len(abs_candidates))

        return OptionMap(
            options=options,
            panel_bounds=ap,
            detection_method=method,
            image_w=layout.image_w,
            image_h=layout.image_h,
            debug_meta={
                "adaptive": True,
                "best_strip_x1": (best_strip[0] if best_strip else None),
                "best_strip_x2": (best_strip[1] if best_strip else None),
                "search_y1": best_search_y1,
                "search_y2": best_search_y2,
                "row_filter_min_y": ap.y,
                "row_filter_max_y": max_row_y,
                "clusters_before_filter": len(original_clusters),
                "clusters_after_filter": len(filtered_clusters),
                "best_score": best_score,
                "raw_candidates_count": int(len(abs_candidates)),
            },
        )

    def _stable_radio_anchor_x(self, clusters: list[dict], ap: Rect) -> int:
        """
        Derive a robust click X for radio buttons from cluster centers.

        We bias to the left-most consistent column so clicks stay on the
        radio circles rather than drifting onto option text.
        """
        if not clusters:
            return ap.x + int(ap.w * 0.10)

        xs = sorted(int(c.get("center_x", ap.x + int(ap.w * 0.10))) for c in clusters)
        # Use median as the stable radio column anchor.
        # (Previously lower-quartile, but that biased clicks LEFT of the
        # true column center when HoughCircle centres have natural jitter.)
        q_idx = max(0, min(len(xs) - 1, int(round((len(xs) - 1) * 0.50))))
        x = xs[q_idx]

        # Keep inside a conservative left band of answer panel.
        min_x = ap.x + int(ap.w * 0.03)
        max_x = ap.x + int(ap.w * 0.28)
        return max(min_x, min(max_x, x))

    _ANSWER_HERE_KEYWORDS = {"answer", "here", "answerhere"}

    def _filter_answer_here_options(
        self, options: list["DetectedOption"],
    ) -> tuple[list["DetectedOption"], bool]:
        """Remove options whose OCR text matches the 'Answer here' header.

        Only checks the first option (topmost row) because the header is
        always above the real options.  If its text is short and matches
        known header keywords, it is dropped and the remaining options are
        re-labeled A, B, C... sequentially.

        Returns (filtered_options, was_header_dropped).
        """
        if not options:
            return options, False

        first = options[0]
        raw = (first.text or "").strip().lower()
        # Remove punctuation / dashes
        cleaned = "".join(c for c in raw if c.isalnum() or c == " ")
        words = set(cleaned.split())

        is_header = bool(words & self._ANSWER_HERE_KEYWORDS)

        # Also flag if the first option text is short and contains "here" or
        # "answer" as a substring (OCR sometimes partially reads it, e.g.
        # "werhere", "here", "answerhere", "- Answer here", "re").
        if not is_header and 0 < len(raw) <= 25:
            if "answer" in raw or "here" in raw:
                is_header = True
            elif 1 <= len(raw) <= 4 and raw in "answerhere":
                is_header = True

        # When 5 options are detected and the first has very short/garbled
        # text with low OCR confidence, it's almost certainly the "Answer here"
        # header whose text was mangled by OCR (e.g. 'Tre', '- a ) .').
        if not is_header and len(options) >= 5:
            is_short_garbage = len(cleaned) <= 6 and first.text_confidence < 70.0
            if is_short_garbage:
                is_header = True

        if not is_header:
            return options, False

        logger.info(
            "Dropping 'Answer here' phantom option %s (text='%s', Y=%d)",
            first.label, first.text[:40] if first.text else "", first.circle_y,
        )

        remaining = options[1:]
        relabeled: list[DetectedOption] = []
        for i, opt in enumerate(remaining):
            new_label = OPTION_LABELS[i] if i < len(OPTION_LABELS) else opt.label
            relabeled.append(DetectedOption(
                label=new_label,
                text=opt.text,
                circle_x=opt.circle_x,
                circle_y=opt.circle_y,
                circle_r=opt.circle_r,
                click_x=opt.click_x,
                click_y=opt.click_y,
                bounds=opt.bounds,
                text_confidence=opt.text_confidence,
            ))
        return relabeled, True

    def _assign_labels_from_calibration(
        self,
        clusters: list[dict],
        image_w: int,
        image_h: int,
    ) -> dict[int, str]:
        """Assign A-E labels to detected cluster rows using calibration
        Y-proximity matching.

        Uses exact pixel positions stored during calibration to convert
        screen-space Y → capture-image Y, then greedily matches each
        detected cluster to the nearest calibrated option position.

        This correctly handles the common case where the topmost radio
        button is missed by HoughCircles and the remaining 3 circles
        are actually B-C-D rather than A-B-C.

        Falls back to sequential labeling only when calibration data is
        unavailable or the match is non-monotonic.
        """
        if not clusters:
            return {}

        n = len(clusters)

        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
        except Exception:
            return self._sequential_labels(n, "no calibration data")

        if gm.resolution[1] <= 0 or image_h <= 0:
            return self._sequential_labels(n, "invalid resolution")

        cap_h = gm.capture_resolution[1] if gm.capture_resolution[1] > 0 else image_h

        calib_ys: dict[str, float] = {}
        for letter in OPTION_LABELS:
            exact = gm.pixel_positions.get(letter)
            if exact is not None:
                screen_y = float(exact[1])
            else:
                pos = gm.positions.get(letter)
                if pos is None:
                    continue
                grid_col, grid_row = pos
                cell_h = float(gm.resolution[1]) / float(max(1, gm.grid_size[1]))
                screen_y = (grid_row + 0.5) * cell_h

            scale_y = gm.transform.get("scale_y", 1.0)
            offset_y = float(gm.transform.get("offset_y", 0.0))
            if abs(scale_y) < 1e-9:
                continue
            capture_y = (screen_y - offset_y) / scale_y
            capture_y_for_image = capture_y * image_h / max(1, cap_h)
            calib_ys[letter] = capture_y_for_image

        if len(calib_ys) < 3:
            return self._sequential_labels(n, f"only {len(calib_ys)} calibrated")

        available = dict(calib_ys)
        assignment: dict[int, str] = {}
        for i, cluster in enumerate(clusters):
            cy = float(cluster.get("center_y", 0))
            best_label = None
            best_dist = float("inf")
            for label, cal_y in available.items():
                dist = abs(cy - cal_y)
                if dist < best_dist:
                    best_dist = dist
                    best_label = label
            if best_label is not None and best_dist < 300:
                assignment[i] = best_label
                del available[best_label]
            else:
                break

        if len(assignment) != n:
            return self._sequential_labels(n, "calibration anchor mismatch")

        labels_in_order = [assignment[i] for i in range(n)]
        if labels_in_order != sorted(labels_in_order):
            logger.warning(
                "Calibration anchor labels not monotonic (%s); falling back to sequential",
                labels_in_order,
            )
            return self._sequential_labels(n, "non-monotonic match")

        logger.info(
            "Calibration-anchored labels: %s (from %d calibrated positions)",
            labels_in_order, len(calib_ys),
        )
        return assignment

    @staticmethod
    def _sequential_labels(n: int, reason: str) -> dict[int, str]:
        assignment = {i: OPTION_LABELS[i] for i in range(min(n, len(OPTION_LABELS)))}
        labels = [assignment[i] for i in range(len(assignment))]
        logger.info("Sequential labels (n=%d, reason=%s): %s", n, reason, labels)
        return assignment

    def _recover_missing_rows(
        self,
        img: np.ndarray,
        clusters: list[dict],
        strip: tuple[int, int],
        ap: "Rect",
    ) -> list[dict]:
        """Try to find missing option rows when only 2-3 were detected.

        Extrapolates expected Y positions from the detected row spacing,
        then runs a very relaxed HoughCircles search in narrow Y bands
        around each expected position.  Any confirmed circle creates a
        new cluster entry.
        """
        import cv2

        ordered = sorted(clusters, key=lambda c: c["center_y"])
        ys = [c["center_y"] for c in ordered]
        diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        if not diffs or all(d <= 0 for d in diffs):
            return clusters

        step = int(round(float(np.median([d for d in diffs if d > 0]))))
        if step < 30 or step > 500:
            return clusters

        median_x = int(np.median([c["center_x"] for c in ordered]))
        median_r = int(np.median([c["median_r"] for c in ordered]))

        expected_ys: list[int] = []
        for idx in range(len(ys)):
            expected_ys.append(ys[0] + idx * step)
        # Extend one step beyond the last detected row (downward).
        next_y = ys[-1] + step
        if next_y <= ap.y2:
            expected_ys.append(next_y)
        # Extend one step above the first detected row (upward).
        # This catches a missed top option whose circle was too faint for
        # HoughCircles while still staying within the answer panel bounds.
        prev_y = ys[0] - step
        if prev_y >= ap.y:
            expected_ys.append(prev_y)

        # Identify missing positions: expected Ys that have no detected cluster nearby.
        margin = step // 3
        missing_ys: list[int] = []
        for ey in expected_ys:
            if ey < ap.y or ey > ap.y2:
                continue
            if not any(abs(ey - dy) < margin for dy in ys):
                missing_ys.append(ey)

        if not missing_ys:
            return clusters

        # Targeted HoughCircles in narrow bands around each missing Y.
        strip_x1, strip_x2 = strip
        band_half = max(30, step // 4)
        new_clusters = list(clusters)

        for target_y in missing_ys:
            band_y1 = max(0, target_y - band_half)
            band_y2 = min(img.shape[0], target_y + band_half)
            band_x1 = max(0, strip_x1 - 30)
            band_x2 = min(img.shape[1], strip_x2 + 30)
            band = img[band_y1:band_y2, band_x1:band_x2]
            if band.size == 0:
                continue
            gray_band = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray_band, (9, 9), 2)

            # Very relaxed parameters to catch faint circles.
            raw = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=1.0,
                minDist=10,
                param1=50,
                param2=8,
                minRadius=3,
                maxRadius=35,
            )
            if raw is not None:
                cand = np.round(raw[0]).astype(int)
                # Pick the candidate closest to expected X.
                best_cx, best_cy, best_cr = None, None, None
                best_dx = float("inf")
                for cx_local, cy_local, cr in cand:
                    cx_abs = band_x1 + int(cx_local)
                    cy_abs = band_y1 + int(cy_local)
                    dx = abs(cx_abs - median_x)
                    if dx < best_dx:
                        best_dx = dx
                        best_cx, best_cy, best_cr = cx_abs, cy_abs, int(cr)

                if best_cx is not None and best_dx < step * 0.5:
                    new_cluster = {
                        "center_x": best_cx,
                        "center_y": best_cy,
                        "median_r": best_cr,
                        "count": 1,
                    }
                    new_clusters.append(new_cluster)
                    logger.info(
                        "Recovered missing row at Y=%d (expected=%d, dx=%d)",
                        best_cy, target_y, int(best_dx),
                    )
                    continue

            # If HoughCircles fails, synthesize at the expected position only
            # if it falls within 1 step beyond the furthest detected row.
            furthest_detected = max(ys)
            if target_y <= furthest_detected + step * 1.2:
                synth = {
                    "center_x": median_x,
                    "center_y": target_y,
                    "median_r": median_r,
                    "count": 0,
                }
                new_clusters.append(synth)
                logger.info(
                    "Synthesized missing row at Y=%d (no circle found, using median X=%d)",
                    target_y, median_x,
                )

        new_clusters.sort(key=lambda c: c["center_y"])
        # Cap to 5 max.
        if len(new_clusters) > self.MAX_EXPECTED_OPTIONS:
            new_clusters = new_clusters[:self.MAX_EXPECTED_OPTIONS]
        return new_clusters

    def _candidate_strips(self, ap: Rect) -> list[tuple[int, int]]:
        """Generate deterministic candidate strip ranges inside answer panel."""
        width = max(
            self.SEARCH_STRIP_MIN_WIDTH,
            min(self.SEARCH_STRIP_MAX_WIDTH, int(ap.w * self.SEARCH_STRIP_WIDTH_FRAC)),
        )
        right_limit = ap.x + int(ap.w * self.SEARCH_MAX_RIGHT_FRAC)
        if right_limit <= ap.x + width:
            right_limit = min(ap.x2, ap.x + width + 10)

        # Deterministic offsets from panel left. Finer steps for better
        # isolation of the narrow radio-button column.
        rel_starts = [0.00, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14]
        strips: list[tuple[int, int]] = []
        for rel in rel_starts:
            sx1 = ap.x + int(ap.w * rel)
            sx2 = min(ap.x2, sx1 + width)
            if sx2 - sx1 < 40:
                continue
            if sx1 >= right_limit:
                continue
            strips.append((sx1, sx2))

        if not strips:
            strips.append((ap.x, min(ap.x2, ap.x + width)))

        # De-duplicate while preserving order.
        dedup: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for s in strips:
            if s not in seen:
                seen.add(s)
                dedup.append(s)
        return dedup

    def _detect_best_sequence_for_strip(
        self,
        img: np.ndarray,
        strip_x1: int,
        strip_x2: int,
        strip_y1: int,
        strip_y2: int,
    ) -> tuple[list[dict], float, list[tuple[int, int, int]]]:
        """Run multi-pass Hough on one strip and return best coherent 3-5 row sequence."""
        import cv2

        strip_img = img[strip_y1:strip_y2, strip_x1:strip_x2]
        if strip_img.size == 0:
            return ([], float("-inf"), [])
        gray_strip = cv2.cvtColor(strip_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray_strip, (9, 9), 2)

        param_sets = [
            dict(dp=self.HOUGH_DP, minDist=self.HOUGH_MIN_DIST, param1=self.HOUGH_PARAM1, param2=self.HOUGH_PARAM2, minRadius=self.HOUGH_MIN_RADIUS, maxRadius=self.HOUGH_MAX_RADIUS),
            dict(dp=1.0, minDist=15, param1=60, param2=12, minRadius=4, maxRadius=28),
            dict(dp=1.0, minDist=12, param1=60, param2=9, minRadius=4, maxRadius=35),
            dict(dp=1.0, minDist=10, param1=45, param2=7, minRadius=3, maxRadius=40),
        ]

        best_seq: list[dict] = []
        best_score = float("-inf")
        best_abs_candidates: list[tuple[int, int, int]] = []
        for ps in param_sets:
            raw = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=ps["dp"],
                minDist=ps["minDist"],
                param1=ps["param1"],
                param2=ps["param2"],
                minRadius=ps["minRadius"],
                maxRadius=ps["maxRadius"],
            )
            if raw is None:
                continue
            cand = np.round(raw[0]).astype(int)
            abs_candidates = [(strip_x1 + int(cx), strip_y1 + int(cy), int(cr)) for cx, cy, cr in cand]
            clusters = self._cluster_by_y(abs_candidates)
            seq, score = self._select_best_cluster_sequence(clusters)
            logger.debug(
                "HoughPass p2=%d: %d raw → %d clusters → best seq %d rows (score=%.0f) cluster_ys=%s",
                ps["param2"], len(cand), len(clusters), len(seq), score,
                [c["center_y"] for c in sorted(clusters, key=lambda c: c["center_y"])],
            )
            if score > best_score:
                best_score = score
                best_seq = seq
                best_abs_candidates = abs_candidates
        return (best_seq, best_score, best_abs_candidates)

    def _select_best_cluster_sequence(self, clusters: list[dict]) -> tuple[list[dict], float]:
        """Pick the best contiguous 3-5 row sequence from cluster candidates."""
        if not clusters:
            return ([], float("-inf"))
        ordered = sorted(clusters, key=lambda c: c["center_y"])
        n = len(ordered)
        best_seq: list[dict] = []
        best_score = float("-inf")

        min_k = min(self.MIN_EXPECTED_OPTIONS, n)
        max_k = min(self.MAX_EXPECTED_OPTIONS, n)
        for k in range(max_k, min_k - 1, -1):
            for i in range(0, n - k + 1):
                seq = ordered[i : i + k]
                score = self._score_cluster_sequence(seq)
                if score > best_score:
                    best_score = score
                    best_seq = seq
        return (best_seq, best_score)

    def _score_cluster_sequence(self, seq: list[dict]) -> float:
        """Score how much a sequence looks like real radio rows."""
        if not seq:
            return float("-inf")
        k = len(seq)
        if k < self.MIN_EXPECTED_OPTIONS:
            return -1e6

        xs = np.array([float(s["center_x"]) for s in seq], dtype=np.float64)
        ys = np.array([float(s["center_y"]) for s in seq], dtype=np.float64)
        rs = np.array([float(max(1, s["median_r"])) for s in seq], dtype=np.float64)
        counts = np.array([float(max(1, s.get("count", 1))) for s in seq], dtype=np.float64)

        if k > 1:
            y_diffs = np.diff(ys)
            gap_penalty = float(
                np.sum((y_diffs < self.MIN_ROW_GAP_PX) | (y_diffs > self.MAX_ROW_GAP_PX))
            )
            y_std = float(np.std(y_diffs))
        else:
            gap_penalty = 5.0
            y_std = 999.0

        x_std = float(np.std(xs))
        r_std = float(np.std(rs))
        mean_count = float(np.mean(counts))
        y_span = float(ys[-1] - ys[0]) if k > 1 else 0.0

        # Higher is better.
        score = 0.0
        if gap_penalty > 0:
            return -1e6
        score += 250.0 if self.MIN_EXPECTED_OPTIONS <= k <= self.MAX_EXPECTED_OPTIONS else -200.0
        # Strongly prefer more rows — each extra row is very valuable
        # because missing a real option is far worse than including
        # one with slight X jitter.
        score += (k * 55.0)
        score += (mean_count * 6.0)
        # X-alignment: penalise but with a soft floor — real radio
        # buttons can have x_std up to ~25 px due to camera angle.
        effective_x_std = max(0.0, x_std - 10.0)
        score -= (effective_x_std * 2.0)
        score -= (y_std * 0.7)
        score -= (r_std * 6.0)
        score -= (gap_penalty * 120.0)
        score -= (max(0.0, y_span - 1200.0) * 0.25)
        return score

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calibrated_min_row_y(self, image_h: int) -> int:
        """Return the lowest allowed Y for an option cluster.

        Uses the calibrated pixel position for option A to compute a
        generous floor.  Any circle more than half a typical inter-option
        step above calibrated-A is a phantom ("Answer here" header).

        Falls back to 0 (no filtering) when calibration data is unavailable.
        """
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
        except Exception:
            return 0

        cap_h = gm.capture_resolution[1] if gm.capture_resolution[1] > 0 else image_h

        calib_ys: list[float] = []
        for letter in OPTION_LABELS:
            exact = gm.pixel_positions.get(letter)
            if exact is not None:
                screen_y = float(exact[1])
            else:
                pos = gm.positions.get(letter)
                if pos is None:
                    continue
                cell_h = float(gm.resolution[1]) / float(max(1, gm.grid_size[1]))
                screen_y = (pos[1] + 0.5) * cell_h

            scale_y = gm.transform.get("scale_y", 1.0)
            offset_y = float(gm.transform.get("offset_y", 0.0))
            if abs(scale_y) < 1e-9:
                continue
            capture_y = (screen_y - offset_y) / scale_y
            capture_y_for_image = capture_y * image_h / max(1, cap_h)
            calib_ys.append(capture_y_for_image)

        if len(calib_ys) < 2:
            return 0

        calib_ys.sort()
        diffs = [calib_ys[i + 1] - calib_ys[i] for i in range(len(calib_ys) - 1)]
        step = float(sorted(diffs)[len(diffs) // 2]) if diffs else 200.0
        min_y = int(calib_ys[0] - step * 0.6)
        logger.debug(
            "Calibrated min_row_y=%d (calib_A_y=%.0f, step=%.0f)",
            min_y, calib_ys[0], step,
        )
        return max(0, min_y)

    def _cluster_by_y(
        self,
        circles: list[tuple[int, int, int]],
    ) -> list[dict]:
        """
        Cluster circles by Y-coordinate proximity.

        Returns list of cluster dicts, each with:
            center_x: median X of the cluster
            center_y: median Y of the cluster
            median_r: median radius
            count: number of circles in the cluster
        """
        if not circles:
            return []

        # Sort by Y
        sorted_circles = sorted(circles, key=lambda c: c[1])

        clusters: list[list[tuple[int, int, int]]] = []
        current_cluster = [sorted_circles[0]]

        for i in range(1, len(sorted_circles)):
            if sorted_circles[i][1] - sorted_circles[i - 1][1] <= self.Y_CLUSTER_GAP:
                current_cluster.append(sorted_circles[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_circles[i]]
        clusters.append(current_cluster)

        # Summarize each cluster
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

    def _drop_spacing_outliers(self, clusters: list[dict]) -> list[dict]:
        """Remove leading/trailing phantom rows that break even spacing.

        Real radio-button rows follow a roughly regular vertical rhythm.
        A phantom "Answer here" header circle will create an abnormally
        large first gap.  Similarly a phantom near the bottom can create
        an abnormally large last gap.

        Algorithm:
            1. Compute all inter-row gaps.
            2. If the first gap is > 1.8× the median of the *other* gaps,
               drop the first cluster (it's a header phantom).
            3. Repeat analogous check for the last gap.
        """
        if len(clusters) < 3:
            return clusters

        ys = [c["center_y"] for c in clusters]
        gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]

        result = list(clusters)

        # Check first row
        if len(gaps) >= 2:
            first_gap = gaps[0]
            other_gaps = gaps[1:]
            median_other = float(np.median(other_gaps))
            if median_other > 0 and first_gap > median_other * 1.8:
                logger.info(
                    "Dropping phantom header row at Y=%d (first_gap=%d, median_other=%.0f)",
                    result[0]["center_y"], first_gap, median_other,
                )
                result = result[1:]

        # Recompute gaps for trailing check
        if len(result) >= 3:
            ys2 = [c["center_y"] for c in result]
            gaps2 = [ys2[i + 1] - ys2[i] for i in range(len(ys2) - 1)]
            if len(gaps2) >= 2:
                last_gap = gaps2[-1]
                other_gaps2 = gaps2[:-1]
                median_other2 = float(np.median(other_gaps2))
                if median_other2 > 0 and last_gap > median_other2 * 1.8:
                    logger.info(
                        "Dropping phantom trailing row at Y=%d (last_gap=%d, median_other=%.0f)",
                        result[-1]["center_y"], last_gap, median_other2,
                    )
                    result = result[:-1]

        if len(result) >= self.MIN_EXPECTED_OPTIONS:
            return result
        return clusters

    def _trim_to_expected_count(
        self, clusters: list[dict], target: int, image_h: int = 0,
    ) -> list[dict]:
        """Select the best `target`-sized subset of clusters.

        Strategy:
        1. If calibration data is available, score each contiguous subset
           by how well it matches the calibrated A-E Y positions (lower
           total distance = better).  This avoids dropping a real option
           row just because the first gap is slightly larger.
        2. Fall back to spacing regularity (lowest gap std) when
           calibration is unavailable.
        """
        if target <= 0 or len(clusters) <= target:
            return clusters

        ordered = sorted(clusters, key=lambda c: c["center_y"])

        if image_h <= 0:
            image_h = max(c["center_y"] for c in ordered) + 500

        calib_ys = self._get_calibrated_option_ys(image_h=image_h)
        if calib_ys and len(calib_ys) >= target:
            sorted_cal = sorted(calib_ys.values())[:target]
            best_subset = ordered[:target]
            best_dist = float("inf")
            for start in range(len(ordered) - target + 1):
                subset = ordered[start : start + target]
                sub_ys = [c["center_y"] for c in subset]
                total = sum(
                    min(abs(sy - cy) for cy in sorted_cal)
                    for sy in sub_ys
                )
                if total < best_dist:
                    best_dist = total
                    best_subset = subset

            dropped_ys = [c["center_y"] for c in ordered if c not in best_subset]
            logger.info(
                "Trimmed options from %d to %d (calibration-guided, dropped Y=%s, "
                "total_dist=%.0f)",
                len(clusters), target, dropped_ys, best_dist,
            )
            return best_subset

        # Fallback: spacing regularity.
        best_subset = ordered[:target]
        best_std = float("inf")
        for start in range(len(ordered) - target + 1):
            subset = ordered[start : start + target]
            ys = [c["center_y"] for c in subset]
            if len(ys) < 2:
                return subset
            gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            std = float(np.std(gaps))
            if std < best_std:
                best_std = std
                best_subset = subset

        dropped_ys = [c["center_y"] for c in ordered if c not in best_subset]
        logger.info(
            "Trimmed options from %d to %d (spacing-based, dropped Y=%s, "
            "best_spacing_std=%.1f)",
            len(clusters), target, dropped_ys, best_std,
        )
        return best_subset

    def _get_calibrated_option_ys(self, image_h: int) -> dict[str, float]:
        """Load calibrated A-E Y positions in capture-image space.

        Returns dict mapping letter -> capture-space Y, or empty dict.
        """
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
        except Exception:
            return {}
        if gm.resolution[1] <= 0 or image_h <= 0:
            return {}
        cap_h = gm.capture_resolution[1] if gm.capture_resolution[1] > 0 else image_h
        scale_y = float(gm.transform.get("scale_y", 1.0))
        if abs(scale_y) < 1e-9:
            return {}
        result: dict[str, float] = {}
        for letter in OPTION_LABELS:
            pos = gm.positions.get(letter)
            if pos is None:
                continue
            _, grid_row = pos
            cell_h = float(gm.resolution[1]) / float(max(1, gm.grid_size[1]))
            screen_y = (grid_row + 0.5) * cell_h
            offset_y = float(gm.transform.get("offset_y", 0.0))
            capture_y = (screen_y - offset_y) / scale_y
            capture_y_for_image = capture_y * image_h / max(1, cap_h)
            result[letter] = capture_y_for_image
        return result

    def _compute_option_row(
        self,
        index: int,
        clusters: list[dict],
        panel_height: int,
        cy_local: int,
    ) -> tuple[int, int]:
        """
        Compute top and bottom Y for a row, returned as panel-relative.

        Uses midpoints between consecutive cluster centers as boundaries.
        cy_local is the cluster center Y relative to the panel top.
        """
        n = len(clusters)
        if n <= 1:
            half = panel_height // 6
            return (max(0, cy_local - half), min(panel_height, cy_local + half))

        # Work in panel-relative Y
        # First compute all cluster Ys relative to the panel
        # We approximate panel_top from the layout
        # Since cy_local = clusters[index]["center_y"] - panel_y,
        # we can derive panel_y:
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

    @staticmethod
    def _remove_color_watermark(bgr: np.ndarray) -> np.ndarray:
        """Remove colored watermark text (red/pink/orange) from an option crop.

        Watermarks on this exam UI are red/pink diagonal numbers.  We
        detect pixels in the red/pink hue range with moderate-to-high
        saturation and replace them with white, leaving black option
        text untouched.
        """
        import cv2

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # Red wraps around hue 0 and 180 in OpenCV's 0-180 range.
        red_lo1 = cv2.inRange(hsv, np.array([0, 40, 80]), np.array([15, 255, 255]))
        red_lo2 = cv2.inRange(hsv, np.array([160, 40, 80]), np.array([180, 255, 255]))
        # Pink/magenta range.
        pink = cv2.inRange(hsv, np.array([140, 30, 80]), np.array([170, 255, 255]))
        # Orange range (some watermarks can be orange-tinted).
        orange = cv2.inRange(hsv, np.array([10, 50, 80]), np.array([25, 255, 255]))

        watermark_mask = red_lo1 | red_lo2 | pink | orange

        # Dilate slightly so we erase edges of watermark glyphs too.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        watermark_mask = cv2.dilate(watermark_mask, kernel, iterations=1)

        cleaned = bgr.copy()
        cleaned[watermark_mask > 0] = (255, 255, 255)
        return cleaned

    def _ocr_text(self, text_region: np.ndarray) -> tuple[str, float]:
        """Run OCR on a cropped text region. Returns (text, confidence).

        Applies watermark removal (color-based), then tries multiple
        preprocessing strategies across PSM modes and returns the best.
        """
        if text_region.size == 0:
            return ("", 0.0)

        try:
            import cv2
            import pytesseract
            from controller.config import TESSERACT_CMD, OCR_TIMEOUT_SECONDS

            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()

            # Step 1: Remove colored watermarks if we have a colour image.
            if len(text_region.shape) == 3 and text_region.shape[2] == 3:
                cleaned_bgr = self._remove_color_watermark(text_region)
                gray = cv2.cvtColor(cleaned_bgr, cv2.COLOR_BGR2GRAY)
            elif len(text_region.shape) == 3:
                gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
            else:
                gray = text_region

            def _upscale(img: np.ndarray) -> np.ndarray:
                ih, iw = img.shape[:2]
                if ih < 50:
                    s = max(2, 80 // max(ih, 1))
                    return cv2.resize(img, (iw * s, ih * s), interpolation=cv2.INTER_CUBIC)
                return img

            variants: list[np.ndarray] = []

            # Variant 1: Adaptive threshold.
            cleaned1 = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 15,
            )
            variants.append(_upscale(cleaned1))

            # Variant 2: Otsu threshold.
            _, cleaned2 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(_upscale(cleaned2))

            # Variant 3: Raw grayscale.
            variants.append(_upscale(gray))

            best_text = ""
            best_conf = 0.0
            whitelist = "0123456789/.-+%()^abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ,"

            for variant in variants:
                for psm in (6, 7):
                    cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist={whitelist}"
                    try:
                        data = pytesseract.image_to_data(
                            variant,
                            output_type=pytesseract.Output.DICT,
                            config=cfg,
                            timeout=OCR_TIMEOUT_SECONDS,
                        )
                    except Exception:
                        continue
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
                    avg = (sum(confidences) / len(confidences)) if confidences else 0.0
                    if len(text) > len(best_text) or (len(text) == len(best_text) and avg > best_conf):
                        best_conf = avg
                        best_text = text

            return (best_text, best_conf)

        except Exception as e:
            logger.debug("OCR failed: %s", e)
            return ("", 0.0)
