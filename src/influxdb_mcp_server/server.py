from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .influx import InfluxService
from .settings import load_settings


settings = load_settings()
mcp = FastMCP(settings.server.name)
_service = InfluxService(settings)


@mcp.tool()
def health() -> dict[str, Any]:
    """Check InfluxDB connectivity and return server health."""
    return _service.health()


@mcp.tool()
def list_buckets() -> dict[str, Any]:
    """List InfluxDB buckets allowed by the server settings."""
    return _service.list_buckets()


@mcp.tool()
def list_measurements(
    bucket: str | None = None,
    start: str | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    """List measurements in a bucket for a time range.

    Use start like "-24h", "-7d" or "2026-07-04T00:00:00Z".
    """
    return _service.list_measurements(bucket=bucket, start=start, max_records=max_records)


@mcp.tool()
def list_field_keys(
    measurement: str,
    bucket: str | None = None,
    start: str | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    """List field keys for a measurement."""
    return _service.list_field_keys(
        measurement=measurement,
        bucket=bucket,
        start=start,
        max_records=max_records,
    )


@mcp.tool()
def list_tag_keys(
    measurement: str | None = None,
    bucket: str | None = None,
    start: str | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    """List tag keys, optionally filtered by measurement."""
    return _service.list_tag_keys(
        measurement=measurement,
        bucket=bucket,
        start=start,
        max_records=max_records,
    )


@mcp.tool()
def list_tag_values(
    tag: str,
    measurement: str | None = None,
    bucket: str | None = None,
    start: str | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    """List values for a tag key, optionally filtered by measurement."""
    return _service.list_tag_values(
        tag=tag,
        measurement=measurement,
        bucket=bucket,
        start=start,
        max_records=max_records,
    )


@mcp.tool()
def query_measurement(
    measurement: str,
    bucket: str | None = None,
    start: str | None = None,
    stop: str | None = None,
    fields: list[str] | None = None,
    tags: dict[str, str] | None = None,
    aggregate_window: str | None = None,
    aggregate_fn: str = "mean",
    max_records: int | None = None,
) -> dict[str, Any]:
    """Query a measurement using a guarded Flux template.

    Parameters:
    - start/stop: Flux duration or ISO timestamp.
    - fields: optional list of _field values.
    - tags: optional exact-match tag filters.
    - aggregate_window: optional duration like 5m or 1h.
    - aggregate_fn: mean, sum, min, max, count, last, first or median.
    """
    return _service.query_measurement(
        measurement=measurement,
        bucket=bucket,
        start=start,
        stop=stop,
        fields=fields,
        tags=tags,
        aggregate_window=aggregate_window,
        aggregate_fn=aggregate_fn,
        max_records=max_records,
    )


@mcp.tool()
def run_flux_query(query: str, max_records: int | None = None) -> dict[str, Any]:
    """Run raw Flux query if explicitly enabled in settings.

    This is disabled by default. Prefer the structured read-only tools above.
    """
    if not settings.security.allow_raw_flux:
        return {
            "ok": False,
            "error": (
                "Raw Flux queries are disabled. Set security.allow_raw_flux: true "
                "or MCP_ALLOW_RAW_FLUX=true to enable this tool."
            ),
        }

    result = _service.query_flux(query=query, max_records=max_records)
    return {"ok": True, **result}
