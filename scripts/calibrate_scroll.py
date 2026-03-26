"""
Simulato — CV Scroll Detector Calibration Tool

Run this on your exam screen photos to see exactly what the
scroll detector sees. It outputs per-image scores and a
PASS/FAIL summary so we can tune thresholds.

Usage:
    python scripts/calibrate_scroll.py <image_or_folder> [--label scroll|noscroll]

Examples:
    # Test a single image (unknown label):
    python scripts/calibrate_scroll.py datasets/calibration/sample1.jpg

    # Test a folder of "needs scroll" images:
    python scripts/calibrate_scroll.py datasets/calibration/scroll --label scroll

    # Test a folder of "no scroll" images:
    python scripts/calibrate_scroll.py datasets/calibration/noscroll --label noscroll

    # Test all images in calibration folder (auto-detect label from subfolder name):
    python scripts/calibrate_scroll.py datasets/calibration/
"""

import sys
import os
from pathlib import Path

# Allow running from project root or scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np


# ======================================================================
# These are the CURRENT thresholds from scroll_detector.py
# Change them here to test different values, then copy back
# ======================================================================
SCROLLBAR_EDGE_WIDTH = 30
SCROLLBAR_MIN_HEIGHT_RATIO = 0.3
BOTTOM_TEXT_DENSITY_THRESHOLD = 0.05
TEXT_DISTRIBUTION_RATIO = 0.65
DECISION_THRESHOLD = 0.5   # max(scores) > this → "needs scroll"


def detect_scrollbar(img):
    """Detect scrollbar on right edge."""
    h, w = img.shape[:2]
    right_strip = img[:, max(0, w - SCROLLBAR_EDGE_WIDTH):w]
    gray = cv2.cvtColor(right_strip, cv2.COLOR_BGR2GRAY)

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    col_sums = np.sum(binary == 0, axis=1)
    continuous_dark = 0
    max_continuous = 0
    for val in col_sums:
        if val > SCROLLBAR_EDGE_WIDTH * 0.3:
            continuous_dark += 1
            max_continuous = max(max_continuous, continuous_dark)
        else:
            continuous_dark = 0

    ratio = max_continuous / max(h, 1)
    if ratio > SCROLLBAR_MIN_HEIGHT_RATIO and ratio < 0.9:
        return min(ratio * 1.5, 1.0), ratio
    return ratio * 0.3, ratio


def detect_clipped_text(img):
    """Detect text clipped at bottom."""
    h, w = img.shape[:2]
    bottom_strip = img[int(h * 0.85):h, :]
    gray = cv2.cvtColor(bottom_strip, cv2.COLOR_BGR2GRAY)

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / max(edges.size, 1)

    if edge_density > BOTTOM_TEXT_DENSITY_THRESHOLD:
        score = min(edge_density / (BOTTOM_TEXT_DENSITY_THRESHOLD * 2), 1.0)
    else:
        score = edge_density / BOTTOM_TEXT_DENSITY_THRESHOLD * 0.3
    return score, edge_density


