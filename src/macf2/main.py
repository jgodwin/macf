from __future__ import annotations

import argparse
import asyncio
import json
import threading
from pathlib import Path

import uvicorn

from macf2.models import ConferenceConfig
from macf2.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="MACF2 - Multi-Agent Conference Framework")
    parser.add_argument("--topic", default=None, help="Conference topic")
    parser.add_argument("--goal", default="", help="What the agents should accomplish")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a JSON config file defining topic, goal, and roles",
    )
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

    # Load config from file or CLI args
    if args.config:
        config_path = Path(args.config)
        config = ConferenceConfig.model_validate_json(config_path.read_text())
    else:
        config = ConferenceConfig(
            topic=args.topic or "Untitled Conference",
            goal=args.goal,
        )

    # CLI --topic and --goal override config file values
    if args.topic:
        config.topic = args.topic
    if args.goal:
        config.goal = args.goal

    workspace = Path(args.workspace) if args.workspace else None
    app = create_app(
        topic=config.topic,
        goal=config.goal,
        roles=config.roles,
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

    print(f"MACF2 Conference: {config.topic}")
    if config.goal:
        print(f"Goal: {config.goal}")
    if config.roles:
        print(f"Roles: {', '.join(r.name for r in config.roles)}")
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"MCP Server: http://{args.host}:{args.mcp_port}/mcp")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
