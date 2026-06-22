from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from core.mcp_client import MCPClientHost
from core.schemas import (
    ChatRequest,
    ConnectServerRequest,
    HitlDecisionRequest,
    PendingToolCall,
    ServerView,
    ToolDescriptor,
)
from services.agent.hitl import ApprovalGate
from services.agent.service import AgentService

router = APIRouter(prefix="/api")


def _services(request: Request) -> tuple[MCPClientHost, ApprovalGate, AgentService]:
    return request.app.state.mcp_host, request.app.state.approvals, request.app.state.agent


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    host, _, _ = _services(request)
    servers = host.list_servers()
    return {
        "status": "ok",
        "connected_servers": sum(server.status == "connected" for server in servers),
        "tool_count": len(host.list_tools()),
    }


@router.get("/mcp/servers", response_model=list[ServerView])
async def list_servers(request: Request) -> list[ServerView]:
    host, _, _ = _services(request)
    return host.list_servers()


@router.post(
    "/mcp/servers", response_model=ServerView, status_code=status.HTTP_201_CREATED
)
async def connect_server(payload: ConnectServerRequest, request: Request) -> ServerView:
    host, _, _ = _services(request)
    try:
        return await host.connect(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP connection failed: {exc}") from exc


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_server(server_id: str, request: Request) -> Response:
    host, _, _ = _services(request)
    try:
        await host.disconnect(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mcp/tools", response_model=list[ToolDescriptor])
async def list_tools(request: Request) -> list[ToolDescriptor]:
    host, _, _ = _services(request)
    return host.list_tools()


@router.post("/mcp/servers/{server_id}/refresh", response_model=list[ToolDescriptor])
async def refresh_tools(server_id: str, request: Request) -> list[ToolDescriptor]:
    host, _, _ = _services(request)
    try:
        return await host.refresh_tools(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/hitl/pending", response_model=list[PendingToolCall])
async def pending_approvals(request: Request) -> list[PendingToolCall]:
    _, approvals, _ = _services(request)
    return approvals.list_pending()


@router.post("/hitl/{approval_id}/decision", response_model=PendingToolCall)
async def decide_tool_call(
    approval_id: UUID, payload: HitlDecisionRequest, request: Request
) -> PendingToolCall:
    _, approvals, _ = _services(request)
    try:
        return await approvals.decide(approval_id, payload.decision, payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval is absent or already resolved") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=410, detail="Approval expired") from exc


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    _, _, agent = _services(request)

    async def encode() -> AsyncIterator[str]:
        async for event in agent.stream(payload):
            data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
            yield f"event: {event.event}\ndata: {data}\n\n"

    return StreamingResponse(
        encode(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

