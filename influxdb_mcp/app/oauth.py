from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .config import (
    OAUTH_LOGIN_PASSWORD,
    OAUTH_TOKEN_TTL_HOURS,
    PERSIST_OAUTH_TOKENS,
    PUBLIC_BASE_URL,
    TOKEN_STORE_PATH,
)


def now_ts() -> int:
    return int(time.time())


def load_access_tokens() -> dict[str, dict[str, Any]]:
    if not PERSIST_OAUTH_TOKENS or not TOKEN_STORE_PATH.exists():
        return {}

    try:
        with TOKEN_STORE_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {}

        current = now_ts()
        cleaned: dict[str, dict[str, Any]] = {}
        for token, info in data.items():
            if not isinstance(token, str) or not isinstance(info, dict):
                continue
            try:
                expires_at = int(info.get("expires_at", 0))
            except Exception:
                continue
            if expires_at >= current:
                cleaned[token] = info

        if cleaned != data:
            save_access_tokens(cleaned)
        return cleaned
    except Exception as exc:
        print(f"Failed to load OAuth tokens: {exc}")
        return {}


def save_access_tokens(tokens: Optional[dict[str, dict[str, Any]]] = None) -> None:
    if not PERSIST_OAUTH_TOKENS:
        return

    try:
        data = ACCESS_TOKENS if tokens is None else tokens
        TOKEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = TOKEN_STORE_PATH.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(TOKEN_STORE_PATH)
        try:
            TOKEN_STORE_PATH.chmod(0o600)
        except Exception:
            pass
    except Exception as exc:
        print(f"Failed to save OAuth tokens: {exc}")


AUTH_CODES: dict[str, dict[str, Any]] = {}
ACCESS_TOKENS: dict[str, dict[str, Any]] = load_access_tokens()


def parse_body_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


async def request_form_or_json(request: Request) -> dict[str, str]:
    body = await request.body()
    if "application/json" in request.headers.get("content-type", ""):
        try:
            data = json.loads(body.decode("utf-8"))
            return {str(key): "" if value is None else str(value) for key, value in data.items()}
        except Exception:
            return {}
    return parse_body_form(body)


def oauth_metadata() -> dict[str, Any]:
    return {
        "issuer": PUBLIC_BASE_URL,
        "authorization_endpoint": f"{PUBLIC_BASE_URL}/authorize",
        "token_endpoint": f"{PUBLIC_BASE_URL}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp:read"],
    }


def protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": PUBLIC_BASE_URL,
        "authorization_servers": [PUBLIC_BASE_URL],
        "scopes_supported": ["mcp:read"],
        "bearer_methods_supported": ["header"],
    }


def oauth_www_authenticate() -> bytes:
    value = f'Bearer resource_metadata="{PUBLIC_BASE_URL}/.well-known/oauth-protected-resource"'
    return value.encode("latin-1")


def oauth_token_valid(token: str) -> bool:
    info = ACCESS_TOKENS.get(token)
    if not info:
        return False

    try:
        expires_at = int(info.get("expires_at", 0))
    except Exception:
        expires_at = 0

    if expires_at < now_ts():
        ACCESS_TOKENS.pop(token, None)
        save_access_tokens()
        return False
    return True


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def register_oauth_routes(mcp) -> None:
    @mcp.custom_route(
        "/.well-known/oauth-authorization-server",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_authorization_server(request: Request) -> Response:
        return JSONResponse(oauth_metadata())

    @mcp.custom_route(
        "/.well-known/openid-configuration",
        methods=["GET"],
        include_in_schema=False,
    )
    async def openid_configuration(request: Request) -> Response:
        return JSONResponse(oauth_metadata())

    @mcp.custom_route(
        "/.well-known/oauth-protected-resource",
        methods=["GET"],
        include_in_schema=False,
    )
    async def oauth_protected_resource(request: Request) -> Response:
        return JSONResponse(protected_resource_metadata())

    @mcp.custom_route("/authorize", methods=["GET", "POST"], include_in_schema=False)
    async def authorize(request: Request) -> Response:
        if request.method == "GET":
            params = dict(request.query_params)
            hidden_inputs = "\n".join(
                f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
                for key, value in params.items()
            )
            body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>InfluxDB MCP authorization</title></head>
<body>
  <h3>InfluxDB MCP authorization</h3>
  <p>Enter the OAuth password from the Home Assistant add-on configuration.</p>
  <form method="post" action="/authorize">
    {hidden_inputs}
    <label>Password: <input type="password" name="login_password" autofocus></label>
    <button type="submit">Authorize</button>
  </form>
</body>
</html>
"""
            return HTMLResponse(body)

        params = await request_form_or_json(request)
        if not OAUTH_LOGIN_PASSWORD:
            return HTMLResponse(
                "<h3>OAuth login password is empty</h3>"
                "<p>Set it in the add-on configuration.</p>",
                status_code=503,
            )
        if not secrets.compare_digest(params.get("login_password", ""), OAUTH_LOGIN_PASSWORD):
            return HTMLResponse("<h3>Invalid password</h3>", status_code=401)

        response_type = params.get("response_type", "")
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")
        scope = params.get("scope", "mcp:read")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "plain")

        if response_type != "code" or not client_id or not redirect_uri:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        code = secrets.token_urlsafe(32)
        AUTH_CODES[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "expires_at": now_ts() + 300,
        }

        query = {"code": code}
        if state:
            query["state"] = state
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302)

    @mcp.custom_route("/token", methods=["POST"], include_in_schema=False)
    async def token(request: Request) -> Response:
        params = await request_form_or_json(request)
        if params.get("grant_type") != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        code_info = AUTH_CODES.pop(params.get("code", ""), None)
        if not code_info or int(code_info.get("expires_at", 0)) < now_ts():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if params.get("redirect_uri", "") != code_info.get("redirect_uri", ""):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        verifier = params.get("code_verifier", "")
        challenge = code_info.get("code_challenge", "")
        method = code_info.get("code_challenge_method", "plain")
        if challenge:
            if method == "S256":
                valid = verifier and secrets.compare_digest(pkce_s256(verifier), challenge)
            elif method == "plain":
                valid = verifier and secrets.compare_digest(verifier, challenge)
            else:
                valid = False
            if not valid:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)

        ttl = max(300, OAUTH_TOKEN_TTL_HOURS * 3600)
        access_token = secrets.token_urlsafe(48)
        ACCESS_TOKENS[access_token] = {
            "client_id": code_info.get("client_id"),
            "scope": code_info.get("scope", "mcp:read"),
            "expires_at": now_ts() + ttl,
        }
        save_access_tokens()

        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": ttl,
                "scope": code_info.get("scope", "mcp:read"),
            }
        )
