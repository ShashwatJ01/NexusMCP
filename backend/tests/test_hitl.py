from __future__ import annotations

import asyncio

import pytest

from core.config import Settings
from core.schemas import HitlDecision, ToolAccess
from services.agent.hitl import ApprovalGate


@pytest.mark.asyncio
async def test_sensitive_call_requires_one_time_decision() -> None:
    gate = ApprovalGate(Settings(environment="test", hitl_timeout_seconds=10))
    pending = await gate.create(
        conversation_id="conversation-1",
        server_id="crm",
        tool_name="delete_contact",
        access=ToolAccess.DELETE,
        arguments={"contact_id": "C-42"},
    )

    waiting = asyncio.create_task(gate.wait(pending.id))
    decided = await gate.decide(pending.id, HitlDecision.APPROVE, "Validated ticket")

    assert await waiting is HitlDecision.APPROVE
    assert decided.status == "approved"
    assert gate.list_pending() == []
    with pytest.raises(KeyError):
        await gate.decide(pending.id, HitlDecision.APPROVE, None)


@pytest.mark.asyncio
async def test_rejection_is_returned_to_waiter() -> None:
    gate = ApprovalGate(Settings(environment="test", hitl_timeout_seconds=10))
    pending = await gate.create(
        conversation_id="conversation-2",
        server_id="repo",
        tool_name="write_file",
        access=ToolAccess.WRITE,
        arguments={"path": "policy.md"},
    )
    waiting = asyncio.create_task(gate.wait(pending.id))
    await gate.decide(pending.id, HitlDecision.REJECT, "Incorrect repository")

    assert await waiting is HitlDecision.REJECT

