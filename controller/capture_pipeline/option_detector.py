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

    # Width of the search strip (pixels from the left edge of the answer panel)
    SEARCH_STRIP_WIDTH = 130

    # HoughCircles parameters (kept loose — we filter with clustering afterwards)
    HOUGH_DP = 1.2
    HOUGH_MIN_DIST = 20             # Pixels between circle centers
    HOUGH_PARAM1 = 80               # Canny upper threshold
    HOUGH_PARAM2 = 18               # Accumulator threshold (low → more circles)
    HOUGH_MIN_RADIUS = 5
    HOUGH_MAX_RADIUS = 25

    # Y-clustering: merge circles within this Y distance into one cluster
    Y_CLUSTER_GAP = 60              # Pixels

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

        # Step 1: Extract narrow search strip at left edge of answer panel
        strip_x1 = ap.x
        strip_x2 = min(ap.x2, ap.x + self.SEARCH_STRIP_WIDTH)
        strip_y1 = ap.y
        strip_y2 = ap.y2

        strip_img = img[strip_y1:strip_y2, strip_x1:strip_x2]
        if strip_img.size == 0:
            logger.warning("Search strip is empty")
            return OptionMap(options=[], panel_bounds=ap,
                             image_w=layout.image_w, image_h=layout.image_h)

        gray_strip = cv2.cvtColor(strip_img, cv2.COLOR_BGR2GRAY)

        # Step 2: HoughCircles on the narrow strip
        blurred = cv2.GaussianBlur(gray_strip, (9, 9), 2)
        raw_circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=self.HOUGH_DP,
            minDist=self.HOUGH_MIN_DIST,
            param1=self.HOUGH_PARAM1,
            param2=self.HOUGH_PARAM2,
            minRadius=self.HOUGH_MIN_RADIUS,
            maxRadius=self.HOUGH_MAX_RADIUS,
        )

        if raw_circles is None:
            logger.warning("No HoughCircles detected in search strip")
            return OptionMap(
                options=[], panel_bounds=ap, detection_method="none",
                image_w=layout.image_w, image_h=layout.image_h,
            )

        candidates = np.round(raw_circles[0]).astype(int)
        logger.debug("HoughCircles raw: %d candidates in strip", len(candidates))

        # Convert to absolute coordinates
        abs_candidates = []
        for cx, cy, cr in candidates:
            abs_candidates.append((strip_x1 + int(cx), strip_y1 + int(cy), int(cr)))

        # Step 3: Cluster by Y-coordinate
        clusters = self._cluster_by_y(abs_candidates)
        logger.debug("Y-clusters: %d clusters from %d candidates",
                      len(clusters), len(abs_candidates))

        if len(clusters) < self.MIN_EXPECTED_OPTIONS:
            # Try with more permissive HoughCircles
            raw_circles2 = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=1.0,
                minDist=15,
                param1=60,
                param2=12,
                minRadius=4,
                maxRadius=28,
            )
            if raw_circles2 is not None:
                candidates2 = np.round(raw_circles2[0]).astype(int)
                abs_candidates2 = []
                for cx, cy, cr in candidates2:
                    abs_candidates2.append((strip_x1 + int(cx), strip_y1 + int(cy), int(cr)))
                clusters2 = self._cluster_by_y(abs_candidates2)
                if len(clusters2) > len(clusters):
                    clusters = clusters2
                    logger.debug("Permissive pass: %d clusters from %d candidates",
                                  len(clusters2), len(candidates2))

        # Step 4: Build options from clusters
        # Sort clusters by Y (top to bottom)
        clusters.sort(key=lambda c: c["center_y"])

        # Trim to max expected options
        if len(clusters) > self.MAX_EXPECTED_OPTIONS:
            clusters = clusters[:self.MAX_EXPECTED_OPTIONS]

        options: list[DetectedOption] = []
        for i, cluster in enumerate(clusters):
            if i >= len(OPTION_LABELS):
                break

            label = OPTION_LABELS[i]
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

            # OCR text region: from right of circle to end of panel
            text_x = cx + cr + self.TEXT_OFFSET_X_PX
            text_region = img[row_top_abs:row_bottom_abs, text_x:ap.x2]

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
                click_x=cx,
                click_y=cy,
                bounds=option_bounds,
                text_confidence=text_conf,
            ))

            logger.debug(
                "Option %s: (%d,%d) r=%d text='%s' conf=%.1f",
                label, cx, cy, cr, text[:60] if text else "", text_conf,
            )

        method = "y-cluster" if options else "none"
        logger.info("Detected %d options via %s (%d raw candidates)",
                     len(options), method, len(abs_candidates))

        return OptionMap(
            options=options,
            panel_bounds=ap,
            detection_method=method,
            image_w=layout.image_w,
            image_h=layout.image_h,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    def _ocr_text(self, text_region: np.ndarray) -> tuple[str, float]:
        """Run OCR on a cropped text region. Returns (text, confidence)."""
        if text_region.size == 0:
            return ("", 0.0)

        try:
            import cv2
            import pytesseract
            from controller.config import TESSERACT_CMD, OCR_TIMEOUT_SECONDS

            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()

            # Convert to grayscale if needed
            if len(text_region.shape) == 3:
                gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
            else:
                gray = text_region

            # Upscale small regions for better OCR accuracy
            h, w = gray.shape[:2]
            if h < 30:
                scale = max(2, 60 // max(h, 1))
                gray = cv2.resize(gray, (w * scale, h * scale),
                                  interpolation=cv2.INTER_CUBIC)

            data = pytesseract.image_to_data(
                gray,
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 6",
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
