"""Diagnostic: measure scrollbar pixel properties in failed images."""
import sys, cv2, numpy as np
from pathlib import Path

ROOT = Path("d:/Python Projects/simulato")
sys.path.insert(0, str(ROOT))

from controller.capture_pipeline.exam_layout import ExamLayoutDetector

layout_det = ExamLayoutDetector()

# These images should have scrollbars but are currently detected as no-scroll
failed_files = [
    ROOT / "datasets/calibration/answer-scroll/IMG20260326002106.jpg",
    ROOT / "datasets/calibration/answer-scroll/IMG20260326002554.jpg",
    ROOT / "datasets/calibration/answer-and-question-scroll/IMG20260326002239.jpg",
    ROOT / "datasets/calibration/question-scroll/IMG20260326001859.jpg",
]

for img_path in failed_files:
    if not img_path.exists():
        print(f"SKIP: {img_path.name} not found")
        continue
    
    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    layout = layout_det.detect(img_path)
    
    print(f"\n{'='*60}")
    print(f"Image: {img_path.name}")
    print(f"Divider: {layout.divider_x}")
    
    for panel_name, panel in [("question", layout.question_panel), ("answer", layout.answer_panel)]:
        if panel is None:
            print(f"  {panel_name}: no panel")
            continue
        
        panel_img = gray[panel.y:panel.y2, panel.x:panel.x2]
        ph, pw = panel_img.shape[:2]
        
        # Look at the rightmost 25 pixels of this panel
        edge_w = 25
        right_strip = panel_img[:, max(0, pw - edge_w):pw]
        
        print(f"\n  {panel_name} panel: {pw}x{ph}, right strip {right_strip.shape}")
        
        # Print gray value statistics for the right strip
        print(f"  Right strip gray: min={right_strip.min()}, max={right_strip.max()}, mean={right_strip.mean():.1f}")
        
        # For each column in the right strip, find darkest run
        for col_offset in [0, 5, 10, 15, 20, 24]:
            col_idx = min(col_offset, right_strip.shape[1] - 1)
            col = right_strip[:, col_idx]
            
            # Test multiple dark thresholds
            for thresh in [180, 200, 210, 220, 230]:
                dark_mask = col < thresh
                
                # Find longest contiguous dark run
                longest_run = 0
                current_run = 0
                for is_dark in dark_mask:
                    if is_dark:
                        current_run += 1
                        longest_run = max(longest_run, current_run)
                    else:
                        current_run = 0
                
                span_frac = longest_run / max(ph, 1)
                if span_frac > 0.10:
                    print(f"    col[{col_idx}] thresh<{thresh}: span={span_frac:.3f} ({longest_run}px)")
        
        # Bottom strip cutoff analysis
        bottom_h = max(10, int(ph * 0.12))
        bottom_strip = panel_img[ph - bottom_h:ph, :]
        edges = cv2.Canny(bottom_strip, 50, 150)
        edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)
        print(f"  Bottom edge density: {edge_density:.4f} (thresh: 0.04)")
        
        # Also check a wider bottom fraction
        for frac in [0.15, 0.20, 0.25]:
            bottom_h2 = max(10, int(ph * frac))
            bottom_strip2 = panel_img[ph - bottom_h2:ph, :]
            edges2 = cv2.Canny(bottom_strip2, 50, 150)
            ed2 = float(np.count_nonzero(edges2)) / max(edges2.size, 1)
            print(f"    Bottom {frac:.0%} edge density: {ed2:.4f}")

print("\nDone.")
