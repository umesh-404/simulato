"""Detailed click-pipeline trace for the 4 questions from the live run."""
import cv2
from pathlib import Path
from calibration.grid_mapper import GridMap
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.capture_pipeline.option_detector import OptionDetector
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer

gm = GridMap.load()
print(f"Transform: scale_y={gm.transform['scale_y']}, offset_y={gm.transform['offset_y']}")
print(f"Resolution: {gm.resolution}, Capture: {gm.capture_resolution}")
print()

RUN_DIR = Path("runs/default_test_20260328_111807/screenshots")

click_frames = {
    "Q1": "capture_0002_20260328T111829_preprocessed.jpg",
    "Q2": "capture_0007_20260328T111856_preprocessed.jpg",
    "Q3": "capture_0012_20260328T111919_preprocessed.jpg",
    "Q4": "capture_0017_20260328T111941_preprocessed.jpg",
}

ai_answers = {"Q1": "B", "Q2": "B", "Q3": "A", "Q4": "C"}
pi_hid = {"Q1": (16375, 14759), "Q2": (17280, 14728), "Q3": (16341, 12755), "Q4": (16938, 18555)}

for q_name, fname in click_frames.items():
    img_path = RUN_DIR / fname
    if not img_path.exists():
        print(f"{q_name}: {fname} NOT FOUND")
        continue
    
    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]
    
    layout = ExamLayoutDetector().detect(img_path)
    omap = OptionDetector().detect(img_path, layout)
    
    print(f"=== {q_name}: AI={ai_answers[q_name]}, Image={w}x{h} ===")
    print(f"  Options detected: {omap.count}")
    
    ocr = OCRLayoutAnalyzer().analyze(img_path)
    
    for opt in sorted(omap.options, key=lambda o: o.circle_y):
        cx, cy = int(opt.click_x), int(opt.click_y)
        
        # Method 1: OptionMap.norm (used in some paths)
        nx_om, ny_om = omap.norm(cx, cy)
        
        # Method 2: OCRLayoutResult._norm (used in the actual click path)
        nx_ocr, ny_ocr = ocr._norm(cx, cy)
        
        # Compute HID from normalized (as click_dispatcher does)
        cap_w, cap_h = gm.capture_resolution
        px = int(round(nx_ocr * max(1, cap_w - 1)))
        py = int(round(ny_ocr * max(1, cap_h - 1)))
        sx, sy = gm.capture_to_screen_pixel(px, py)
        hid_x = int(round(sx * 32767 / (gm.resolution[0] - 1)))
        hid_y = int(round(sy * 32767 / (gm.resolution[1] - 1)))
        
        is_ai = opt.label == ai_answers[q_name]
        marker = " <<< AI TARGET" if is_ai else ""
        print(f"  {opt.label}: circle=({cx},{cy}) r={opt.circle_r}")
        print(f"     norm(OM)=({nx_om:.6f},{ny_om:.6f})")
        print(f"     norm(OCR)=({nx_ocr:.6f},{ny_ocr:.6f})")
        print(f"     -> capture({px},{py}) -> screen({sx},{sy}) -> HID({hid_x},{hid_y}){marker}")
    
    pi_x, pi_y = pi_hid[q_name]
    phys_x = pi_x * (gm.resolution[0] - 1) / 32767
    phys_y = pi_y * (gm.resolution[1] - 1) / 32767
    print(f"  Pi actually sent: HID({pi_x},{pi_y}) -> physical screen ({phys_x:.1f},{phys_y:.1f})")
    print()
