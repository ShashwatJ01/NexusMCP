from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from opentelemetry import trace

from core.config import Settings
from core.logging_config import system_logger
from core.mcp_client import MCPClientHost
from core.schemas import ChatRequest, HitlDecision, StreamEvent, ToolAccess, ToolDescriptor
from services.agent.hitl import ApprovalGate

tracer = trace.get_tracer(__name__)
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_-]")
_SYSTEM_PROMPT = """You are the Nexus enterprise operations assistant. Use MCP tools when they provide
authoritative information. Never claim a tool succeeded unless its result confirms success. Explain
rejected or failed operations plainly. Prefer read-only inspection before mutation. Keep answers concise
and include material identifiers from tool results."""


class ConversationMemory:
    """Process-local, bounded dialogue memory; replace with a shared store at scale."""

    def __init__(self, max_messages: int, max_conversations: int) -> None:
        self._max_messages = max_messages
        self._max_conversations = max_conversations
        self._messages: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()

    def get(self, conversation_id: str) -> list[dict[str, Any]]:
        history = self._messages.get(conversation_id)
        if history is None:
            return []
        self._messages.move_to_end(conversation_id)
        return list(history)

    def append(self, conversation_id: str, message: dict[str, Any]) -> None:
        history = self._messages.get(conversation_id)
        if history is None:
            history = deque(maxlen=self._max_messages)
            self._messages[conversation_id] = history
        history.append(message)
        self._messages.move_to_end(conversation_id)
        while len(self._messages) > self._max_conversations:
            self._messages.popitem(last=False)


