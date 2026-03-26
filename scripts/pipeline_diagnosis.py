"""
Pipeline diagnosis v1: Run the full CV pipeline against all 30
calibration images and produce a detailed per-image report.

Purpose:
    - ExamLayoutDetector: Does it find the divider? What x-coordinate?
    - OptionDetector: Does it detect 3-5 radio buttons? Where?
    - ScrollDetector: Does it match the ground-truth label?
    - Saves annotated debug images to runs/pipeline_debug/

Ground truth:
    no-scroll/             → question=no-scroll, answer=no-scroll
    answer-scroll/         → question=no-scroll, answer=SCROLL
    question-scroll/       → question=SCROLL,    answer=no-scroll
    answer-and-question-scroll/ → question=SCROLL, answer=SCROLL

Usage:
    cd d:\\Python Projects\\simulato
    python scripts/pipeline_diagnosis.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from controller.capture_pipeline.exam_layout import ExamLayoutDetector, Rect
from controller.capture_pipeline.option_detector import OptionDetector
from controller.capture_pipeline.scroll_detector import ScrollDetector

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

CALIBRATION_DIR = PROJECT_ROOT / "datasets" / "calibration"
OUTPUT_DIR = PROJECT_ROOT / "runs" / "pipeline_debug"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ground truth mapping: folder name → (question_scroll, answer_scroll)
GROUND_TRUTH = {
    "no-scroll":                    (False, False),
    "answer-scroll":                (False, True),
    "question-scroll":              (True,  False),
    "answer-and-question-scroll":   (True,  True),
}

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def draw_rect(img, rect: Rect, color, label: str, thickness: int = 2):
    """Draw a labeled rectangle on the image."""
    cv2.rectangle(img, (rect.x, rect.y), (rect.x2, rect.y2), color, thickness)
    cv2.putText(img, label, (rect.x + 4, rect.y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_circle(img, cx, cy, cr, color, label: str):
    """Draw a labeled circle on the image."""
    cv2.circle(img, (cx, cy), cr, color, 2)
    cv2.putText(img, label, (cx + cr + 5, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


# -------------------------------------------------------------------------
# Main diagnosis
# -------------------------------------------------------------------------

layout_detector = ExamLayoutDetector()
option_detector = OptionDetector()
scroll_detector = ScrollDetector()

results = []
total_images = 0
layout_failures = 0
option_failures = 0
scroll_mismatches = 0

for folder_name, (gt_q_scroll, gt_a_scroll) in GROUND_TRUTH.items():
    folder_path = CALIBRATION_DIR / folder_name
    if not folder_path.exists():
        print(f"  SKIP: {folder_path} does not exist")
        continue

    images = sorted(folder_path.glob("*.jpg"))
    for img_path in images:
        total_images += 1
        print(f"\n{'='*70}")
        print(f"  [{folder_name}] {img_path.name}")
        print(f"  Ground truth: Q={'SCROLL' if gt_q_scroll else 'no-scroll'}, "
              f"A={'SCROLL' if gt_a_scroll else 'no-scroll'}")
        print(f"{'='*70}")

        img = cv2.imread(str(img_path))
        if img is None:
            print("  ERROR: Could not read image")
            layout_failures += 1
            continue

        h, w = img.shape[:2]
        print(f"  Image size: {w}x{h}")

        # --- 1. Layout Detection ---
        layout = layout_detector.detect(img_path)
        layout_ok = layout.is_valid()

        if layout_ok:
            print(f"  LAYOUT: OK (confidence={layout.confidence:.2f})")
            print(f"    divider_x = {layout.divider_x}  "
                  f"({layout.divider_x/w*100:.1f}% of width)")
            if layout.question_panel:
                qp = layout.question_panel
                print(f"    Q panel: ({qp.x},{qp.y}) -> ({qp.x2},{qp.y2})  "
                      f"[{qp.w}x{qp.h}]")
            if layout.answer_panel:
                ap = layout.answer_panel
                print(f"    A panel: ({ap.x},{ap.y}) -> ({ap.x2},{ap.y2})  "
                      f"[{ap.w}x{ap.h}]")
            if layout.detection_notes:
                print(f"    Notes: {layout.detection_notes}")
        else:
            print(f"  LAYOUT: FAILED (confidence={layout.confidence:.2f})")
            print(f"    Notes: {layout.detection_notes}")
            layout_failures += 1

        # --- 2. Option Detection (only if layout is valid) ---
        option_map = None
        if layout_ok:
            option_map = option_detector.detect(img_path, layout)
            if option_map.count >= 3:
                print(f"  OPTIONS: {option_map.count} detected "
                      f"(method={option_map.detection_method})")
                for opt in option_map.options:
                    print(f"    {opt.label}: circle=({opt.circle_x},{opt.circle_y}) "
                          f"r={opt.circle_r}  click=({opt.click_x},{opt.click_y})  "
                          f"text='{opt.text[:50]}...' conf={opt.text_confidence:.0f}")
            else:
                print(f"  OPTIONS: FAILED — only {option_map.count} detected "
                      f"(method={option_map.detection_method})")
                option_failures += 1
        else:
            print(f"  OPTIONS: SKIPPED (layout invalid)")
            option_failures += 1

        # --- 3. Scroll Detection (only if layout is valid) ---
        scroll_result = None
        scroll_q_ok = True
        scroll_a_ok = True
        if layout_ok:
            scroll_result = scroll_detector.detect_dual(img_path, layout)
            q_scroll = scroll_result.question.needs_scroll
            a_scroll = scroll_result.answer.needs_scroll

            scroll_q_ok = (q_scroll == gt_q_scroll)
            scroll_a_ok = (a_scroll == gt_a_scroll)

            q_status = "OK" if scroll_q_ok else "MISMATCH"
            a_status = "OK" if scroll_a_ok else "MISMATCH"

            print(f"  SCROLL Q: {'SCROLL' if q_scroll else 'no-scroll'} "
                  f"(conf={scroll_result.question.confidence:.2f}, "
                  f"scrollbar={scroll_result.question.scrollbar_score:.2f}, "
                  f"cutoff={scroll_result.question.cutoff_score:.2f}) {q_status}")
            print(f"  SCROLL A: {'SCROLL' if a_scroll else 'no-scroll'} "
                  f"(conf={scroll_result.answer.confidence:.2f}, "
                  f"scrollbar={scroll_result.answer.scrollbar_score:.2f}, "
                  f"cutoff={scroll_result.answer.cutoff_score:.2f}) {a_status}")

            if not scroll_q_ok or not scroll_a_ok:
                scroll_mismatches += 1
        else:
            print(f"  SCROLL: SKIPPED (layout invalid)")
            scroll_mismatches += 1

        # --- 4. Save annotated debug image ---
        debug_img = img.copy()

        if layout.header:
            draw_rect(debug_img, layout.header, (0, 200, 200), "HEADER")
        if layout.nav_sidebar:
            draw_rect(debug_img, layout.nav_sidebar, (200, 200, 0), "NAV")
        if layout.question_panel:
            draw_rect(debug_img, layout.question_panel, (0, 255, 0), "Q_PANEL", 3)
        if layout.answer_panel:
            draw_rect(debug_img, layout.answer_panel, (255, 0, 0), "A_PANEL", 3)
        if layout.bottom_bar:
            draw_rect(debug_img, layout.bottom_bar, (0, 200, 200), "BOTTOM_BAR")
        if layout.next_button:
            draw_rect(debug_img, layout.next_button, (0, 0, 255), "NEXT", 3)
        if layout.prev_button:
            draw_rect(debug_img, layout.prev_button, (0, 0, 200), "PREV")
        if layout.clear_button:
            draw_rect(debug_img, layout.clear_button, (0, 0, 200), "CLEAR")

        # Draw divider line
        if layout.divider_x > 0:
            cv2.line(debug_img, (layout.divider_x, 0), (layout.divider_x, h),
                     (0, 165, 255), 3)

        # Draw detected options
        if option_map:
            for opt in option_map.options:
                draw_circle(debug_img, opt.circle_x, opt.circle_y,
                           opt.circle_r, (255, 0, 255), opt.label)
                # Draw click target
                cv2.drawMarker(debug_img, (opt.click_x, opt.click_y),
                              (0, 255, 255), cv2.MARKER_CROSS, 20, 2)

        # Scroll status overlay
        scroll_text = ""
        if scroll_result:
            q_s = "Q:SCROLL" if scroll_result.question.needs_scroll else "Q:ok"
            a_s = "A:SCROLL" if scroll_result.answer.needs_scroll else "A:ok"
            scroll_text = f"{q_s} {a_s}"
        else:
            scroll_text = "scroll:N/A"

        gt_text = (f"GT: Q={'SCROLL' if gt_q_scroll else 'ok'} "
                   f"A={'SCROLL' if gt_a_scroll else 'ok'}")
        match_text = "MATCH" if (scroll_q_ok and scroll_a_ok) else "MISMATCH"

        cv2.putText(debug_img, f"{scroll_text}  |  {gt_text}  |  {match_text}",
                    (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 255, 0) if (scroll_q_ok and scroll_a_ok) else (0, 0, 255), 2)

        out_name = f"{folder_name}__{img_path.stem}.jpg"
        cv2.imwrite(str(OUTPUT_DIR / out_name), debug_img)

        # Collect result
        results.append({
            "image": str(img_path),
            "category": folder_name,
            "layout_valid": layout_ok,
            "layout_confidence": layout.confidence,
            "divider_x": layout.divider_x,
            "divider_pct": round(layout.divider_x / w * 100, 1) if w > 0 else 0,
            "options_detected": option_map.count if option_map else 0,
            "option_method": option_map.detection_method if option_map else "N/A",
            "gt_q_scroll": gt_q_scroll,
            "gt_a_scroll": gt_a_scroll,
            "detected_q_scroll": scroll_result.question.needs_scroll if scroll_result else None,
            "detected_a_scroll": scroll_result.answer.needs_scroll if scroll_result else None,
            "q_scroll_match": scroll_q_ok,
            "a_scroll_match": scroll_a_ok,
            "scroll_q_confidence": scroll_result.question.confidence if scroll_result else 0,
            "scroll_a_confidence": scroll_result.answer.confidence if scroll_result else 0,
        })

# -------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------

print(f"\n\n{'='*70}")
print(f"  PIPELINE DIAGNOSIS SUMMARY")
print(f"{'='*70}")
print(f"  Total images:       {total_images}")
print(f"  Layout failures:    {layout_failures} / {total_images}")
print(f"  Option failures:    {option_failures} / {total_images}")
print(f"  Scroll mismatches:  {scroll_mismatches} / {total_images}")
print(f"\n  Accuracy:")
print(f"    Layout:  {(total_images - layout_failures)/total_images*100:.0f}%")
print(f"    Options: {(total_images - option_failures)/total_images*100:.0f}%")
print(f"    Scroll:  {(total_images - scroll_mismatches)/total_images*100:.0f}%")

# Group mismatches
print(f"\n  Scroll mismatches by category:")
for folder_name in GROUND_TRUTH:
    cat_results = [r for r in results if r["category"] == folder_name]
    mismatches = [r for r in cat_results if not r["q_scroll_match"] or not r["a_scroll_match"]]
    total_cat = len(cat_results)
    print(f"    {folder_name}: {len(mismatches)}/{total_cat} wrong")
    for r in mismatches:
        fname = Path(r["image"]).name
        print(f"      {fname}: detected Q={'SCROLL' if r['detected_q_scroll'] else 'ok'} "
              f"A={'SCROLL' if r['detected_a_scroll'] else 'ok'} "
              f"(expected Q={'SCROLL' if r['gt_q_scroll'] else 'ok'} "
              f"A={'SCROLL' if r['gt_a_scroll'] else 'ok'})")

# Save JSON report
report_path = OUTPUT_DIR / "diagnosis_report.json"
with open(report_path, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n  Debug images saved to: {OUTPUT_DIR}")
print(f"  JSON report saved to:  {report_path}")
print(f"{'='*70}")
