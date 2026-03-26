"""
Calibration test harness for the exam screen CV pipeline.

Tests all 3 modules (ExamLayout, OptionDetector, ScrollDetector)
against the calibration dataset of 30 images, organized in labeled
subfolders:

    datasets/calibration/
        no-scroll/          → neither panel scrolls
        question-scroll/    → left panel scrolls
        answer-scroll/      → right panel scrolls
        answer-and-question-scroll/ → both panels scroll

Usage:
    python scripts/calibrate_cv_pipeline.py
    python scripts/calibrate_cv_pipeline.py --annotate   (saves annotated images)
    python scripts/calibrate_cv_pipeline.py --verbose     (detailed per-image output)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayoutDetector, Rect
from controller.capture_pipeline.option_detector import OptionDetector
from controller.capture_pipeline.scroll_detector import ScrollDetector


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALIBRATION_DIR = PROJECT_ROOT / "datasets" / "calibration"
ANNOTATED_OUTPUT_DIR = PROJECT_ROOT / "runs" / "calibration_annotated"

# Map folder name → expected scroll state (question_scroll, answer_scroll)
EXPECTED_SCROLL = {
    "no-scroll": (False, False),
    "question-scroll": (True, False),
    "answer-scroll": (False, True),
    "answer-and-question-scroll": (True, True),
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def draw_rect(img: np.ndarray, rect: Rect, color: tuple, label: str, thickness: int = 2) -> None:
    """Draw a labeled rectangle on the image."""
    cv2.rectangle(img, (rect.x, rect.y), (rect.x2, rect.y2), color, thickness)
    cv2.putText(
        img, label,
        (rect.x + 5, rect.y + 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
    )


def annotate_image(
    img: np.ndarray,
    layout,
    options,
    scroll_result,
    image_name: str,
) -> np.ndarray:
    """Create an annotated copy of the image with all detections drawn."""
    annotated = img.copy()

    # Draw panels
    if layout.question_panel:
        draw_rect(annotated, layout.question_panel, (255, 200, 0), "Question Panel")
    if layout.answer_panel:
        draw_rect(annotated, layout.answer_panel, (0, 200, 255), "Answer Panel")
    if layout.nav_sidebar:
        draw_rect(annotated, layout.nav_sidebar, (200, 200, 200), "Nav")
    if layout.header:
        draw_rect(annotated, layout.header, (200, 200, 200), "Header")
    if layout.bottom_bar:
        draw_rect(annotated, layout.bottom_bar, (200, 200, 200), "Bottom Bar")

    # Draw buttons
    if layout.next_button:
        draw_rect(annotated, layout.next_button, (0, 255, 0), "NEXT", 3)
    if layout.prev_button:
        draw_rect(annotated, layout.prev_button, (0, 255, 0), "PREV", 3)
    if layout.clear_button:
        draw_rect(annotated, layout.clear_button, (0, 200, 200), "CLEAR", 3)

    # Draw divider line
    if layout.divider_x > 0:
        h = annotated.shape[0]
        cv2.line(annotated, (layout.divider_x, 0), (layout.divider_x, h), (0, 0, 255), 2)
        cv2.putText(
            annotated, f"Divider x={layout.divider_x}",
            (layout.divider_x + 5, 50),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1,
        )

    # Draw detected option circles
    for opt in options.options:
        # Draw circle
        cv2.circle(annotated, (opt.circle_x, opt.circle_y), opt.circle_r, (0, 255, 0), 2)
        # Draw label
        cv2.putText(
            annotated, f"{opt.label}: {opt.text[:40]}",
            (opt.circle_x + opt.circle_r + 10, opt.circle_y + 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )
        # Draw click point
        cv2.drawMarker(
            annotated, (opt.click_x, opt.click_y),
            (0, 0, 255), cv2.MARKER_CROSS, 15, 2,
        )

    # Draw scroll status
    q_scroll = scroll_result.question.needs_scroll
    a_scroll = scroll_result.answer.needs_scroll
    scroll_text = f"Q-Scroll: {'YES' if q_scroll else 'NO'} ({scroll_result.question.confidence:.2f})  " \
                  f"A-Scroll: {'YES' if a_scroll else 'NO'} ({scroll_result.answer.confidence:.2f})"
    cv2.putText(
        annotated, scroll_text,
        (10, annotated.shape[0] - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
    )

    return annotated


# ---------------------------------------------------------------------------
# Main calibration logic
# ---------------------------------------------------------------------------

def run_calibration(annotate: bool = False, verbose: bool = False) -> None:
    """Run the calibration test harness on all labeled images."""
    layout_detector = ExamLayoutDetector()
    option_detector = OptionDetector()
    scroll_detector = ScrollDetector()

    if not CALIBRATION_DIR.exists():
        print(f"ERROR: Calibration directory not found: {CALIBRATION_DIR}")
        sys.exit(1)

    if annotate:
        ANNOTATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    correct_scroll = 0
    layout_ok = 0
    option_counts: list[int] = []
    results_table: list[dict] = []

    for folder_name, (expect_q, expect_a) in sorted(EXPECTED_SCROLL.items()):
        folder = CALIBRATION_DIR / folder_name
        if not folder.exists():
            print(f"  SKIP folder (missing): {folder_name}/")
            continue

        images = sorted(
            f for f in folder.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS
        )
        print(f"\n{'='*60}")
        print(f"  {folder_name}/ - {len(images)} images")
        print(f"  Expected: Q-scroll={expect_q}, A-scroll={expect_a}")
        print(f"{'='*60}")

        for img_path in images:
            total += 1

            # Phase 1: Layout detection
            layout = layout_detector.detect(img_path)
            layout_valid = layout.is_valid()
            if layout_valid:
                layout_ok += 1

            # Phase 2: Option detection
            options = option_detector.detect(img_path, layout)
            option_counts.append(options.count)

            # Phase 3: Scroll detection
            scroll = scroll_detector.detect_dual(img_path, layout)

            # Check scroll accuracy
            q_correct = scroll.question.needs_scroll == expect_q
            a_correct = scroll.answer.needs_scroll == expect_a
            both_correct = q_correct and a_correct
            if both_correct:
                correct_scroll += 1

            status = "OK" if both_correct else "FAIL"

            results_table.append({
                "image": img_path.name,
                "folder": folder_name,
                "layout_ok": layout_valid,
                "divider_x": layout.divider_x,
                "options": options.count,
                "opt_method": options.detection_method,
                "q_scroll_expected": expect_q,
                "q_scroll_actual": scroll.question.needs_scroll,
                "q_scroll_conf": scroll.question.confidence,
                "a_scroll_expected": expect_a,
                "a_scroll_actual": scroll.answer.needs_scroll,
                "a_scroll_conf": scroll.answer.confidence,
                "correct": both_correct,
            })

            if verbose or not both_correct:
                print(f"  {status} {img_path.name}")
                print(f"      Layout: divider_x={layout.divider_x}, valid={layout_valid}, conf={layout.confidence:.2f}")
                print(f"      Options: count={options.count}, method={options.detection_method}")
                for opt in options.options:
                    print(f"        {opt.label}: ({opt.click_x},{opt.click_y}) '{opt.text[:50]}'")
                print(f"      Scroll Q: expected={expect_q}, actual={scroll.question.needs_scroll}, "
                      f"score={scroll.question.confidence:.2f} [{scroll.question.method}]")
                print(f"      Scroll A: expected={expect_a}, actual={scroll.answer.needs_scroll}, "
                      f"score={scroll.answer.confidence:.2f} [{scroll.answer.method}]")
                if not both_correct:
                    if not q_correct:
                        print(f"      >> QUESTION scroll mismatch!")
                    if not a_correct:
                        print(f"      >> ANSWER scroll mismatch!")

            # Save annotated image
            if annotate and layout_valid:
                img = cv2.imread(str(img_path))
                if img is not None:
                    ann = annotate_image(img, layout, options, scroll, img_path.name)
                    out_path = ANNOTATED_OUTPUT_DIR / f"{folder_name}_{img_path.stem}_annotated.jpg"
                    cv2.imwrite(str(out_path), ann)

    # Summary
    print(f"\n{'='*60}")
    print(f"  CALIBRATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Total images:       {total}")
    print(f"  Layout detected:    {layout_ok}/{total} ({layout_ok/max(total,1)*100:.0f}%)")
    print(f"  Scroll accuracy:    {correct_scroll}/{total} ({correct_scroll/max(total,1)*100:.0f}%)")
    if option_counts:
        print(f"  Options detected:   min={min(option_counts)}, max={max(option_counts)}, "
              f"avg={sum(option_counts)/len(option_counts):.1f}")
    print()

    # Misclassified images
    misclassified = [r for r in results_table if not r["correct"]]
    if misclassified:
        print(f"  WARNING: {len(misclassified)} misclassified image(s):")
        for r in misclassified:
            print(f"    - {r['folder']}/{r['image']}: "
                  f"Q({r['q_scroll_expected']}->{r['q_scroll_actual']}), "
                  f"A({r['a_scroll_expected']}->{r['a_scroll_actual']})")
    else:
        print("  [PASS] All images correctly classified!")

    if annotate:
        print(f"\n  Annotated images saved to: {ANNOTATED_OUTPUT_DIR}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate exam screen CV pipeline")
    parser.add_argument("--annotate", action="store_true", help="Save annotated images")
    parser.add_argument("--verbose", action="store_true", help="Detailed per-image output")
    args = parser.parse_args()

    run_calibration(annotate=args.annotate, verbose=args.verbose)