class AgentService:
    """Run model/tool loops while enforcing approval before sensitive execution."""

    def __init__(
        self, settings: Settings, mcp_host: MCPClientHost, approvals: ApprovalGate
    ) -> None:
        self._settings = settings
        self._mcp = mcp_host
        self._approvals = approvals
        self._memory = ConversationMemory(
            settings.max_history_messages, settings.max_active_conversations
        )
        self._client = (
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=str(settings.openai_base_url) if settings.openai_base_url else None,
            )
            if settings.openai_api_key
            else None
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        with tracer.start_as_current_span("agent.chat") as span:
            span.set_attribute("conversation.id", request.conversation_id)
            trace_id = format(span.get_span_context().trace_id, "032x")
            yield StreamEvent(
                event="session",
                trace_id=trace_id,
                data={"conversation_id": request.conversation_id},
            )

            if self._client is None:
                message = (
                    "The model gateway is not configured. Set NEXUS_OPENAI_API_KEY on the backend "
                    "and restart the service; MCP server discovery remains available."
                )
                yield StreamEvent(event="error", trace_id=trace_id, data={"message": message})
                yield StreamEvent(event="done", trace_id=trace_id, data={"status": "blocked"})
                return

            tools = self._mcp.list_tools(request.server_ids)
            tool_specs, aliases = _model_tools(tools)
            self._memory.append(
                request.conversation_id, {"role": "user", "content": request.message}
            )

            for turn in range(self._settings.max_agent_turns):
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    *self._memory.get(request.conversation_id),
                ]
                try:
                    response = await self._client.chat.completions.create(
                        model=self._settings.openai_model,
                        messages=messages,  # type: ignore[arg-type]
                        tools=tool_specs or None,  # type: ignore[arg-type]
                        tool_choice="auto" if tool_specs else None,
                        stream=True,
                    )
                    content_parts: list[str] = []
                    calls: dict[int, dict[str, str]] = {}
                    async for chunk in response:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta.content:
                            content_parts.append(delta.content)
                            yield StreamEvent(
                                event="token", trace_id=trace_id, data={"text": delta.content}
                            )
                        for call in delta.tool_calls or []:
                            target = calls.setdefault(
                                call.index, {"id": "", "name": "", "arguments": ""}
                            )
                            if call.id:
                                target["id"] = call.id
                            if call.function and call.function.name:
                                target["name"] = call.function.name
                            if call.function and call.function.arguments:
                                target["arguments"] += call.function.arguments
                except Exception as exc:
                    system_logger(component="agent", trace_id=trace_id).exception(
                        "Model stream failed: {reason}", reason=str(exc)
                    )
                    yield StreamEvent(
                        event="error",
                        trace_id=trace_id,
                        data={"message": "The model stream failed.", "detail": str(exc)},
                    )
                    yield StreamEvent(event="done", trace_id=trace_id, data={"status": "error"})
                    return

                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                }
                if calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": item["id"],
                            "type": "function",
                            "function": {
                                "name": item["name"],
                                "arguments": item["arguments"],
                            },
                        }
                        for _, item in sorted(calls.items())
                    ]
                self._memory.append(request.conversation_id, assistant_message)

                if not calls:
                    yield StreamEvent(
                        event="done", trace_id=trace_id, data={"status": "complete", "turn": turn + 1}
                    )
                    return

                for _, call in sorted(calls.items()):
                    descriptor = aliases.get(call["name"])
                    if descriptor is None:
                        result = {"is_error": True, "message": "Model selected an unknown tool"}
                    else:
                        try:
                            arguments = json.loads(call["arguments"] or "{}")
                            if not isinstance(arguments, dict):
                                raise ValueError("Tool arguments must be a JSON object")
                        except (json.JSONDecodeError, ValueError) as exc:
                            result = {"is_error": True, "message": str(exc)}
                        else:
                            yield StreamEvent(
                                event="tool_call",
                                trace_id=trace_id,
                                data={
                                    "call_id": call["id"],
                                    "server_id": descriptor.server_id,
                                    "tool_name": descriptor.name,
                                    "access": descriptor.access.value,
                                    "arguments": arguments,
                                },
                            )
                            allowed = True
                            if descriptor.access in {ToolAccess.WRITE, ToolAccess.DELETE}:
                                pending = await self._approvals.create(
                                    conversation_id=request.conversation_id,
                                    server_id=descriptor.server_id,
                                    tool_name=descriptor.name,
                                    access=descriptor.access,
                                    arguments=arguments,
                                )
                                yield StreamEvent(
                                    event="hitl_required",
                                    trace_id=trace_id,
                                    data=pending.model_dump(mode="json"),
                                )
                                allowed = (
                                    await self._approvals.wait(pending.id)
                                ) is HitlDecision.APPROVE
                            if allowed:
                                try:
                                    result = await self._mcp.call_tool(
                                        descriptor.server_id, descriptor.name, arguments
                                    )
                                except Exception as exc:
                                    result = {"is_error": True, "message": str(exc)}
                            else:
                                result = {
                                    "is_error": True,
                                    "message": "Tool execution was rejected or its approval expired.",
                                }

                    yield StreamEvent(
                        event="tool_result",
                        trace_id=trace_id,
                        data={"call_id": call["id"], "result": result},
                    )
                    self._memory.append(
                        request.conversation_id,
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str)[:100_000],
                        },
                    )

            yield StreamEvent(
                event="error",
                trace_id=trace_id,
                data={"message": "Agent stopped after reaching the configured turn limit."},
            )
            yield StreamEvent(event="done", trace_id=trace_id, data={"status": "limit"})


def _model_tools(
    tools: list[ToolDescriptor],
) -> tuple[list[dict[str, Any]], dict[str, ToolDescriptor]]:
    specs: list[dict[str, Any]] = []
    aliases: dict[str, ToolDescriptor] = {}
    for tool in tools:
        digest = hashlib.sha1(f"{tool.server_id}/{tool.name}".encode()).hexdigest()[:8]
        base = _SAFE_NAME.sub("_", f"{tool.server_id}__{tool.name}")[:54]
        alias = f"{base}_{digest}"
        aliases[alias] = tool
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": alias,
                    "description": f"[{tool.server_id}] {tool.description}"[:1024],
                    "parameters": tool.input_schema,
                },
            }
        )
    return specs, aliases
