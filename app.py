import base64
import hashlib
import html
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

import requests
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

APP_VERSION = "0.4.5"
OPTIONS_PATH = Path("/data/options.json")
TOKEN_STORE_PATH = Path("/data/oauth_tokens.json")


def now_ts() -> int:
    return int(time.time())


def load_options() -> dict[str, Any]:
    if OPTIONS_PATH.exists():
        with OPTIONS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


OPTIONS = load_options()

INFLUX_URL = str(OPTIONS.get("influx_url", "http://a0d7b954-influxdb.local.hass.io:8086")).rstrip("/")
DATABASE = str(OPTIONS.get("database", "homeassistant"))
USERNAME = str(OPTIONS.get("username", ""))
PASSWORD = str(OPTIONS.get("password", ""))
MAX_ROWS = int(OPTIONS.get("max_rows", 1000))
MAX_DAYS = int(OPTIONS.get("max_days", 90))

AUTH_MODE = str(OPTIONS.get("auth_mode", "oauth")).strip().lower()
AUTH_HEADER = str(OPTIONS.get("auth_header", "Authorization")).strip() or "Authorization"
AUTH_SCHEME = str(OPTIONS.get("auth_scheme", "Bearer")).strip()
AUTH_TOKEN = str(OPTIONS.get("auth_token", "")).strip()

PUBLIC_BASE_URL = str(OPTIONS.get("public_base_url", "")).strip().rstrip("/") or "http://localhost:8000"
OAUTH_LOGIN_PASSWORD = str(OPTIONS.get("oauth_login_password", "")).strip()
OAUTH_TOKEN_TTL_HOURS = int(OPTIONS.get("oauth_token_ttl_hours", 720))
PERSIST_OAUTH_TOKENS = bool(OPTIONS.get("persist_oauth_tokens", True))


def option_list(name: str) -> list[str]:
    value = OPTIONS.get(name, [])
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def host_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def origin_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return ""


public_host = host_from_url(PUBLIC_BASE_URL)
public_origin = origin_from_url(PUBLIC_BASE_URL)

allowed_hosts = option_list("allowed_hosts")
for item in [public_host, f"{public_host}:*", "127.0.0.1:*", "localhost:*"]:
    if item and item not in allowed_hosts:
        allowed_hosts.append(item)

allowed_origins = option_list("allowed_origins")
for item in [public_origin, "http://127.0.0.1:*", "http://localhost:*"]:
    if item and item not in allowed_origins:
        allowed_origins.append(item)

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=allowed_hosts,
    allowed_origins=allowed_origins,
)

mcp = FastMCP(
    "InfluxDB MCP",
    host="0.0.0.0",
    port=8000,
    sse_path="/sse",
    message_path="/messages/",
    transport_security=transport_security,
)


def load_access_tokens() -> dict[str, dict[str, Any]]:
    if not PERSIST_OAUTH_TOKENS or not TOKEN_STORE_PATH.exists():
        return {}

    try:
        with TOKEN_STORE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
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
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
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
            return {str(k): "" if v is None else str(v) for k, v in data.items()}
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
                    extra_headers=[(b"www-authenticate", f"{AUTH_SCHEME or 'Bearer'}".encode("latin-1"))],
                )
            return await self.app(scope, receive, send)

        if AUTH_MODE == "oauth":
            auth = headers.get(b"authorization", b"").decode("latin-1")
            prefix = "Bearer "
            if not auth.startswith(prefix) or not oauth_token_valid(auth[len(prefix):].strip()):
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
            "allowed_hosts": allowed_hosts,
            "influx": ping,
        }
    )


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"], include_in_schema=False)
async def oauth_authorization_server(request: Request) -> Response:
    return JSONResponse(oauth_metadata())


@mcp.custom_route("/.well-known/openid-configuration", methods=["GET"], include_in_schema=False)
async def openid_configuration(request: Request) -> Response:
    return JSONResponse(oauth_metadata())


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"], include_in_schema=False)
async def oauth_protected_resource(request: Request) -> Response:
    return JSONResponse(protected_resource_metadata())


