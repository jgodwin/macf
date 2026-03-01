from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from macf2.conference import ConferenceManager
from macf2.file_manager import FileManager
from macf2.mcp_server import create_mcp_server


class ConfigureRequest(BaseModel):
    topic: str
    goal: str = ""
    roles: list[dict] = []


class RegisterRequest(BaseModel):
    name: str
    role: str = ""


class ModeratorMessageRequest(BaseModel):
    content: str


class HaltRequest(BaseModel):
    reason: str = ""


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_text(data)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)


def create_app(
    topic: str = "Untitled Conference",
    goal: str = "",
    roles: list | None = None,
    workspace_dir: Path | None = None,
    mcp_host: str = "127.0.0.1",
    mcp_port: int = 8001,
) -> FastAPI:
    app = FastAPI(title="MACF2 Dashboard")
    ws_manager = ConnectionManager()
    mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"

    mcp_components = create_mcp_server(
        topic=topic, goal=goal, roles=roles,
        workspace_dir=workspace_dir,
        mcp_host=mcp_host, mcp_port=mcp_port,
    )
    conference: ConferenceManager = mcp_components["conference"]
    file_manager: FileManager = mcp_components["file_manager"]
    mcp = mcp_components["mcp"]

    # Wire conference events to WebSocket broadcast
    async def on_conference_event(event_type: str, data: dict) -> None:
        await ws_manager.broadcast({"event": event_type, **data})

    conference.on_event(on_conference_event)

    # --- REST endpoints for dashboard ---

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/conference")
    async def get_conference():
        return {
            "topic": conference.state.topic,
            "goal": conference.state.goal,
            "status": conference.state.status.value,
            "current_round": conference.state.current_round,
            "agent_count": len(conference._active_agent_ids()),
            "roles": [{"name": r.name, "description": r.description} for r in conference._roles],
        }

    @app.get("/api/agents")
    async def get_agents():
        return conference.get_agents_info()

    @app.get("/api/board")
    async def get_board():
        return conference.get_board()

    @app.get("/api/round")
    async def get_round():
        if not conference.state.rounds:
            return {"round_number": 0, "status": "waiting"}
        return conference.get_round_info()

    @app.get("/api/files")
    async def get_files():
        return file_manager.list_files()

    @app.post("/api/register")
    async def register(req: RegisterRequest):
        agent_id = conference.register_agent(req.name, role=req.role)
        return {"agent_id": agent_id}

    @app.post("/api/start")
    async def start():
        conference.start()
        return {"status": "started"}

    @app.post("/api/moderator/message")
    async def moderator_message(req: ModeratorMessageRequest):
        conference.add_moderator_message(req.content)
        return {"status": "sent"}

    @app.post("/api/halt")
    async def halt(req: HaltRequest):
        conference.halt(req.reason)
        return {"status": "halted"}

    @app.post("/api/configure")
    async def configure(req: ConfigureRequest):
        from macf2.models import RoleConfig
        role_configs = [RoleConfig(**r) for r in req.roles] if req.roles else None
        conference.configure(topic=req.topic, goal=req.goal, roles=role_configs)
        return {"status": "configured"}

    @app.get("/api/roles")
    async def get_roles():
        return conference.get_available_roles()

    @app.get("/api/prompt")
    async def get_prompt():
        from macf2.conference import generate_agent_prompt
        return {"prompt": generate_agent_prompt(mcp_url), "mcp_url": mcp_url}

    # --- WebSocket for real-time updates ---

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            # Send current state on connect
            await websocket.send_text(json.dumps({
                "event": "initial_state",
                "topic": conference.state.topic,
                "status": conference.state.status.value,
                "agents": conference.get_agents_info(),
                "messages": conference.get_board(),
                "current_round": conference.state.current_round,
            }, default=str))
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "moderator_message":
                    conference.add_moderator_message(msg["content"])
                elif msg.get("type") == "halt":
                    conference.halt(msg.get("reason", ""))
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # --- Dashboard HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        html_path = Path(__file__).parent / "static" / "index.html"
        return HTMLResponse(html_path.read_text())

    # --- Store references for external access ---
    app.state.mcp = mcp
    app.state.conference = conference
    app.state.file_manager = file_manager

    return app
