"""
End-to-end FITB pipeline test.

Traces every step from image -> layout -> textbox detection -> AI parse -> dispatch
to verify the entire chain works correctly on real captured FITB screenshots.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.capture_pipeline.option_detector import OptionDetector
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer
from controller.ai_pipeline.response_parser import parse_ai_response


# ── Step 0: Find FITB images ──
FITB_IMAGES = [
    Path(r"runs\default_test_20260411_161609\screenshots\capture_0001_20260411T161611.jpg"),
    Path(r"runs\default_test_20260411_161609\screenshots\capture_0004_20260411T161615.jpg"),
    Path(r"runs\default_test_20260411_161609\screenshots\capture_0008_20260411T161619.jpg"),
]

# Use first available image
test_image = None
for img in FITB_IMAGES:
    if img.exists():
        test_image = img
        break

if test_image is None:
    print("[FAIL] No FITB test images found!")
    sys.exit(1)

print(f"[OK] Using test image: {test_image}")
print()

# ── Step 1: Layout Detection ──
print("=" * 60)
print("STEP 1: ExamLayoutDetector.detect()")
print("=" * 60)
layout_detector = ExamLayoutDetector()
layout = layout_detector.detect(test_image)
print(f"  Layout valid: {layout.is_valid()}")
print(f"  Divider X:    {layout.divider_x}")
print(f"  Q Panel:      {layout.question_panel}")
print(f"  A Panel:      {layout.answer_panel}")
print(f"  Image size:   {layout.image_w}x{layout.image_h}")
print()

if not layout.is_valid():
    print("[FAIL] Layout detection failed!")
    sys.exit(1)

# ── Step 2: OCR Layout Analyzer ──
print("=" * 60)
print("STEP 2: OCRLayoutAnalyzer.analyze()")
print("=" * 60)
ocr_analyzer = OCRLayoutAnalyzer()
ocr_result = ocr_analyzer.analyze(test_image)
print(f"  OCR result type: {type(ocr_result).__name__}")
print(f"  Has layout:      {ocr_result.layout is not None}")
print(f"  Layout type:     {type(ocr_result.layout).__name__ if ocr_result.layout else 'None'}")
print(f"  Image path:      {ocr_result.image_path}")
print()

# ── Step 3: Text Box Detection ──
print("=" * 60)
print("STEP 3: OptionDetector.detect_textbox()")
print("=" * 60)
option_detector = OptionDetector()

# Test with layout from layout_detector directly
tb_coords_direct = option_detector.detect_textbox(test_image, layout)
print(f"  [Direct layout] Textbox coords: {tb_coords_direct}")

# Test with layout from OCR result (this is what workflow_engine actually uses)
if ocr_result.layout is not None:
    tb_coords_ocr = option_detector.detect_textbox(test_image, ocr_result.layout)
    print(f"  [OCR layout]    Textbox coords: {tb_coords_ocr}")
else:
    tb_coords_ocr = None
    print(f"  [OCR layout]    SKIPPED (layout is None)")
print()

# ── Step 4: AI Response Parsing ──
print("=" * 60)
print("STEP 4: Response Parser (FITB)")
print("=" * 60)
test_responses = [
    '{"answer": "FITB: 41"}',
    '{"answer": "FITB: 993"}',
    '{"answer": "FITB: hello"}',
]
for raw in test_responses:
    parsed = parse_ai_response(raw)
    print(f"  Raw: {raw}")
    print(f"    Parsed answer:  {parsed.answer}")
    is_fitb = parsed.answer.startswith("FITB:")
    print(f"    Is FITB:        {is_fitb}")
    if is_fitb:
        text_to_type = parsed.answer.replace("FITB:", "", 1).strip()
        print(f"    Text to type:   '{text_to_type}'")
    print()

# ── Step 5: Simulate Workflow Engine FITB branch ──
print("=" * 60)
print("STEP 5: Simulating Workflow Engine FITB branch")
print("=" * 60)

# This is exactly what workflow_engine.py does at lines 471-491
simulated_click_letter = "FITB: 41"
if simulated_click_letter.startswith("FITB:"):
    text_to_type = simulated_click_letter.replace("FITB:", "", 1).strip()
    print(f"  Decision click_letter: '{simulated_click_letter}'")
    print(f"  Extracted text:        '{text_to_type}'")
    
    # Simulate: if self._latest_ocr_layout is not None and self._latest_ocr_layout.layout is not None:
    print(f"  ocr_result is not None: {ocr_result is not None}")
    print(f"  ocr_result.layout is not None: {ocr_result.layout is not None}")
    
    if ocr_result is not None and ocr_result.layout is not None:
        tb_coords = option_detector.detect_textbox(test_image, ocr_result.layout)
        print(f"  Textbox detected: {tb_coords}")
        
        if tb_coords:
            norm_x, norm_y = tb_coords
            print(f"  Would call: click_and_type_at_normalized({norm_x:.4f}, {norm_y:.4f}, '{text_to_type}')")
            
            # Verify the normalized coords map to a sane pixel position
            px_x = int(norm_x * layout.image_w)
            px_y = int(norm_y * layout.image_h)
            print(f"  Pixel position: ({px_x}, {px_y})")
            
            # Verify it's inside the answer panel
            ap = layout.answer_panel
            in_panel = (ap.x <= px_x <= ap.x + ap.w) and (ap.y <= px_y <= ap.y + ap.h)
            print(f"  Inside answer panel: {in_panel}")
            
            if in_panel:
                print(f"  [OK] FITB pipeline would execute correctly!")
            else:
                print(f"  [WARN] Click target is OUTSIDE answer panel!")
                print(f"    Answer panel bounds: x=[{ap.x}, {ap.x+ap.w}], y=[{ap.y}, {ap.y+ap.h}]")
        else:
            print(f"  [FAIL] No textbox detected!")
    else:
        print(f"  [FAIL] No OCR layout available - FITB branch would NOT execute!")

print()

# ── Step 6: Verify click_dispatcher path ──
print("=" * 60)
print("STEP 6: Verify click_dispatcher.click_and_type_at_normalized path")
print("=" * 60)
from controller.hardware_control.click_dispatcher import ClickDispatcher
import inspect
src = inspect.getsource(ClickDispatcher.click_and_type_at_normalized)
print(f"  Method source:")
for line in src.strip().split('\n'):
    print(f"    {line}")
print()

# ── Step 7: Verify pi_client CLICK command is valid ──
print("=" * 60)
print("STEP 7: Verify CLICK in VALID_COMMANDS")
print("=" * 60)
from controller.hardware_control.pi_client import VALID_COMMANDS
print(f"  VALID_COMMANDS: {VALID_COMMANDS}")
print(f"  'CLICK' in VALID_COMMANDS: {'CLICK' in VALID_COMMANDS}")
print(f"  'TYPE_TEXT' in VALID_COMMANDS: {'TYPE_TEXT' in VALID_COMMANDS}")
print()

# ── Summary ──
print("=" * 60)
print("PIPELINE SUMMARY")
print("=" * 60)

issues = []

if not layout.is_valid():
    issues.append("Layout detection FAILED")

if ocr_result is None or ocr_result.layout is None:
    issues.append("OCR layout is None - FITB branch will SKIP entirely")

if tb_coords_direct is None:
    issues.append("Textbox detection failed with direct layout")

if tb_coords_ocr is None:
    issues.append("Textbox detection failed with OCR layout")

if "CLICK" not in VALID_COMMANDS:
    issues.append("'CLICK' not in pi_client VALID_COMMANDS")

if "TYPE_TEXT" not in VALID_COMMANDS:
    issues.append("'TYPE_TEXT' not in pi_client VALID_COMMANDS")

if issues:
    print("[ISSUES FOUND]:")
    for issue in issues:
        print(f"  !! {issue}")
else:
    print("[ALL CHECKS PASSED] - FITB pipeline is fully operational")
