"""
Alert manager.

Coordinates system alerts when anomalies occur (Canonical Law 6, 12).

Alert flow:
    1. Anomaly detected (conflict, verification failure, unexpected screen)
    2. Alert manager triggered
    3. Sound alarm played
    4. Remote phone notified via WebSocket/callback
    5. System enters ERROR/PAUSED state
    6. Operator decision awaited

No automatic overrides are permitted.
"""

from enum import Enum
from typing import Optional, Callable, Any
from datetime import datetime, timezone

from controller.utils.logger import get_logger

logger = get_logger("alert_manager")


class AlertType(str, Enum):
    AI_CONFLICT = "AI_CONFLICT"
    INPUT_FAILURE = "INPUT_FAILURE"
    UNEXPECTED_SCREEN = "UNEXPECTED_SCREEN"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    AI_PARSE_FAILURE = "AI_PARSE_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"


class OperatorDecision(str, Enum):
    REQUERY_AI = "REQUERY_AI"
    SKIP_QUESTION = "SKIP_QUESTION"
    USE_DATABASE_ANSWER = "USE_DATABASE_ANSWER"
    USE_AI_ANSWER = "USE_AI_ANSWER"


class Alert:
    """Represents a system alert requiring operator attention."""

    def __init__(
        self,
        alert_type: AlertType,
        message: str,
        data: Optional[dict] = None,
    ) -> None:
        self.alert_type = alert_type
        self.message = message
        self.data = data or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.resolved = False
        self.resolution: Optional[OperatorDecision] = None

    def to_payload(self) -> dict:
        return {
            "type": "SYSTEM_ALERT",
            "payload": {
                "alert_type": self.alert_type.value,
                "message": self.message,
                "timestamp": self.timestamp,
                **self.data,
            },
        }


class AlertManager:
    """
    Manages the alert lifecycle.

    When an alert is raised:
        1. Calls the sound callback (alarm)
        2. Calls the notification callback (remote phone)
        3. Stores alert for resolution
        4. Waits for operator decision
    """

    def __init__(self) -> None:
        self._sound_callback: Optional[Callable[[], None]] = None
        self._notify_callback: Optional[Callable[[dict], None]] = None
        self._pending_alert: Optional[Alert] = None
        self._decision_callback: Optional[Callable[[], OperatorDecision]] = None

    def set_sound_callback(self, callback: Callable[[], None]) -> None:
        self._sound_callback = callback

    def set_notify_callback(self, callback: Callable[[dict], None]) -> None:
        self._notify_callback = callback

    def set_decision_callback(self, callback: Callable[[], OperatorDecision]) -> None:
        self._decision_callback = callback

    @property
    def has_pending_alert(self) -> bool:
        return self._pending_alert is not None and not self._pending_alert.resolved

    def raise_alert(self, alert_type: AlertType, message: str, data: Optional[dict] = None) -> Alert:
        """
        Raise a system alert. Triggers alarm sound and remote notification.

        Returns the Alert object. The caller must wait for resolution
        via resolve_alert() before continuing.
        """
        alert = Alert(alert_type=alert_type, message=message, data=data)
        self._pending_alert = alert

        logger.error(
            "ALERT RAISED: type=%s, message=%s",
            alert_type.value, message,
        )

        if self._sound_callback:
            try:
                self._sound_callback()
            except Exception as e:
                logger.error("Sound callback failed: %s", e)

        if self._notify_callback:
            try:
                self._notify_callback(alert.to_payload())
            except Exception as e:
                logger.error("Notify callback failed: %s", e)

        return alert

    def resolve_alert(self, decision: OperatorDecision) -> None:
        """
        Resolve the pending alert with an operator decision.
        """
        if self._pending_alert is None:
            logger.warning("No pending alert to resolve")
            return

        self._pending_alert.resolved = True
        self._pending_alert.resolution = decision
        logger.info(
            "Alert resolved: type=%s, decision=%s",
            self._pending_alert.alert_type.value, decision.value,
        )
        self._pending_alert = None

    @property
    def pending_alert(self) -> Optional[Alert]:
        return self._pending_alert
