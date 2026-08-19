#!/usr/bin/env python3
"""Generate a GPT Image 2 image through Atlas Cloud."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


MODEL = "openai/gpt-image-2/text-to-image"
ALLOWED_SIZES = {
    "1024x1024",
    "1024x768",
    "768x1024",
    "1024x1536",
    "1536x1024",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "2560x1088",
    "1088x2560",
    "2880x2160",
    "2160x2880",
    "3840x2160",
    "2160x3840",
}
TERMINAL_FAILURES = {"failed", "canceled", "cancelled"}


class AtlasError(RuntimeError):
    """Raised when the Atlas Cloud request cannot produce an image."""


class AtlasHttpError(AtlasError):
    """Raised for an Atlas Cloud HTTP response with a non-success status."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"Atlas Cloud returned HTTP {status}: {detail[:500]}")
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500


class AtlasTransportError(AtlasError):
    """Raised when a request cannot reach Atlas Cloud."""


def _api_root(value: str) -> str:
    """Normalize OpenAI-compatible and generation API base URLs."""
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    path = parsed.path.rstrip("/")
    for suffix in ("/api/v1", "/v1"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _request_json(
    url: str,
    api_key: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "gpt-image-bridge/atlas",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AtlasHttpError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise AtlasTransportError(f"Atlas Cloud request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise AtlasError("Atlas Cloud returned a non-object JSON response")
    code = result.get("code")
    if isinstance(code, int) and code not in {0, 200}:
        detail = str(result.get("message") or result.get("msg") or "request failed")
        raise AtlasHttpError(code, detail)
    return result


def _prediction(
    api_root: str,
    api_key: str,
    request_id: str,
    *,
    poll_attempts: int,
    poll_interval: float,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    url = f"{api_root}/api/v1/model/result/{urllib.parse.quote(request_id, safe='')}"
    last_error: AtlasError | None = None

    for attempt in range(poll_attempts):
        try:
            result = _unwrap(_request_json(url, api_key, method="GET"))
            last_error = None
        except (AtlasHttpError, AtlasTransportError) as exc:
            if isinstance(exc, AtlasHttpError) and not exc.retryable:
                raise
            last_error = exc
            if attempt == poll_attempts - 1:
                break
            sleep(min(poll_interval * (2 ** min(attempt, 3)), 10))
            continue
        except AtlasError:
            raise

        status = str(result.get("status", "")).lower()
        outputs = result.get("outputs")
        if status == "completed" and isinstance(outputs, list) and outputs:
            return result
        if status in TERMINAL_FAILURES:
            detail = result.get("error") or result.get("message") or "no error detail"
            raise AtlasError(f"Atlas Cloud prediction {status}: {detail}")
        if attempt < poll_attempts - 1:
            sleep(poll_interval)

    if last_error is not None:
        raise last_error
    raise AtlasError(f"Atlas Cloud prediction did not complete after {poll_attempts} polls")


def _download(url: str, destination: Path, *, timeout: float = 60) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-image-bridge/atlas"})
    temp_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
            ) as temp:
                temp_path = Path(temp.name)
                while chunk := response.read(1024 * 1024):
                    temp.write(chunk)
                temp.flush()
                os.fsync(temp.fileno())
        if temp_path.stat().st_size == 0:
            raise AtlasError("Atlas Cloud returned an empty image")
        os.replace(temp_path, destination)
        temp_path = None
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise AtlasError(f"Could not download the generated image: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def generate(
    prompt: str,
    destination: Path,
    *,
    api_key: str,
    api_base: str,
    size: str,
    quality: str,
    poll_attempts: int = 120,
    poll_interval: float = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Submit one generation request, poll it, and atomically save the image."""
    if size not in ALLOWED_SIZES:
        raise AtlasError(f"Unsupported Atlas Cloud size: {size}")
    if quality not in {"low", "medium", "high"}:
        raise AtlasError(f"Unsupported Atlas Cloud quality: {quality}")
    if not destination.parent.is_dir():
        raise AtlasError(f"Output directory does not exist: {destination.parent}")

    root = _api_root(api_base)
    submitted = _unwrap(
        _request_json(
            f"{root}/api/v1/model/generateImage",
            api_key,
            method="POST",
            payload={
                "model": MODEL,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "output_format": "png",
                "enable_sync_mode": False,
                "enable_base64_output": False,
            },
        )
    )

    outputs = submitted.get("outputs")
    if str(submitted.get("status", "")).lower() == "completed" and isinstance(outputs, list) and outputs:
        result = submitted
    else:
        request_id = submitted.get("id")
        if not isinstance(request_id, str) or not request_id:
            raise AtlasError("Atlas Cloud response did not include a prediction id")
        result = _prediction(
            root,
            api_key,
            request_id,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            sleep=sleep,
        )

    image_url = result["outputs"][0]
    if not isinstance(image_url, str) or not image_url.startswith(("https://", "http://")):
        raise AtlasError("Atlas Cloud returned an invalid image URL")
    _download(image_url, destination)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate GPT Image 2 images through Atlas Cloud")
    parser.add_argument("prompt", help="Image generation prompt")
    parser.add_argument("output", type=Path, help="Destination PNG path")
    parser.add_argument("--size", default="1024x1024", choices=sorted(ALLOWED_SIZES))
    parser.add_argument("--quality", default="medium", choices=("low", "medium", "high"))
    parser.add_argument(
        "--api-base",
        default=os.environ.get("ATLASCLOUD_API_BASE", "https://api.atlascloud.ai"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--poll-attempts", type=int, default=120, help=argparse.SUPPRESS)
    parser.add_argument("--poll-interval", type=float, default=2, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("ATLASCLOUD_API_KEY")
    if not api_key:
        print("gpt-image-2: ATLASCLOUD_API_KEY is required for --provider atlas", file=sys.stderr)
        return 2
    try:
        output = generate(
            args.prompt,
            args.output.expanduser().resolve(),
            api_key=api_key,
            api_base=args.api_base,
            size=args.size,
            quality=args.quality,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
        )
    except AtlasError as exc:
        print(f"gpt-image-2: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