@mcp.custom_route("/authorize", methods=["GET", "POST"], include_in_schema=False)
async def authorize(request: Request) -> Response:
    if request.method == "GET":
        params = dict(request.query_params)
        hidden_inputs = "\n".join(
            f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
            for k, v in params.items()
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
            "<h3>OAuth login password is empty</h3><p>Set it in the add-on configuration.</p>",
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


def influx_auth():
    if USERNAME:
        return (USERNAME, PASSWORD)
    return None


def influx_query_raw(query: str, *, database: Optional[str] = None, epoch: str = "s") -> dict[str, Any]:
    response = requests.get(
        f"{INFLUX_URL}/query",
        params={"db": database or DATABASE, "q": query, "epoch": epoch},
        auth=influx_auth(),
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    errors: list[str] = []
    for result in data.get("results", []):
        if "error" in result:
            errors.append(result["error"])
        for series in result.get("series", []) or []:
            if "error" in series:
                errors.append(series["error"])
    if errors:
        raise RuntimeError("; ".join(errors))
    return data


def influx_ping() -> dict[str, Any]:
    response = requests.get(f"{INFLUX_URL}/ping", auth=influx_auth(), timeout=10)
    return {
        "ok": response.status_code in (200, 204),
        "status_code": response.status_code,
        "version": response.headers.get("X-Influxdb-Version"),
    }


def table_from_result(data: dict[str, Any], max_rows: int = MAX_ROWS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in data.get("results", []):
        for series in result.get("series", []) or []:
            columns = series.get("columns", [])
            for values in series.get("values", []) or []:
                item = dict(zip(columns, values))
                if "name" in series:
                    item["_measurement"] = series["name"]
                if "tags" in series:
                    item.update(series["tags"])
                rows.append(item)
                if len(rows) >= max_rows:
                    return rows
    return rows


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', r'\"') + '"'


def quote_string(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


FORBIDDEN_QUERY_WORDS = re.compile(
    r"\b(INTO|DROP|DELETE|CREATE|ALTER|GRANT|REVOKE|SET\s+PASSWORD|KILL|DROP\s+SERIES|DROP\s+MEASUREMENT)\b",
    re.IGNORECASE,
)


def validate_readonly_influxql(query: str) -> str:
    q = query.strip()
    if not q:
        raise ValueError("Query is empty.")
    if ";" in q.rstrip(";"):
        raise ValueError("Multiple statements are not allowed.")
    q = q.rstrip(";").strip()
    upper = q.upper()
    if not (upper.startswith("SELECT ") or upper.startswith("SHOW ")):
        raise ValueError("Only SELECT and SHOW queries are allowed.")
    if FORBIDDEN_QUERY_WORDS.search(q):
        raise ValueError("This query contains a forbidden write/admin keyword.")
    return q


def parse_epoch_seconds(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    raise ValueError(f"Unsupported time value: {value!r}")


@mcp.tool()
def health() -> dict[str, Any]:
    """Check MCP add-on and InfluxDB connectivity."""
    return {
        "mcp": "ok",
        "version": APP_VERSION,
        "influx_url": INFLUX_URL,
        "database": DATABASE,
        "auth_mode": AUTH_MODE,
        "public_base_url": PUBLIC_BASE_URL,
        "persist_oauth_tokens": PERSIST_OAUTH_TOKENS,
        "loaded_oauth_tokens": len(ACCESS_TOKENS),
        "token_store_path": str(TOKEN_STORE_PATH),
        "allowed_hosts": allowed_hosts,
        "influx": influx_ping(),
    }


@mcp.tool()
def show_databases() -> list[dict[str, Any]]:
    """Show InfluxDB databases."""
    return table_from_result(influx_query_raw("SHOW DATABASES", database=DATABASE))


@mcp.tool()
def show_measurements(database: Optional[str] = None) -> list[dict[str, Any]]:
    """Show measurements in the configured InfluxDB database."""
    return table_from_result(influx_query_raw("SHOW MEASUREMENTS", database=database or DATABASE))


@mcp.tool()
def show_field_keys(measurement: str, database: Optional[str] = None) -> list[dict[str, Any]]:
    """Show fields for one measurement, for example measurement='kWh'."""
    query = f"SHOW FIELD KEYS FROM {quote_identifier(measurement)}"
    return table_from_result(influx_query_raw(query, database=database or DATABASE))


@mcp.tool()
def show_tag_values(
    tag: str = "entity_id",
    measurement: Optional[str] = None,
    database: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Show values for a tag, optionally limited to one measurement."""
    if measurement:
        query = f"SHOW TAG VALUES FROM {quote_identifier(measurement)} WITH KEY = {quote_identifier(tag)}"
    else:
        query = f"SHOW TAG VALUES WITH KEY = {quote_identifier(tag)}"
    return table_from_result(influx_query_raw(query, database=database or DATABASE))


@mcp.tool()
def find_series_by_entity(entity_id: str, database: Optional[str] = None) -> list[dict[str, Any]]:
    """Find InfluxDB series that have the specified Home Assistant entity_id tag."""
    query = f"SHOW SERIES WHERE \"entity_id\" = {quote_string(entity_id)}"
    return table_from_result(influx_query_raw(query, database=database or DATABASE), max_rows=MAX_ROWS)


@mcp.tool()
def query_influx(query: str, database: Optional[str] = None, max_rows: Optional[int] = None) -> dict[str, Any]:
    """Run a read-only InfluxQL SELECT/SHOW query and return rows."""
    q = validate_readonly_influxql(query)
    limit = min(int(max_rows or MAX_ROWS), MAX_ROWS)
    rows = table_from_result(influx_query_raw(q, database=database or DATABASE), max_rows=limit)
    return {"query": q, "rows": rows, "row_count": len(rows), "truncated": len(rows) >= limit}


@mcp.tool()
def energy_day_night(
    entity_id: str = "energy_consumption",
    measurement: str = "kWh",
    field: str = "value",
    days: int = 30,
    timezone_name: str = "Europe/Kyiv",
    night_start_hour: int = 23,
    night_end_hour: int = 7,
) -> dict[str, Any]:
    """Calculate total kWh split into day/night using real timezone rules."""
    if days < 1:
        raise ValueError("days must be >= 1")
    if days > MAX_DAYS:
        raise ValueError(f"days must be <= max_days ({MAX_DAYS})")
    if not (0 <= night_start_hour <= 23 and 0 <= night_end_hour <= 23):
        raise ValueError("night_start_hour and night_end_hour must be 0..23")

    tz = ZoneInfo(timezone_name)
    query = (
        f"SELECT last({quote_identifier(field)}) AS value "
        f"FROM {quote_identifier(measurement)} "
        f"WHERE \"entity_id\" = {quote_string(entity_id)} "
        f"AND time >= now() - {int(days)}d "
        f"GROUP BY time(1h) fill(previous)"
    )
    rows = table_from_result(influx_query_raw(query, epoch="s"), max_rows=24 * days + 48)

    points: list[tuple[datetime, float]] = []
    for row in rows:
        if row.get("value") is not None:
            points.append((parse_epoch_seconds(row["time"]), float(row["value"])))
    points.sort(key=lambda item: item[0])

    totals = {"day": 0.0, "night": 0.0}
    hourly = {f"{hour:02d}:00": 0.0 for hour in range(24)}
    used_intervals = 0
    skipped_resets = 0

    for index in range(1, len(points)):
        _prev_time, prev_value = points[index - 1]
        cur_time, cur_value = points[index]
        delta = cur_value - prev_value
        if delta < 0:
            skipped_resets += 1
            continue
        if delta == 0:
            continue

        local_hour = cur_time.astimezone(tz).hour
        period = "night" if local_hour >= night_start_hour or local_hour < night_end_hour else "day"
        totals[period] += delta
        hourly[f"{local_hour:02d}:00"] += delta
        used_intervals += 1

    return {
        "entity_id": entity_id,
        "measurement": measurement,
        "field": field,
        "days": days,
        "timezone": timezone_name,
        "night_rule": f"{night_start_hour:02d}:00-{night_end_hour:02d}:00",
        "totals_kwh": {key: round(value, 3) for key, value in totals.items()},
        "total_kwh": round(sum(totals.values()), 3),
        "hourly_distribution_kwh": {key: round(value, 3) for key, value in hourly.items()},
        "points": len(points),
        "used_intervals": used_intervals,
        "skipped_resets": skipped_resets,
        "attribution": "current_interval_hour",
    }


@mcp.tool()
def energy_hourly_distribution(
    entity_id: str = "energy_consumption",
    measurement: str = "kWh",
    field: str = "value",
    days: int = 30,
    timezone_name: str = "Europe/Kyiv",
) -> dict[str, Any]:
    """Return total kWh by local hour of day for the selected period."""
    result = energy_day_night(
        entity_id=entity_id,
        measurement=measurement,
        field=field,
        days=days,
        timezone_name=timezone_name,
        night_start_hour=23,
        night_end_hour=7,
    )
    return {
        "entity_id": result["entity_id"],
        "days": result["days"],
        "timezone": result["timezone"],
        "hourly_distribution_kwh": result["hourly_distribution_kwh"],
        "total_kwh": result["total_kwh"],
        "attribution": result["attribution"],
    }


def build_asgi_app():
    return AuthASGIMiddleware(mcp.sse_app())


if __name__ == "__main__":
    print("InfluxDB MCP version:", APP_VERSION)
    print("Auth mode:", AUTH_MODE)
    print("Public base URL:", PUBLIC_BASE_URL)
    print("Persist OAuth tokens:", PERSIST_OAUTH_TOKENS)
    print("Loaded OAuth tokens:", len(ACCESS_TOKENS))
    print("Token store path:", TOKEN_STORE_PATH)
    print("Allowed hosts:", ", ".join(allowed_hosts))
    print("Allowed origins:", ", ".join(allowed_origins))
    uvicorn.run(build_asgi_app(), host="0.0.0.0", port=8000, log_level="info")
