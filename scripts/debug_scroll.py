"""Debug the content bounds detection for scroll detector."""
import sys, cv2, numpy as np
from pathlib import Path

ROOT = Path("d:/Python Projects/simulato")
sys.path.insert(0, str(ROOT))

from controller.capture_pipeline.exam_layout import ExamLayoutDetector

layout_det = ExamLayoutDetector()

# One no-scroll image and one answer-scroll image
test_files = [
    ("no-scroll", ROOT / "datasets/calibration/no-scroll/IMG20260326002409.jpg"),
    ("answer-scroll", ROOT / "datasets/calibration/answer-scroll/IMG20260326002106.jpg"),
]

CONTENT_BG_THRESHOLD = 170

for label, img_path in test_files:
    img = cv2.imread(str(img_path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    layout = layout_det.detect(img_path)

    print(f"\n{'='*60}")
    print(f"{label}: {img_path.name}")

    for pname, panel in [("question", layout.question_panel), ("answer", layout.answer_panel)]:
        if panel is None:
            continue

        panel_gray = gray[panel.y:panel.y2, panel.x:panel.x2]
        ph, pw = panel_gray.shape[:2]

        # Column means
        col_means = np.mean(panel_gray, axis=0)

        # Find rightmost bright column
        content_right = pw
        for i in range(pw - 1, -1, -1):
            if col_means[i] > CONTENT_BG_THRESHOLD:
                content_right = i + 1
                break

        print(f"\n  {pname} panel [{panel.x},{panel.y}]-[{panel.x2},{panel.y2}] = {pw}x{ph}")
        print(f"  Content right edge: col {content_right}/{pw}")
        print(f"  Content width: {content_right}px ({content_right/pw*100:.1f}%)")
        
        # Print column means near the right edge
        for offset in [0, 5, 10, 20, 30, 50, 100, 150, 200]:
            col_idx = content_right - 1 - offset
            if col_idx < 0:
                break
            print(f"    col[{col_idx}] (right-{offset}): mean={col_means[col_idx]:.1f}")

        # Also print some columns in the dark area
        for offset in [0, 5, 10, 20, 50]:
            col_idx = content_right + offset
            if col_idx >= pw:
                break
            print(f"    col[{col_idx}] (right+{offset}): mean={col_means[col_idx]:.1f}")

        # Show what happens in the search strip
        search_w = 50
        search_left = max(0, content_right - search_w)
        search_right = content_right
        search_strip = panel_gray[:, search_left:search_right]

        print(f"\n  Scrollbar search strip [{search_left},{search_right}]:")
        print(f"    Strip shape: {search_strip.shape}")
        print(f"    Strip mean: {search_strip.mean():.1f}")
        print(f"    Strip min: {search_strip.min()}, max: {search_strip.max()}")

        # Check longest dark runs with threshold=210
        for col_offset in [0, 10, 20, 30, 40, 49]:
            real_col = min(col_offset, search_strip.shape[1] - 1)
            col = search_strip[:, real_col]
            dark_mask = col < 210
            longest = 0
            cur = 0
            for d in dark_mask:
                if d:
                    cur += 1
                    longest = max(longest, cur)
                else:
                    cur = 0
            span = longest / max(ph, 1)
            print(f"    search_col[{real_col}] dark<210: span={span:.3f} ({longest}px), mean={col.mean():.1f}")
