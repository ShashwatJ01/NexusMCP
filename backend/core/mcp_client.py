from __future__ import annotations

import asyncio
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncContextManager, cast

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from opentelemetry import propagate, trace
from opentelemetry.trace import Status, StatusCode

from core.logging_config import audit_logger, system_logger
from core.schemas import (
    ConnectServerRequest,
    RemoteServerConfig,
    ServerStatus,
    ServerView,
    StdioServerConfig,
    ToolAccess,
    ToolDescriptor,
    TransportKind,
)

tracer = trace.get_tracer(__name__)
_DESTRUCTIVE = re.compile(r"(^|[_-])(delete|remove|drop|destroy|purge|revoke)([_-]|$)", re.I)
_MUTATING = re.compile(
    r"(^|[_-])(create|write|update|edit|set|send|post|put|patch|execute)([_-]|$)", re.I
)


@dataclass(slots=True)
class ConnectedServer:
    request: ConnectServerRequest
    stack: AsyncExitStack
    session: ClientSession
    tools: list[ToolDescriptor] = field(default_factory=list)
    status: ServerStatus = ServerStatus.CONNECTED
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    def view(self) -> ServerView:
        return ServerView(
            id=self.request.id,
            name=self.request.name,
            transport=self.request.connection.transport,
            status=self.status,
            tool_count=len(self.tools),
            error=self.error,
            connected_at=self.connected_at,
        )


class MCPClientHost:
    """Own MCP sessions and expose a transport-neutral, typed tool catalog."""

    def __init__(self) -> None:
        self._servers: dict[str, ConnectedServer] = {}
        self._lock = asyncio.Lock()

    async def connect(self, request: ConnectServerRequest) -> ServerView:
        async with self._lock:
            if request.id in self._servers:
                raise ValueError(f"Server '{request.id}' is already connected")

        stack = AsyncExitStack()
        with tracer.start_as_current_span("mcp.server.connect") as span:
            span.set_attribute("mcp.server.id", request.id)
            span.set_attribute("mcp.transport", request.connection.transport.value)
            try:
                read_stream, write_stream = await self._open_transport(stack, request)
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
                connected = ConnectedServer(request=request, stack=stack, session=session)
                connected.tools = await self._load_tools(connected)
                async with self._lock:
                    self._servers[request.id] = connected
                system_logger(server_id=request.id, transport=request.connection.transport.value).info(
                    "MCP server connected with {count} tools", count=len(connected.tools)
                )
                audit_logger(action="server.connect", server_id=request.id).info(
                    "MCP server connection authorized"
                )
                return connected.view()
            except BaseException as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                await stack.aclose()
                raise

    async def _open_transport(
        self, stack: AsyncExitStack, request: ConnectServerRequest
    ) -> tuple[Any, Any]:
        connection = request.connection
        if isinstance(connection, StdioServerConfig):
            params = StdioServerParameters(
                command=connection.command,
                args=connection.args,
                env=connection.env or None,
                cwd=connection.cwd,
            )
            streams = await stack.enter_async_context(stdio_client(params))
            return streams[0], streams[1]

        headers = dict(connection.headers)
        trace_headers: dict[str, str] = {}
        propagate.inject(trace_headers)
        headers.update(trace_headers)
        url = str(connection.url)
        transport: AsyncContextManager[Any]
        if connection.transport is TransportKind.SSE:
            transport = cast(AsyncContextManager[Any], sse_client(url=url, headers=headers))
        else:
            transport = cast(
                AsyncContextManager[Any],
                streamablehttp_client(url=url, headers=headers),
            )
        streams = await stack.enter_async_context(transport)
        return streams[0], streams[1]

    async def _load_tools(self, server: ConnectedServer) -> list[ToolDescriptor]:
        response = await server.session.list_tools()
        result: list[ToolDescriptor] = []
        for tool in response.tools:
            annotations = _as_mapping(getattr(tool, "annotations", None))
            result.append(
                ToolDescriptor(
                    server_id=server.request.id,
                    name=tool.name,
                    title=getattr(tool, "title", None) or tool.name.replace("_", " ").title(),
                    description=tool.description or "",
                    input_schema=cast(dict[str, Any], tool.inputSchema),
                    access=_infer_access(tool.name, annotations),
                )
            )
        return result

    async def refresh_tools(self, server_id: str) -> list[ToolDescriptor]:
        server = self._require_server(server_id)
        try:
            server.tools = await self._load_tools(server)
            server.status = ServerStatus.CONNECTED
            server.error = None
            return list(server.tools)
        except Exception as exc:
            server.status = ServerStatus.DEGRADED
            server.error = str(exc)
            raise

    async def disconnect(self, server_id: str) -> None:
        async with self._lock:
            server = self._servers.pop(server_id, None)
        if server is None:
            raise KeyError(server_id)
        await server.stack.aclose()
        audit_logger(action="server.disconnect", server_id=server_id).info(
            "MCP server disconnected"
        )

    async def close(self) -> None:
        async with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
        await asyncio.gather(*(server.stack.aclose() for server in servers), return_exceptions=True)

    def list_servers(self) -> list[ServerView]:
        return [server.view() for server in self._servers.values()]

    def list_tools(self, server_ids: list[str] | None = None) -> list[ToolDescriptor]:
        selected = set(server_ids) if server_ids is not None else None
        return [
            tool
            for server_id, server in self._servers.items()
            if selected is None or server_id in selected
            for tool in server.tools
        ]

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        server = self._require_server(server_id)
        descriptor = next((tool for tool in server.tools if tool.name == tool_name), None)
        if descriptor is None:
            raise KeyError(f"Unknown tool '{server_id}/{tool_name}'")

        with tracer.start_as_current_span("mcp.tool.call") as span:
            span.set_attribute("mcp.server.id", server_id)
            span.set_attribute("mcp.tool.name", tool_name)
            span.set_attribute("mcp.tool.access", descriptor.access.value)
            try:
                response = await server.session.call_tool(tool_name, arguments)
                return {
                    "content": [_as_mapping(item) for item in response.content],
                    "is_error": bool(getattr(response, "isError", False)),
                    "structured_content": getattr(response, "structuredContent", None),
                }
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                server.status = ServerStatus.DEGRADED
                server.error = str(exc)
                raise

    def _require_server(self, server_id: str) -> ConnectedServer:
        server = self._servers.get(server_id)
        if server is None:
            raise KeyError(f"Unknown MCP server '{server_id}'")
        return server


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return cast(dict[str, Any], model_dump(mode="json", by_alias=True))
    return {"value": str(value)}


def _infer_access(name: str, annotations: dict[str, Any]) -> ToolAccess:
    if annotations.get("destructiveHint") is True or _DESTRUCTIVE.search(name):
        return ToolAccess.DELETE
    if annotations.get("readOnlyHint") is True:
        return ToolAccess.READ
    if _MUTATING.search(name):
        return ToolAccess.WRITE
    return ToolAccess.UNKNOWN

