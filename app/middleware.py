"""ASGI middleware: proxy path prefix and request timing."""

from __future__ import annotations

import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PREFIX = re.compile(r"^(/[A-Za-z0-9_.-]+)+$")


class ForwardedPrefixMiddleware:
    """Use Traefik's `X-Forwarded-Prefix` (set by stripprefix) as the ASGI root_path.

    On the explorer hosts the API is mounted under /api and Traefik strips the prefix before
    forwarding; setting root_path makes /docs, redirects and pagination links point back to /api.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-prefix":
                    prefix = value.decode("latin-1").split(",")[0].strip().rstrip("/")
                    if _PREFIX.match(prefix):
                        scope = dict(scope)
                        scope["root_path"] = prefix
                    break
        await self.app(scope, receive, send)


class TimingMiddleware:
    """Adds a `Server-Timing: app;dur=<ms>` header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                duration = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", f"app;dur={duration:.1f}".encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_timing)
