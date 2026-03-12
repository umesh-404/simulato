"""
FastAPI server for mobile device communication.

Provides HTTP endpoints and WebSocket connections for:
    - Capture Phone: image upload
    - Remote Control Phone: commands, alerts, status

Implements communication protocols defined in COMMUNICATION_PROTOCOLS.md:
    - Device registration
    - Heartbeat
    - Image upload
    - Remote commands
    - Alert distribution
    - Operator decisions

All endpoints log their activity (Canonical Law 11).
"""

import asyncio
import json
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from controller.config import CONTROLLER_HOST, CONTROLLER_PORT
from controller.utils.logger import get_logger

logger = get_logger("api_server")

app = FastAPI(title="Simulato Controller API", version="1.0.0")


# ---------------------------------------------------------------------------
# Pydantic models for request/response
# ---------------------------------------------------------------------------

class DeviceRegisterRequest(BaseModel):
    """Accepts the standard protocol envelope for DEVICE_REGISTER."""
    type: str = "DEVICE_REGISTER"
    device_id: str
    timestamp: str = ""
    payload: dict  # expects {"device_role": "capture" | "remote_control" | "pi"}


class HeartbeatRequest(BaseModel):
    """Accepts the standard protocol envelope for HEARTBEAT."""
    type: str = "HEARTBEAT"
    device_id: str
    timestamp: str = ""


class RemoteCommandRequest(BaseModel):
    """Accepts the standard protocol envelope for REMOTE_COMMAND."""
    type: str = "REMOTE_COMMAND"
    device_id: str
    timestamp: str = ""
    payload: dict  # expects {"command": "...", ...}


class OperatorDecisionRequest(BaseModel):
    """Accepts the standard protocol envelope for OPERATOR_DECISION."""
    type: str = "OPERATOR_DECISION"
    device_id: str = ""
    timestamp: str = ""
    payload: dict  # expects {"decision": "..."}


class ImageUploadRequest(BaseModel):
    """Accepts base64-encoded image upload from capture phone."""
    device_id: str = ""
    timestamp: str = ""
    image: str  # base64-encoded JPEG


class StatusResponse(BaseModel):
    system_state: str
    active_test: Optional[str] = None
    active_ai_provider: str = "gemini"
    question_number: int = 0
    api_calls: int = 0
    cache_hits: int = 0
    connected_devices: list[str] = []


# ---------------------------------------------------------------------------
# Device registry
# ---------------------------------------------------------------------------

