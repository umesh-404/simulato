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
    import glob
    files = sorted(glob.glob('runs/default_test_20260410_155432/screenshots/capture_000*.jpg'))
    # Filter out preprocessed ones just in case
    files = [f for f in files if "preprocessed" not in f]
    
    test_images = [Path(f) for f in files[:4]]
    if len(test_images) < 4:
         print("Not enough test images found. Found:", len(test_images))
         sys.exit(1)
         
    print(f"=== TESTING Ghost Mode Pipeline (4 Questions) ===")
    
    sm = MockStateMachine()
    receiver = MockImageReceiver()
    click = MockClickDispatcher()
    workflow = WorkflowEngine(sm, MockAlertManager(), click, MockVerificationEngine(), receiver, MockEventLogger())
    workflow.set_test_context("test_speed_run")
    
    total_start = time.time()
    
    for idx, TEST_IMAGE in enumerate(test_images):
        print(f"\n--- Question {idx+1}/4 ---")
        print(f"Using image: {TEST_IMAGE.name}")
        
        # We need receiver to return the current loop's image
        def fake_receive(data, current_img=TEST_IMAGE):
            import shutil
            out_path = Path(f"runs/test_working/{current_img.name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy(current_img, out_path)
            except shutil.SameFileError:
                pass
            return out_path
            
        receiver.receive_image = fake_receive
        
        img_bytes = TEST_IMAGE.read_bytes()
        
        def fake_wait(timeout=None, bytes_data=img_bytes):
            workflow.on_verification_frame_received(bytes_data)
            return True
        workflow._verification_frame_event.wait = fake_wait
        
        click.clicks.clear()
        
        q_start = time.time()
        try:
             workflow.process_question(img_bytes)
        except Exception as e:
             print(f"Exception in pipeline (ignoring for validation): {e}")
        q_end = time.time()
        
        print(f"Cycle time: {q_end - q_start:.2f}s")
        if len(click.clicks) > 0 and isinstance(click.clicks[0], dict):
            nx = click.clicks[0]["nx"]
            ny = click.clicks[0]["ny"]
            
            img = cv2.imread(str(TEST_IMAGE))
            h, w = img.shape[:2]
            pixel_x = int(nx * w)
            pixel_y = int(ny * h)
            
            # Draw a red crosshair
            cv2.drawMarker(img, (pixel_x, pixel_y), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
            cv2.circle(img, (pixel_x, pixel_y), 5, (0, 0, 255), -1)
            
            res_file = f"runs/test_working/accuracy_{TEST_IMAGE.name}"
            cv2.imwrite(res_file, img)
            print(f"Mapped click coordinate: ({pixel_x}, {pixel_y}) -> Saved map.")

    total_end = time.time()
    total_time = total_end - total_start
    print(f"\n=== Test Results ===")
    print(f"Total time for 4 questions: {total_time:.2f}s")
    print(f"Average time per question: {total_time/4:.2f}s")

if __name__ == '__main__':
    run_test()
