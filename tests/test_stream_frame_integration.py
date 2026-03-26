import asyncio
import base64
import sys
import unittest
from unittest.mock import Mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from controller.mobile_api import api_server
from controller.mobile_api.api_server import ImageUploadRequest


class TestStreamFrameIntegration(unittest.TestCase):
    def test_stream_callback_does_not_break_upload_image(self) -> None:
        image_cb = Mock()
        stream_cb = Mock()

        api_server.set_image_callback(image_cb)
        api_server.set_stream_frame_callback(stream_cb)

        dummy_bytes = b"not-a-real-jpeg-but-valid-bytes"
        b64 = base64.b64encode(dummy_bytes).decode("utf-8")

        req = ImageUploadRequest(device_id="phone_capture_01", timestamp="t", image=b64)

        resp = asyncio.run(api_server.upload_image(req))
        # upload_image returns a dict in success cases.
        self.assertIsInstance(resp, dict)
        self.assertEqual(resp.get("status"), "received")

        image_cb.assert_called_once()
        # STREAM_FRAME callback must not be invoked by upload_image.
        stream_cb.assert_not_called()

