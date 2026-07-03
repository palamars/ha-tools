# InfluxDB MCP Home Assistant add-on

Read-only MCP server for Home Assistant + InfluxDB v1 / InfluxQL.

This repository is formatted as a Home Assistant add-on repository. The add-on code is in `influx_mcp/`, but the Home Assistant add-on slug is `influxdb_mcp`, so it does not conflict with an older local add-on installed as `local_influx_mcp`.

## Add this repository to Home Assistant

Home Assistant → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add:

```text
https://github.com/palamars/ha-tools
```

Then install **InfluxDB MCP** from the add-on store.

## Secrets

No real local values are stored in this repository.

Configure sensitive values only in Home Assistant add-on options. OAuth access tokens are created at runtime in `/data/oauth_tokens.json` inside the add-on data directory.

## Tools

- `health` — add-on and InfluxDB connectivity check.
- `show_databases` — list InfluxDB databases.
- `show_measurements` — list measurements.
- `show_field_keys` — list fields for a measurement.
- `show_tag_values` — list tag values.
- `find_series_by_entity` — find series by Home Assistant `entity_id`.
- `query_influx` — run read-only `SELECT` or `SHOW` InfluxQL.
- `energy_day_night` — calculate kWh split by day/night tariff.
- `energy_hourly_distribution` — calculate energy distribution by local hour.

`query_influx` blocks write/admin statements and multiple statements.

## Required configuration

Open the add-on configuration and replace the example values with your real values.

For ChatGPT / external MCP access, `public_base_url` must be the external HTTPS URL that points to this add-on through your reverse proxy.

## Test

```bash
curl -i https://mcp.example.com/health
curl -i -N https://mcp.example.com/sse
```

Without an OAuth token, `/sse` should return `401`, not `500`.
