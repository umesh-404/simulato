"""
Simulato system state machine.

Defines valid states and legal transitions.
All transitions are logged (Canonical Law 14 — System State Explicitness).
Implicit state changes are forbidden.
"""

from enum import Enum

from controller.utils.logger import get_logger

logger = get_logger("state_machine")


class SystemState(str, Enum):
    IDLE = "IDLE"
    CALIBRATION = "CALIBRATION"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


# Legal transitions: source_state -> set of allowed target states.
_VALID_TRANSITIONS: dict[SystemState, set[SystemState]] = {
    SystemState.IDLE: {SystemState.CALIBRATION, SystemState.RUNNING, SystemState.STOPPED},
    SystemState.CALIBRATION: {SystemState.IDLE, SystemState.ERROR, SystemState.STOPPED},
    SystemState.RUNNING: {SystemState.PAUSED, SystemState.ERROR, SystemState.STOPPED},
    SystemState.PAUSED: {SystemState.RUNNING, SystemState.ERROR, SystemState.STOPPED},
    SystemState.ERROR: {SystemState.PAUSED, SystemState.IDLE, SystemState.STOPPED},
    SystemState.STOPPED: {SystemState.IDLE},
}


class InvalidTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class StateMachine:
    """
    Manages the lifecycle state of the Simulato system.

    Enforces that only legal transitions occur.
    Every transition is logged with source, target, and reason.
    """

    def __init__(self) -> None:
        self._state = SystemState.IDLE
        logger.info("State machine initialized in %s", self._state.value)

    @property
    def state(self) -> SystemState:
        return self._state

    def transition_to(self, target: SystemState, reason: str = "") -> None:
        if target == self._state:
            logger.warning(
                "Redundant transition requested: %s -> %s (reason: %s)",
                self._state.value, target.value, reason,
            )
            return

        if target not in _VALID_TRANSITIONS.get(self._state, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {target.value}. "
                f"Allowed targets: {sorted(s.value for s in _VALID_TRANSITIONS.get(self._state, set()))}. "
                f"Reason attempted: {reason}"
            )

        previous = self._state
        self._state = target
        logger.info(
            "State transition: %s -> %s | reason: %s",
            previous.value, self._state.value, reason,
        )

    def can_transition_to(self, target: SystemState) -> bool:
        return target in _VALID_TRANSITIONS.get(self._state, set())

    def force_error(self, reason: str) -> None:
        """
        Force transition to ERROR from any state except STOPPED.
        Used by the fail-safe and alert systems (Canonical Law 12).
        """
        if self._state == SystemState.STOPPED:
            logger.error(
                "Cannot enter ERROR from STOPPED state. Reason: %s", reason,
            )
            return
        previous = self._state
        self._state = SystemState.ERROR
        logger.error(
            "FORCED ERROR: %s -> ERROR | reason: %s",
            previous.value, reason,
        )
