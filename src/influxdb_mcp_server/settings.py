from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class ServerSettings(BaseModel):
    name: str = "influxdb-mcp-server"
    host: str = "127.0.0.1"
    port: int = 8000


class InfluxDBSettings(BaseModel):
    url: str = "http://localhost:8086"
    org: str
    bucket: str | None = None
    token: str | None = None
    timeout_seconds: float = 20
    verify_ssl: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("InfluxDB URL must start with http:// or https://")
        return value.rstrip("/")


class SecuritySettings(BaseModel):
    allow_raw_flux: bool = False
    max_records: int = Field(default=1000, ge=1, le=100_000)
    max_query_chars: int = Field(default=10_000, ge=100, le=200_000)
    allowed_buckets: list[str] = Field(default_factory=list)


class DefaultSettings(BaseModel):
    range_start: str = "-24h"


class AppSettings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    influxdb: InfluxDBSettings
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    defaults: DefaultSettings = Field(default_factory=DefaultSettings)

    def bucket_allowed(self, bucket: str | None) -> bool:
        effective_bucket = bucket or self.influxdb.bucket
        if not effective_bucket:
            return False

        allowed = self.security.allowed_buckets
        if not allowed:
            return effective_bucket == self.influxdb.bucket

        return effective_bucket in allowed


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Settings file {path} must contain a YAML object")

    return data


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"Environment variable {name} must be a boolean")


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else None


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else None


def _env_list(name: str) -> list[str] | None:
    raw = os.getenv(name)
    if raw in (None, ""):
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_token(name: str) -> str | None:
    token_file = os.getenv(f"{name}_FILE")
    if token_file:
        return Path(token_file).read_text(encoding="utf-8").strip()

    value = os.getenv(name)
    return value if value not in (None, "") else None


def _deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_update(result[key], value)
        elif value is not None:
            result[key] = value
    return result


def load_settings() -> AppSettings:
    settings_path = Path(
        os.getenv("INFLUXDB_MCP_SETTINGS")
        or os.getenv("SETTINGS_PATH")
        or "settings.yaml"
    )

    data = _read_yaml(settings_path)

    env_patch: dict[str, Any] = {
        "server": {
            "name": os.getenv("MCP_SERVER_NAME"),
            "host": os.getenv("MCP_HOST"),
            "port": _env_int("MCP_PORT"),
        },
        "influxdb": {
            "url": os.getenv("INFLUXDB_URL"),
            "org": os.getenv("INFLUXDB_ORG"),
            "bucket": os.getenv("INFLUXDB_BUCKET"),
            "token": _env_token("INFLUXDB_TOKEN"),
            "timeout_seconds": _env_float("INFLUXDB_TIMEOUT_SECONDS"),
            "verify_ssl": _env_bool("INFLUXDB_VERIFY_SSL"),
        },
        "security": {
            "allow_raw_flux": _env_bool("MCP_ALLOW_RAW_FLUX"),
            "max_records": _env_int("MCP_MAX_RECORDS"),
            "max_query_chars": _env_int("MCP_MAX_QUERY_CHARS"),
            "allowed_buckets": _env_list("MCP_ALLOWED_BUCKETS"),
        },
        "defaults": {
            "range_start": os.getenv("MCP_DEFAULT_RANGE_START"),
        },
    }

    merged = _deep_update(data, env_patch)
    return AppSettings.model_validate(merged)