def detect_uneven_distribution(img):
    """Detect content concentrated in top half."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    h = edges.shape[0]

    top_half = edges[:h // 2, :]
    bottom_half = edges[h // 2:, :]

    top_density = float(np.count_nonzero(top_half)) / max(top_half.size, 1)
    bottom_density = float(np.count_nonzero(bottom_half)) / max(bottom_half.size, 1)

    if top_density > 0 and bottom_density > 0:
        ratio = top_density / (top_density + bottom_density)
        if ratio > TEXT_DISTRIBUTION_RATIO:
            return min((ratio - 0.5) * 2, 1.0), ratio, top_density, bottom_density
    return 0.0, 0.0, top_density, bottom_density


def analyze_image(image_path, expected_label=None):
    """Analyze a single image and return detailed results."""
    img = cv2.imread(str(image_path))
    if img is None:
        return {"error": f"Could not read: {image_path}"}

    h, w = img.shape[:2]

    scrollbar_score, scrollbar_ratio = detect_scrollbar(img)
    text_clip_score, edge_density = detect_clipped_text(img)
    distrib_score, distrib_ratio, top_d, bot_d = detect_uneven_distribution(img)

    max_score = max(scrollbar_score, text_clip_score, distrib_score)
    prediction = "SCROLL" if max_score > DECISION_THRESHOLD else "NO_SCROLL"

    correct = None
    if expected_label is not None:
        expected = "SCROLL" if expected_label == "scroll" else "NO_SCROLL"
        correct = prediction == expected

    return {
        "file": image_path.name,
        "size": f"{w}x{h}",
        "scrollbar_score": scrollbar_score,
        "scrollbar_ratio": scrollbar_ratio,
        "text_clip_score": text_clip_score,
        "edge_density": edge_density,
        "distrib_score": distrib_score,
        "distrib_ratio": distrib_ratio,
        "top_density": top_d,
        "bottom_density": bot_d,
        "max_score": max_score,
        "prediction": prediction,
        "correct": correct,
    }


def print_result(r):
    """Print one image's analysis in a readable format."""
    if "error" in r:
        print(f"  ❌ {r['error']}")
        return

    status = ""
    if r["correct"] is True:
        status = " ✅"
    elif r["correct"] is False:
        status = " ❌ WRONG"

    print(f"\n  📷 {r['file']} ({r['size']})")
    print(f"  ├─ Scrollbar:    score={r['scrollbar_score']:.3f}  (dark_ratio={r['scrollbar_ratio']:.3f})")
    print(f"  ├─ Text clip:    score={r['text_clip_score']:.3f}  (edge_density={r['edge_density']:.4f})")
    print(f"  ├─ Distribution: score={r['distrib_score']:.3f}  (top/total={r['distrib_ratio']:.3f}, top={r['top_density']:.4f}, bot={r['bottom_density']:.4f})")
    print(f"  └─ RESULT: {r['prediction']} (max_score={r['max_score']:.3f}){status}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    label = None

    if "--label" in sys.argv:
        idx = sys.argv.index("--label")
        if idx + 1 < len(sys.argv):
            label = sys.argv[idx + 1].lower()

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    # Collect images
    images = []
    if target.is_file():
        images.append((target, label))
    elif target.is_dir():
        # Check for scroll/ and noscroll/ subfolders
        scroll_dir = target / "scroll"
        noscroll_dir = target / "noscroll"
        if scroll_dir.is_dir() or noscroll_dir.is_dir():
            if scroll_dir.is_dir():
                for f in sorted(scroll_dir.iterdir()):
                    if f.suffix.lower() in image_exts:
                        images.append((f, "scroll"))
            if noscroll_dir.is_dir():
                for f in sorted(noscroll_dir.iterdir()):
                    if f.suffix.lower() in image_exts:
                        images.append((f, "noscroll"))
        else:
            for f in sorted(target.iterdir()):
                if f.suffix.lower() in image_exts:
                    images.append((f, label))

    if not images:
        print("No images found!")
        sys.exit(1)

    print("=" * 60)
    print("  SIMULATO — Scroll Detector Calibration")
    print("=" * 60)
    print(f"\n  Thresholds:")
    print(f"    SCROLLBAR_EDGE_WIDTH         = {SCROLLBAR_EDGE_WIDTH}")
    print(f"    SCROLLBAR_MIN_HEIGHT_RATIO   = {SCROLLBAR_MIN_HEIGHT_RATIO}")
    print(f"    BOTTOM_TEXT_DENSITY_THRESHOLD = {BOTTOM_TEXT_DENSITY_THRESHOLD}")
    print(f"    TEXT_DISTRIBUTION_RATIO       = {TEXT_DISTRIBUTION_RATIO}")
    print(f"    DECISION_THRESHOLD            = {DECISION_THRESHOLD}")
    print(f"\n  Images: {len(images)}")

    results = []
    for img_path, img_label in images:
        r = analyze_image(img_path, img_label)
        results.append(r)
        print_result(r)

    # Summary
    valid = [r for r in results if "error" not in r]
    labeled = [r for r in valid if r["correct"] is not None]

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Total images:  {len(results)}")
    print(f"  Predicted SCROLL:    {sum(1 for r in valid if r['prediction'] == 'SCROLL')}")
    print(f"  Predicted NO_SCROLL: {sum(1 for r in valid if r['prediction'] == 'NO_SCROLL')}")

    if labeled:
        correct_count = sum(1 for r in labeled if r["correct"])
        accuracy = correct_count / len(labeled) * 100
        print(f"\n  Labeled: {len(labeled)}")
        print(f"  Correct: {correct_count}/{len(labeled)} ({accuracy:.0f}%)")

        wrong = [r for r in labeled if not r["correct"]]
        if wrong:
            print(f"\n  ❌ MISCLASSIFIED ({len(wrong)}):")
            for r in wrong:
                print(f"     {r['file']}: predicted {r['prediction']}, max_score={r['max_score']:.3f}")
    else:
        print("\n  (No labels provided — add --label scroll/noscroll or use subfolders)")

    print()


if __name__ == "__main__":
    main()
