import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestHeaderAnchorAndScroll(unittest.TestCase):
    def test_header_anchor_roi_computation_template_match(self) -> None:
        import cv2
        import numpy as np

        from controller.capture_pipeline.header_anchor import HeaderAnchor

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            template_path = td_path / "header_template.jpg"
            frame_path = td_path / "frame.jpg"

            h, w = 200, 200
            th, tw = 40, 100
            anchor_x, anchor_y = 0, 20

            rng = np.random.default_rng(42)
            template = rng.integers(0, 255, size=(th, tw), dtype=np.uint8)
            template_bgr = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)

            frame = np.zeros((h, w), dtype=np.uint8)
            frame[anchor_y : anchor_y + th, anchor_x : anchor_x + tw] = template
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            cv2.imwrite(str(template_path), template_bgr)
            cv2.imwrite(str(frame_path), frame_bgr)

            old_template_path = HeaderAnchor.TEMPLATE_PATH
            HeaderAnchor.TEMPLATE_PATH = template_path
            try:
                meta = HeaderAnchor.locate_anchor(frame_path)
                self.assertIsNotNone(meta)
                self.assertEqual(meta.method, "template_match")

                expected_roi_y = max(0, min(h - 1, anchor_y + th - HeaderAnchor.ROI_MARGIN_PX))
                self.assertEqual(meta.roi_y, expected_roi_y)
                self.assertEqual(meta.roi_h, h - expected_roi_y)
            finally:
                HeaderAnchor.TEMPLATE_PATH = old_template_path

    def test_ocr_scroll_heuristic_needs_scroll_true(self) -> None:
        from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutResult, OCRWord
        from controller.ai_pipeline import ollama_client

        image_h = 1000
        image_w = 1200
        bottom_bar_frac = 0.08
        panel_end_y = int(image_h * (1.0 - bottom_bar_frac))  # 920
        band_px = max(10, int(image_h * 0.06))  # 60
        band_start = panel_end_y - band_px  # 860

        # Words with bottom edges inside the bottom band.
        words = []
        for i in range(6):
            y = band_start + 20  # y+h will be > band_start
            h = 10
            words.append(
                OCRWord(
                    text=f"w{i}",
                    conf=90.0,
                    x=10 + i * 5,
                    y=y,
                    w=20,
                    h=h,
                )
            )

        result = OCRLayoutResult(image_w=image_w, image_h=image_h, words=words)

        with (
            patch("controller.ai_pipeline.ollama_client.OCR_LAYOUT_PRIMARY_ENABLED", True),
            patch("controller.capture_pipeline.ocr_layout_analyzer.OCRLayoutAnalyzer.analyze", return_value=result),
        ):
            needs_scroll, conf = ollama_client._check_needs_scroll_ocr_heuristic(Path("dummy.jpg"))
            self.assertTrue(needs_scroll)
            self.assertGreaterEqual(conf, 0.65)

    def test_check_needs_scroll_falls_back_to_ollama_on_low_confidence(self) -> None:
        from controller.ai_pipeline import ollama_client

        with (
            patch("controller.ai_pipeline.ollama_client.OCR_LAYOUT_PRIMARY_ENABLED", True),
            patch(
                "controller.ai_pipeline.ollama_client._check_needs_scroll_ocr_heuristic",
                return_value=(False, 0.2),
            ),
            patch(
                "controller.ai_pipeline.ollama_client._call_ollama_task",
                return_value={"needs_scroll": True},
            ) as call_mock,
        ):
            needs_scroll = ollama_client.check_needs_scroll(Path("dummy.jpg"))
            self.assertTrue(needs_scroll)
            self.assertEqual(call_mock.call_count, 1)

