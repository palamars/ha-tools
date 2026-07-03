from __future__ import annotations

import re
from typing import Any, Optional

import requests

from .config import DATABASE, INFLUX_URL, MAX_ROWS, PASSWORD, USERNAME


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
