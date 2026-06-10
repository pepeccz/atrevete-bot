"""Change N (N8) — JSONFormatter must serialize arbitrary extra fields.

V6 audit W2: `tool.response.rejected` log lines carried reason / next_step /
conversation_id in extra={…} but the JSON formatter only whitelisted 5 keys,
so server logs showed bare messages and root-causing C3 required inference.
"""

from __future__ import annotations

import json
import logging

from shared.logging_config import JSONFormatter


def _format_with_extra(extra: dict) -> dict:
    logger = logging.getLogger("test.extras")
    record = logger.makeRecord(
        name="test.extras",
        level=logging.INFO,
        fn="test.py",
        lno=1,
        msg="tool.response.rejected",
        args=(),
        exc_info=None,
        extra=extra,
    )
    return json.loads(JSONFormatter().format(record))


def test_formatter_includes_arbitrary_extras():
    data = _format_with_extra(
        {
            "tool_name": "book",
            "next_step": "reoffer_slots",
            "conversation_id": "conv-1",
            "missing": ["service_ids"],
        }
    )
    assert data["message"] == "tool.response.rejected"
    assert data["tool_name"] == "book"
    assert data["next_step"] == "reoffer_slots"
    assert data["conversation_id"] == "conv-1"
    assert data["missing"] == ["service_ids"]


def test_formatter_stringifies_non_serializable_extras():
    """Non-JSON-serializable extras must not crash the formatter."""

    class Opaque:
        def __str__(self) -> str:
            return "opaque-value"

    data = _format_with_extra({"weird": Opaque()})
    assert data["weird"] == "opaque-value"


def test_formatter_does_not_leak_standard_record_attrs():
    """Standard LogRecord attributes (lineno, process, …) stay out of the JSON."""
    data = _format_with_extra({"reason": "x"})
    for noise_key in ("lineno", "process", "thread", "pathname", "args", "msg"):
        assert noise_key not in data
    assert data["reason"] == "x"
