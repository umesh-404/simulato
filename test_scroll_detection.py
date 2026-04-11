"""
Diagnostic: test scroll detector against latest run images.
Identifies which questions need scrolling and whether the detector catches them.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from controller.capture_pipeline.exam_layout import ExamLayoutDetector
from controller.capture_pipeline.scroll_detector import ScrollDetector

layout_det = ExamLayoutDetector()
scroll_det = ScrollDetector()

run_dir = Path(r"runs\default_test_20260411_165252\screenshots")
images = sorted(run_dir.glob("capture_*.jpg"))
# Filter out blank frames (33267 bytes) and preprocessed frames
images = [p for p in images if p.stat().st_size > 50000 and "preprocessed" not in p.name]

print(f"Testing {len(images)} images for scroll detection\n")
print(f"{'Image':<50} {'Q-Scroll':<12} {'Q-Score':<10} {'A-Scroll':<12} {'A-Score':<10}")
print("-" * 94)

scroll_needed = []
for img in images:
    layout = layout_det.detect(img)
    if not layout.is_valid():
        continue
    result = scroll_det.detect_dual(img, layout)
    q = result.question
    a = result.answer
    
    marker = ""
    if q.needs_scroll or a.needs_scroll:
        marker = " <<<< SCROLL"
        scroll_needed.append(img.name)
    
    print(f"{img.name:<50} {str(q.needs_scroll):<12} {q.confidence:<10.3f} {str(a.needs_scroll):<12} {a.confidence:<10.3f}{marker}")

print(f"\n{'='*60}")
print(f"Summary: {len(scroll_needed)}/{len(images)} images detected as needing scroll")
if scroll_needed:
    print("Images needing scroll:")
    for name in scroll_needed:
        print(f"  - {name}")
else:
    print("NO images detected as needing scroll -- detector is failing!")
