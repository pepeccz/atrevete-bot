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


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.

    Outputs logs as JSON with consistent fields:
    - timestamp (ISO 8601)
    - level (INFO, ERROR, etc.)
    - logger (module name)
    - message
    - conversation_id (if available in extra)
    - appointment_id (if available in extra)
    - request_path (if available in extra)
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

        # Add extra fields if present
        if hasattr(record, "conversation_id"):
            log_data["conversation_id"] = record.conversation_id

        if hasattr(record, "customer_phone"):
            log_data["customer_phone"] = record.customer_phone

        if hasattr(record, "node_name"):
            log_data["node_name"] = record.node_name

        if hasattr(record, "appointment_id"):
            log_data["appointment_id"] = record.appointment_id

        if hasattr(record, "request_path"):
            log_data["request_path"] = record.request_path

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

    # Log configuration complete
    root_logger.info(
        f"Logging configured: level={settings.LOG_LEVEL}, format=JSON"
    )
