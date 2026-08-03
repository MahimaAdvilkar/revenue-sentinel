"""Structured logging.

JSON by default so logs are queryable; `LOG_FORMAT=console` for a readable local
stream. Configured once at process start.

Log events carry structured key-value pairs, never interpolated prose. This is not
style: from Session 4 onward, log records are correlated by `trace_id` / `run_id`,
and a message that buried those in a formatted string would not be correlatable.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from revenue_sentinel.core.config import LogFormat, LogLevel


def configure_logging(*, level: LogLevel = "INFO", log_format: LogFormat = "json") -> None:
    """Configure structlog and the stdlib root logger. Idempotent."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level),
        force=True,
    )

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for a module."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
