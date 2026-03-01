from __future__ import annotations

import argparse
import asyncio
import threading
from pathlib import Path

import uvicorn

from macf2.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="MACF2 - Multi-Agent Conference Framework")
    parser.add_argument("--topic", default="Untitled Conference", help="Conference topic")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Directory for shared files (default: temp dir)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=8001,
        help="Port for the MCP server (streamable HTTP)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace) if args.workspace else None
    app = create_app(
        topic=args.topic,
        workspace_dir=workspace,
        mcp_host=args.host,
        mcp_port=args.mcp_port,
    )

    # Run MCP server in a background thread on a separate port
    mcp = app.state.mcp

    def run_mcp():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mcp.run_streamable_http_async())

    mcp_thread = threading.Thread(target=run_mcp, daemon=True)
    mcp_thread.start()

    print(f"MACF2 Conference: {args.topic}")
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"MCP Server: http://{args.host}:{args.mcp_port}/mcp")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
