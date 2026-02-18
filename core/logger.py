"""Structured logging configuration helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import structlog
from rich.logging import RichHandler
from structlog.stdlib import BoundLogger

_RUN_ID = "unknown"


def configure_logging(
    *,
    run_id: str,
    environment: str,
    log_level: str,
    log_dir: Path = Path("logs"),
) -> None:
    """Configure structlog for development console or production JSON output."""

    global _RUN_ID
    _RUN_ID = run_id

    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    if environment == "development":
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=cast(Any, shared_processors),
        )
        handler: logging.Handler = RichHandler(rich_tracebacks=True, show_path=False)
        handler.setFormatter(formatter)
    else:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "auto_trading_pro.jsonl"
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=cast(Any, shared_processors),
        )
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(formatter)

    root_logger.addHandler(handler)

    structlog.configure(
        processors=cast(
            Any,
            [
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
        ),
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id)


def get_logger(module_name: str, *, strategy_id: str | None = None) -> BoundLogger:
    """Get a logger bound with module and run context."""

    logger = structlog.get_logger(module_name).bind(module=module_name, run_id=_RUN_ID)
    if strategy_id is not None:
        logger = logger.bind(strategy_id=strategy_id)
    return cast(BoundLogger, logger)
