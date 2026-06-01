"""Structured logger setup."""

import logging
import structlog

from app.config import get_settings


def setup_logging() -> structlog.stdlib.BoundLogger:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    return structlog.get_logger("trezo.agents")
