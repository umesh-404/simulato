"""
Test: stitch a pre-scroll and post-scroll frame together,
send the stitched composite to Gemini with is_stitched=True,
and verify the AI receives both question text + diagram.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from controller.capture_pipeline.image_stitcher import ImageStitcher
from controller.ai_pipeline.gemini_client import query_gemini

# Pick a known scrollable question pair:
# capture_0082 = Question 19 pre-scroll (question text visible, diagram cut off)
# capture_0085 = Question 19 post-scroll (diagram visible, question text scrolled up) 
pre_scroll = Path(r"runs\default_test_20260411_165252\screenshots\capture_0082_20260411T165404.jpg")
post_scroll = Path(r"runs\default_test_20260411_165252\screenshots\capture_0085_20260411T165407.jpg")

output_dir = Path("runs/stitch_test")
output_dir.mkdir(parents=True, exist_ok=True)

# Step 1: Stitch
stitcher = ImageStitcher()
stitched_path = stitcher.stitch(
    [pre_scroll, post_scroll],
    output_dir / "stitched_q19.jpg",
)
print(f"Stitched image: {stitched_path}")
print(f"  Size: {stitched_path.stat().st_size / 1024:.1f} KB")

# Step 2: Query AI with stitched image (is_stitched=True)
print("\nQuerying Gemini with stitched composite (is_stitched=True)...")
t0 = time.perf_counter()
response_stitched = query_gemini(stitched_path, is_stitched=True)
t1 = time.perf_counter()
print(f"  Answer (stitched): {response_stitched.answer}")
print(f"  Time: {(t1-t0)*1000:.0f}ms")

# Step 3: Query AI with ONLY post-scroll (what old code did — no question text)
print("\nQuerying Gemini with ONLY post-scroll frame (is_stitched=False)...")
t0 = time.perf_counter()
response_post_only = query_gemini(post_scroll, is_stitched=False) 
t1 = time.perf_counter()
print(f"  Answer (post-only): {response_post_only.answer}")
print(f"  Time: {(t1-t0)*1000:.0f}ms")

# Step 4: Query AI with ONLY pre-scroll (partial question — diagram cut off)
print("\nQuerying Gemini with ONLY pre-scroll frame (is_stitched=False)...")
t0 = time.perf_counter()
response_pre_only = query_gemini(pre_scroll, is_stitched=False)
t1 = time.perf_counter()
print(f"  Answer (pre-only): {response_pre_only.answer}")
print(f"  Time: {(t1-t0)*1000:.0f}ms")

# Summary
print(f"\n{'='*60}")
print(f"COMPARISON:")
print(f"  Stitched (full context):  {response_stitched.answer}")
print(f"  Post-only (diagram only): {response_post_only.answer}")
print(f"  Pre-only (text only):     {response_pre_only.answer}")
print(f"{'='*60}")
