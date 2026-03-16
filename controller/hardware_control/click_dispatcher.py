"""
Click dispatcher.

Maps answer letters to Pi commands and dispatches them.
Also dispatches navigation commands (NEXT, SCROLL).

Follows the Hardware Input Transaction flow
(Architecture Spec Section 10):
    1. Send click
    2. Capture screen (via callback)
    3. Verify highlight (via verification engine)
"""

from controller.hardware_control.pi_client import PiClient
from controller.utils.logger import get_logger

logger = get_logger("click_dispatcher")

LETTER_TO_COMMAND = {
    "A": "CLICK_A",
    "B": "CLICK_B",
    "C": "CLICK_C",
    "D": "CLICK_D",
}


class ClickDispatcher:
    """
    Dispatches click commands to the Pi via the PiClient.
    """

    def __init__(self, pi_client: PiClient) -> None:
        self._pi = pi_client

    @staticmethod
    def _pixel_to_absolute(pixel_x: int, pixel_y: int, width: int, height: int) -> tuple[int, int]:
        """Convert pixel coordinates to HID absolute range (0..32767)."""
        if width <= 1 or height <= 1:
            return (0, 0)
        abs_x = int(round(pixel_x * 32767 / (width - 1)))
        abs_y = int(round(pixel_y * 32767 / (height - 1)))
        return (max(0, min(32767, abs_x)), max(0, min(32767, abs_y)))

    def _coords_for(self, key: str) -> tuple[int, int] | None:
        """Load latest controller calibration and return absolute HID coords for key."""
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            pixel = gm.get_pixel_for(key)
            if pixel is None:
                return None
            return self._pixel_to_absolute(pixel[0], pixel[1], gm.resolution[0], gm.resolution[1])
        except Exception as e:
            logger.warning("Could not resolve calibrated coords for %s: %s", key, e)
            return None

    def click_option(self, letter: str) -> dict:
        """
        Click an answer option by letter.

        Args:
            letter: "A", "B", "C", or "D"

        Returns:
            Pi response dict.

        Raises:
            ValueError if letter is invalid.
        """
        command = LETTER_TO_COMMAND.get(letter.upper())
        if command is None:
            raise ValueError(f"Invalid option letter: {letter}")

        logger.info("Dispatching click for option %s -> %s", letter, command)
        coords = self._coords_for(letter.upper())
        return self._pi.send_command(command, coords=coords)

    def click_next(self) -> dict:
        logger.info("Dispatching CLICK_NEXT")
        coords = self._coords_for("NEXT")
        return self._pi.send_command("CLICK_NEXT", coords=coords)

    def scroll_left(self) -> dict:
        logger.info("Dispatching SCROLL_LEFT")
        coords = self._coords_for("SCROLL_LEFT")
        return self._pi.send_command("SCROLL_LEFT", coords=coords)

    def scroll_right(self) -> dict:
        logger.info("Dispatching SCROLL_RIGHT")
        coords = self._coords_for("SCROLL_RIGHT")
        return self._pi.send_command("SCROLL_RIGHT", coords=coords)
