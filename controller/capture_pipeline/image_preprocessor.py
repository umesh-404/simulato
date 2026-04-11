"""
Image preprocessor.

Applies preprocessing steps to captured/stitched images
before sending them to the AI model. This includes:
    - Contrast enhancement
    - Sharpening
    - Noise reduction
    - Resolution validation

The goal is to maximize OCR/AI accuracy on exam screenshots.
"""

from pathlib import Path
from typing import Optional

from controller.config import MIN_IMAGE_WIDTH
from controller.utils.logger import get_logger

logger = get_logger("image_preprocessor")


class ImagePreprocessor:
    """
    Preprocesses images for optimal AI analysis.
    """

    def preprocess(self, image_path: Path, output_path: Optional[Path] = None) -> Path:
        """
        Preprocess an image for AI consumption.

        Args:
            image_path: Input image path.
            output_path: Where to save the preprocessed image.
                         If None, saves next to input as a new file.

        Returns:
            Path to the preprocessed image.
        """
        if output_path is None:
            # Important: do not overwrite the input image.
            # Downstream code may use the raw image bytes for DB lookups (pHash).
            output_path = image_path.with_name(f"{image_path.stem}_preprocessed{image_path.suffix}")

        from controller.config import CAPTURE_MODE

        # --- Ghost mode fast-path ---
        # Ghost captures are pixel-perfect 1920×1080 sRGB screenshots via DXGI.
        # No CLAHE, no header masking, no copy needed.  Returning the original
        # path avoids ~100ms of redundant OpenCV imread + imwrite per question.
        # A lightweight sidecar meta is still written for replay/debug.
        if CAPTURE_MODE == "ghost":
            import json
            meta_path = output_path.parent / f"{output_path.stem}.preprocess_meta.json"
            meta_payload = {
                "input_image": image_path.name,
                "output_image": image_path.name,
                "mask_applied": False,
                "roi_y": 0,
                "header_anchor": {"method": "ghost_mode_skip"},
            }
            try:
                meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
            except Exception:
                pass
            logger.info("Preprocessed image saved: %s (ghost_mode_passthrough)", image_path.name)
            return image_path

        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — skipping preprocessing")
            return image_path

        img = cv2.imread(str(image_path))
        if img is None:
            logger.error("Cannot read image: %s", image_path)
            return image_path

        width = img.shape[1]
        if width < MIN_IMAGE_WIDTH:
            logger.warning(
                "Image width %d < minimum %d — quality may be degraded",
                width, MIN_IMAGE_WIDTH,
            )

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        img_enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        # --- Header anchored masking ---
        roi_y = 0
        mask_applied = False
        header_meta: dict | None = None

        try:
            from controller.capture_pipeline.header_anchor import HeaderAnchor

            anchor_meta = HeaderAnchor.locate_anchor(image_path)
            if anchor_meta is not None:
                roi_y = int(anchor_meta.roi_y)
                mask_applied = roi_y > 0
                header_meta = anchor_meta.to_dict()
            else:
                roi_y = max(0, int(img.shape[0] * HeaderAnchor.FALLBACK_HEADER_HEIGHT_FRAC) - HeaderAnchor.ROI_MARGIN_PX)
                mask_applied = roi_y > 0
                header_meta = {
                    "method": "no_template_or_match",
                    "template_path": str(HeaderAnchor.TEMPLATE_PATH),
                    "template_w": 0,
                    "template_h": 0,
                    "anchor_x": 0,
                    "anchor_y": 0,
                    "match_score": 0.0,
                    "roi_x": 0,
                    "roi_y": roi_y,
                    "roi_w": img.shape[1],
                    "roi_h": img.shape[0] - roi_y,
                }
        except Exception as e:
            logger.debug("Header anchor masking failed: %s", e)
            roi_y = 0
            mask_applied = False

        if mask_applied and roi_y > 0:
            img_enhanced[0:roi_y, :, :] = 0  # Mask out the top header region for OCR/local AI.

        cv2.imwrite(str(output_path), img_enhanced)

        # Sidecar meta for replay/debug.
        import json

        meta_path = output_path.parent / f"{output_path.stem}.preprocess_meta.json"
        meta_payload = {
            "input_image": image_path.name,
            "output_image": output_path.name,
            "mask_applied": mask_applied,
            "roi_y": int(roi_y),
            "header_anchor": header_meta,
        }
        try:
            meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Could not write preprocess meta: %s", e)

        logger.info("Preprocessed image saved: %s (mask_applied=%s, roi_y=%d)", output_path.name, mask_applied, roi_y)
        return output_path

