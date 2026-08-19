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

import muapi_image  # noqa: E402


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


class MuAPIImageTests(unittest.TestCase):
    def generate(self, output, **overrides):
        options = {
            "api_key": "test-key",
            "api_base": "https://api.muapi.ai/api/v1",
            "model": "flux-dev-image",
            "size": "1024x1024",
            "poll_attempts": 3,
            "poll_interval": 0,
            "sleep": lambda _seconds: None,
        }
        options.update(overrides)
        return muapi_image.generate("a red balloon", output, **options)

    @patch("muapi_image.urllib.request.urlopen")
    def test_submits_once_then_polls_and_downloads(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"request_id": "req-1", "status": "processing"}),
            FakeResponse({"id": "req-1", "status": "processing", "outputs": []}),
            FakeResponse({"id": "req-1", "status": "completed", "outputs": ["https://cdn.test/out.png"]}),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.png"
            self.assertEqual(self.generate(output), output)
            self.assertEqual(output.read_bytes(), b"png-bytes")

        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(sum(request.get_method() == "POST" for request in requests), 1)
        self.assertEqual(requests[0].full_url, "https://api.muapi.ai/api/v1/flux-dev-image")
        self.assertEqual(requests[1].full_url, "https://api.muapi.ai/api/v1/predictions/req-1/result")
        self.assertEqual(requests[0].get_header("X-api-key"), "test-key")
        self.assertIsNone(requests[-1].get_header("X-api-key"))
        submitted = json.loads(requests[0].data)
        self.assertEqual(
            submitted,
            {
                "prompt": "a red balloon",
                "image": "",
                "size": "1024*1024",
                "num_inference_steps": 28,
                "seed": -1,
                "guidance_scale": 3.5,
                "num_images": 1,
                "enable_base64_output": False,
                "enable_safety_checker": True,
            },
        )

    @patch("muapi_image.urllib.request.urlopen")
    def test_synchronous_completion_skips_polling(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"status": "completed", "outputs": ["https://cdn.test/out.png"]}),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 2)

    @patch("muapi_image.urllib.request.urlopen")
    def test_failed_prediction_has_clear_error(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"request_id": "req-1", "status": "processing"}),
            FakeResponse({"id": "req-1", "status": "failed", "error": "blocked"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(muapi_image.MuAPIError, "prediction failed: blocked"):
                self.generate(Path(directory) / "out.png")

    @patch("muapi_image.urllib.request.urlopen")
    def test_submit_http_error_is_not_retried(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.muapi.ai/api/v1/flux-dev-image",
            503,
            "unavailable",
            {},
            io.BytesIO(b'{"message":"try later"}'),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(muapi_image.MuAPIError, "HTTP 503"):
                self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 1)

    @patch("muapi_image.urllib.request.urlopen")
    def test_transient_poll_error_is_retried(self, urlopen):
        urlopen.side_effect = [
            FakeResponse({"request_id": "req-1", "status": "processing"}),
            urllib.error.HTTPError(
                "https://api.muapi.ai/api/v1/predictions/req-1/result",
                503,
                "unavailable",
                {},
                io.BytesIO(b'{"message":"try later"}'),
            ),
            FakeResponse({"id": "req-1", "status": "completed", "outputs": ["https://cdn.test/out.png"]}),
            FakeResponse(b"png-bytes"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            self.generate(Path(directory) / "out.png")
        self.assertEqual(urlopen.call_count, 4)

    def test_rejects_invalid_size_before_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(muapi_image.MuAPIError, "between 512 and 1536"):
                self.generate(Path(directory) / "out.png", size="1792x1024")

    def test_rejects_non_official_api_base(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(muapi_image.MuAPIError, "api base must be https"):
                self.generate(Path(directory) / "out.png", api_base="http://localhost:8080/api/v1")


if __name__ == "__main__":
    unittest.main()
