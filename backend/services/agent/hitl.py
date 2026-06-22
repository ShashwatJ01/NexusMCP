from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.config import Settings
from core.logging_config import audit_logger
from core.schemas import HitlDecision, PendingToolCall, ToolAccess


class ApprovalGate:
    """One-shot asynchronous approval state machine for sensitive calls."""

    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.hitl_timeout_seconds
        self._pending: dict[UUID, PendingToolCall] = {}
        self._waiters: dict[UUID, asyncio.Future[HitlDecision]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        conversation_id: str,
        server_id: str,
        tool_name: str,
        access: ToolAccess,
        arguments: dict[str, object],
    ) -> PendingToolCall:
        now = datetime.now(UTC)
        pending = PendingToolCall(
            conversation_id=conversation_id,
            server_id=server_id,
            tool_name=tool_name,
            access=access,
            arguments=arguments,
            expires_at=now + timedelta(seconds=self._timeout),
        )
        waiter = asyncio.get_running_loop().create_future()
        async with self._lock:
            expired = [
                approval_id
                for approval_id, item in self._pending.items()
                if item.expires_at <= now
            ]
            for approval_id in expired:
                self._pending.pop(approval_id, None)
                self._waiters.pop(approval_id, None)
            self._pending[pending.id] = pending
            self._waiters[pending.id] = waiter
        audit_logger(
            action="tool.approval.requested",
            approval_id=str(pending.id),
            server_id=server_id,
            tool_name=tool_name,
            access=access.value,
        ).info("Sensitive MCP tool call awaiting a human decision")
        return pending

    async def wait(self, approval_id: UUID) -> HitlDecision:
        async with self._lock:
            waiter = self._waiters.get(approval_id)
        if waiter is None:
            raise KeyError(approval_id)
        try:
            decision = await asyncio.wait_for(asyncio.shield(waiter), timeout=self._timeout)
            async with self._lock:
                self._waiters.pop(approval_id, None)
            return decision
        except TimeoutError:
            async with self._lock:
                pending = self._pending.get(approval_id)
                if pending is not None:
                    pending.status = "expired"
                self._waiters.pop(approval_id, None)
            audit_logger(action="tool.approval.expired", approval_id=str(approval_id)).warning(
                "Sensitive MCP tool approval expired"
            )
            return HitlDecision.REJECT

    async def decide(
        self, approval_id: UUID, decision: HitlDecision, reason: str | None
    ) -> PendingToolCall:
        async with self._lock:
            pending = self._pending.get(approval_id)
            waiter = self._waiters.get(approval_id)
            if pending is None or waiter is None or waiter.done():
                raise KeyError(approval_id)
            if pending.expires_at <= datetime.now(UTC):
                pending.status = "expired"
                self._waiters.pop(approval_id, None)
                raise TimeoutError(str(approval_id))
            pending.status = "approved" if decision is HitlDecision.APPROVE else "rejected"
            waiter.set_result(decision)

        audit_logger(
            action=f"tool.approval.{pending.status}",
            approval_id=str(approval_id),
            server_id=pending.server_id,
            tool_name=pending.tool_name,
            reason=reason,
        ).info("Sensitive MCP tool decision recorded")
        return pending

    def list_pending(self) -> list[PendingToolCall]:
        now = datetime.now(UTC)
        return [
            item
            for item in self._pending.values()
            if item.status == "pending" and item.expires_at > now
        ]
