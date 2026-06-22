from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core.config import get_settings
from core.logging_config import configure_logging, system_logger
from core.mcp_client import MCPClientHost
from core.observability import configure_observability
from services.agent.hitl import ApprovalGate
from services.agent.service import AgentService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(
        level=settings.log_level,
        diagnostic_path=settings.diagnostic_log_path,
        audit_path=settings.audit_log_path,
    )
    configure_observability(settings)
    mcp_host = MCPClientHost()
    approvals = ApprovalGate(settings)
    app.state.mcp_host = mcp_host
    app.state.approvals = approvals
    app.state.agent = AgentService(settings, mcp_host, approvals)
    system_logger(component="lifecycle").info("NexusMCP backend started")
    try:
        yield
    finally:
        await mcp_host.close()
        system_logger(component="lifecycle").info("NexusMCP backend stopped")


app = FastAPI(
    title="NexusMCP",
    version="1.0.0",
    description="Enterprise MCP-powered agentic assistant gateway",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Traceparent", "Tracestate"],
    expose_headers=["Traceparent"],
)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)

