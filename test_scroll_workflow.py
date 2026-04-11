"""
Diagnostic: tests workflow engine process_question with a scrollable image
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path

# We'll mock out some stuff to run workflow engine in isolation
from controller.orchestrator.workflow_engine import WorkflowEngine
from controller.orchestrator.state_machine import StateMachine, SystemState
from controller.alerts.alert_manager import AlertManager
from controller.hardware_control.click_dispatcher import ClickDispatcher
from controller.hardware_control.verification_engine import VerificationEngine
from controller.capture_pipeline.image_receiver import ImageReceiver
from controller.utils.logger import EventLogger
from controller.hardware_control.pi_client import PiClient
import concurrent.futures

class MockPi:
    def list_endpoints(self): return {"endpoints": ["/api/click"]}
    def send_command(self, cmd, **k): return True

class MockClickDispatcher(ClickDispatcher):
    def __init__(self):
        super().__init__(MockPi(), "192.168.1.100", 8080)
    def scroll_down_at_normalized(self, x, y, clicks=5):
        print(f"MOCK: Scroll down at {x}, {y}")
        return True

class MockWorkflowEngine(WorkflowEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mock_capture_idx = 0
        self.mock_scroll_frames = []
        
    def _capture_scroll_frames(self, direction):
        print(f"MOCK: Capturing scroll frames {direction}")
        return self.mock_scroll_frames

def run_test():
    sm = StateMachine()
    sm.push_state(SystemState.RUNNING)
    alerts = AlertManager(sm)
    pi = MockPi()
    click = MockClickDispatcher()
    verify = VerificationEngine()
    receiver = ImageReceiver(Path("runs/test"))
    event_log = EventLogger(Path("runs/test/events.jsonl"))
    
    wf = MockWorkflowEngine(sm, alerts, click, verify, receiver, event_log)
    wf.start()
    
    try:
        # Give it a known scrollable image
        img_path = Path(r"runs\default_test_20260411_165252\screenshots\capture_0080_20260411T165403.jpg")
        
        # We need to simulate the scroll capture returning a new frame
        post_scroll_img = Path(r"runs\default_test_20260411_165252\screenshots\capture_0102_20260411T165428.jpg")
        wf.mock_scroll_frames = [post_scroll_img]
        
        print("Starting process_question...")
        decision = wf.process_question(img_path)
        print(f"Decision: {decision}")
        
    finally:
        wf.stop()

if __name__ == "__main__":
    run_test()
