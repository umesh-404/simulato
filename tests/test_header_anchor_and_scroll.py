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

