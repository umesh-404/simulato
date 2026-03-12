"""
Image stitcher.

Combines multiple captured frames into a single composite image
representing the full question context.

Used when scrolling is required: multiple screenshots are captured
and then stitched vertically to produce stitched_question.png
(Architecture Spec Section 6).
"""

from pathlib import Path
from typing import Optional

import numpy as np

from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("image_stitcher")


class ImageStitcher:
    """
    Stitches multiple image frames vertically into a composite.
    """

    def stitch(self, image_paths: list[Path], output_path: Path) -> Path:
        """
        Stitch multiple images vertically.

        Args:
            image_paths: Ordered list of image paths (top to bottom).
            output_path: Where to save the stitched result.

        Returns:
            Path to the stitched output image.

        Raises:
            ValueError: If no images provided.
            RuntimeError: If stitching fails.
        """
        if not image_paths:
            raise ValueError("No images to stitch")

        if len(image_paths) == 1:
            import shutil
            shutil.copy2(image_paths[0], output_path)
            logger.info("Single frame — copied directly to %s", output_path.name)
            return output_path

        with ExecutionTimer("image_stitch"):
            return self._vertical_stitch(image_paths, output_path)

    def _vertical_stitch(self, image_paths: list[Path], output_path: Path) -> Path:
        try:
            import cv2
        except ImportError:
            raise RuntimeError("OpenCV required for image stitching")

        images = []
        for p in image_paths:
            img = cv2.imread(str(p))
            if img is None:
                raise RuntimeError(f"Failed to load image: {p}")
            images.append(img)
            logger.debug("Loaded frame: %s (%dx%d)", p.name, img.shape[1], img.shape[0])

        max_width = max(img.shape[1] for img in images)
        resized = []
        for img in images:
            if img.shape[1] != max_width:
                scale = max_width / img.shape[1]
                new_h = int(img.shape[0] * scale)
                img = cv2.resize(img, (max_width, new_h))
            resized.append(img)

        stitched = np.vstack(resized)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), stitched)

        logger.info(
            "Stitched %d frames -> %s (%dx%d)",
            len(images), output_path.name, stitched.shape[1], stitched.shape[0],
        )
        return output_path
