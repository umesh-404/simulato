"""
Unit tests for the system state machine.

Validates:
    - Legal state transitions
    - Illegal transition rejection
    - Force error behavior
    - State property access
    - Canonical Law 14 (System State Explicitness)
"""

import pytest

from controller.orchestrator.state_machine import (
    StateMachine,
    SystemState,
    InvalidTransitionError,
)


class TestInitialState:

    def test_initial_state_is_idle(self):
        sm = StateMachine()
        assert sm.state == SystemState.IDLE

    def test_state_is_system_state_enum(self):
        sm = StateMachine()
        assert isinstance(sm.state, SystemState)


class TestLegalTransitions:

    def test_idle_to_calibration(self):
        sm = StateMachine()
        sm.transition_to(SystemState.CALIBRATION, "test")
        assert sm.state == SystemState.CALIBRATION

    def test_idle_to_running(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        assert sm.state == SystemState.RUNNING

    def test_idle_to_stopped(self):
        sm = StateMachine()
        sm.transition_to(SystemState.STOPPED, "test")
        assert sm.state == SystemState.STOPPED

    def test_calibration_to_idle(self):
        sm = StateMachine()
        sm.transition_to(SystemState.CALIBRATION, "test")
        sm.transition_to(SystemState.IDLE, "test")
        assert sm.state == SystemState.IDLE

    def test_running_to_paused(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.transition_to(SystemState.PAUSED, "test")
        assert sm.state == SystemState.PAUSED

    def test_paused_to_running(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.transition_to(SystemState.PAUSED, "test")
        sm.transition_to(SystemState.RUNNING, "resume")
        assert sm.state == SystemState.RUNNING

    def test_running_to_stopped(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.transition_to(SystemState.STOPPED, "test")
        assert sm.state == SystemState.STOPPED

    def test_stopped_to_idle(self):
        sm = StateMachine()
        sm.transition_to(SystemState.STOPPED, "test")
        sm.transition_to(SystemState.IDLE, "reset")
        assert sm.state == SystemState.IDLE

    def test_error_to_paused(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.force_error("test error")
        sm.transition_to(SystemState.PAUSED, "recover")
        assert sm.state == SystemState.PAUSED

    def test_error_to_idle(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.force_error("test error")
        sm.transition_to(SystemState.IDLE, "reset")
        assert sm.state == SystemState.IDLE


class TestIllegalTransitions:

    def test_idle_to_paused_fails(self):
        sm = StateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(SystemState.PAUSED, "test")

    def test_idle_to_error_fails(self):
        sm = StateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(SystemState.ERROR, "test")

    def test_calibration_to_running_fails(self):
        sm = StateMachine()
        sm.transition_to(SystemState.CALIBRATION, "test")
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(SystemState.RUNNING, "test")

    def test_stopped_to_running_fails(self):
        sm = StateMachine()
        sm.transition_to(SystemState.STOPPED, "test")
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(SystemState.RUNNING, "test")

    def test_stopped_to_paused_fails(self):
        sm = StateMachine()
        sm.transition_to(SystemState.STOPPED, "test")
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(SystemState.PAUSED, "test")


class TestRedundantTransition:

    def test_redundant_does_not_raise(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.transition_to(SystemState.RUNNING, "redundant")
        assert sm.state == SystemState.RUNNING


class TestCanTransitionTo:

    def test_can_from_idle(self):
        sm = StateMachine()
        assert sm.can_transition_to(SystemState.CALIBRATION)
        assert sm.can_transition_to(SystemState.RUNNING)
        assert sm.can_transition_to(SystemState.STOPPED)
        assert not sm.can_transition_to(SystemState.PAUSED)
        assert not sm.can_transition_to(SystemState.ERROR)

    def test_can_from_running(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        assert sm.can_transition_to(SystemState.PAUSED)
        assert sm.can_transition_to(SystemState.ERROR)
        assert sm.can_transition_to(SystemState.STOPPED)
        assert not sm.can_transition_to(SystemState.IDLE)
        assert not sm.can_transition_to(SystemState.CALIBRATION)


class TestForceError:

    def test_force_error_from_running(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.force_error("something broke")
        assert sm.state == SystemState.ERROR

    def test_force_error_from_idle(self):
        sm = StateMachine()
        sm.force_error("startup failure")
        assert sm.state == SystemState.ERROR

    def test_force_error_from_paused(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "test")
        sm.transition_to(SystemState.PAUSED, "test")
        sm.force_error("new error")
        assert sm.state == SystemState.ERROR

    def test_force_error_from_stopped_no_effect(self):
        sm = StateMachine()
        sm.transition_to(SystemState.STOPPED, "test")
        sm.force_error("shouldn't work")
        assert sm.state == SystemState.STOPPED

    def test_force_error_from_calibration(self):
        sm = StateMachine()
        sm.transition_to(SystemState.CALIBRATION, "test")
        sm.force_error("cal error")
        assert sm.state == SystemState.ERROR


class TestFullWorkflow:
    """Test complete realistic state machine workflows."""

    def test_normal_session(self):
        sm = StateMachine()
        sm.transition_to(SystemState.CALIBRATION, "calibrate")
        sm.transition_to(SystemState.IDLE, "calibration_done")
        sm.transition_to(SystemState.RUNNING, "start")
        sm.transition_to(SystemState.PAUSED, "user_pause")
        sm.transition_to(SystemState.RUNNING, "resume")
        sm.transition_to(SystemState.STOPPED, "exam_done")
        assert sm.state == SystemState.STOPPED

    def test_error_recovery_session(self):
        sm = StateMachine()
        sm.transition_to(SystemState.RUNNING, "start")
        sm.force_error("click verification failed")
        sm.transition_to(SystemState.PAUSED, "operator_acknowledged")
        sm.transition_to(SystemState.RUNNING, "resume")
        sm.transition_to(SystemState.STOPPED, "done")
        assert sm.state == SystemState.STOPPED
