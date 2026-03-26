"""
Diagnostic v4: Look at specific visual features to understand
what's different between scroll and no-scroll panels.

Save debug crops of the right edge region for visual inspection.
Also look at the BOTTOM edge content pattern more carefully.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayoutDetector

CALIBRATION_DIR = PROJECT_ROOT / "datasets" / "calibration"
OUTPUT_DIR = PROJECT_ROOT / "runs" / "scroll_debug_v4"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

layout_detector = ExamLayoutDetector()

# Focus on one image from each category for detailed analysis
test_cases = [
    ("no-scroll", sorted((CALIBRATION_DIR / "no-scroll").glob("*.jpg"))[1]),  # IMG20260326001811
    ("question-scroll", list((CALIBRATION_DIR / "question-scroll").glob("*.jpg"))[0]),
    ("answer-scroll", sorted((CALIBRATION_DIR / "answer-scroll").glob("*.jpg"))[0]),  # image-1774464402734
    ("answer-scroll-2", sorted((CALIBRATION_DIR / "answer-scroll").glob("*.jpg"))[1]),  # IMG20260326002106
    ("both-scroll", list((CALIBRATION_DIR / "answer-and-question-scroll").glob("*.jpg"))[0]),
]

for label, img_path in test_cases:
    print(f"\n{'='*70}")
    print(f"  {label}: {img_path.name}")
    print(f"{'='*70}")
    
    layout = layout_detector.detect(img_path)
    if not layout.is_valid():
        print("  LAYOUT INVALID")
        continue
    
    img = cv2.imread(str(img_path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    for panel_name, panel in [("Q", layout.question_panel), ("A", layout.answer_panel)]:
        if panel is None:
            continue
        
        panel_gray = gray[panel.y:panel.y2, panel.x:panel.x2]
        panel_color = img[panel.y:panel.y2, panel.x:panel.x2]
        p_h, p_w = panel_gray.shape
        
        # Save cropped panel for visual inspection
        out_name = f"{label}_{panel_name}_panel.jpg"
        cv2.imwrite(str(OUTPUT_DIR / out_name), panel_color)
        
        # Save bottom 15% crop
        bot_h = int(p_h * 0.15)
        bottom_crop = panel_color[p_h - bot_h:, :]
        out_name = f"{label}_{panel_name}_bottom15.jpg"
        cv2.imwrite(str(OUTPUT_DIR / out_name), bottom_crop)
        
        # Find content right edge using adaptive method
        col_means = np.mean(panel_gray, axis=0)
        peak_brightness = float(np.max(col_means))
        content_threshold = peak_brightness * 0.70
        
        content_right = 0
        for i in range(p_w - 1, -1, -1):
            if col_means[i] > content_threshold:
                content_right = i
                break
        
        # Save tight right edge crop (last 100px of content area)
        edge_left = max(0, content_right - 100)
        right_edge_crop = panel_color[:, edge_left:content_right+20]
        out_name = f"{label}_{panel_name}_right_edge.jpg"
        cv2.imwrite(str(OUTPUT_DIR / out_name), right_edge_crop)
        
        print(f"\n  {panel_name} [{p_w}x{p_h}] content_right={content_right}, peak_bright={peak_brightness:.0f}")
        
        # Now let's look at the question: what does the SCROLLBAR area look like?
        # In the exam UI, the scrollbar is INSIDE the panel, between content and divider.
        # For the question panel: scrollbar is near the divider (at right edge).
        # For the answer panel: scrollbar is at the right edge of the actual screen content.
        
        # Let's look at this differently:
        # The exam screen has a fixed structure inside the photo.
        # Let's look for the actual SCREEN CONTENT boundary by finding
        # where a solid vertical line exists (the panel border in the exam UI).
        
        # Use Sobel-X to find vertical edges
        sobel_x = cv2.Sobel(panel_gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_abs = np.abs(sobel_x)
        
        # Column-wise edge energy
        col_edge_energy = np.mean(sobel_abs, axis=0)
        
        # Find the rightmost strong vertical edge (this is likely the panel border)
        edge_threshold = np.max(col_edge_energy) * 0.3
        
        panel_border_x = 0
        for i in range(p_w - 10, max(0, p_w // 2), -1):
            if col_edge_energy[i] > edge_threshold:
                panel_border_x = i
                break
        
        print(f"  Panel border (rightmost strong vert edge): x={panel_border_x}")
        
        # Now look between content text area and panel border for scrollbar
        # The scrollbar would be a thin vertical strip between text content and border
        
        if panel_border_x > 50:
            # Look at the strip from (panel_border_x - 50) to panel_border_x
            border_strip = panel_gray[:, panel_border_x-50:panel_border_x]
            
            # Column means in this strip
            strip_col_means = np.mean(border_strip, axis=0)
            print(f"  Border strip col means (50px): {[f'{v:.0f}' for v in strip_col_means]}")
            
            # Save this strip
            border_strip_color = panel_color[:, panel_border_x-50:panel_border_x]
            out_name = f"{label}_{panel_name}_border_strip.jpg"
            cv2.imwrite(str(OUTPUT_DIR / out_name), border_strip_color)

print(f"\nDebug images saved to: {OUTPUT_DIR}")
