"""
Ghost Receiver — TCP server for the Ghost Agent.

Runs on the Main Control PC.  Listens for incoming TCP connections from
the Ghost Agent running on the exam laptop, and provides a simple
request/response interface to the rest of the Simulato controller:

    receiver = GhostReceiver(host="0.0.0.0", port=9500)
    receiver.start()                     # non-blocking, starts bg thread
    jpeg_bytes = receiver.capture()      # blocking, returns JPEG bytes
    receiver.shutdown()                  # tells agent to exit, closes

Protocol:
    - Agent connects and sends b"GHOS" (4-byte handshake magic)
    - Server responds with b"\\x06" (ACK)
    - Server sends 1-byte commands; agent responds with [4B len][payload]
    - Commands: 0x01=CAPTURE, 0x02=PING, 0xFF=SHUTDOWN
"""

import socket
import struct
import threading
import time
from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("ghost_receiver")

# Protocol constants — must match ghost_agent/agent.py.
HANDSHAKE_MAGIC = b"GHOS"
ACK_BYTE = b"\x06"

CMD_CAPTURE = bytes([0x01])
CMD_PING = bytes([0x02])
CMD_SHUTDOWN = bytes([0xFF])

# Heartbeat interval and timeout (seconds).
_HEARTBEAT_INTERVAL = 5.0
_HEARTBEAT_TIMEOUT = 2.0

# UDP discovery beacon — lets ghost agents find the controller automatically.
_DISCOVERY_PORT = 9501
_BEACON_INTERVAL = 2.0
_BEACON_MAGIC = b"SIMULATO"


