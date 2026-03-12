"""
Command listener for Raspberry Pi.

Listens for TCP connections from the Main Control PC and
executes HID commands. Each command is acknowledged after execution.

Protocol: JSON over TCP (Communication Protocols Spec Section 11-12).
"""

import json
import socket
import sys
from typing import Optional

from raspberry_pi.device_config import LISTEN_HOST, LISTEN_PORT
from raspberry_pi.hid_controller import HIDController

GRID_MAP: dict[str, tuple[int, int]] = {}


def load_grid_map(grid_data: dict) -> None:
    """Load grid coordinate mapping from controller."""
    global GRID_MAP
    GRID_MAP = {}
    for name, coords in grid_data.items():
        GRID_MAP[name] = (int(coords[0]), int(coords[1]))


def _command_to_coords(command: str) -> Optional[tuple[int, int]]:
    """Map a command name to screen pixel coordinates."""
    letter_map = {
        "CLICK_A": "A",
        "CLICK_B": "B",
        "CLICK_C": "C",
        "CLICK_D": "D",
        "CLICK_NEXT": "NEXT",
        "SCROLL_LEFT": "SCROLL_LEFT",
        "SCROLL_RIGHT": "SCROLL_RIGHT",
    }
    key = letter_map.get(command)
    if key:
        return GRID_MAP.get(key)
    return None


def run_listener() -> None:
    """Main listener loop — accepts connections and processes commands."""
    hid = HIDController()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(1)

    print(f"[Pi] Listening on {LISTEN_HOST}:{LISTEN_PORT}")

    while True:
        conn, addr = server.accept()
        print(f"[Pi] Connection from {addr}")

        try:
            _handle_connection(conn, hid)
        except Exception as e:
            print(f"[Pi] Connection error: {e}")
        finally:
            conn.close()


def _handle_connection(conn: socket.socket, hid: HIDController) -> None:
    """Handle a single connection from the controller."""
    buffer = ""
    while True:
        data = conn.recv(4096)
        if not data:
            break
        buffer += data.decode("utf-8")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
                response = _process_message(message, hid)
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            except json.JSONDecodeError as e:
                error_resp = {"type": "PI_RESPONSE", "payload": {"status": "error", "detail": str(e)}}
                conn.sendall((json.dumps(error_resp) + "\n").encode("utf-8"))


def _process_message(message: dict, hid: HIDController) -> dict:
    """Process a single command message."""
    msg_type = message.get("type", "")
    command = message.get("payload", {}).get("command", "")

    if msg_type != "PI_COMMAND":
        return {"type": "PI_RESPONSE", "payload": {"status": "error", "detail": f"Unknown type: {msg_type}"}}

    coords = _command_to_coords(command)
    if coords is None:
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "error", "detail": "Unknown command or no coordinates"}}

    try:
        hid.click_at(coords[0], coords[1])
        print(f"[Pi] Executed: {command} at {coords}")
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "executed"}}
    except Exception as e:
        print(f"[Pi] Execution error: {command}: {e}")
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "error", "detail": str(e)}}


if __name__ == "__main__":
    run_listener()
