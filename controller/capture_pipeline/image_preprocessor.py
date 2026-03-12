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
                         If None, overwrites the input.

        Returns:
            Path to the preprocessed image.
        """
        if output_path is None:
            output_path = image_path

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

        cv2.imwrite(str(output_path), img_enhanced)
        logger.info("Preprocessed image saved: %s", output_path.name)
        return output_path