class GhostReceiver:
    """TCP server that communicates with the Ghost Agent on the exam laptop.

    Thread-safety: capture() and ping() acquire ``_cmd_lock`` so that only
    one command is in-flight at a time.  The accept loop runs in its own
    daemon thread and never touches ``_cmd_lock``.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9500) -> None:
        self._host = host
        self._port = port
        self._server_sock: Optional[socket.socket] = None
        self._agent_sock: Optional[socket.socket] = None
        self._agent_addr: Optional[tuple] = None
        self._connected = False
        self._cmd_lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._beacon_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the TCP server in a background thread.

        Non-blocking.  The accept loop waits for the ghost agent to
        connect and automatically re-accepts if the connection drops.
        """
        if self._running:
            return

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.settimeout(1.0)  # allows periodic check of _running
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(1)
        self._running = True

        self._accept_thread = threading.Thread(
            target=self._accept_loop, daemon=True, name="ghost-accept"
        )
        self._accept_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="ghost-heartbeat"
        )
        self._heartbeat_thread.start()

        self._beacon_thread = threading.Thread(
            target=self._beacon_loop, daemon=True, name="ghost-beacon"
        )
        self._beacon_thread.start()

        logger.info(
            "GhostReceiver started — waiting for ghost agent connection on %s:%d",
            self._host,
            self._port,
        )
        logger.info(
            "UDP discovery beacon active on port %d",
            _DISCOVERY_PORT,
        )

    def stop(self) -> None:
        """Stop the server and close all connections."""
        self._running = False
        self._disconnect_agent()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        logger.info("GhostReceiver stopped")

    def is_connected(self) -> bool:
        """Return True if the ghost agent is currently connected."""
        return self._connected and self._agent_sock is not None

    def capture(self) -> Optional[bytes]:
        """Send CAPTURE command and return the JPEG image bytes.

        Returns None if the agent is not connected or if the capture
        fails (timeout, network error, etc.).

        Thread-safe: only one command can be in-flight at a time.
        """
        return self._send_command(CMD_CAPTURE)

    def ping(self) -> bool:
        """Send PING and wait for PONG.  Returns True on success."""
        resp = self._send_command(CMD_PING, timeout=_HEARTBEAT_TIMEOUT)
        return resp == b"PONG"

    def shutdown_agent(self) -> None:
        """Send SHUTDOWN command to the ghost agent and disconnect."""
        try:
            with self._cmd_lock:
                if self._agent_sock is not None:
                    self._agent_sock.sendall(CMD_SHUTDOWN)
        except OSError:
            pass
        self._disconnect_agent()
        logger.info("Shutdown command sent to ghost agent")

    # ------------------------------------------------------------------
    # Internal — accept loop
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        """Background thread: accept agent connections in a loop."""
        while self._running:
            try:
                assert self._server_sock is not None
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.debug("Accept loop OS error (shutting down?)")
                break

            # Validate handshake.
            try:
                conn.settimeout(5.0)
                magic = conn.recv(4)
                if magic != HANDSHAKE_MAGIC:
                    logger.warning(
                        "Invalid handshake from %s: %r (expected %r)",
                        addr,
                        magic,
                        HANDSHAKE_MAGIC,
                    )
                    conn.close()
                    continue

                conn.sendall(ACK_BYTE)
            except (OSError, socket.timeout):
                logger.warning("Handshake failed from %s", addr)
                conn.close()
                continue

            # If we already have a connected agent, disconnect the old one.
            self._disconnect_agent()

            self._agent_sock = conn
            self._agent_addr = addr
            self._connected = True
            logger.info("Ghost agent connected from %s:%d", addr[0], addr[1])

    # ------------------------------------------------------------------
    # Internal — heartbeat loop
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """Background thread: periodic PING to detect dead connections."""
        while self._running:
            time.sleep(_HEARTBEAT_INTERVAL)
            if not self._connected:
                continue

            if not self.ping():
                logger.warning(
                    "Ghost agent heartbeat failed — marking as disconnected"
                )
                self._disconnect_agent()

    # ------------------------------------------------------------------
    # Internal — UDP discovery beacon
    # ------------------------------------------------------------------

    def _beacon_loop(self) -> None:
        """Background thread: broadcast UDP beacon so agents can discover us.

        Beacon payload: b"SIMULATO|<tcp_port>"
        Sent to 255.255.255.255:<DISCOVERY_PORT> every _BEACON_INTERVAL seconds.
        """
        beacon_payload = _BEACON_MAGIC + b"|" + str(self._port).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)

        try:
            while self._running:
                try:
                    sock.sendto(beacon_payload, ("255.255.255.255", _DISCOVERY_PORT))
                except OSError:
                    pass  # network blip — retry next interval
                time.sleep(_BEACON_INTERVAL)
        finally:
            sock.close()

    # ------------------------------------------------------------------
    # Internal — command helpers
    # ------------------------------------------------------------------

    def _send_command(
        self,
        cmd: bytes,
        timeout: float = 5.0,
    ) -> Optional[bytes]:
        """Send a 1-byte command and receive the length-prefixed response.

        Returns the response payload bytes, or None on failure.
        """
        with self._cmd_lock:
            if self._agent_sock is None:
                return None

            try:
                self._agent_sock.settimeout(timeout)
                self._agent_sock.sendall(cmd)

                # Read 4-byte length header.
                len_buf = self._recv_exact(4)
                if len_buf is None:
                    self._disconnect_agent()
                    return None

                payload_len = struct.unpack(">I", len_buf)[0]
                if payload_len > 20 * 1024 * 1024:  # sanity cap: 20 MB
                    logger.error(
                        "Ghost agent payload too large: %d bytes", payload_len
                    )
                    self._disconnect_agent()
                    return None

                payload = self._recv_exact(payload_len)
                if payload is None:
                    self._disconnect_agent()
                    return None

                return payload

            except (OSError, socket.timeout, ConnectionResetError) as e:
                logger.warning("Ghost agent command failed: %s", e)
                self._disconnect_agent()
                return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        """Receive exactly ``n`` bytes from the agent socket."""
        assert self._agent_sock is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self._agent_sock.recv(n - len(buf))
            if not chunk:
                return None  # connection closed
            buf.extend(chunk)
        return bytes(buf)

    def _disconnect_agent(self) -> None:
        """Close the current agent connection (if any)."""
        if self._agent_sock is not None:
            addr_str = (
                f"{self._agent_addr[0]}:{self._agent_addr[1]}"
                if self._agent_addr
                else "unknown"
            )
            try:
                self._agent_sock.close()
            except OSError:
                pass
            self._agent_sock = None
            self._agent_addr = None
            if self._connected:
                self._connected = False
                logger.info("Ghost agent disconnected (%s)", addr_str)
