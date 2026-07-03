#!/bin/sh
set -e

echo "Starting InfluxDB MCP server..."
exec python3 -u /app.py
