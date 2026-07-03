from __future__ import annotations

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from .auth import AuthASGIMiddleware
from .config import (
    ALLOWED_HOSTS,
    ALLOWED_ORIGINS,
    APP_VERSION,
    AUTH_MODE,
    PERSIST_OAUTH_TOKENS,
    PUBLIC_BASE_URL,
    TOKEN_STORE_PATH,
)
from .domain_tools import register_domain_tools
from .influx import influx_ping
from .oauth import ACCESS_TOKENS, register_oauth_routes

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=ALLOWED_HOSTS,
    allowed_origins=ALLOWED_ORIGINS,
)

mcp = FastMCP(
    "InfluxDB MCP",
    host="0.0.0.0",
    port=8000,
    sse_path="/sse",
    message_path="/messages/",
    transport_security=transport_security,
)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def root(request: Request) -> Response:
    return PlainTextResponse("InfluxDB MCP server is running\n")


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health_http(request: Request) -> Response:
    try:
        ping = influx_ping()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "version": APP_VERSION,
            "auth_mode": AUTH_MODE,
            "public_base_url": PUBLIC_BASE_URL,
            "persist_oauth_tokens": PERSIST_OAUTH_TOKENS,
            "loaded_oauth_tokens": len(ACCESS_TOKENS),
            "token_store_path": str(TOKEN_STORE_PATH),
            "allowed_hosts": ALLOWED_HOSTS,
            "influx": ping,
        }
    )


register_oauth_routes(mcp)
register_domain_tools(mcp)


def build_asgi_app():
    return AuthASGIMiddleware(mcp.sse_app())


def run() -> None:
    print("InfluxDB MCP version:", APP_VERSION)
    print("Auth mode:", AUTH_MODE)
    print("Public base URL:", PUBLIC_BASE_URL)
    print("Persist OAuth tokens:", PERSIST_OAUTH_TOKENS)
    print("Loaded OAuth tokens:", len(ACCESS_TOKENS))
    print("Token store path:", TOKEN_STORE_PATH)
    print("Allowed hosts:", ", ".join(ALLOWED_HOSTS))
    print("Allowed origins:", ", ".join(ALLOWED_ORIGINS))
    uvicorn.run(build_asgi_app(), host="0.0.0.0", port=8000, log_level="info")
