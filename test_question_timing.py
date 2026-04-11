"""
Timing test: measure per-question pipeline latency across 4 consecutive questions.

Measures each step independently:
  1. Screen validation
  2. Image preprocessing
  3. Layout + OCR detection
  4. AI query (real Gemini call)
  5. Response parsing + decision
  
Total = sum of all steps per question.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from controller.capture_pipeline.screen_validator import ScreenValidator
from controller.capture_pipeline.image_preprocessor import ImagePreprocessor
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.ai_pipeline.gemini_client import query_gemini
from controller.ai_pipeline.response_parser import parse_ai_response

# Pick 4 consecutive NON-blank question images from the latest run
run_dir = Path(r"runs\default_test_20260411_165252\screenshots")
all_images = sorted(run_dir.glob("capture_*.jpg"))
# Filter: non-blank (>50KB), no preprocessed
images = [p for p in all_images if p.stat().st_size > 50000 and "preprocessed" not in p.name]

# Pick 4 distinct question screens (skip verification/duplicate frames)
# Use images that are spaced apart (different questions)
test_images = [images[0], images[4], images[8], images[12]]

print(f"Testing {len(test_images)} questions for pipeline timing")
print(f"{'='*90}")

validator = ScreenValidator()
preprocessor = ImagePreprocessor()
ocr_analyzer = OCRLayoutAnalyzer()
layout_detector = ExamLayoutDetector()

# Warm up Gemini client once (auto-inits on first call in `query_gemini`)
print("Warming up Gemini client (one-time auth)...")
t0 = time.perf_counter()
# gemini = GeminiClient()
warmup_time = time.perf_counter() - t0
print(f"  Gemini client init skipped (lazy)\n")

total_times = []

for idx, img_path in enumerate(test_images):
    print(f"\n{'='*90}")
    print(f"QUESTION {idx+1}: {img_path.name}")
    print(f"{'='*90}")
    
    q_start = time.perf_counter()
    
    # Step 1: Screen Validation
    t1 = time.perf_counter()
    validation = validator.validate(img_path)
    t1_end = time.perf_counter()
    step1 = t1_end - t1
    print(f"  1. Screen validation:  {step1*1000:7.1f}ms  (valid={validation.valid})")
    
    if not validation.valid:
        print(f"     SKIPPED (invalid screen)")
        continue
    
    # Step 2: Image Preprocessing
    t2 = time.perf_counter()
    preprocessed = preprocessor.preprocess(img_path)
    t2_end = time.perf_counter()
    step2 = t2_end - t2
    print(f"  2. Preprocessing:      {step2*1000:7.1f}ms")
    
    # Step 3: Layout + OCR detection
    t3 = time.perf_counter()
    ocr_result = ocr_analyzer.analyze(preprocessed)
    t3_end = time.perf_counter()
    step3 = t3_end - t3
    n_options = len(ocr_result.option_map()) if hasattr(ocr_result, 'option_map') else 0
    print(f"  3. Layout + OCR:       {step3*1000:7.1f}ms  (options={n_options})")
    
    # Step 4: AI Query (real Gemini call)
    t4 = time.perf_counter()
    try:
        ai_response = query_gemini(img_path)
        t4_end = time.perf_counter()
        step4 = t4_end - t4
        print(f"  4. Gemini AI query:    {step4*1000:7.1f}ms  (answer={ai_response.answer})")
    except Exception as e:
        t4_end = time.perf_counter()
        step4 = t4_end - t4
        print(f"  4. Gemini AI query:    {step4*1000:7.1f}ms  (FAILED: {e})")
    
    # Step 5: Total
    q_end = time.perf_counter()
    total = q_end - q_start
    total_times.append(total)
    
    print(f"  -------")
    print(f"  TOTAL:                 {total*1000:7.1f}ms ({total:.2f}s)")
    
    # Breakdown
    local_time = step1 + step2 + step3
    print(f"  Local processing:      {local_time*1000:7.1f}ms")
    print(f"  AI network time:       {step4*1000:7.1f}ms")
    print(f"  AI % of total:         {step4/total*100:.1f}%")

# Summary
print(f"\n{'='*90}")
print(f"TIMING SUMMARY ({len(total_times)} questions)")
print(f"{'='*90}")
if total_times:
    avg = sum(total_times) / len(total_times)
    fastest = min(total_times)
    slowest = max(total_times)
    print(f"  Average:   {avg:.2f}s ({avg*1000:.0f}ms)")
    print(f"  Fastest:   {fastest:.2f}s ({fastest*1000:.0f}ms)")
    print(f"  Slowest:   {slowest:.2f}s ({slowest*1000:.0f}ms)")
    print(f"  Total 4q:  {sum(total_times):.2f}s")
