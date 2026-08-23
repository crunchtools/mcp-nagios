"""MCP server for Nagios Core monitoring."""

import argparse

__version__ = "0.1.0"


def main() -> None:
    from .server import mcp

    parser = argparse.ArgumentParser(description="Nagios MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8026)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)
