"""
Command listener for Raspberry Pi.

Listens for TCP connections from the Main Control PC and
executes HID commands. Each command is acknowledged after execution.

Protocol: JSON over TCP (Communication Protocols Spec Section 11-12).
"""

import json
import socket
import sys
from pathlib import Path
from typing import Optional

from raspberry_pi.device_config import LISTEN_HOST, LISTEN_PORT
from raspberry_pi.hid_controller import HIDController

GRID_MAP: dict[str, tuple[int, int]] = {}
MAX_BUFFER_BYTES = 65536


def load_grid_map(grid_data: dict) -> None:
    """Load grid coordinate mapping from controller."""
    global GRID_MAP
    GRID_MAP = {}
    for name, coords in grid_data.items():
        GRID_MAP[name] = (int(coords[0]), int(coords[1]))


def _load_grid_map_from_file() -> None:
    """Load optional fallback coordinates from local config/grid_map.json."""
    root = Path(__file__).resolve().parent.parent
    path = root / "config" / "grid_map.json"
    if not path.exists():
        print(f"[Pi] No local grid map found at {path}, waiting for command coords")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        resolution = data.get("resolution", [1920, 1080])
        grid_size = data.get("grid_size", [20, 20])
        positions = data.get("positions", {})
        width = max(1, int(resolution[0]))
        height = max(1, int(resolution[1]))
        cols = max(1, int(grid_size[0]))
        rows = max(1, int(grid_size[1]))
        converted: dict[str, tuple[int, int]] = {}
        for name, grid_coords in positions.items():
            gc = int(grid_coords[0])
            gr = int(grid_coords[1])
            px = int((gc + 0.5) * (width / cols))
            py = int((gr + 0.5) * (height / rows))
            ax = max(0, min(32767, int(round(px * 32767 / max(1, width - 1)))))
            ay = max(0, min(32767, int(round(py * 32767 / max(1, height - 1)))))
            converted[name] = (ax, ay)
        load_grid_map(converted)
        print(f"[Pi] Loaded fallback grid map with {len(converted)} positions")
    except Exception as e:
        print(f"[Pi] Failed to load local grid map: {e}")


def _command_to_coords(command: str) -> Optional[tuple[int, int]]:
    """Map a command name to screen pixel coordinates."""
    letter_map = {
        "CLICK_A": "A",
        "CLICK_B": "B",
        "CLICK_C": "C",
        "CLICK_D": "D",
        "CLICK_E": "E",
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
    _load_grid_map_from_file()

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
        if len(buffer.encode("utf-8")) > MAX_BUFFER_BYTES:
            error_resp = {
                "type": "PI_RESPONSE",
                "payload": {"status": "error", "detail": f"Input frame exceeded {MAX_BUFFER_BYTES} bytes"},
            }
            conn.sendall((json.dumps(error_resp) + "\n").encode("utf-8"))
            buffer = ""
            continue

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
    payload = message.get("payload", {})
    command = payload.get("command", "")

    if msg_type != "PI_COMMAND":
        return {"type": "PI_RESPONSE", "payload": {"status": "error", "detail": f"Unknown type: {msg_type}"}}

    coords_payload = payload.get("coords")
    coords = None
    if isinstance(coords_payload, list) and len(coords_payload) == 2:
        try:
            coords = (int(coords_payload[0]), int(coords_payload[1]))
        except Exception:
            coords = None
    if coords is None:
        coords = _command_to_coords(command)
    if coords is None:
        detail = "Unknown command or no coordinates"
        # If controller didn't provide coords, we fall back to local grid_map.json.
        # If that fallback is missing a key (often E), report it explicitly.
        if command in ("CLICK_A", "CLICK_B", "CLICK_C", "CLICK_D", "CLICK_E", "CLICK_NEXT", "SCROLL_LEFT", "SCROLL_RIGHT"):
            detail = (
                "No coords provided by controller and local grid_map.json has no entry for this command "
                "(grid map may be outdated/incomplete)."
            )
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "error", "detail": detail}}

    try:
        hid.click_at(coords[0], coords[1])
        print(f"[Pi] Executed: {command} at {coords}")
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "executed"}}
    except Exception as e:
        print(f"[Pi] Execution error: {command}: {e}")
        return {"type": "PI_RESPONSE", "payload": {"command": command, "status": "error", "detail": str(e)}}


if __name__ == "__main__":
    run_listener()
