import os
import sys
import time
import cv2
from pathlib import Path
from dotenv import load_dotenv

# Force ghost mode for the test
os.environ["CAPTURE_MODE"] = "ghost"
load_dotenv()

from controller.orchestrator.workflow_engine import WorkflowEngine
from controller.orchestrator.state_machine import StateMachine, SystemState
from controller.capture_pipeline.option_detector import OptionDetector
from controller.capture_pipeline.exam_layout import ExamLayoutDetector

# --- Mock Dependencies ---
class MockStateMachine(StateMachine):
    def __init__(self):
        super().__init__()
        # Force the initial state to RUNNING so the workflow will process questions
        self._state = SystemState.RUNNING

class MockImageReceiver:
    def receive_image(self, data: bytes) -> Path:
        # Just return the test image path
        return Path("test_image.jpg")

class MockClickDispatcher:
    def __init__(self):
        self.clicks = []
    def click_option(self, letter: str) -> None:
        print(f"[MockClickDispatcher] Clicked option {letter}")
        self.clicks.append(letter)
    def click_next(self) -> None:
        print(f"[MockClickDispatcher] Clicked NEXT")
    def click_at_normalized(self, nx: float, ny: float, **kwargs) -> None:
        print(f"[MockClickDispatcher] Clicked normalized at nx={nx:.4f}, ny={ny:.4f}")
        self.clicks.append({"nx": nx, "ny": ny})
        
class MockAlertManager:
    def raise_alert(self, alert_type, msg, data=None):
        print(f"[MockAlertManager] Alert {alert_type}: {msg}")

class MockEventLogger:
    def log_event(self, t, d):
        if t == "ai_response":
            print(f"\n[AI RESPONSE] Model: {d.get('model')}")
            print(f"[AI RESPONSE] Answer: {d.get('answer')}")

class MockVerificationEngine:
    def verify_click_change(self, *args, **kwargs):
        class Res:
            verified = True
            diff_score = 0.5
            drift_x = 0
            drift_y = 0
            issues = []
        return Res()
    def verify_option_selected(self, *args, **kwargs):
        class Res:
            verified = True
            diff_score = 0.5
            drift_x = 0
            drift_y = 0
            issues = []
        return Res()

# --- Main Test ---
def run_test():
    TEST_IMAGE = Path('datasets/ghost_test/raw/ghost_q1.jpg')
    if not TEST_IMAGE.exists():
        import glob
        files = glob.glob('runs/**/screenshots/capture_*.jpg', recursive=True)
        if files:
            TEST_IMAGE = Path(files[5]) # Try to grab one
            
    if not TEST_IMAGE.exists():
        print("No test image found.")
        sys.exit(1)
        
    print(f"=== TESTING Ghost Mode Pipeline ===")
    print(f"Using image: {TEST_IMAGE.name}")
    
    # 1. Test Option Detection / Layout (Right vs Left panel check)
    t0 = time.time()
    layout = ExamLayoutDetector().detect(TEST_IMAGE)
    opt_map = OptionDetector().detect(TEST_IMAGE, layout)
    t_layout = time.time() - t0
    
    print(f"\n[Layout Check]")
    print(f"Divider X: {layout.divider_x if layout else 'None'}")
    if layout and layout.answer_panel:
        print(f"Answer Panel (Click Target Zone): X=[{layout.answer_panel.x} to {layout.answer_panel.x + layout.answer_panel.w}]")
    else:
        print("No answer panel detected.")
        
    print(f"\n[Option Coordinates] (Verify these fall on the RIGHT panel)")
    if opt_map:
        for opt in opt_map.options:
            print(f"Option {opt.label}: click_x={opt.click_x}, click_y={opt.click_y}, text='{opt.text}'")
    else:
        print("No options detected.")
        
    # 2. Test Full Pipeline via WorkflowEngine
    print(f"\n=== Running Full API Pipeline ===")
    img_bytes = TEST_IMAGE.read_bytes()
    
    sm = MockStateMachine()
    receiver = MockImageReceiver()
    click = MockClickDispatcher()
    workflow = WorkflowEngine(sm, MockAlertManager(), click, MockVerificationEngine(), receiver, MockEventLogger())
    workflow.set_test_context("test_speed_run")
    
    # Override receive_image in the receiver to just return our pre-existing file path
    def fake_receive(data):
        import shutil
        out_path = Path(f"runs/test_working/{TEST_IMAGE.name}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TEST_IMAGE, out_path)
        return out_path
    receiver.receive_image = fake_receive
    
    # Fake the wait method to simulate frames arriving instantly
    def fake_wait(timeout=None):
        # Simulate arrival without immediately calling into the workflow to prevent recursion depth/crash issues
        return True
        
    workflow._verification_frame_event.wait = fake_wait
    
    t_pipe_start = time.time()
    
    try:
         workflow.process_question(img_bytes)
    except Exception as e:
         print(f"Exception in pipeline (ignoring for validation): {e}")
         
    t_pipe_end = time.time()
    
    print(f"\n=== Test Results ===")
    print(f"Layout/Option pass time: {t_layout:.2f}s")
    print(f"Full pipeline cycle time : {t_pipe_end - t_pipe_start:.2f}s")
    
    # Check Accuracy Visuals
    print(f"\nDispatched Clicks: {click.clicks}")
    if len(click.clicks) > 0 and isinstance(click.clicks[0], dict):
        nx = click.clicks[0]["nx"]
        ny = click.clicks[0]["ny"]
        
        img = cv2.imread(str(TEST_IMAGE))
        h, w = img.shape[:2]
        pixel_x = int(nx * w)
        pixel_y = int(ny * h)
        print(f"Mapped click coordinate: {pixel_x}, {pixel_y}")
        
        # Draw a red crosshair
        cv2.drawMarker(img, (pixel_x, pixel_y), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
        cv2.circle(img, (pixel_x, pixel_y), 5, (0, 0, 255), -1)
        
        res_file = f"runs/test_working/accuracy_{TEST_IMAGE.name}"
        cv2.imwrite(res_file, img)
        print(f"Accuracy image saved to: {res_file}")

if __name__ == '__main__':
    run_test()
