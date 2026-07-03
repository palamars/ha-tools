from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .config import (
    ALLOWED_HOSTS,
    APP_VERSION,
    AUTH_MODE,
    DATABASE,
    INFLUX_URL,
    MAX_DAYS,
    MAX_ROWS,
    PERSIST_OAUTH_TOKENS,
    PUBLIC_BASE_URL,
    TOKEN_STORE_PATH,
)
from .influx import (
    influx_ping,
    influx_query_raw,
    quote_identifier,
    quote_string,
    table_from_result,
    validate_readonly_influxql,
)
from .oauth import ACCESS_TOKENS


def parse_epoch_seconds(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    raise ValueError(f"Unsupported time value: {value!r}")


def register_domain_tools(mcp) -> None:
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
            "allowed_hosts": ALLOWED_HOSTS,
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
        """Show fields for one measurement."""
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