class DeviceRegistry:
    """Tracks connected devices and their last heartbeat."""

    def __init__(self) -> None:
        self._devices: dict[str, dict] = {}
        self._websockets: dict[str, WebSocket] = {}

    def register(self, device_id: str, role: str) -> None:
        # Enforce: a device can only have one role at a time.
        existing = self._devices.get(device_id)
        if existing and existing["role"] != role:
            old_role = existing["role"]
            logger.warning(
                "Device %s re-registering: role changed from %s to %s",
                device_id, old_role, role,
            )
            self.remove_websocket(device_id)

        # Enforce: only one device per role (e.g. only one capture device).
        for did, info in list(self._devices.items()):
            if info["role"] == role and did != device_id:
                logger.warning(
                    "Role '%s' reassigned from device %s to %s",
                    role, did, device_id,
                )
                del self._devices[did]
                self.remove_websocket(did)

        self._devices[device_id] = {
            "device_id": device_id,
            "role": role,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Device registered: %s (role=%s)", device_id, role)

    def heartbeat(self, device_id: str) -> bool:
        if device_id in self._devices:
            self._devices[device_id]["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def is_registered(self, device_id: str) -> bool:
        return device_id in self._devices

    def get_device(self, device_id: str) -> Optional[dict]:
        return self._devices.get(device_id)

    def get_connected_ids(self) -> list[str]:
        return list(self._devices.keys())

    def has_role(self, role: str) -> bool:
        """Return True if any registered device currently has the given role."""
        return any(info.get("role") == role for info in self._devices.values())

    def set_websocket(self, device_id: str, ws: WebSocket) -> None:
        self._websockets[device_id] = ws

    def remove_websocket(self, device_id: str) -> None:
        self._websockets.pop(device_id, None)

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        ws = self._websockets.get(device_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error("Failed to send to %s: %s", device_id, e)
        return False

    async def broadcast_to_role(self, role: str, message: dict) -> int:
        count = 0
        for did, info in self._devices.items():
            if info["role"] == role:
                if await self.send_to_device(did, message):
                    count += 1
        return count


registry = DeviceRegistry()

_command_callback = None
_image_callback = None
_decision_callback = None
_status_provider = None
_disconnection_callback = None

_pending_alerts: deque[dict] = deque()
_event_loop = None


def set_command_callback(callback) -> None:
    global _command_callback
    _command_callback = callback


def set_image_callback(callback) -> None:
    global _image_callback
    _image_callback = callback


def set_decision_callback(callback) -> None:
    global _decision_callback
    _decision_callback = callback


def set_status_provider(provider) -> None:
    global _status_provider
    _status_provider = provider


def set_disconnection_callback(callback) -> None:
    global _disconnection_callback
    _disconnection_callback = callback


def queue_alert_for_broadcast(alert_payload: dict) -> None:
    """
    Thread-safe: enqueue an alert for async broadcast to remote devices.
    Called from synchronous AlertManager notify callback.
    """
    _pending_alerts.append(alert_payload)
    logger.debug("Alert queued for broadcast (queue size: %d)", len(_pending_alerts))


# ---------------------------------------------------------------------------
# Background tasks: alert flushing + heartbeat monitoring
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _start_background_tasks():
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    asyncio.create_task(_alert_flush_loop())
    asyncio.create_task(_heartbeat_monitor_loop())


async def _alert_flush_loop():
    """Flush queued alerts to remote control devices every 0.5s."""
    while True:
        while _pending_alerts:
            payload = _pending_alerts.popleft()
            await broadcast_alert(payload)
        await asyncio.sleep(0.5)


async def _heartbeat_monitor_loop():
    """
    Check for stale device heartbeats every 5 seconds.
    If a device hasn't sent a heartbeat in HEARTBEAT_TIMEOUT seconds,
    it is considered disconnected (Communication Protocol Section 6/14).
    """
    from controller.config import HEARTBEAT_TIMEOUT

    while True:
        await asyncio.sleep(5)
        now = datetime.now(timezone.utc)
        for device_id, info in list(registry._devices.items()):
            last_hb = datetime.fromisoformat(info["last_heartbeat"])
            elapsed = (now - last_hb).total_seconds()
            if elapsed > HEARTBEAT_TIMEOUT:
                logger.warning(
                    "Device %s heartbeat timeout (%.1fs since last)",
                    device_id, elapsed,
                )
                del registry._devices[device_id]
                registry.remove_websocket(device_id)
                if _disconnection_callback:
                    _disconnection_callback(device_id, info.get("role", "unknown"))


# ---------------------------------------------------------------------------
# HTTP Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/register")
async def register_device(req: DeviceRegisterRequest):
    device_role = req.payload.get("device_role", "unknown")
    registry.register(req.device_id, device_role)
    logger.info("Registration: device_id=%s, role=%s", req.device_id, device_role)
    return {"type": "REGISTER_ACK", "payload": {"status": "accepted"}}


@app.post("/api/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    ok = registry.heartbeat(req.device_id)
    if ok:
        return {"type": "HEARTBEAT_ACK"}
    return JSONResponse(status_code=404, content={"error": "device not registered"})


@app.post("/api/upload_image")
async def upload_image(req: ImageUploadRequest):
    """Accept base64-encoded image from capture phone."""
    import base64
    image_data = base64.b64decode(req.image)
    logger.info(
        "Image upload: device=%s, size=%d bytes, ts=%s",
        req.device_id, len(image_data), req.timestamp,
    )

    if _image_callback:
        _image_callback(image_data, req.device_id)

    return {"status": "received"}


@app.post("/api/command")
async def remote_command(req: RemoteCommandRequest):
    command = req.payload.get("command", "")
    extra_payload = {k: v for k, v in req.payload.items() if k != "command"}
    logger.info("Remote command: device=%s, command=%s", req.device_id, command)

    # Enforce: commands that depend on a capture device require one to be connected.
    if command in ("CALIBRATE", "START") and not registry.has_role("capture"):
        logger.warning("Command %s rejected — no capture device connected", command)
        return {
            "type": "COMMAND_ACK",
            "payload": {
                "status": "error",
                "error": "No capture device connected. Please connect the capture phone first.",
            },
        }

    if _command_callback:
        result = _command_callback(command, extra_payload or None)
        return {"type": "COMMAND_ACK", "payload": {"status": "accepted", "result": result}}

    return {"type": "COMMAND_ACK", "payload": {"status": "accepted"}}


@app.post("/api/operator_decision")
async def operator_decision(req: OperatorDecisionRequest):
    decision = req.payload.get("decision", "")
    logger.info("Operator decision received: %s", decision)

    if _decision_callback:
        _decision_callback(decision)

    return {"type": "DECISION_ACK", "payload": {"status": "accepted"}}


@app.get("/api/status")
async def get_status():
    if _status_provider:
        return _status_provider()
    return StatusResponse(system_state="UNKNOWN")


# ---------------------------------------------------------------------------
# WebSocket endpoint for real-time communication
# ---------------------------------------------------------------------------

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    if device_id not in registry._devices:
        logger.warning("WebSocket rejected: %s is not registered", device_id)
        # Using 4000s range for custom application errors
        await websocket.close(code=4003, reason="Device not registered")
        return

    await websocket.accept()
    registry.set_websocket(device_id, websocket)
    logger.info("WebSocket connected: %s", device_id)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type", "")

            if msg_type == "HEARTBEAT":
                registry.heartbeat(device_id)
                await websocket.send_json({"type": "HEARTBEAT_ACK"})

            elif msg_type == "OPERATOR_DECISION":
                decision = message.get("payload", {}).get("decision", "")
                logger.info("WS operator decision from %s: %s", device_id, decision)
                if _decision_callback:
                    _decision_callback(decision)

            else:
                logger.debug("WS message from %s: %s", device_id, msg_type)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", device_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", device_id, e)
    finally:
        registry.remove_websocket(device_id)


# ---------------------------------------------------------------------------
# Alert broadcasting
# ---------------------------------------------------------------------------

async def broadcast_alert(alert_payload: dict) -> int:
    """Send an alert to all remote control devices."""
    count = await registry.broadcast_to_role("remote_control", alert_payload)
    logger.info("Alert broadcast to %d remote control device(s)", count)
    return count
