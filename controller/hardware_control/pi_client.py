"""
Raspberry Pi TCP client.

Sends HID commands to the Pi and receives execution acknowledgements.
Communication protocol: TCP socket with JSON messages
(Communication Protocols Spec Section 11).

Commands are retried up to COMMAND_MAX_RETRIES times.
If all retries fail, an error is raised for the alert system
(Canonical Law 5 — Hardware Input Transaction Safety).
"""

import json
import socket
from typing import Optional

from controller.config import PI_HOST, PI_PORT, COMMAND_ACK_TIMEOUT, COMMAND_MAX_RETRIES
from controller.utils.logger import get_logger
from controller.utils.timer import ExecutionTimer

logger = get_logger("pi_client")

VALID_COMMANDS = {
    "CLICK_A", "CLICK_B", "CLICK_C", "CLICK_D",
    "CLICK_NEXT", "SCROLL_LEFT", "SCROLL_RIGHT",
}


class PiConnectionError(Exception):
    """Raised when the Pi cannot be reached."""
    pass


class PiCommandError(Exception):
    """Raised when a command fails after all retries."""
    pass


class PiClient:
    """
    TCP client for communicating with the Raspberry Pi HID injector.

    Each command is sent as a JSON message and must receive an ACK
    within COMMAND_ACK_TIMEOUT seconds.
    """

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        self._host = host or PI_HOST
        self._port = port or PI_PORT
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(COMMAND_ACK_TIMEOUT)
            self._socket.connect((self._host, self._port))
            logger.info("Connected to Pi at %s:%d", self._host, self._port)
        except (socket.error, OSError) as e:
            logger.error("Failed to connect to Pi at %s:%d: %s", self._host, self._port, e)
            self._socket = None
            raise PiConnectionError(f"Cannot connect to Pi: {e}") from e

    def disconnect(self) -> None:
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
            logger.info("Disconnected from Pi")

    def is_connected(self) -> bool:
        return self._socket is not None

    def send_command(self, command: str) -> dict:
        """
        Send a command to the Pi and wait for ACK.

        Args:
            command: One of VALID_COMMANDS.

        Returns:
            The Pi's response dict.

        Raises:
            PiCommandError: If command fails after all retries.
            PiConnectionError: If not connected.
        """
        if command not in VALID_COMMANDS:
            raise ValueError(f"Invalid Pi command: {command}. Must be one of {VALID_COMMANDS}")

        if not self._socket:
            raise PiConnectionError("Not connected to Pi")

        last_error: Optional[Exception] = None
        for attempt in range(1, COMMAND_MAX_RETRIES + 1):
            try:
                return self._send_once(command, attempt)
            except (socket.timeout, socket.error, json.JSONDecodeError) as e:
                logger.warning(
                    "Pi command '%s' attempt %d/%d failed: %s",
                    command, attempt, COMMAND_MAX_RETRIES, e,
                )
                last_error = e

        raise PiCommandError(
            f"Command '{command}' failed after {COMMAND_MAX_RETRIES} attempts: {last_error}"
        )

    def _send_once(self, command: str, attempt: int) -> dict:
        message = json.dumps({
            "type": "PI_COMMAND",
            "payload": {"command": command},
        })

        with ExecutionTimer(f"pi_command_{command}_attempt_{attempt}"):
            self._socket.sendall((message + "\n").encode("utf-8"))
            raw = self._socket.recv(4096).decode("utf-8").strip()

        response = json.loads(raw)
        status = response.get("payload", {}).get("status", "unknown")

        if status == "executed":
            logger.info("Pi executed: %s (attempt %d)", command, attempt)
            return response
        else:
            raise socket.error(f"Pi returned status '{status}' for command '{command}'")
