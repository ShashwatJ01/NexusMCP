from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TransportKind(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class ServerStatus(StrEnum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class ToolAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    UNKNOWN = "unknown"


class StdioServerConfig(StrictModel):
    transport: Literal[TransportKind.STDIO] = TransportKind.STDIO
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class RemoteServerConfig(StrictModel):
    transport: Literal[TransportKind.SSE, TransportKind.STREAMABLE_HTTP]
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)


ServerConnection = Annotated[
    StdioServerConfig | RemoteServerConfig, Field(discriminator="transport")
]
SERVER_CONNECTION_ADAPTER = TypeAdapter(ServerConnection)


class ConnectServerRequest(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    connection: ServerConnection


class ServerView(StrictModel):
    id: str
    name: str
    transport: TransportKind
    status: ServerStatus
    tool_count: int = 0
    error: str | None = None
    connected_at: datetime | None = None


class ToolDescriptor(StrictModel):
    server_id: str
    name: str
    title: str
    description: str = ""
    input_schema: dict[str, Any]
    access: ToolAccess


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(StrictModel):
    conversation_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=32_000)
    server_ids: list[str] | None = None


class HitlDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class HitlDecisionRequest(StrictModel):
    decision: HitlDecision
    reason: str | None = Field(default=None, max_length=500)


class PendingToolCall(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: str
    server_id: str
    tool_name: str
    access: ToolAccess
    arguments: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"


class StreamEvent(StrictModel):
    event: Literal[
        "session", "token", "tool_call", "tool_result", "hitl_required", "error", "done"
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None

