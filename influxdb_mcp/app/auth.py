from __future__ import annotations

import json
import secrets
from typing import Any

from .config import AUTH_HEADER, AUTH_MODE, AUTH_SCHEME, AUTH_TOKEN
from .oauth import oauth_token_valid, oauth_www_authenticate


class AuthASGIMiddleware:
    """Protect MCP endpoints while leaving OAuth discovery and health public."""

    PUBLIC_PREFIXES = ("/.well-known/",)
    PUBLIC_PATHS = {"/", "/health", "/healthz", "/authorize", "/token", "/favicon.ico"}

    def __init__(self, app):
        self.app = app
        self.header_name = AUTH_HEADER.lower().encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path in self.PUBLIC_PATHS or any(path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        if AUTH_MODE in ("", "none", "disabled", "off"):
            return await self.app(scope, receive, send)

        headers = {key.lower(): value for key, value in scope.get("headers", [])}

        if AUTH_MODE == "header":
            if not AUTH_TOKEN:
                return await self._send_json(send, 503, {"error": "Header auth token is empty."})

            incoming = headers.get(self.header_name, b"").decode("latin-1")
            expected = f"{AUTH_SCHEME} {AUTH_TOKEN}" if AUTH_SCHEME else AUTH_TOKEN
            if not incoming or not secrets.compare_digest(incoming, expected):
                return await self._send_json(
                    send,
                    401,
                    {"error": "Unauthorized"},
                    extra_headers=[
                        (b"www-authenticate", f"{AUTH_SCHEME or 'Bearer'}".encode("latin-1"))
                    ],
                )
            return await self.app(scope, receive, send)

        if AUTH_MODE == "oauth":
            auth = headers.get(b"authorization", b"").decode("latin-1")
            prefix = "Bearer "
            if not auth.startswith(prefix) or not oauth_token_valid(auth[len(prefix) :].strip()):
                return await self._send_json(
                    send,
                    401,
                    {"error": "Unauthorized"},
                    extra_headers=[(b"www-authenticate", oauth_www_authenticate())],
                )
            return await self.app(scope, receive, send)

        return await self._send_json(send, 503, {"error": f"Unknown auth_mode: {AUTH_MODE}"})

    @staticmethod
    async def _send_json(send, status: int, data: dict[str, Any], extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
