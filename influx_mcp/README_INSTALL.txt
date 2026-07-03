InfluxDB MCP Home Assistant add-on v0.4.5

What changed in v0.4.5:
- Removed local secrets and replaced site-specific defaults with examples.
- Fixed OAuth middleware 401 response bug.
  Previous build could throw KeyError: 'type' on unauthorized POST /sse,
  which appeared to ChatGPT as 502 / upstream error.
- Keeps the v0.4.3 Dockerfile build fix: uses BUILD_ARCH instead of BUILD_FROM.
- OAuth access tokens are persisted in /data/oauth_tokens.json.
- energy_day_night assigns hourly deltas to the current interval hour.

Install/update:
1. Copy all files into:
   /addons/influx_mcp/

2. Reload and update:
   ha addons reload
   ha addons update local_influx_mcp
   ha addons restart local_influx_mcp

If update does not pick it up:
   ha supervisor restart
   ha addons reload
   ha addons update local_influx_mcp
   ha addons restart local_influx_mcp

If update fails:
   ha addons rebuild local_influx_mcp
   ha addons restart local_influx_mcp

Test:
curl -i https://mcp.example.com/health
curl -i -N https://mcp.example.com/sse

Without OAuth token /sse should return 401, not 500.
After reconnecting ChatGPT, /health should show loaded_oauth_tokens >= 1.
