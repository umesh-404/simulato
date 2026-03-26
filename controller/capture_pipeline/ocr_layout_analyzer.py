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

    def get_option_map(self):
        if self.image_path is None or self.layout is None:
            return None
        if self._option_map_cache is None:
            self._option_map_cache = OptionDetector().detect(self.image_path, self.layout)
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
            self._option_map_cache = OptionDetector().detect(self.image_path, self.layout)
        opt = self._option_map_cache.get(letter)
        if opt is None:
            # Geometric fallback: if an exact label is missing due partial detection,
            # extrapolate row center from detected radio-row sequence instead of
            # falling back to stale calibration grid coordinates.
            options = list(self._option_map_cache.options)
            if len(options) < 2:
                return None
            options = sorted(options, key=lambda o: o.circle_y)
            ys = [int(o.circle_y) for o in options]
            xs = [int(o.circle_x) for o in options]
            # Median row step between detected radio rows.
            diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            diffs = [d for d in diffs if d > 0]
            if not diffs:
                return None
            step = int(round(float(sorted(diffs)[len(diffs) // 2])))
            if step < 12 or step > 500:
                return None

            req_idx = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}[letter]
            base_idx = min(req_idx, len(ys) - 1)
            y = ys[base_idx]
            if req_idx > len(ys) - 1:
                y = ys[-1] + step * (req_idx - (len(ys) - 1))
            x = int(round(sum(xs) / max(1, len(xs))))

            if self.answer_panel is not None:
                x = max(self.answer_panel.x, min(self.answer_panel.x2 - 1, x))
                y = max(self.answer_panel.y, min(self.answer_panel.y2 - 1, y))
            return self._norm(int(x), int(y))
        return self._norm(int(opt.click_x), int(opt.click_y))

    def locate_next_target(self) -> Optional[tuple[float, float]]:
        next_words: list[OCRWord] = []
        for w in self.words:
            txt = re.sub(r"[^a-zA-Z]", "", w.text).lower()
            if "next" in txt:
                next_words.append(w)
        if not next_words:
            return None
        # Prefer bottom-right NEXT if multiple are found.
        best = sorted(next_words, key=lambda w: (w.y + w.x, w.conf), reverse=True)[0]
        return self._norm(best.cx, best.cy)


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

