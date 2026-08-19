#!/usr/bin/env python3
"""Generate an image through MuAPI's Flux Dev image endpoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_API_BASE = "https://api.muapi.ai/api/v1"
DEFAULT_MODEL = "flux-dev-image"
DEFAULT_SIZE = "1024x1024"
TERMINAL_FAILURES = {"failed", "cancelled", "canceled"}
MODEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SIZE_PATTERN = re.compile(r"(?P<width>\d{3,4})x(?P<height>\d{3,4})\Z")


class MuAPIError(RuntimeError):
    """Raised when MuAPI cannot produce an image."""


class MuAPIHttpError(MuAPIError):
    """Raised for an HTTP or API-level MuAPI error."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"MuAPI returned HTTP {status}: {detail[:500]}")
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status in {408, 409, 425, 429} or self.status >= 500


class MuAPITransportError(MuAPIError):
    """Raised when a request cannot reach MuAPI."""


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
            "x-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "gpt-image-bridge/muapi",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            try:
                result = json.load(response)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise MuAPIError("MuAPI returned invalid JSON") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MuAPIHttpError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise MuAPITransportError(f"MuAPI request failed: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise MuAPIError("MuAPI returned a non-object JSON response")

    code = result.get("code")
    if isinstance(code, int) and code not in {0, 200}:
        detail = str(result.get("message") or result.get("error") or "request failed")
        raise MuAPIHttpError(code, detail)
    return result


def _muapi_size(value: str) -> str:
    match = SIZE_PATTERN.fullmatch(value)
    if not match:
        raise MuAPIError("size must use WxH with each dimension between 512 and 1536")
    width = int(match.group("width"))
    height = int(match.group("height"))
    if not (512 <= width <= 1536 and 512 <= height <= 1536):
        raise MuAPIError("size must use WxH with each dimension between 512 and 1536")
    return f"{width}*{height}"


def _model_path(value: str) -> str:
    if not MODEL_PATTERN.fullmatch(value):
        raise MuAPIError("model must contain only lowercase letters, numbers, hyphens, or underscores")
    return value


def _api_base(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.muapi.ai"
        or parsed.path != "/api/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise MuAPIError("api base must be https://api.muapi.ai/api/v1")
    return "https://api.muapi.ai/api/v1"


def _prediction(
    api_base: str,
    api_key: str,
    request_id: str,
    *,
    poll_attempts: int,
    poll_interval: float,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    if poll_attempts < 1:
        raise MuAPIError("poll_attempts must be at least 1")

    url = f"{api_base}/predictions/{urllib.parse.quote(request_id, safe='')}/result"
    last_error: MuAPIError | None = None
    for attempt in range(poll_attempts):
        try:
            result = _unwrap(_request_json(url, api_key, method="GET"))
            last_error = None
        except (MuAPIHttpError, MuAPITransportError) as exc:
            if isinstance(exc, MuAPIHttpError) and not exc.retryable:
                raise
            last_error = exc
            if attempt == poll_attempts - 1:
                break
            sleep(min(poll_interval * (2 ** min(attempt, 3)), 10))
            continue

        status = str(result.get("status", "")).lower()
        outputs = result.get("outputs")
        if status == "completed":
            if isinstance(outputs, list) and outputs:
                return result
            raise MuAPIError("MuAPI prediction completed without an output")
        if status in TERMINAL_FAILURES:
            detail = result.get("error") or result.get("message") or "no error detail"
            raise MuAPIError(f"MuAPI prediction {status}: {detail}")
        if attempt < poll_attempts - 1:
            sleep(poll_interval)

    if last_error is not None:
        raise last_error
    raise MuAPIError(f"MuAPI prediction did not complete after {poll_attempts} polls")


def _download(url: str, destination: Path, *, timeout: float = 60) -> None:
    if not url.startswith("https://"):
        raise MuAPIError("MuAPI returned a non-HTTPS image URL")

    request = urllib.request.Request(url, headers={"User-Agent": "gpt-image-bridge/muapi"})
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
            raise MuAPIError("MuAPI returned an empty image")
        os.replace(temp_path, destination)
        temp_path = None
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise MuAPIError(f"could not download the generated image: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def generate(
    prompt: str,
    destination: Path,
    *,
    api_key: str,
    api_base: str = DEFAULT_API_BASE,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    poll_attempts: int = 120,
    poll_interval: float = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Submit one MuAPI generation request, poll it, and atomically save PNG."""
    if not api_key:
        raise MuAPIError("MUAPI_API_KEY is required")
    if not prompt.strip():
        raise MuAPIError("prompt must not be empty")
    if poll_interval < 0:
        raise MuAPIError("poll_interval must not be negative")
    if not destination.parent.is_dir():
        raise MuAPIError(f"output directory does not exist: {destination.parent}")

    root = _api_base(api_base)
    endpoint = _model_path(model)
    muapi_size = _muapi_size(size)
    submitted_payload = _request_json(
        f"{root}/{endpoint}",
        api_key,
        method="POST",
        payload={
            "prompt": prompt,
            "image": "",
            "size": muapi_size,
            "num_inference_steps": 28,
            "seed": -1,
            "guidance_scale": 3.5,
            "num_images": 1,
            "enable_base64_output": False,
            "enable_safety_checker": True,
        },
    )
    submitted = _unwrap(submitted_payload)
    outputs = submitted.get("outputs")
    status = str(submitted.get("status", "")).lower()
    if status == "completed" and isinstance(outputs, list) and outputs:
        result = submitted
    else:
        request_id = (
            submitted.get("request_id")
            or submitted.get("id")
            or submitted_payload.get("request_id")
            or submitted_payload.get("id")
        )
        if not isinstance(request_id, str) or not request_id:
            raise MuAPIError("MuAPI response did not include a request id")
        result = _prediction(
            root,
            api_key,
            request_id,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            sleep=sleep,
        )

    outputs = result.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise MuAPIError("MuAPI returned no image outputs")
    image_url = outputs[0]
    if not isinstance(image_url, str):
        raise MuAPIError("MuAPI returned an invalid image URL")
    _download(image_url, destination)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an image through MuAPI")
    parser.add_argument("prompt", help="Image generation prompt")
    parser.add_argument("output", type=Path, help="Destination PNG path")
    parser.add_argument("--size", default=DEFAULT_SIZE, help="Image size, for example 1024x1024")
    parser.add_argument("--model", default=os.environ.get("MUAPI_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--api-base",
        default=os.environ.get("MUAPI_API_BASE", DEFAULT_API_BASE),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--poll-attempts", type=int, default=120, help=argparse.SUPPRESS)
    parser.add_argument("--poll-interval", type=float, default=2, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("MUAPI_API_KEY") or os.environ.get("MUAPIAPP_API_KEY")
    if not api_key:
        print("gpt-image-2: MUAPI_API_KEY is required for --provider muapi", file=sys.stderr)
        return 2
    try:
        output = generate(
            args.prompt,
            args.output.expanduser().resolve(),
            api_key=api_key,
            api_base=args.api_base,
            model=args.model,
            size=args.size,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
        )
    except MuAPIError as exc:
        print(f"gpt-image-2: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
