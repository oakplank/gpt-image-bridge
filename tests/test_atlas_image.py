from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


BIN = Path(__file__).parents[1] / "skills" / "gpt-image-bridge" / "bin"
sys.path.insert(0, str(BIN))

import atlas_image  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if not self.body:
            return b""
        if size < 0:
            result, self.body = self.body, b""
            return result
        result, self.body = self.body[:size], self.body[size:]
        return result


class AtlasImageTests(unittest.TestCase):
    def generate(self, output, **overrides):
        options = {
            "api_key": "test-key",
            "api_base": "https://api.atlascloud.ai/v1",
            "size": "1024x1024",
            "quality": "medium",
            "poll_attempts": 3,
            "poll_interval": 0,
            "sleep": lambda _seconds: None,
        }
        options.update(overrides)
        return atlas_image.generate("a red balloon", output, **options)

    @patch("atlas_image.urllib.request.urlopen")
    def test_submits_once_then_polls_and_downloads(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "created"}}),
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "processing"}}),
            FakeResponse(
                {"code": 200, "data": {"id": "pred-1", "status": "completed", "outputs": ["https://cdn.test/out.png"]}}
            ),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.png"
            self.assertEqual(self.generate(output), output)
            self.assertEqual(output.read_bytes(), b"png-bytes")

        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(sum(request.get_method() == "POST" for request in requests), 1)
        self.assertEqual(requests[0].full_url, "https://api.atlascloud.ai/api/v1/model/generateImage")
        self.assertEqual(requests[1].full_url, "https://api.atlascloud.ai/api/v1/model/result/pred-1")
        submitted = json.loads(requests[0].data)
        self.assertEqual(
            submitted,
            {
                "model": "openai/gpt-image-2/text-to-image",
                "prompt": "a red balloon",
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
                "enable_sync_mode": False,
                "enable_base64_output": False,
            },
        )

    @patch("atlas_image.urllib.request.urlopen")
    def test_synchronous_completion_skips_polling(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "completed", "outputs": ["https://cdn.test/out.png"]}}),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 2)

    @patch("atlas_image.urllib.request.urlopen")
    def test_failed_prediction_has_clear_error(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "created"}}),
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "failed", "message": "blocked"}}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(atlas_image.AtlasError, "prediction failed: blocked"):
                self.generate(Path(directory) / "out.png")

    @patch("atlas_image.urllib.request.urlopen")
    def test_submit_http_error_is_not_retried(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.atlascloud.ai/api/v1/model/generateImage",
            503,
            "unavailable",
            {},
            io.BytesIO(b'{"message":"try later"}'),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(atlas_image.AtlasError, "HTTP 503"):
                self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 1)

    @patch("atlas_image.urllib.request.urlopen")
    def test_non_retryable_poll_error_is_not_retried(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "created"}}),
            urllib.error.HTTPError(
                "https://api.atlascloud.ai/api/v1/model/result/pred-1",
                404,
                "not found",
                {},
                io.BytesIO(b'{"message":"missing"}'),
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(atlas_image.AtlasError, "HTTP 404"):
                self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 2)

    @patch("atlas_image.urllib.request.urlopen")
    def test_transient_poll_error_is_retried(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"code": 200, "data": {"id": "pred-1", "status": "created"}}),
            urllib.error.HTTPError(
                "https://api.atlascloud.ai/api/v1/model/result/pred-1",
                503,
                "unavailable",
                {},
                io.BytesIO(b'{"message":"try later"}'),
            ),
            FakeResponse(
                {"code": 200, "data": {"id": "pred-1", "status": "completed", "outputs": ["https://cdn.test/out.png"]}}
            ),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 4)


if __name__ == "__main__":
    unittest.main()
