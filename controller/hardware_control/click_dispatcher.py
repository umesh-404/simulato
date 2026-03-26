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
    "E": "CLICK_E",
}


class ClickDispatcher:
    """
    Dispatches click commands to the Pi via the PiClient.
    """

    def __init__(self, pi_client: PiClient) -> None:
        self._pi = pi_client

    @staticmethod
    def _pixel_to_absolute(pixel_x: int, pixel_y: int, width: int, height: int) -> tuple[int, int]:
        """Convert pixel coordinates to HID absolute range (0..65535)."""
        if width <= 1 or height <= 1:
            return (0, 0)
        abs_x = int(round(pixel_x * 65535 / (width - 1)))
        abs_y = int(round(pixel_y * 65535 / (height - 1)))
        return (max(0, min(65535, abs_x)), max(0, min(65535, abs_y)))

    def _coords_for(self, key: str) -> tuple[int, int] | None:
        """Load latest controller calibration and return absolute HID coords for key."""
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            pixel = gm.get_pixel_for(key)
            if pixel is None and key.strip().upper() == "E":
                # If E was not part of the calibration grid_map, deterministically
                # extrapolate it from the calibrated A-D option row spacing.
                # This keeps click_option('E') usable for operator conflict resolution.
                pA = gm.get_pixel_for("A")
                pB = gm.get_pixel_for("B")
                pC = gm.get_pixel_for("C")
                pD = gm.get_pixel_for("D")
                if pC and pD:
                    # Average step between consecutive known rows.
                    steps = []
                    for l1, l2 in (("A", "B"), ("B", "C"), ("C", "D")):
                        p1 = gm.get_pixel_for(l1)
                        p2 = gm.get_pixel_for(l2)
                        if p1 and p2:
                            steps.append((p2[0] - p1[0], p2[1] - p1[1]))
                    if steps:
                        avg_dx = int(round(sum(dx for dx, _dy in steps) / len(steps)))
                        avg_dy = int(round(sum(dy for _dx, dy in steps) / len(steps)))
                        pixel = (pD[0] + avg_dx, pD[1] + avg_dy)
                    else:
                        pixel = (pD[0], pD[1] + (pD[1] - pC[1]))
            if pixel is None:
                return None
            return self._pixel_to_absolute(pixel[0], pixel[1], gm.resolution[0], gm.resolution[1])
        except Exception as e:
            logger.warning("Could not resolve calibrated coords for %s: %s", key, e)
            return None

    def _absolute_for_grid(self, grid_col: int, grid_row: int) -> tuple[int, int] | None:
        """Convert a calibrated grid cell to absolute HID coordinates."""
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            pixel = gm.grid_to_pixel(grid_col, grid_row)
            return self._pixel_to_absolute(pixel[0], pixel[1], gm.resolution[0], gm.resolution[1])
        except Exception as e:
            logger.warning("Could not resolve absolute coords for grid (%d,%d): %s", grid_col, grid_row, e)
            return None

    def _absolute_for_normalized(self, norm_x: float, norm_y: float) -> tuple[int, int] | None:
        """Convert normalized [0,1] capture-space coordinates to HID absolute coordinates."""
        try:
            from calibration.grid_mapper import GridMap
            gm = GridMap.load()
            capture_w, capture_h = gm.capture_resolution
            px = int(round(max(0.0, min(1.0, norm_x)) * max(1, capture_w - 1)))
            py = int(round(max(0.0, min(1.0, norm_y)) * max(1, capture_h - 1)))
            screen_x, screen_y = gm.capture_to_screen_pixel(px, py)
            return self._pixel_to_absolute(screen_x, screen_y, gm.resolution[0], gm.resolution[1])
        except Exception as e:
            logger.warning(
                "Could not resolve absolute coords for normalized target (%.4f, %.4f): %s",
                norm_x, norm_y, e,
            )
            return None

    def click_option(self, letter: str) -> dict:
        """
        Click an answer option by letter.

        Args:
            letter: "A", "B", "C", "D", or "E"

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

    def click_next_at_grid(self, grid_col: int, grid_row: int) -> dict:
        logger.info("Dispatching CLICK_NEXT at grid (%d,%d)", grid_col, grid_row)
        coords = self._absolute_for_grid(grid_col, grid_row)
        return self._pi.send_command("CLICK_NEXT", coords=coords)

    def click_at_normalized(self, norm_x: float, norm_y: float, command: str = "CLICK_NEXT") -> dict:
        """
        Click at a normalized target coordinate.

        Args:
            norm_x: X coordinate in [0, 1].
            norm_y: Y coordinate in [0, 1].
            command: Pi command label for logging/protocol consistency.
        """
        logger.info("Dispatching %s at normalized (%.4f, %.4f)", command, norm_x, norm_y)
        #region agent log
        from controller.utils.debug_ndjson import dbg as _dbg
        _dbg(
            location="controller/hardware_control/click_dispatcher.py:click_at_normalized",
            message="click_at_normalized",
            data={"command": command, "norm_x": float(norm_x), "norm_y": float(norm_y)},
            hypothesisId="H3",
        )
        #endregion agent log
        coords = self._absolute_for_normalized(norm_x, norm_y)
        return self._pi.send_command(command, coords=coords)

    def scroll_left(self) -> dict:
        logger.info("Dispatching SCROLL_LEFT")
        coords = self._coords_for("SCROLL_LEFT")
        return self._pi.send_command("SCROLL_LEFT", coords=coords)

    def scroll_right(self) -> dict:
        logger.info("Dispatching SCROLL_RIGHT")
        coords = self._coords_for("SCROLL_RIGHT")
        return self._pi.send_command("SCROLL_RIGHT", coords=coords)

    def scroll_down_at_normalized(self, norm_x: float, norm_y: float) -> dict:
        """
        Scroll down at a normalized target coordinate.
        Uses wheel scroll on Pi after moving cursor to the target.
        """
        logger.info("Dispatching SCROLL_DOWN at normalized (%.4f, %.4f)", norm_x, norm_y)
        coords = self._absolute_for_normalized(norm_x, norm_y)
        return self._pi.send_command("SCROLL_DOWN", coords=coords)
