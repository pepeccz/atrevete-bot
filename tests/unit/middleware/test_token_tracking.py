"""Unit tests for ``agent.middleware.token_tracking.TokenTrackingMiddleware``.

All tests are offline — ``record_token_usage`` is patched so no DB session is
opened. The middleware is exercised directly via ``aafter_model(state, runtime=None)``
which is how ``create_agent`` invokes it at runtime.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.middleware.token_tracking import (
    TokenTrackingMiddleware,
    _extract_token_counts,
)


# ---------------------------------------------------------------------------
# _extract_token_counts — pure helper
# ---------------------------------------------------------------------------


class TestExtractTokenCounts:
    def test_reads_usage_metadata(self) -> None:
        msg = AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
        )
        assert _extract_token_counts(msg) == (100, 25)

    def test_reads_response_metadata_fallback(self) -> None:
        msg = AIMessage(
            content="hi",
            response_metadata={
                "token_usage": {"prompt_tokens": 42, "completion_tokens": 7},
            },
        )
        assert _extract_token_counts(msg) == (42, 7)

    def test_usage_metadata_takes_precedence_over_response_metadata(self) -> None:
        msg = AIMessage(
            content="hi",
            usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
            response_metadata={
                "token_usage": {"prompt_tokens": 999, "completion_tokens": 999},
            },
        )
        assert _extract_token_counts(msg) == (10, 3)

    def test_missing_metadata_returns_zero(self) -> None:
        msg = AIMessage(content="hi")
        assert _extract_token_counts(msg) == (0, 0)

    def test_empty_token_usage_returns_zero(self) -> None:
        msg = AIMessage(content="hi", response_metadata={"token_usage": {}})
        assert _extract_token_counts(msg) == (0, 0)


# ---------------------------------------------------------------------------
# TokenTrackingMiddleware.aafter_model — integration with record_token_usage
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_record():
    """Patch record_token_usage at its import site inside the middleware module."""
    with patch(
        "agent.services.token_tracking.record_token_usage", new_callable=AsyncMock
    ) as mock:
        yield mock


class TestAfterModelHook:
    @pytest.mark.asyncio
    async def test_records_usage_when_ai_message_has_metadata(self, mock_record) -> None:
        mw = TokenTrackingMiddleware(mode_name="GREETING")
        state = {
            "messages": [
                HumanMessage(content="hola"),
                AIMessage(
                    content="hi",
                    usage_metadata={
                        "input_tokens": 80,
                        "output_tokens": 12,
                        "total_tokens": 92,
                    },
                ),
            ]
        }

        result = await mw.aafter_model(state, runtime=None)

        assert result is None  # never mutates state
        mock_record.assert_awaited_once()
        call_kwargs = mock_record.await_args.kwargs
        assert call_kwargs["input_tokens"] == 80
        assert call_kwargs["output_tokens"] == 12
        assert call_kwargs["mode_name"] == "GREETING"
        # turn_count = len(messages) // 2 = 2 // 2 = 1
        assert call_kwargs["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_skips_when_last_message_is_not_ai(self, mock_record) -> None:
        mw = TokenTrackingMiddleware(mode_name="GREETING")
        state = {"messages": [HumanMessage(content="hola")]}

        result = await mw.aafter_model(state, runtime=None)

        assert result is None
        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_messages_empty(self, mock_record) -> None:
        mw = TokenTrackingMiddleware(mode_name="GREETING")
        state = {"messages": []}

        result = await mw.aafter_model(state, runtime=None)

        assert result is None
        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_token_counts_zero(self, mock_record) -> None:
        mw = TokenTrackingMiddleware(mode_name="GREETING")
        state = {"messages": [AIMessage(content="hi")]}  # no usage metadata

        result = await mw.aafter_model(state, runtime=None)

        assert result is None
        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_exception_is_swallowed(self, mock_record) -> None:
        """Token tracking must never propagate exceptions into the agent loop."""
        mock_record.side_effect = RuntimeError("DB down")
        mw = TokenTrackingMiddleware(mode_name="BOOKING")
        state = {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(
                    content="a",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
            ]
        }

        # Must NOT raise
        result = await mw.aafter_model(state, runtime=None)

        assert result is None
        mock_record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_count_reflects_message_history_length(self, mock_record) -> None:
        mw = TokenTrackingMiddleware(mode_name="GENERAL")
        # 5 messages → turn_count = 2
        state = {
            "messages": [
                HumanMessage(content="1"),
                AIMessage(content="2"),
                HumanMessage(content="3"),
                AIMessage(content="4"),
                AIMessage(
                    content="5",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                ),
            ]
        }

        await mw.aafter_model(state, runtime=None)

        assert mock_record.await_args.kwargs["turn_count"] == 2
        assert mock_record.await_args.kwargs["mode_name"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_default_mode_name_is_empty_string(self, mock_record) -> None:
        mw = TokenTrackingMiddleware()
        state = {
            "messages": [
                AIMessage(
                    content="a",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        }

        await mw.aafter_model(state, runtime=None)

        assert mock_record.await_args.kwargs["mode_name"] == ""
