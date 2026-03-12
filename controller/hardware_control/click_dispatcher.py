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
        return self._pi.send_command(command)

    def click_next(self) -> dict:
        logger.info("Dispatching CLICK_NEXT")
        return self._pi.send_command("CLICK_NEXT")

    def scroll_left(self) -> dict:
        logger.info("Dispatching SCROLL_LEFT")
        return self._pi.send_command("SCROLL_LEFT")

    def scroll_right(self) -> dict:
        logger.info("Dispatching SCROLL_RIGHT")
        return self._pi.send_command("SCROLL_RIGHT")
