"""
Image receiver.

Receives captured images from the Capture Phone via the FastAPI endpoint.
Images are saved to the current run's screenshot directory
with deterministic naming for replay support.
"""

import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("image_receiver")


class ImageReceiver:
    """
    Manages receipt and storage of captured exam screenshots.
    """

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._screenshots_dir = run_dir / "screenshots"
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._capture_count = 0
        self._latest_path: Optional[Path] = None

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def latest_path(self) -> Optional[Path]:
        return self._latest_path

    def receive_image(self, image_data: bytes, device_id: str = "") -> Path:
        """
        Save a received image and return its path.

        Args:
            image_data: Raw image bytes (JPEG).
            device_id: Identifier of the sending device.

        Returns:
            Path to the saved image file.
        """
        self._capture_count += 1
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"capture_{self._capture_count:04d}_{timestamp}.jpg"
        path = self._screenshots_dir / filename

        path.write_bytes(image_data)
        self._latest_path = path

        logger.info(
            "Image received: %s (%d bytes, device=%s)",
            filename, len(image_data), device_id,
        )
        return path

    def receive_base64_image(self, base64_data: str, device_id: str = "") -> Path:
        """
        Decode a base64-encoded image and save it.
        """
        image_bytes = base64.b64decode(base64_data)
        return self.receive_image(image_bytes, device_id)

    @property
    def capture_count(self) -> int:
        return self._capture_count
