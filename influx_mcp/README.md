# InfluxDB MCP Home Assistant add-on

Read-only MCP server for Home Assistant + InfluxDB v1 / InfluxQL.

This is a Home Assistant local add-on. It exposes an MCP SSE endpoint and lets an AI assistant query InfluxDB through safe read-only tools.

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

## Install as a local Home Assistant add-on

Copy this folder to Home Assistant:

```bash
/addons/influx_mcp/
```

Then run:

```bash
ha addons reload
ha addons update local_influx_mcp
ha addons restart local_influx_mcp
```

If Home Assistant does not detect the update:

```bash
ha supervisor restart
ha addons reload
ha addons update local_influx_mcp
ha addons restart local_influx_mcp
```

## Required configuration

Open the add-on configuration and replace the example values with your real values.

For ChatGPT / external MCP access, `public_base_url` must be the external HTTPS URL that points to this add-on through your reverse proxy.

## Test

```bash
curl -i https://mcp.example.com/health
curl -i -N https://mcp.example.com/sse
```

Without an OAuth token, `/sse` should return `401`, not `500`.

## Files

- `config.yaml` — Home Assistant add-on manifest and option schema.
- `Dockerfile` — add-on image build.
- `app.py` — MCP server, OAuth and InfluxQL logic.
- `run.sh` — container entrypoint.
- `requirements.txt` — Python dependencies.
