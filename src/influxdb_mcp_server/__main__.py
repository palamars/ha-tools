from __future__ import annotations

import argparse

from .server import mcp, settings


def main() -> None:
    parser = argparse.ArgumentParser(description="InfluxDB MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="MCP transport. Use stdio for local desktop clients or sse for HTTP.",
    )
    parser.add_argument("--host", default=settings.server.host)
    parser.add_argument("--port", default=settings.server.port, type=int)
    args = parser.parse_args()

    if hasattr(mcp, "settings"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
