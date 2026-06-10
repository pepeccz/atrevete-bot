"""Structured JSON logging configuration."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from shared.config import get_settings


def sanitize_phone(phone: str) -> str:
    """
    Mask middle digits of phone number for logs.

    Args:
        phone: E.164 format phone number (e.g., "+34612345678")

    Returns:
        Sanitized phone with middle digits masked (e.g., "+34***5678")
    """
    if not phone or len(phone) < 7:
        return "***"
    return f"{phone[:3]}***{phone[-4:]}"


def truncate_message(message: str, max_length: int = 200) -> str:
    """
    Truncate message content for logs with length indicator.

    Args:
        message: Full message text
        max_length: Maximum characters to show (default: 200)

    Returns:
        Truncated message with total length indicator
    """
    if not message:
        return ""
    if len(message) <= max_length:
        return message
    return f"{message[:max_length]}... (truncated, total: {len(message)} chars)"


# Standard LogRecord attributes — everything NOT in this set is an `extra`
# supplied by the caller and must be serialized (Change N / V6 W2: dropping
# extras left `tool.response.rejected` lines without reason/conversation_id).
_STANDARD_LOG_ATTRS: frozenset[str] = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.

    Outputs logs as JSON with consistent fields:
    - timestamp (ISO 8601)
    - level (INFO, ERROR, etc.)
    - logger (module name)
    - message
    - every `extra` field passed by the caller (conversation_id, tool_name,
      next_step, reason, …). Non-JSON-serializable values are stringified.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON string.

        Args:
            record: Python log record

        Returns:
            JSON-formatted log string
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add ALL extra fields (anything beyond the standard LogRecord attrs)
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_ATTRS or key in log_data:
                continue
            try:
                json.dumps(value)
                log_data[key] = value
            except (TypeError, ValueError):
                log_data[key] = str(value)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def configure_logging() -> None:
    """
    Configure application logging with JSON formatter.

    Reads LOG_LEVEL from settings (default: INFO).
    Outputs to stderr (captured by Docker logs).
    """
    settings = get_settings()

    # Parse log level from settings
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)

    # Set JSON formatter
    json_formatter = JSONFormatter()
    console_handler.setFormatter(json_formatter)

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    # Silence noisy third-party loggers in production
    _noisy_loggers = [
        "httpcore",
        "httpcore.http11",
        "httpcore.connection",
        "httpx",
        "openai",
        "openai._base_client",
        "urllib3",
        "urllib3.connectionpool",
    ]
    for logger_name in _noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Log configuration complete
    root_logger.info(f"Logging configured: level={settings.LOG_LEVEL}, format=JSON")
