"""Single-user authentication and signed session handling."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import threading
import time
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


SESSION_COOKIE = "stocktracker_session"
SESSION_MAX_AGE = 12 * 60 * 60
MAX_LOGIN_BODY_BYTES = 16 * 1024
MAX_CREDENTIAL_CHARS = 1_024
THROTTLE_ATTEMPTS = 5
THROTTLE_WINDOW_SECONDS = 60
NOINDEX_VALUE = "noindex, nofollow, noarchive"
BROWSER_PATHS = {"/", "/index.html", "/app.js", "/style.css", "/docs", "/redoc"}


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password_hash: str
    session_secret: str
    production: bool


class AuthConfigurationError(RuntimeError):
    """Raised when required authentication configuration is unavailable."""


def load_auth_config() -> AuthConfig:
    values = {
        "AUTH_USERNAME": os.getenv("AUTH_USERNAME", ""),
        "AUTH_PASSWORD_HASH": os.getenv("AUTH_PASSWORD_HASH", ""),
        "SESSION_SECRET": os.getenv("SESSION_SECRET", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise AuthConfigurationError(
            "Authentication is unavailable because required configuration is missing"
        )
    if len(values["SESSION_SECRET"].encode("utf-8")) < 32:
        raise AuthConfigurationError("Authentication session secret is too short")
    return AuthConfig(
        username=values["AUTH_USERNAME"],
        password_hash=values["AUTH_PASSWORD_HASH"],
        session_secret=values["SESSION_SECRET"],
        production=os.getenv("APP_ENV", "").strip().lower() == "production",
    )


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Return a versioned scrypt password hash suitable for AUTH_PASSWORD_HASH."""
    password_bytes = password.encode("utf-8")
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.scrypt(password_bytes, salt=salt, n=2**14, r=8, p=1, dklen=32)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"scrypt$16384$8$1${encoded_salt}${encoded_digest}"


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        n, r, p = int(n_value), int(r_value), int(p_value)
        if (n, r, p) != (2**14, 8, 1):
            return False
        salt = _decode_base64(salt_value)
        expected = _decode_base64(digest_value)
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except (UnicodeError, ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def create_session(config: AuthConfig, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else now
    username_digest = hmac.new(
        config.session_secret.encode("utf-8"),
        config.username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    payload = json.dumps(
        {"iat": issued_at, "exp": issued_at + SESSION_MAX_AGE, "usr": username_digest},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    encoded_payload = _b64encode(payload)
    signature = hmac.new(
        config.session_secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def valid_session(cookie: str | None, config: AuthConfig, now: int | None = None) -> bool:
    if not cookie or len(cookie) > 2_048:
        return False
    try:
        encoded_payload, encoded_signature = cookie.split(".")
        supplied_signature = _decode_base64(encoded_signature)
        expected_signature = hmac.new(
            config.session_secret.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        payload = json.loads(_decode_base64(encoded_payload))
        current_time = int(time.time()) if now is None else now
        if not isinstance(payload, dict):
            return False
        issued_at, expires_at = payload.get("iat"), payload.get("exp")
        if type(issued_at) is not int or type(expires_at) is not int:
            return False
        if expires_at <= current_time or expires_at - issued_at != SESSION_MAX_AGE:
            return False
        if issued_at > current_time + 60:
            return False
        expected_username = hmac.new(
            config.session_secret.encode("utf-8"),
            config.username.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(str(payload.get("usr", "")), expected_username)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return False


class LoginThrottle:
    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - THROTTLE_WINDOW_SECONDS
        return [value for value in self._failures.get(key, []) if value > cutoff]

    def retry_after(self, key: str, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        with self._lock:
            recent = self._recent(key, current)
            if recent:
                self._failures[key] = recent
            else:
                self._failures.pop(key, None)
            if len(recent) < THROTTLE_ATTEMPTS:
                return 0
            return max(1, int(THROTTLE_WINDOW_SECONDS - (current - recent[0]) + 0.999))

    def fail(self, key: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            recent = self._recent(key, current)
            recent.append(current)
            self._failures[key] = recent[-THROTTLE_ATTEMPTS:]
            if len(self._failures) > 10_000:
                self._failures.clear()

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def read_credentials(request: Request) -> tuple[str, str] | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/x-www-form-urlencoded":
        return None
    content_length = request.headers.get("content-length")
    try:
        if content_length is not None and int(content_length) > MAX_LOGIN_BODY_BYTES:
            return None
    except ValueError:
        return None
    body = await request.body()
    if len(body) > MAX_LOGIN_BODY_BYTES:
        return None
    try:
        fields = parse_qs(
            body.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=8,
        )
        username_values = fields.get("username", [])
        password_values = fields.get("password", [])
        if len(username_values) != 1 or len(password_values) != 1:
            return None
        username, password = username_values[0], password_values[0]
        if len(username) > MAX_CREDENTIAL_CHARS or len(password) > MAX_CREDENTIAL_CHARS:
            return None
        return username, password
    except (UnicodeError, ValueError):
        return None


def _is_browser_request(request: Request) -> bool:
    if request.url.path in BROWSER_PATHS:
        return True
    return "text/html" in request.headers.get("accept", "").lower()


class AuthenticationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        if path == "/health":
            response = None
        else:
            try:
                config = load_auth_config()
            except AuthConfigurationError:
                response = JSONResponse(
                    {"detail": "Authentication service unavailable"}, status_code=503
                )
            else:
                is_public = path == "/login" and request.method in {"GET", "POST"}
                authenticated = valid_session(request.cookies.get(SESSION_COOKIE), config)
                if is_public or authenticated:
                    scope.setdefault("state", {})["auth_config"] = config
                    response = None
                elif _is_browser_request(request):
                    response = RedirectResponse("/login", status_code=303)
                else:
                    response = JSONResponse(
                        {"detail": "Authentication required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Session"},
                    )

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-robots-tag", NOINDEX_VALUE.encode("ascii")))
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        if response is None:
            await self.app(scope, receive, send_with_security_headers)
        else:
            await response(scope, receive, send_with_security_headers)


def set_session_cookie(response: Response, config: AuthConfig) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session(config),
        max_age=SESSION_MAX_AGE,
        path="/",
        secure=config.production,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, config: AuthConfig) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=config.production,
        httponly=True,
        samesite="lax",
    )
