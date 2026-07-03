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

    @mcp.tool()
    def find_series_by_entity(entity_id: str, database: Optional[str] = None) -> list[dict[str, Any]]:
        """Find InfluxDB series that have the specified Home Assistant entity_id tag."""
        query = f"SHOW SERIES WHERE \"entity_id\" = {quote_string(entity_id)}"
        return table_from_result(influx_query_raw(query, database=database or DATABASE), max_rows=MAX_ROWS)

    @mcp.tool()
    def query_influx(
        query: str,
        database: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> dict[str, Any]:
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
