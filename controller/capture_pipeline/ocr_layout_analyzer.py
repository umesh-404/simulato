"""
OCR layout analyzer.

Runs OCR over the whole screen to infer clickable targets for:
- answer options A/B/C/D
- NEXT button

This module is deterministic and returns normalized coordinates in [0,1].
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from controller.config import (
    OCR_MIN_WORD_CONFIDENCE,
    OCR_PSM,
    OCR_TIMEOUT_SECONDS,
    TESSERACT_CMD,
)
from controller.utils.logger import get_logger
from controller.capture_pipeline.exam_layout import ExamLayoutDetector, Rect
from controller.capture_pipeline.exam_layout import ExamLayout
from controller.capture_pipeline.option_detector import OptionDetector
from controller.answer_engine.option_matcher import match_option_by_content

logger = get_logger("ocr_layout")


@dataclass(frozen=True)
class OCRWord:
    text: str
    conf: float
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + (self.w // 2)

    @property
    def cy(self) -> int:
        return self.y + (self.h // 2)


class OCRLayoutResult:
    def __init__(
        self,
        image_w: int,
        image_h: int,
        words: list[OCRWord],
        answer_panel: Optional[Rect] = None,
        image_path: Optional[Path] = None,
        layout: Optional[ExamLayout] = None,
    ) -> None:
        self.image_w = image_w
        self.image_h = image_h
        self.words = words
        # Used to constrain A/B/C/D anchors to the answer panel.
        self.answer_panel = answer_panel
        self.image_path = image_path
        self.layout = layout
        self._option_map_cache: Optional[Any] = None
        self._max_options: int | None = None  # Set by workflow after AI response

    def detect_question_number(self) -> Optional[tuple[int, int]]:
        """Extract the current question number and total from OCR words.

        Looks for patterns like "Question No : 3 / 30" or just "3 / 30"
        in the top portion of the screen (header area).

        Returns:
            (current_question, total_questions) or None.
        """
        # Collect words from the top 20% of the image (header area).
        header_limit = int(self.image_h * 0.20)
        header_words = [w for w in self.words if w.y < header_limit]

        # Build a single text line from header words sorted left-to-right.
        header_words.sort(key=lambda w: (w.y // 30, w.x))
        header_text = " ".join(w.text for w in header_words)

        # Pattern: "N / M" or "N/M" where N and M are digits.
        m = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})", header_text)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            if 1 <= current <= total <= 999:
                return (current, total)

        # Fallback: look for "Question" followed by number.
        m = re.search(r"[Qq]uestion\s*(?:[Nn]o\.?\s*:?\s*)?(\d{1,3})", header_text)
        if m:
            current = int(m.group(1))
            return (current, 0)

        return None

    def set_max_options(self, max_options: int | None) -> None:
        """Set expected option count (from AI response) to constrain detection."""
        if max_options != self._max_options:
            self._option_map_cache = None  # Invalidate cache on change
            self._max_options = max_options

    def get_option_map(self):
        if self.image_path is None or self.layout is None:
            return None
        if self._option_map_cache is None:
            self._option_map_cache = OptionDetector().detect(
                self.image_path, self.layout, max_options=self._max_options,
            )
        return self._option_map_cache

    def _norm(self, x: int, y: int) -> tuple[float, float]:
        nx = max(0.0, min(1.0, float(x) / float(max(1, self.image_w - 1))))
        ny = max(0.0, min(1.0, float(y) / float(max(1, self.image_h - 1))))
        return (nx, ny)

    def _letter_anchors(self) -> dict[str, list[OCRWord]]:
        anchors: dict[str, list[OCRWord]] = {"A": [], "B": [], "C": [], "D": []}
        for w in self.words:
            if self.answer_panel is not None:
                # Constrain anchors to the answer panel region to avoid
                # picking stray A/B/C/D letters elsewhere on the screen.
                if not (self.answer_panel.x <= w.cx <= self.answer_panel.x2):
                    continue
                if not (self.answer_panel.y <= w.cy <= self.answer_panel.y2):
                    continue
            txt = w.text.strip().upper()
            cleaned = re.sub(r"[^A-Z]", "", txt)
            if cleaned in anchors and len(cleaned) == 1:
                anchors[cleaned].append(w)
        return anchors

    def locate_option_target(self, letter: str) -> Optional[tuple[float, float]]:
        letter = letter.strip().upper()
        if letter not in {"A", "B", "C", "D", "E"}:
            return None

        # Deterministic source of truth: use the radio-circle Y-clustering
        # from OptionDetector (no OCR-letter anchoring on the exam UI).
        if self.image_path is None or self.layout is None:
            return None
        if self._option_map_cache is None:
            self._option_map_cache = OptionDetector().detect(
                self.image_path, self.layout, max_options=self._max_options,
            )
        opt = self._option_map_cache.get(letter)
        if opt is None:
            options = list(self._option_map_cache.options)
            if len(options) < 2:
                return None
            options = sorted(options, key=lambda o: o.circle_y)
            ys = [int(o.circle_y) for o in options]
            xs = [int(o.circle_x) for o in options]
            labels = [o.label for o in options]
            diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            diffs = [d for d in diffs if d > 0]
            if not diffs:
                return None
            step = int(round(float(sorted(diffs)[len(diffs) // 2])))
            if step < 12 or step > 500:
                return None

            label_idx_map = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
            req_idx = label_idx_map[letter]
            x = int(round(sum(xs) / max(1, len(xs))))

            first_label_idx = label_idx_map.get(labels[0], 0)
            last_label_idx = label_idx_map.get(labels[-1], 4)

            if req_idx < first_label_idx:
                y = ys[0] - step * (first_label_idx - req_idx)
            elif req_idx > last_label_idx:
                y = ys[-1] + step * (req_idx - last_label_idx)
            else:
                for i, lbl in enumerate(labels):
                    if label_idx_map.get(lbl, -1) >= req_idx:
                        offset = label_idx_map.get(lbl, 0) - req_idx
                        y = ys[i] - step * offset
                        break
                else:
                    y = ys[-1] + step

            if self.answer_panel is not None:
                x = max(self.answer_panel.x, min(self.answer_panel.x2 - 1, x))
                y = max(self.answer_panel.y, min(self.answer_panel.y2 - 1, y))
            logger.info(
                "Extrapolated option %s from %d detected rows (step=%d, y=%d, labels=%s)",
                letter, len(ys), step, y, labels,
            )
            return self._norm(int(x), int(y))
        return self._norm(int(opt.click_x), int(opt.click_y))

    def locate_option_target_by_content(
        self,
        answer_text: str,
        fallback_letter: str,
    ) -> Optional[tuple[str, tuple[float, float]]]:
        """
        Resolve option target by current on-screen option text first, then fallback letter.

        Returns:
            (resolved_letter, (norm_x, norm_y)) when available, otherwise None.
        """
        option_map = self.get_option_map()
        if option_map is None or not option_map.options:
            target = self.locate_option_target(fallback_letter)
            if target is None:
                return None
            return (fallback_letter.strip().upper(), target)

        current_options = {opt.label: (opt.text or "") for opt in option_map.options}
        ans = (answer_text or "").strip()
        if ans:
            match = match_option_by_content(ans, current_options)
            if match.found and match.matched_letter:
                opt = option_map.get(match.matched_letter)
                if opt is not None:
                    return (
                        match.matched_letter,
                        self._norm(int(opt.click_x), int(opt.click_y)),
                    )

        # Deterministic fallback to caller-provided letter if content match fails.
        fallback = fallback_letter.strip().upper()
        opt = option_map.get(fallback)
        if opt is not None:
            return (fallback, self._norm(int(opt.click_x), int(opt.click_y)))
        target = self.locate_option_target(fallback)
        if target is None:
            return None
        return (fallback, target)

    def locate_next_target(self) -> Optional[tuple[float, float]]:
        # --- Priority 1: Use the layout detector's next_button bounding box.
        # This is the most reliable because it uses a dedicated bottom-bar
        # OCR scan and returns the full button rect, not just the text center.
        if self.layout is not None and self.layout.next_button is not None:
            nb = self.layout.next_button
            # Click the center of the button rect.
            cx = nb.x + nb.w // 2
            cy = nb.y + nb.h // 2
            logger.debug(
                "NEXT target from layout detector: (%d,%d) btn=(%d,%d,%d,%d)",
                cx, cy, nb.x, nb.y, nb.w, nb.h,
            )
            return self._norm(cx, cy)

        # --- Priority 2: CV-based green/blue button detection in bottom bar.
        cv_target = self._detect_next_button_by_color()
        if cv_target is not None:
            return cv_target

        # --- Priority 3: OCR word search for "next" anywhere on screen.
        next_words: list[OCRWord] = []
        for w in self.words:
            txt = re.sub(r"[^a-zA-Z]", "", w.text).lower()
            if "next" in txt:
                next_words.append(w)
        if not next_words:
            return None
        best = sorted(next_words, key=lambda w: (w.y + w.x, w.conf), reverse=True)[0]
        target_y = best.cy + int(best.h * 0.25)
        return self._norm(best.cx, target_y)

    def _detect_next_button_by_color(self) -> Optional[tuple[float, float]]:
        """Find the NEXT button by detecting colored button shapes in the bottom bar.

        The exam UI has distinctive blue/green buttons ("Prev", "Next") in
        the bottom-right corner.  We scan the bottom 10% of the image for
        saturated blue/green rectangles and pick the rightmost one.
        """
        if self.image_path is None:
            return None
        try:
            import cv2
            img = cv2.imread(str(self.image_path))
            if img is None:
                return None
            h, w = img.shape[:2]

            # Bottom bar region: bottom 10% of image, right 60%.
            bar_y1 = int(h * 0.88)
            bar_x1 = int(w * 0.40)
            bar = img[bar_y1:h, bar_x1:w]
            hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)

            # Detect blue buttons (H: 90-130, S: 50+, V: 50+)
            blue_mask = cv2.inRange(hsv, (90, 50, 50), (130, 255, 255))
            # Detect green buttons (H: 35-85, S: 50+, V: 50+)
            green_mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255))
            combined = cv2.bitwise_or(blue_mask, green_mask)

            # Morphological close to merge fragmented button regions.
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 8))
            combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None

            # Filter by minimum button size.
            min_area = int((w * 0.03) * (h * 0.02))
            candidates = []
            for c in contours:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bw * bh < min_area:
                    continue
                if bh < 10 or bw < 20:
                    continue
                # Convert to absolute image coordinates.
                abs_cx = bar_x1 + bx + bw // 2
                abs_cy = bar_y1 + by + bh // 2
                candidates.append((abs_cx, abs_cy, bw * bh))

            if not candidates:
                return None

            # The rightmost candidate is most likely "Next" (Prev is to its left).
            rightmost = max(candidates, key=lambda c: c[0])
            logger.debug(
                "NEXT button detected by color: center=(%d,%d) area=%d",
                rightmost[0], rightmost[1], rightmost[2],
            )
            return self._norm(rightmost[0], rightmost[1])

        except Exception:
            return None


class OCRLayoutAnalyzer:
    def analyze(self, image_path: Path) -> Optional[OCRLayoutResult]:
        try:
            import cv2
        except Exception as e:
            logger.debug("OCR analyzer unavailable: %s", e)
            return None

        pytesseract = None
        Output = None
        try:
            import pytesseract as _pytesseract
            from pytesseract import Output as _Output
            pytesseract = _pytesseract
            Output = _Output
            if TESSERACT_CMD.strip():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD.strip()
        except Exception as e:
            logger.warning("pytesseract unavailable; continuing with layout-only option targeting: %s", e)

        img = cv2.imread(str(image_path))
        if img is None:
            return None
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Use deterministic layout detection to constrain anchors.
        layout: Optional[ExamLayout] = None
        try:
            layout = ExamLayoutDetector().detect(image_path)
            answer_panel = layout.answer_panel
        except Exception as e:
            logger.debug("ExamLayoutDetector failed inside OCR analyzer: %s", e)
            answer_panel = None

        words: list[OCRWord] = []
        if pytesseract is not None and Output is not None:
            try:
                data = pytesseract.image_to_data(
                    gray,
                    output_type=Output.DICT,
                    config=f"--oem 3 --psm {OCR_PSM}",
                    timeout=OCR_TIMEOUT_SECONDS,
                )
                n = len(data.get("text", []))
                for i in range(n):
                    txt = str(data["text"][i]).strip()
                    if not txt:
                        continue
                    try:
                        conf = float(data["conf"][i])
                    except Exception:
                        conf = -1.0
                    if conf < OCR_MIN_WORD_CONFIDENCE:
                        continue
                    words.append(
                        OCRWord(
                            text=txt,
                            conf=conf,
                            x=int(data["left"][i]),
                            y=int(data["top"][i]),
                            w=max(1, int(data["width"][i])),
                            h=max(1, int(data["height"][i])),
                        )
                    )
            except Exception as e:
                logger.warning("OCR text extraction failed; continuing with layout-only option targeting: %s", e)

        logger.info("OCR words extracted: %d", len(words))
        return OCRLayoutResult(
            image_w=w,
            image_h=h,
            words=words,
            answer_panel=answer_panel,
            image_path=image_path,
            layout=layout,
        )

