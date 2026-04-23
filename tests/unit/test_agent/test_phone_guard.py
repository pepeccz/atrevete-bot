"""Unit tests for pre-graph phone guard in agent.main."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.main import _is_phone_empty, _maybe_reject_empty_phone


@pytest.mark.parametrize(
    "phone, expected",
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("\t\n", True),
        ("+34612345678", False),
        (" +34612345678 ", False),
    ],
)
def test_is_phone_empty(phone: str | None, expected: bool) -> None:
    assert _is_phone_empty(phone) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("phone", [None, "", "   ", "\t\n"])
async def test_maybe_reject_empty_phone_sends_canned_reply_and_returns_true(
    phone: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    with patch("agent.main.publish_to_channel", new=AsyncMock()) as mock_publish:
        caplog.set_level("WARNING", logger="agent.main")
        rejected = await _maybe_reject_empty_phone(conversation_id="conv-123", customer_phone=phone)

    assert rejected is True
    mock_publish.assert_awaited_once()
    channel, payload = mock_publish.call_args.args
    assert channel == "outgoing_messages"
    assert payload["conversation_id"] == "conv-123"
    assert payload["customer_phone"] == (phone or "")
    assert "No pude identificar tu número" in payload["message"]
    assert any(
        record.levelname == "WARNING"
        and getattr(record, "event", None) == "phone_guard_tripped"
        and getattr(record, "conversation_id", None) == "conv-123"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_maybe_reject_empty_phone_passes_valid_phone_through() -> None:
    with patch("agent.main.publish_to_channel", new=AsyncMock()) as mock_publish:
        rejected = await _maybe_reject_empty_phone(
            conversation_id="conv-456", customer_phone="+34612345678"
        )

    assert rejected is False
    mock_publish.assert_not_awaited()
