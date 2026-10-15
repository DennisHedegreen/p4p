from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


@dataclass(frozen=True)
class RateLimitRule:
    method: str
    path: str
    requests: int
    window_seconds: int = 60


async def _json_response(
    send: Send,
    *,
    status: int,
    detail: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
    response_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    response_headers.extend(headers or [])
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_max_body_bytes: int,
        route_limits: dict[str, int] | None = None,
    ) -> None:
        if default_max_body_bytes < 1:
            raise ValueError("default_max_body_bytes must be positive")
        self.app = app
        self.default_max_body_bytes = default_max_body_bytes
        self.route_limits = route_limits or {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() not in self.BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = self.route_limits.get(scope.get("path", ""), self.default_max_body_bytes)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_content_length = headers.get(b"content-length")
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                await _json_response(send, status=400, detail="Invalid Content-Length header")
                return
            if content_length < 0:
                await _json_response(send, status=400, detail="Invalid Content-Length header")
                return
            if content_length > limit:
                await _json_response(send, status=413, detail="Request body too large")
                return

        total = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await _json_response(send, status=413, detail="Request body too large")


class RequestBodyTooLarge(Exception):
    pass


class InMemoryRateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, rules: tuple[RateLimitRule, ...]) -> None:
        if any(rule.requests < 1 or rule.window_seconds < 1 for rule in rules):
            raise ValueError("rate-limit requests and windows must be positive")
        self.app = app
        self.rules = {(rule.method.upper(), rule.path): rule for rule in rules}
        self._buckets: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._cleanup_interval = max((rule.window_seconds for rule in rules), default=60)
        self._last_cleanup = time.monotonic()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))
        rule = self.rules.get((method, path))
        if rule is None:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_host = str(client[0]) if client else "unknown"
        now = time.monotonic()
        cutoff = now - rule.window_seconds
        key = (client_host, method, path)
        retry_after = rule.window_seconds
        allowed = False
        with self._lock:
            if now - self._last_cleanup >= self._cleanup_interval:
                stale_cutoff = now - self._cleanup_interval
                stale_keys = [
                    bucket_key
                    for bucket_key, timestamps in self._buckets.items()
                    if not timestamps or timestamps[-1] <= stale_cutoff
                ]
                for bucket_key in stale_keys:
                    del self._buckets[bucket_key]
                self._last_cleanup = now
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) < rule.requests:
                bucket.append(now)
                allowed = True
            elif bucket:
                retry_after = max(1, int(rule.window_seconds - (now - bucket[0])) + 1)

        if not allowed:
            await _json_response(
                send,
                status=429,
                detail="Too many requests",
                headers=[(b"retry-after", str(retry_after).encode("ascii"))],
            )
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _value in headers}
                headers.extend((key, value) for key, value in self.HEADERS if key not in existing)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def configure_http_hardening(
    app: Any,
    *,
    default_max_body_bytes: int,
    route_body_limits: dict[str, int] | None = None,
    rate_limit_rules: tuple[RateLimitRule, ...] = (),
) -> None:
    """Add shared API defenses. Add CORS after calling this helper."""
    app.add_middleware(
        RequestBodyLimitMiddleware,
        default_max_body_bytes=default_max_body_bytes,
        route_limits=route_body_limits,
    )
    if rate_limit_rules:
        app.add_middleware(InMemoryRateLimitMiddleware, rules=rate_limit_rules)
    app.add_middleware(SecurityHeadersMiddleware)


__all__ = [
    "InMemoryRateLimitMiddleware",
    "RateLimitRule",
    "RequestBodyLimitMiddleware",
    "SecurityHeadersMiddleware",
    "configure_http_hardening",
]
