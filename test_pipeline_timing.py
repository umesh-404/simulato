"""
Pipeline timing: measures the end-to-end question processing time
for SCROLLABLE vs NON-SCROLLABLE questions under the new architecture
(no speculative call — one AI call per question).

Flow measured:
  1. Screen validation
  2. Preprocessing
  3. Layout + OCR
  4. Scroll detection
  5a. [If scroll] Stitch simulation
  5b. AI query (single call with correct image)
  TOTAL
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from controller.capture_pipeline.screen_validator import ScreenValidator
from controller.capture_pipeline.image_preprocessor import ImagePreprocessor
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.capture_pipeline.scroll_detector import ScrollDetector
from controller.capture_pipeline.image_stitcher import ImageStitcher
from controller.ai_pipeline.gemini_client import query_gemini

# Init components (one-time cost)
validator = ScreenValidator()
preprocessor = ImagePreprocessor()
ocr_analyzer = OCRLayoutAnalyzer()
layout_detector = ExamLayoutDetector()
scroll_detector = ScrollDetector()
stitcher = ImageStitcher()

# --- Test images ---
# NON-SCROLLABLE: math MCQ from the earlier run (short question, fits in one frame)
NON_SCROLL_IMAGES = [
    Path(r"runs\default_test_20260411_165252\screenshots\capture_0001_20260411T165253.jpg"),
    Path(r"runs\default_test_20260411_165252\screenshots\capture_0006_20260411T165259.jpg"),
]

# SCROLLABLE: para-jumbled from the recent run (long question text, requires scroll)
SCROLL_IMAGES = [
    Path(r"runs\default_test_20260411_180419\screenshots\capture_0024_20260411T180449.jpg"),
    Path(r"runs\default_test_20260411_180419\screenshots\capture_0030_20260411T180456.jpg"),
]

# For stitching simulation — we use a second frame (simulating post-scroll capture)
# Since the real scroll didn't work yet, we just pick the next capture as a stand-in
# to measure stitching overhead accurately.
SCROLL_FRAME2 = [
    Path(r"runs\default_test_20260411_180419\screenshots\capture_0025_20260411T180451.jpg"),
    Path(r"runs\default_test_20260411_180419\screenshots\capture_0031_20260411T180458.jpg"),
]

stitch_output_dir = Path("runs/stitch_timing_test")
stitch_output_dir.mkdir(parents=True, exist_ok=True)


def time_question(img_path: Path, label: str, scroll_frame2: Path = None):
    """Time each processing step for a single question image."""
    print(f"\n{'='*70}")
    print(f"{label}: {img_path.name}")
    print(f"{'='*70}")

    steps = {}

    # 1. Screen validation
    t = time.perf_counter()
    v = validator.validate(img_path)
    steps["1_validation"] = time.perf_counter() - t
    print(f"  1. Screen validation:  {steps['1_validation']*1000:7.1f}ms  (valid={v.valid})")

    # 2. Preprocessing
    t = time.perf_counter()
    pp = preprocessor.preprocess(img_path)
    steps["2_preprocess"] = time.perf_counter() - t
    print(f"  2. Preprocessing:      {steps['2_preprocess']*1000:7.1f}ms")

    # 3. Layout + OCR
    t = time.perf_counter()
    ocr_result = ocr_analyzer.analyze(pp)
    steps["3_layout_ocr"] = time.perf_counter() - t
    n_opts = len(ocr_result.layout.detected_options) if (ocr_result.layout and hasattr(ocr_result.layout, 'detected_options') and ocr_result.layout.detected_options) else 0
    print(f"  3. Layout + OCR:       {steps['3_layout_ocr']*1000:7.1f}ms  (layout={'yes' if ocr_result.layout else 'no'})")

    # 4. Scroll detection
    needs_scroll = False
    t = time.perf_counter()
    if ocr_result.layout is not None:
        scroll_res = scroll_detector.detect_dual(pp, ocr_result.layout)
        needs_scroll = scroll_res.question.needs_scroll
    steps["4_scroll_detect"] = time.perf_counter() - t
    print(f"  4. Scroll detection:   {steps['4_scroll_detect']*1000:7.1f}ms  (needs_scroll={needs_scroll})")

    # 5a. Stitch (only if scrollable + we have a second frame)
    ai_image = img_path
    is_stitched = False
    if needs_scroll and scroll_frame2 is not None:
        t = time.perf_counter()
        stitch_out = stitch_output_dir / f"{img_path.stem}_stitched.jpg"
        ai_image = stitcher.stitch([img_path, scroll_frame2], stitch_out)
        is_stitched = True
        steps["5a_stitch"] = time.perf_counter() - t
        print(f"  5a. Stitching:         {steps['5a_stitch']*1000:7.1f}ms  ({ai_image.name})")
    else:
        steps["5a_stitch"] = 0.0

    # 5b. AI query (single call)
    t = time.perf_counter()
    try:
        response = query_gemini(ai_image, is_stitched=is_stitched)
        steps["5b_ai_query"] = time.perf_counter() - t
        print(f"  5b. AI query:          {steps['5b_ai_query']*1000:7.1f}ms  (answer={response.answer}, stitched={is_stitched})")
    except Exception as e:
        steps["5b_ai_query"] = time.perf_counter() - t
        print(f"  5b. AI query:          {steps['5b_ai_query']*1000:7.1f}ms  (FAILED: {e})")

    # Totals
    total = sum(steps.values())
    local = total - steps["5b_ai_query"]
    print(f"  -------")
    print(f"  TOTAL:                 {total*1000:7.1f}ms ({total:.2f}s)")
    print(f"  Local processing:      {local*1000:7.1f}ms")
    print(f"  AI network time:       {steps['5b_ai_query']*1000:7.1f}ms")
    print(f"  AI % of total:         {steps['5b_ai_query']/total*100:.1f}%" if total > 0 else "")

    return steps, total


def main():
    print("Pipeline Timing Test — New Architecture (Single AI Call)")
    print("=" * 70)

    # --- NON-SCROLLABLE questions ---
    non_scroll_totals = []
    for img in NON_SCROLL_IMAGES:
        if not img.exists():
            print(f"\n  SKIP: {img} not found")
            continue
        _, total = time_question(img, "NON-SCROLLABLE")
        non_scroll_totals.append(total)

    # Small delay to avoid 429
    time.sleep(2)

    # --- SCROLLABLE questions ---
    scroll_totals = []
    for img, frame2 in zip(SCROLL_IMAGES, SCROLL_FRAME2):
        if not img.exists():
            print(f"\n  SKIP: {img} not found")
            continue
        _, total = time_question(img, "SCROLLABLE", scroll_frame2=frame2)
        scroll_totals.append(total)

    # --- Summary ---
    print(f"\n\n{'='*70}")
    print(f"COMPARISON SUMMARY")
    print(f"{'='*70}")

    if non_scroll_totals:
        avg_ns = sum(non_scroll_totals) / len(non_scroll_totals)
        print(f"\n  NON-SCROLLABLE ({len(non_scroll_totals)} questions):")
        print(f"    Average:  {avg_ns:.2f}s ({avg_ns*1000:.0f}ms)")
        print(f"    Fastest:  {min(non_scroll_totals):.2f}s")
        print(f"    Slowest:  {max(non_scroll_totals):.2f}s")

    if scroll_totals:
        avg_s = sum(scroll_totals) / len(scroll_totals)
        print(f"\n  SCROLLABLE ({len(scroll_totals)} questions):")
        print(f"    Average:  {avg_s:.2f}s ({avg_s*1000:.0f}ms)")
        print(f"    Fastest:  {min(scroll_totals):.2f}s")
        print(f"    Slowest:  {max(scroll_totals):.2f}s")

    if non_scroll_totals and scroll_totals:
        overhead = avg_s - avg_ns
        print(f"\n  Scroll overhead:  +{overhead:.2f}s (+{overhead*1000:.0f}ms)")
        print(f"    (stitch + larger AI image upload)")


if __name__ == "__main__":
    main()
