from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final

from loguru import logger

AUDIT_CHANNEL: Final[str] = "audit"
SYSTEM_CHANNEL: Final[str] = "system"


def _is_audit(record: dict[str, object]) -> bool:
    extra = record.get("extra", {})
    return isinstance(extra, dict) and extra.get("channel") == AUDIT_CHANNEL


def _is_system(record: dict[str, object]) -> bool:
    return not _is_audit(record)


class InterceptHandler(logging.Handler):
    """Route standard-library logs through Loguru without losing exceptions."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(
    *, level: str, diagnostic_path: str, audit_path: str
) -> None:
    """Install separate JSON sinks for operator diagnostics and audit evidence."""

    diagnostics = Path(diagnostic_path)
    audit = Path(audit_path)
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    audit.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        filter=_is_system,
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )
    logger.add(
        diagnostics,
        level=level.upper(),
        filter=_is_system,
        serialize=True,
        rotation="25 MB",
        retention="14 days",
        compression="gz",
        enqueue=True,
    )
    logger.add(
        audit,
        level="INFO",
        filter=_is_audit,
        serialize=True,
        rotation="25 MB",
        retention="90 days",
        compression="gz",
        enqueue=True,
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "mcp"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False


def system_logger(**context: object):  # type: ignore[no-untyped-def]
    return logger.bind(channel=SYSTEM_CHANNEL, **context)


def audit_logger(**context: object):  # type: ignore[no-untyped-def]
    return logger.bind(channel=AUDIT_CHANNEL, **context)

