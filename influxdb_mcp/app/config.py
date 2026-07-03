from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

APP_VERSION = "0.5.0"
OPTIONS_PATH = Path("/data/options.json")
TOKEN_STORE_PATH = Path("/data/oauth_tokens.json")


def load_options() -> dict[str, Any]:
    if OPTIONS_PATH.exists():
        with OPTIONS_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
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
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
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

ALLOWED_HOSTS = option_list("allowed_hosts")
for item in [public_host, f"{public_host}:*", "127.0.0.1:*", "localhost:*"]:
    if item and item not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(item)

ALLOWED_ORIGINS = option_list("allowed_origins")
for item in [public_origin, "http://127.0.0.1:*", "http://localhost:*"]:
    if item and item not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(item)
