"""
Benchmark calibration dataset quality & speed.

This script scans `datasets/calibration/**.jpg` and measures:
  1) Divider/edge detection quality from `ExamLayoutDetector`
  2) Option/radio mapping from `OptionDetector` (Y-cluster + OCR text confidence)
  3) (Optional) OCR-derived target alignment to detected option circles

Output:
  - prints a concise summary
  - writes a JSON report into `runs/` for later inspection/replay tuning
"""

from __future__ import annotations

import argparse
import json
import time
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _euclid(a_x: float, a_y: float, b_x: float, b_y: float) -> float:
    dx = a_x - b_x
    dy = a_y - b_y
    return (dx * dx + dy * dy) ** 0.5


def _iter_dataset_images(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.jpg")) + sorted(root.rglob("*.png")) + sorted(root.rglob("*.jpeg"))


def _save_radio_debug(
    out_dir: Path,
    image_bgr: Any,
    gray: Any,
    layout: Any,
    option_det: Any,
    opt_map: Any,
    ocr_res: Any = None,
) -> None:
    """
    Save debug overlays for option/radio detection.

    Writes crops + an overlay image showing candidate circles from a few
    deterministic Hough parameter passes, plus the final cluster centers.
    """
    import cv2
    import numpy as np
    from controller.capture_pipeline.option_detector import OPTION_LABELS

    if layout.answer_panel is None:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    h, w = gray.shape[:2]
    ap = layout.answer_panel

    answer_crop = image_bgr[ap.y : ap.y2, ap.x : ap.x2]
    cv2.imwrite(str(out_dir / "answer_panel_crop.jpg"), answer_crop)

    # Visual truth overlay on full answer panel using detector output.
    answer_overlay = answer_crop.copy()
    if hasattr(opt_map, "options"):
        for opt in opt_map.options:
            cx = int(opt.circle_x - ap.x)
            cy = int(opt.circle_y - ap.y)
            cr = int(max(3, opt.circle_r))
            cv2.circle(answer_overlay, (cx, cy), cr, (0, 255, 0), 2)
            cv2.putText(
                answer_overlay,
                str(opt.label),
                (cx + 6, cy - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
    cv2.imwrite(str(out_dir / "answer_panel_detected_options.png"), answer_overlay)

    # Optional OCR word overlay in the answer panel for visual inspection.
    if ocr_res is not None and getattr(ocr_res, "words", None):
        ocr_overlay = answer_crop.copy()
        for wobj in ocr_res.words:
            wx1, wy1 = int(wobj.x), int(wobj.y)
            wx2, wy2 = int(wobj.x + wobj.w), int(wobj.y + wobj.h)
            # Keep only words whose center is in answer panel.
            wcx = int(wobj.x + (wobj.w // 2))
            wcy = int(wobj.y + (wobj.h // 2))
            if not (ap.x <= wcx <= ap.x2 and ap.y <= wcy <= ap.y2):
                continue
            cv2.rectangle(
                ocr_overlay,
                (max(0, wx1 - ap.x), max(0, wy1 - ap.y)),
                (max(0, wx2 - ap.x), max(0, wy2 - ap.y)),
                (255, 0, 0),
                1,
            )
        cv2.imwrite(str(out_dir / "answer_panel_ocr_words.png"), ocr_overlay)

    # Use the actual strip chosen by the detector (so debug matches reality).
    meta = getattr(opt_map, "debug_meta", None) or {}
    sx1 = int(meta.get("best_strip_x1") or ap.x)
    sx2 = int(meta.get("best_strip_x2") or min(ap.x2, ap.x + option_det.SEARCH_STRIP_WIDTH))
    sy1 = int(meta.get("search_y1") or ap.y)
    sy2 = int(meta.get("search_y2") or ap.y2)
    sx1 = max(ap.x, min(sx1, ap.x2 - 1))
    sx2 = max(sx1 + 1, min(sx2, ap.x2))
    sy1 = max(ap.y, min(sy1, ap.y2 - 1))
    sy2 = max(sy1 + 1, min(sy2, ap.y2))

    strip_gray = gray[sy1:sy2, sx1:sx2]
    strip_bgr = cv2.cvtColor(strip_gray, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(out_dir / "radio_strip_gray.jpg"), strip_gray)

    blurred = cv2.GaussianBlur(strip_gray, (9, 9), 2)
    param_sets = [
        ("pass1", dict(dp=option_det.HOUGH_DP, minDist=option_det.HOUGH_MIN_DIST, param1=option_det.HOUGH_PARAM1, param2=option_det.HOUGH_PARAM2, minRadius=option_det.HOUGH_MIN_RADIUS, maxRadius=option_det.HOUGH_MAX_RADIUS)),
        ("pass2", dict(dp=1.0, minDist=15, param1=60, param2=12, minRadius=4, maxRadius=28)),
        ("pass3", dict(dp=1.0, minDist=12, param1=60, param2=9, minRadius=4, maxRadius=35)),
    ]

    # This strip overlay is intentionally a copy of the strip (useful baseline).
    cv2.imwrite(str(out_dir / "radio_strip_overlay.png"), strip_bgr)

    # Draw final clusters derived from the same pipeline.
    # Re-run Hough with pass3 settings (most likely relevant when a miss happens),
    # then cluster by Y using the detector's private method.
    hc3 = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=12,
        param1=60,
        param2=9,
        minRadius=4,
        maxRadius=35,
    )
    if hc3 is not None:
        cand3 = np.round(hc3[0]).astype(int)
        abs_candidates3 = [(sx1 + int(cx), sy1 + int(cy), int(cr)) for cx, cy, cr in cand3]
        clusters3 = option_det._cluster_by_y(abs_candidates3)
        cluster_img = strip_bgr.copy()
        # Clusters sorted by Y inside _cluster_by_y.
        clusters3_sorted = sorted(clusters3, key=lambda c: c["center_y"])
        for idx, cl in enumerate(clusters3_sorted[: len(OPTION_LABELS)]):
            cx = int(cl["center_x"] - sx1)
            cy = int(cl["center_y"] - sy1)
            cv2.drawMarker(cluster_img, (cx, cy), (255, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=8, thickness=2)
            cv2.putText(cluster_img, OPTION_LABELS[idx], (cx + 5, cy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
        cv2.imwrite(str(out_dir / "radio_cluster_centers.png"), cluster_img)

        # Clean, meaningful overlay: only the final accepted option circles.
        final_img = strip_bgr.copy()
        if hasattr(opt_map, "options"):
            for opt in opt_map.options:
                fx = int(opt.circle_x - sx1)
                fy = int(opt.circle_y - sy1)
                fr = int(max(3, opt.circle_r))
                if 0 <= fx < final_img.shape[1] and 0 <= fy < final_img.shape[0]:
                    cv2.circle(final_img, (fx, fy), fr, (0, 255, 0), 2)
                    cv2.putText(final_img, str(opt.label), (fx + 6, fy - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite(str(out_dir / "radio_hough_overlay.png"), final_img)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", default="datasets/calibration")
    parser.add_argument("--enable-ocr-alignment", action="store_true")
    parser.add_argument("--measure-ocr-text-quality", action="store_true")
    parser.add_argument("--save-debug", action="store_true", help="Save debug overlays for failing images")
    parser.add_argument(
        "--save-debug-all",
        action="store_true",
        help="Save debug overlays for every image (requires --save-debug).",
    )
    parser.add_argument("--text-conf-threshold", type=float, default=50.0)
    parser.add_argument("--y-min-gap-threshold", type=float, default=10.0)
    parser.add_argument("--max-images", type=int, default=0, help="0 = all")
    args = parser.parse_args()

    # Ensure `controller/` imports work when running as a script.
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    root = Path(args.dataset_root)
    images = _iter_dataset_images(root)
    if args.max_images and args.max_images > 0:
        images = images[: args.max_images]

    from controller.capture_pipeline.exam_layout import ExamLayoutDetector
    from controller.capture_pipeline.option_detector import OptionDetector

    ocr_layout = None
    if args.enable_ocr_alignment:
        from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer

        ocr_layout = OCRLayoutAnalyzer()

    edge_det = ExamLayoutDetector()
    option_det = OptionDetector()

    # OCR availability check (tesseract binary might be missing even if pytesseract is installed).
    ocr_available = False
    ocr_avail_error: Optional[str] = None
    if args.measure_ocr_text_quality or args.enable_ocr_alignment:
        try:
            import pytesseract

            try:
                _ver = pytesseract.get_tesseract_version()
                ocr_available = True
            except Exception as e:
                ocr_available = False
                ocr_avail_error = str(e)
        except Exception as e:
            ocr_available = False
            ocr_avail_error = str(e)

    report_dir = Path("runs") / f"calibration_benchmark_{time.strftime('%Y%m%d_%H%M%S')}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    debug_dir = report_dir / "debug"

    per_image: list[dict[str, Any]] = []
    total_valid_layout = 0
    total_radio_good = 0
    total_images = len(images)

    for img_path in images:
        try:
            import cv2
            import numpy as np
        except ImportError:
            raise RuntimeError("opencv-python and numpy are required for benchmark")

        img = cv2.imread(str(img_path))
        if img is None:
            continue

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1) Divider / layout detection
        t0 = _now_ms()
        layout = edge_det.detect(img_path)
        t1 = _now_ms()
        layout_ms = t1 - t0

        layout_valid = layout.is_valid() if hasattr(layout, "is_valid") else False
        if layout_valid:
            total_valid_layout += 1

        divider_rel = float(layout.divider_x) / float(max(1, w))

        # Edge density / contrast metrics on answer panel
        edge_density = 0.0
        edge_contrast = 0.0
        if layout.answer_panel is not None:
            ap = layout.answer_panel
            panel = gray[ap.y : ap.y2, ap.x : ap.x2]
            edges = cv2.Canny(panel, 50, 150)
            edge_density = float(np.count_nonzero(edges)) / float(max(1, edges.size))
            edge_contrast = float(panel.std()) if panel.size else 0.0

        # 2) Radio / option mapping
        t2 = _now_ms()
        opt_map = option_det.detect(img_path, layout)
        t3 = _now_ms()
        option_ms = t3 - t2

        detected_count = opt_map.count
        y_centers = [o.circle_y for o in opt_map.options]
        y_centers.sort()
        y_diffs = [b - a for a, b in zip(y_centers, y_centers[1:])]

        min_gap = min(y_diffs) if y_diffs else 0.0
        diff_std = float(__import__("numpy").std(y_diffs)) if y_diffs else 0.0
        text_confs = [float(o.text_confidence) for o in opt_map.options]
        mean_text_conf = _safe_mean(text_confs)
        good_texts = sum(1 for c in text_confs if c >= args.text_conf_threshold)
        nonempty_text_options = sum(1 for o in opt_map.options if getattr(o, "text", "").strip())
        mean_text_len = _safe_mean([float(len(getattr(o, "text", "").strip())) for o in opt_map.options if getattr(o, "text", "").strip()])

        radio_good = (layout_valid and 3 <= detected_count <= 5 and min_gap >= args.y_min_gap_threshold)
        if radio_good:
            total_radio_good += 1

        # Optional: OCR-letter alignment metric (expected_from_text)
        ocr_alignment = None
        if ocr_layout is not None and detected_count > 0:
            t4 = _now_ms()
            ocr_res = ocr_layout.analyze(img_path)
            t5 = _now_ms()
            ocr_ms = t5 - t4

            align_dists: list[float] = []
            missing = 0
            for letter in ["A", "B", "C", "D"]:
                expected = ocr_res.locate_option_target(letter) if ocr_res is not None else None
                opt = opt_map.get(letter) if hasattr(opt_map, "get") else None
                if expected is None or opt is None:
                    missing += 1
                    continue

                exp_x = expected[0] * w
                exp_y = expected[1] * h
                dist = _euclid(exp_x, exp_y, float(opt.circle_x), float(opt.circle_y))
                align_dists.append(dist)

            tol_px = 0.06 * (w * w + h * h) ** 0.5
            aligned = sum(1 for d in align_dists if d <= tol_px)
            ocr_alignment = {
                "ocr_ms": ocr_ms,
                "tolerance_px": tol_px,
                "aligned": aligned,
                "samples": len(align_dists),
                "missing_pairs": missing,
                "align_dist_mean_px": _safe_mean(align_dists),
            }

        per_image.append(
            {
                "image": str(img_path.relative_to(Path("."))),
                "split": img_path.parts[-2] if len(img_path.parts) >= 2 else "",
                "size": [w, h],
                "layout_ms": layout_ms,
                "layout_valid": layout_valid,
                "divider_x": layout.divider_x,
                "divider_rel": divider_rel,
                "edge_density": edge_density,
                "edge_contrast": edge_contrast,
                "option_ms": option_ms,
                "radio_detected_count": detected_count,
                "radio_detection_method": getattr(opt_map, "detection_method", ""),
                "y_min_gap_px": min_gap,
                "y_diff_std": diff_std,
                "mean_text_conf": mean_text_conf,
                "good_text_count": good_texts,
                "nonempty_text_options": nonempty_text_options,
                "mean_text_len_chars": mean_text_len,
                "radio_good": radio_good,
                "ocr_alignment": ocr_alignment,
            }
        )

        if args.save_debug and (args.save_debug_all or not radio_good):
            try:
                fail_out = debug_dir / img_path.stem
                _save_radio_debug(
                    fail_out,
                    img,
                    gray,
                    layout,
                    option_det,
                    opt_map,
                    ocr_res=ocr_res if ocr_layout is not None else None,
                )
            except Exception:
                # Debug artifacts must never break the benchmark.
                pass

    summary = {
        "total_images": total_images,
        "valid_layout_count": total_valid_layout,
        "radio_good_count": total_radio_good,
        "valid_layout_rate": float(total_valid_layout) / float(max(1, total_images)),
        "radio_good_rate": float(total_radio_good) / float(max(1, total_images)),
        "params": {
            "enable_ocr_alignment": bool(args.enable_ocr_alignment),
            "text_conf_threshold": args.text_conf_threshold,
            "y_min_gap_threshold": args.y_min_gap_threshold,
            "measure_ocr_text_quality": bool(args.measure_ocr_text_quality),
        },
        "ocr_availability": {
            "available": bool(ocr_available),
            "error": ocr_avail_error or "",
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    report = {"summary": summary, "per_image": per_image}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nCalibration benchmark summary")
    print(json.dumps(summary, indent=2))
    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    main()

