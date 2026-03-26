"""
Header anchor detection.

Goal: find a stable top-bar anchor on the exam UI so downstream OCR/local AI
can run on a stable, exam-aligned region.

This module is designed to be deterministic:
- template creation is based on a single calibration screenshot
- anchor location uses cv2.matchTemplate with fixed parameters
- ROI masking never changes output image dimensions
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from controller.config import CONFIG_DIR
from controller.utils.logger import get_logger

logger = get_logger("header_anchor")


@dataclass(frozen=True)
class HeaderAnchorMeta:
    method: str
    template_path: str
    template_w: int
    template_h: int
    anchor_x: int
    anchor_y: int
    match_score: float
    roi_x: int
    roi_y: int
    roi_w: int
    roi_h: int

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "template_path": self.template_path,
            "template_w": self.template_w,
            "template_h": self.template_h,
            "anchor_x": self.anchor_x,
            "anchor_y": self.anchor_y,
            "match_score": self.match_score,
            "roi": {"x": self.roi_x, "y": self.roi_y, "w": self.roi_w, "h": self.roi_h},
        }


class HeaderAnchor:
    """
    Finds a top-bar anchor using a saved header template.
    """

    TEMPLATE_PATH = CONFIG_DIR / "header_template.jpg"

    # Search the header inside the top strip of the frame.
    SEARCH_TOP_FRAC = 0.35

    # If template match confidence is too low, fallback to a deterministic band.
    MATCH_SCORE_MIN = 0.55

    # Fallback ROI start (if no template exists or matching fails).
    FALLBACK_HEADER_HEIGHT_FRAC = 0.12

    # Margin so we include the first line(s) of options.
    ROI_MARGIN_PX = 10

    @classmethod
    def ensure_template_from_image(cls, image_path: Path, force: bool = False) -> bool:
        """
        Create the header template from the given image if it doesn't exist.

        Returns:
            True if created/saved, False if already exists or failed.
        """
        if cls.TEMPLATE_PATH.exists() and not force:
            return False

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — cannot create header template")
            return False

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Cannot read calibration image for header template: %s", image_path)
            return False

        h, w = img.shape[:2]
        header_h = max(20, int(h * cls.FALLBACK_HEADER_HEIGHT_FRAC))
        header = img[0:header_h, 0:w]

        cls.TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(cls.TEMPLATE_PATH), header)
        if ok:
            logger.info("Header template created at %s", cls.TEMPLATE_PATH)
        else:
            logger.warning("Failed to write header template to %s", cls.TEMPLATE_PATH)
        return bool(ok)

    @classmethod
    def _load_template(cls):
        if not cls.TEMPLATE_PATH.exists():
            return None
        try:
            import cv2
        except ImportError:
            return None
        templ = cv2.imread(str(cls.TEMPLATE_PATH))
        return templ

    @classmethod
    def locate_anchor(cls, image_path: Path) -> Optional[HeaderAnchorMeta]:
        """
        Locate the header anchor position and compute an exam ROI rectangle.
        """
        try:
            import cv2
        except ImportError:
            logger.debug("OpenCV not available — cannot locate header anchor")
            return None

        template = cls._load_template()
        if template is None:
            return None

        img = cv2.imread(str(image_path))
        if img is None:
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        templ_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        h, w = gray.shape[:2]
        th, tw = templ_gray.shape[:2]
        if th <= 2 or tw <= 2 or h < th or w < tw:
            return None

        search_h = min(h, int(h * cls.SEARCH_TOP_FRAC))
        search = gray[0:search_h, 0:w]
        if search.shape[0] < th:
            return None

        res = cv2.matchTemplate(search, templ_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        match_score = float(max_val)
        anchor_x, anchor_y = int(max_loc[0]), int(max_loc[1])

        if match_score < cls.MATCH_SCORE_MIN:
            roi_y = max(0, int(h * cls.FALLBACK_HEADER_HEIGHT_FRAC) - cls.ROI_MARGIN_PX)
            return HeaderAnchorMeta(
                method="fallback_band",
                template_path=str(cls.TEMPLATE_PATH),
                template_w=tw,
                template_h=th,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                match_score=match_score,
                roi_x=0,
                roi_y=roi_y,
                roi_w=w,
                roi_h=h - roi_y,
            )

        # ROI starts right after the detected header template.
        roi_y = anchor_y + th
        roi_y = max(0, min(h - 1, roi_y - cls.ROI_MARGIN_PX))
        return HeaderAnchorMeta(
            method="template_match",
            template_path=str(cls.TEMPLATE_PATH),
            template_w=tw,
            template_h=th,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            match_score=match_score,
            roi_x=0,
            roi_y=roi_y,
            roi_w=w,
            roi_h=h - roi_y,
        )

    @classmethod
    def compute_roi_rect(cls, image_h: int, anchor_meta: Optional[HeaderAnchorMeta]) -> tuple[int, int, int, int]:
        """
        Helper: compute ROI vertical bounds.

        Returns:
            (x, y, w, h)
        """
        if anchor_meta is None:
            roi_y = max(0, int(image_h * cls.FALLBACK_HEADER_HEIGHT_FRAC) - cls.ROI_MARGIN_PX)
            return (0, roi_y, 0, 0)
        return (anchor_meta.roi_x, anchor_meta.roi_y, anchor_meta.roi_w, anchor_meta.roi_h)

