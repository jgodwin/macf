from __future__ import annotations

import argparse
import asyncio
import threading
from pathlib import Path

import uvicorn

from macf.models import ConferenceConfig
from macf.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="MACF - Multi-Agent Conference Framework")
    parser.add_argument("--topic", default="", help="Pre-set conference topic (can also set from dashboard)")
    parser.add_argument("--goal", default="", help="Pre-set conference goal (can also set from dashboard)")
    parser.add_argument("--config", default=None, help="JSON config file to pre-load topic, goal, and roles")
    parser.add_argument("--from-session", default=None, help="Restart from a previous session's config.json")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--sessions-dir", default=None, help="Base directory for session data (default: ./sessions/)")
    parser.add_argument("--mcp-port", type=int, default=8001, help="Port for the MCP server")
    args = parser.parse_args()

    # Load config if provided, otherwise start blank for dashboard-driven setup
    config = None
    if args.config and args.from_session:
        parser.error("Cannot use both --config and --from-session")
    if args.config:
        config = ConferenceConfig.model_validate_json(Path(args.config).read_text())
    elif args.from_session:
        config_path = Path(args.from_session) / "config.json"
        if not config_path.exists():
            parser.error(f"No config.json found in session directory: {args.from_session}")
        config = ConferenceConfig.model_validate_json(config_path.read_text())

    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else None
    app = create_app(
        topic=args.topic or (config.topic if config else ""),
        goal=args.goal or (config.goal if config else ""),
        roles=config.roles if config else None,
        sessions_dir=sessions_dir,
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

    print("MACF - Multi-Agent Conference Framework")
    print(f"  Dashboard:  http://{args.host}:{args.port}")
    print(f"  MCP Server: http://{args.host}:{args.mcp_port}/mcp")
    print(f"  Workspace:  {app.state.file_manager.workspace_dir.resolve()}")
    if args.topic or (config and config.topic):
        print(f"  Topic: {args.topic or config.topic}")
    else:
        print("  No topic set — configure from the dashboard")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
