# InfluxDB MCP Home Assistant add-on

Read-only MCP server for Home Assistant + InfluxDB v1 / InfluxQL.

This repository is formatted as a Home Assistant add-on repository. The add-on itself is in `influxdb_mcp/` and uses the slug `influxdb_mcp`, so it does not conflict with an older local `/addons/influx_mcp` add-on.

## Add this repository to Home Assistant

Home Assistant → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add:

```text
https://github.com/palamars/ha-tools
```

Then install **InfluxDB MCP** from the add-on store.

## Secrets

No real local values are stored in this repository.

Configure sensitive values only in Home Assistant add-on options. OAuth access tokens are created at runtime in `/data/oauth_tokens.json` inside the add-on data directory.

## Structure

The Python code is split into modules:

- `app/config.py` — add-on options and derived runtime settings.
- `app/auth.py` — MCP endpoint authorization middleware.
- `app/oauth.py` — OAuth discovery, authorization and token routes.
- `app/influx.py` — InfluxDB v1 / InfluxQL access and read-only validation.
- `app/domain_tools.py` — MCP tools for Home Assistant metrics, energy, power and future domain functions.
- `app/mcp_server.py` — FastMCP app composition and HTTP routes.

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

## Optional local add-on install

If you still want to install it as a local add-on instead of through the repository, copy the add-on folder to Home Assistant:

```bash
/addons/influxdb_mcp/
```

Then run:

```bash
ha addons reload
ha addons update local_influxdb_mcp
ha addons restart local_influxdb_mcp
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

- `repository.yaml` — Home Assistant add-on repository metadata.
- `influxdb_mcp/config.yaml` — Home Assistant add-on manifest and option schema.
- `influxdb_mcp/Dockerfile` — add-on image build.
- `influxdb_mcp/app/` — Python package with MCP, OAuth and InfluxDB modules.
- `influxdb_mcp/run.sh` — container entrypoint.
- `influxdb_mcp/requirements.txt` — Python dependencies.
