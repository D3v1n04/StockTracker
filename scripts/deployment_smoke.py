#!/usr/bin/env python3
"""Verify a running StockTracker deployment over HTTP."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    HTTPHandler,
    Request,
    build_opener,
)


MAX_REDIRECTS = 5
HTML_CONTENT_TYPE = "text/html"
CSS_CONTENT_TYPE = "text/css"
JAVASCRIPT_CONTENT_TYPES = {"application/javascript", "text/javascript"}


class SmokeCheckError(RuntimeError):
    """Raised when a deployment check does not meet its contract."""


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Return redirect responses to the caller for explicit validation."""

    def http_error_301(self, request, response, code, message, headers):
        return response

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


_OPENER = build_opener(HTTPHandler(), HTTPSHandler(), _NoRedirectHandler())


def _open_request(request: Request, timeout: float):
    return _OPENER.open(request, timeout=timeout)


def _origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SmokeCheckError(f"malformed URL {url!r}: {error}") from error

    if parsed.scheme not in {"http", "https"}:
        raise SmokeCheckError(f"URL {url!r} must use http or https")
    if not parsed.hostname:
        raise SmokeCheckError(f"URL {url!r} must include a hostname")
    if parsed.username or parsed.password:
        raise SmokeCheckError(f"URL {url!r} must not contain credentials")

    return (
        parsed.scheme.lower(),
        parsed.hostname.lower(),
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


def _validate_redirect_target(
    original_url: str,
    current_url: str,
    location: str | None,
    expected_origin: tuple[str, str, int],
) -> str:
    if not location:
        raise SmokeCheckError(
            f"GET {original_url} redirected from {current_url} without a Location header"
        )

    target_url = urljoin(current_url, location)
    try:
        target_origin = _origin(target_url)
    except SmokeCheckError as error:
        raise SmokeCheckError(
            f"GET {original_url} rejected redirect target {target_url!r}: {error}"
        ) from error

    if expected_origin[0] == "https" and target_origin[0] == "http":
        raise SmokeCheckError(
            f"GET {original_url} rejected redirect target {target_url!r}: HTTPS-to-HTTP downgrade"
        )
    if target_origin != expected_origin:
        raise SmokeCheckError(
            f"GET {original_url} rejected redirect target {target_url!r}: expected origin "
            f"{expected_origin[0]}://{expected_origin[1]}:{expected_origin[2]}"
        )

    return target_url


def _content_type(response: Any) -> str:
    headers = response.headers
    if hasattr(headers, "get_content_type"):
        return headers.get_content_type().lower()
    return headers.get("Content-Type", "").split(";", 1)[0].strip().lower()


def _get(base_url: str, path: str, timeout: float) -> tuple[str, str]:
    expected_origin = _origin(base_url)
    original_url = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    if _origin(original_url) != expected_origin:
        raise SmokeCheckError(f"GET {original_url} is outside the configured base origin")

    current_url = original_url
    seen_urls = {current_url}
    redirects = 0

    while True:
        request = Request(
            current_url,
            headers={"User-Agent": "StockTracker-deployment-smoke/1.0"},
        )
        try:
            with _open_request(request, timeout) as response:
                status = response.status
                if status in {301, 302, 303, 307, 308}:
                    if redirects >= MAX_REDIRECTS:
                        raise SmokeCheckError(
                            f"GET {original_url} exceeded {MAX_REDIRECTS} redirects at {current_url}"
                        )
                    target_url = _validate_redirect_target(
                        original_url,
                        current_url,
                        response.headers.get("Location"),
                        expected_origin,
                    )
                else:
                    content_type = _content_type(response)
                    body = response.read().decode("utf-8")
                    break
        except HTTPError as error:
            raise SmokeCheckError(
                f"GET {original_url} returned HTTP {error.code} at {current_url}"
            ) from error
        except (TimeoutError, URLError) as error:
            raise SmokeCheckError(f"GET {original_url} failed at {current_url}: {error}") from error

        if target_url in seen_urls:
            raise SmokeCheckError(
                f"GET {original_url} detected a redirect loop at {target_url}"
            )
        seen_urls.add(target_url)
        current_url = target_url
        redirects += 1

    if status != 200:
        raise SmokeCheckError(
            f"GET {original_url} returned HTTP {status} at {current_url}, expected 200"
        )

    return content_type, body


def _get_json(base_url: str, path: str, timeout: float) -> Any:
    content_type, body = _get(base_url, path, timeout)
    if content_type != "application/json":
        raise SmokeCheckError(
            f"GET {path} returned {content_type!r}, expected application/json"
        )

    try:
        return json.loads(body, parse_constant=_reject_non_finite)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise SmokeCheckError(f"GET {path} returned invalid JSON: {error}") from error


def run_checks(base_url: str, api_path: str, timeout: float) -> list[str]:
    try:
        _origin(base_url)
    except SmokeCheckError as error:
        raise SmokeCheckError(f"invalid base URL: {error}") from error
    if not api_path.startswith("/"):
        raise SmokeCheckError("API path must start with /")
    if timeout <= 0:
        raise SmokeCheckError("timeout must be greater than zero")

    checks: list[str] = []
    content_type, body = _get(base_url, "/", timeout)
    if content_type != HTML_CONTENT_TYPE or "StockTracker" not in body:
        raise SmokeCheckError("GET / did not return the StockTracker HTML dashboard")
    checks.append("GET /: dashboard HTML available")

    health = _get_json(base_url, "/health", timeout)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SmokeCheckError("GET /health did not report status=ok")
    checks.append("GET /health: API process healthy")

    ready = _get_json(base_url, "/ready", timeout)
    if not isinstance(ready, dict) or ready.get("status") != "ready":
        raise SmokeCheckError("GET /ready did not report status=ready")
    checks.append("GET /ready: database reachable")

    css_content_type, _ = _get(base_url, "/style.css", timeout)
    if css_content_type != CSS_CONTENT_TYPE:
        raise SmokeCheckError(
            f"GET /style.css returned {css_content_type!r}, expected text/css"
        )
    javascript_content_type, _ = _get(base_url, "/app.js", timeout)
    if javascript_content_type not in JAVASCRIPT_CONTENT_TYPES:
        raise SmokeCheckError(
            "GET /app.js returned "
            f"{javascript_content_type!r}, expected application/javascript or text/javascript"
        )
    checks.append("GET /style.css and /app.js: frontend assets available")

    _get_json(base_url, api_path, timeout)
    checks.append(f"GET {api_path}: valid JSON response")
    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="base URL, for example http://127.0.0.1:8000")
    parser.add_argument(
        "--api-path",
        default="/symbols",
        help="known JSON API path to verify (default: /symbols)",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="request timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checks = run_checks(args.base_url, args.api_path, args.timeout)
    except SmokeCheckError as error:
        print(f"SMOKE CHECK FAILED: {error}", file=sys.stderr)
        return 1

    for check in checks:
        print(f"PASS: {check}")
    print("Deployment smoke check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
