InfluxDB MCP Home Assistant add-on v0.5.0

Repository add-on slug: influxdb_mcp
Repository add-on folder: influxdb_mcp/

This intentionally differs from the older local add-on folder /addons/influx_mcp/ so the GitHub version can be installed as a separate add-on without overwriting the local one.

What changed in v0.5.0:
- Refactored the Python code from one app.py file into a modular app package.
- Kept domain MCP tools together in app/domain_tools.py for future energy, power, tariff and statistics functions.
- Removed the old monolithic app.py entrypoint.
- Docker now copies the app package and starts it with python3 -m app.
- Kept the separate add-on slug: influxdb_mcp.
- No real local secrets are stored in the repository.

Previous fixes kept from v0.4.x:
- Removed local secrets and replaced site-specific defaults with examples.
- Fixed OAuth middleware 401 response bug.
  Previous build could throw KeyError: 'type' on unauthorized POST /sse,
  which appeared to ChatGPT as 502 / upstream error.
- Dockerfile uses BUILD_ARCH instead of BUILD_FROM.
- OAuth access tokens are persisted in /data/oauth_tokens.json.
- energy_day_night assigns hourly deltas to the current interval hour.

Install from Home Assistant repository:
1. Settings -> Add-ons -> Add-on Store -> menu -> Repositories.
2. Add:
   https://github.com/palamars/ha-tools
3. Install InfluxDB MCP.

Optional local install/update:
1. Copy the add-on folder into:
   /addons/influxdb_mcp/

2. Reload and update:
   ha addons reload
   ha addons update local_influxdb_mcp
   ha addons restart local_influxdb_mcp

If update does not pick it up:
   ha supervisor restart
   ha addons reload
   ha addons update local_influxdb_mcp
   ha addons restart local_influxdb_mcp

If update fails:
   ha addons rebuild local_influxdb_mcp
   ha addons restart local_influxdb_mcp

Test:
curl -i https://mcp.example.com/health
curl -i -N https://mcp.example.com/sse

Without OAuth token /sse should return 401, not 500.
After reconnecting ChatGPT, /health should show loaded_oauth_tokens >= 1.
