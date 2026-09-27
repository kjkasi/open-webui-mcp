from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .server import create_mcp


class HttpAuthAndHealthMiddleware:
    """Protect the MCP route without ever echoing the configured token."""

    def __init__(self, app: Any, auth_token: str | None, mcp_path: str = "/mcp") -> None:
        self.app = app
        self.auth_token = auth_token
        self.mcp_path = mcp_path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in {"/health", "/ready"}:
            await self._health(send, ready=path == "/ready")
            return
        if self.auth_token and path.startswith(self.mcp_path):
            headers = dict(scope.get("headers", []))
            expected = f"Bearer {self.auth_token}".encode()
            if headers.get(b"authorization") != expected:
                await self._json(send, 401, {"detail": "MCP authentication required"})
                return
        await self.app(scope, receive, send)

    async def _health(self, send: Any, ready: bool) -> None:
        await self._json(send, 200, {"status": True, "ready": ready})

    @staticmethod
    async def _json(send: Any, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        headers: Iterable[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": status, "headers": list(headers)})
        await send({"type": "http.response.body", "body": body})


def create_http_app(settings: Settings, mcp: FastMCP[Any] | None = None) -> Any:
    server = mcp or create_mcp(settings)
    app = server.streamable_http_app()
    token = settings.mcp_auth_token
    return HttpAuthAndHealthMiddleware(
        app,
        token.get_secret_value() if token else None,
    )


def run_http(settings: Settings) -> None:
    import uvicorn

    uvicorn.run(
        create_http_app(settings),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )
