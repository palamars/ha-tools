from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from influxdb_client import InfluxDBClient

from .settings import AppSettings


_DURATION_RE = re.compile(r"^-?\d+(ns|us|µs|ms|s|m|h|d|w)$")
_AGGREGATE_FUNCTIONS = {"mean", "sum", "min", "max", "count", "last", "first", "median"}


def _flux_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _flux_array(values: list[str]) -> str:
    return "[" + ", ".join(_flux_string(value) for value in values) + "]"


def _flux_time(value: str) -> str:
    value = value.strip()
    if value == "now()" or _DURATION_RE.match(value):
        return value

    # ISO-8601 timestamp, for example 2026-07-04T00:00:00Z.
    if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        return f"time(v: {_flux_string(value)})"

    raise ValueError(
        "Time value must be a Flux duration like -24h, now(), "
        "or an ISO timestamp like 2026-07-04T00:00:00Z"
    )


def _flux_duration(value: str) -> str:
    value = value.strip()
    if not _DURATION_RE.match(value) or value.startswith("-"):
        raise ValueError("Duration must look like 10s, 5m, 1h, 1d or 1w")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class InfluxService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        token = settings.influxdb.token
        if not token:
            raise ValueError(
                "InfluxDB token is required. Set INFLUXDB_TOKEN, "
                "INFLUXDB_TOKEN_FILE or influxdb.token in local settings.yaml."
            )

        self.client = InfluxDBClient(
            url=settings.influxdb.url,
            token=token,
            org=settings.influxdb.org,
            timeout=int(settings.influxdb.timeout_seconds * 1000),
            verify_ssl=settings.influxdb.verify_ssl,
        )

    def close(self) -> None:
        self.client.close()

    def _bucket(self, bucket: str | None) -> str:
        effective_bucket = bucket or self.settings.influxdb.bucket
        if not effective_bucket:
            raise ValueError("Bucket is required. Set INFLUXDB_BUCKET or pass bucket.")

        if not self.settings.bucket_allowed(effective_bucket):
            raise ValueError(
                f"Bucket {effective_bucket!r} is not allowed by security.allowed_buckets"
            )

        return effective_bucket

    def health(self) -> dict[str, Any]:
        health = self.client.health()
        return {
            "ok": health.status == "pass",
            "status": health.status,
            "message": getattr(health, "message", None),
            "version": getattr(health, "version", None),
        }

    def list_buckets(self) -> dict[str, Any]:
        buckets = self.client.buckets_api().find_buckets().buckets or []
        allowed = self.settings.security.allowed_buckets
        names = [bucket.name for bucket in buckets]

        if allowed:
            names = [name for name in names if name in allowed]

        return {"buckets": names}

    def query_flux(self, query: str, max_records: int | None = None) -> dict[str, Any]:
        query = query.strip()
        if len(query) > self.settings.security.max_query_chars:
            raise ValueError("Flux query is longer than security.max_query_chars")

        limit = min(max_records or self.settings.security.max_records, self.settings.security.max_records)
        tables = self.client.query_api().query(org=self.settings.influxdb.org, query=query)

        records: list[dict[str, Any]] = []
        truncated = False

        for table in tables:
            for record in table.records:
                if len(records) >= limit:
                    truncated = True
                    break
                records.append(_jsonable(record.values))
            if truncated:
                break

        return {"records": records, "count": len(records), "truncated": truncated}

    def list_measurements(
        self,
        bucket: str | None = None,
        start: str | None = None,
        max_records: int | None = None,
    ) -> dict[str, Any]:
        effective_bucket = self._bucket(bucket)
        range_start = _flux_time(start or self.settings.defaults.range_start)

        query = f"""import "influxdata/influxdb/schema"

schema.measurements(bucket: {_flux_string(effective_bucket)}, start: {range_start})
"""
        result = self.query_flux(query, max_records=max_records)
        measurements = sorted(
            {
                str(record.get("_value"))
                for record in result["records"]
                if record.get("_value") is not None
            }
        )
        return {"measurements": measurements, "count": len(measurements)}

    def list_field_keys(
        self,
        measurement: str,
        bucket: str | None = None,
        start: str | None = None,
        max_records: int | None = None,
    ) -> dict[str, Any]:
        effective_bucket = self._bucket(bucket)
        range_start = _flux_time(start or self.settings.defaults.range_start)

        query = f"""import "influxdata/influxdb/schema"

schema.fieldKeys(
  bucket: {_flux_string(effective_bucket)},
  predicate: (r) => r._measurement == {_flux_string(measurement)},
  start: {range_start}
)
"""
        result = self.query_flux(query, max_records=max_records)
        fields = sorted(
            {
                str(record.get("_value"))
                for record in result["records"]
                if record.get("_value") is not None
            }
        )
        return {"fields": fields, "count": len(fields)}

    def list_tag_keys(
        self,
        measurement: str | None = None,
        bucket: str | None = None,
        start: str | None = None,
        max_records: int | None = None,
    ) -> dict[str, Any]:
        effective_bucket = self._bucket(bucket)
        range_start = _flux_time(start or self.settings.defaults.range_start)

        predicate = ""
        if measurement:
            predicate = f",\n  predicate: (r) => r._measurement == {_flux_string(measurement)}"

        query = f"""import "influxdata/influxdb/schema"

schema.tagKeys(
  bucket: {_flux_string(effective_bucket)}{predicate},
  start: {range_start}
)
"""
        result = self.query_flux(query, max_records=max_records)
        tags = sorted(
            {
                str(record.get("_value"))
                for record in result["records"]
                if record.get("_value") is not None
            }
        )
        return {"tags": tags, "count": len(tags)}

    def list_tag_values(
        self,
        tag: str,
        measurement: str | None = None,
        bucket: str | None = None,
        start: str | None = None,
        max_records: int | None = None,
    ) -> dict[str, Any]:
        effective_bucket = self._bucket(bucket)
        range_start = _flux_time(start or self.settings.defaults.range_start)

        predicate = ""
        if measurement:
            predicate = f",\n  predicate: (r) => r._measurement == {_flux_string(measurement)}"

        query = f"""import "influxdata/influxdb/schema"

schema.tagValues(
  bucket: {_flux_string(effective_bucket)},
  tag: {_flux_string(tag)}{predicate},
  start: {range_start}
)
"""
        result = self.query_flux(query, max_records=max_records)
        values = sorted(
            {
                str(record.get("_value"))
                for record in result["records"]
                if record.get("_value") is not None
            }
        )
        return {"values": values, "count": len(values)}

    def query_measurement(
        self,
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
        effective_bucket = self._bucket(bucket)
        range_start = _flux_time(start or self.settings.defaults.range_start)

        range_clause = f"range(start: {range_start}"
        if stop:
            range_clause += f", stop: {_flux_time(stop)}"
        range_clause += ")"

        parts = [
            f"from(bucket: {_flux_string(effective_bucket)})",
            f"  |> {range_clause}",
            f"  |> filter(fn: (r) => r[\"_measurement\"] == {_flux_string(measurement)})",
        ]

        if fields:
            parts.append(
                f"  |> filter(fn: (r) => contains(value: r[\"_field\"], set: {_flux_array(fields)}))"
            )

        for tag_name, tag_value in (tags or {}).items():
            parts.append(
                "  |> filter(fn: (r) => "
                f"r[{_flux_string(tag_name)}] == {_flux_string(tag_value)})"
            )

        if aggregate_window:
            if aggregate_fn not in _AGGREGATE_FUNCTIONS:
                raise ValueError(
                    "aggregate_fn must be one of: " + ", ".join(sorted(_AGGREGATE_FUNCTIONS))
                )
            parts.append(
                f"  |> aggregateWindow(every: {_flux_duration(aggregate_window)}, "
                f"fn: {aggregate_fn}, createEmpty: false)"
            )

        parts.append('  |> yield(name: "result")')
        query = "\n".join(parts)
        return self.query_flux(query, max_records=max_records)
