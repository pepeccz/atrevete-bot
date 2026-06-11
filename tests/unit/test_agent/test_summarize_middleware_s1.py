"""S1-T2.3 RED — SummarizeMiddleware new cursor semantics (ADR-2).

Tests for the Change S PR-2 cursor semantics fix:
- cursor = total - keep_tail (NOT 1 + keep_tail)
- Gate 2 rebuilds overlay LLM-free from persisted summary
- persist_to_checkpoint used (not overlay-only)
- messages key NOT in Command delta
- exception path logs error (not warning)

Spec: REQ-S1-6, REQ-S1-7, REQ-S2-6, Scenarios S1-E, S1-F, S2-C, ADR-2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response_mock() -> MagicMock:
    """Minimal ModelResponse-like mock."""
    return MagicMock()


def _make_request(messages: list, extra_state: dict | None = None) -> MagicMock:
    """Build a ModelRequest mock with the given messages in state."""
    state: dict = {"messages": messages, **(extra_state or {})}
    req = MagicMock()
    req.state = state

    def _override(**kw):
        new_state = kw.get("state", state)
        new_req = MagicMock()
        new_req.state = new_state
        new_req.override = MagicMock(
            side_effect=lambda **kw2: _make_request(
                kw2.get("state", {}).get("messages", []),
                extra_state={k: v for k, v in kw2.get("state", {}).items() if k != "messages"},
            )
        )
        return new_req

    req.override = MagicMock(side_effect=_override)
    return req


def _human_messages(n: int) -> list:
    return [HumanMessage(content=f"msg {i}") for i in range(n)]


# ---------------------------------------------------------------------------
# S1-T2.3a — cursor is total − keep_tail (ADR-2 new semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_is_raw_count_folded_into_summary():
    """After compaction, last_summarized_msg_count == total - keep_tail (NOT 1 + keep_tail).

    ADR-2: cursor = count of raw messages folded into the summary.
    With total=21, keep_tail=10: cursor = 21 - 10 = 11.
    Old semantics was len(compacted) = 1 + keep_tail = 11 (coincidentally same for 21 msgs).

    Use total=25 to distinguish: old = 1 + 10 = 11; new = 25 - 10 = 15.

    Spec: REQ-S1-6, ADR-2
    """
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    # 25 messages: old cursor would be 11, new cursor should be 25 - 10 = 15
    messages = _human_messages(25)
    request = _make_request(messages)

    returned_response = None

    async def handler(req):
        nonlocal returned_response
        returned_response = _make_response_mock()
        return returned_response

    result = None

    async def capturing_handler(req):
        r = await handler(req)
        return r

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(return_value="RESUMEN_TEST"),
    ):
        result = await mw.awrap_model_call(request, capturing_handler)

    # Result must be ExtendedModelResponse (persist_to_checkpoint was called)
    assert hasattr(result, "command"), (
        "SummarizeMiddleware compaction path must return ExtendedModelResponse with command. "
        "REQ-S1-6: cursor must be persisted to checkpoint, not only via overlay."
    )

    update = result.command.update
    # New cursor semantics: total - keep_tail = 25 - 10 = 15
    assert update.get("last_summarized_msg_count") == 15, (
        f"ADR-2: cursor must be total - keep_tail = 25 - 10 = 15, "
        f"got {update.get('last_summarized_msg_count')!r}. "
        "Old semantics (1 + keep_tail = 11) is WRONG — see ADR-2 analysis."
    )
    assert (
        update.get("conversation_summary") == "RESUMEN_TEST"
    ), "conversation_summary must be persisted via Command."


# ---------------------------------------------------------------------------
# S1-T2.3b — Gate 2 rebuilds overlay LLM-free (no _summarize_messages call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_rebuilds_overlay_llm_free():
    """Gate 2: cursor set, new_since < threshold → overlay rebuilt without calling LLM.

    When cursor is persisted and few new messages have arrived, Gate 2 must:
    1. NOT call _summarize_messages
    2. Build overlay: [SystemMessage(prev_summary)] + messages[cursor:]
    3. Call handler with the overlay state (no persist — just override)

    Spec: REQ-S1-6, Scenario S1-E, ADR-2
    """
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)

    # cursor=15, total=21 → new_since = 21-(15+10) = -4 < threshold(10) → Gate 2
    cursor = 15
    summary_text = "Resumen previo: el cliente quiere un corte."
    messages = _human_messages(21)
    request = _make_request(
        messages,
        extra_state={
            "last_summarized_msg_count": cursor,
            "conversation_summary": summary_text,
        },
    )

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state or {})
        return _make_response_mock()

    mock_summarize = AsyncMock(return_value="SHOULD_NOT_BE_CALLED")

    with patch("agent.middleware.summarize._summarize_messages", new=mock_summarize):
        with patch("shared.config.get_settings") as mock_settings:
            mock_settings.return_value.SUMMARIZE_NEW_MSG_THRESHOLD = 10
            result = await mw.awrap_model_call(request, handler)

    # _summarize_messages must NOT be called (Gate 2 blocks it)
    mock_summarize.assert_not_called()

    # The overlay must include the summary SystemMessage + tail from cursor
    overlay_messages = captured_state.get("messages", [])
    assert len(overlay_messages) > 0, "Gate 2 must pass a message overlay to handler"

    # First message must be the summary SystemMessage
    first_msg = overlay_messages[0]
    assert isinstance(
        first_msg, SystemMessage
    ), "Gate 2 overlay first message must be a SystemMessage with [Resumen previo]."
    assert (
        "[Resumen previo]" in first_msg.content
    ), f"Gate 2 overlay first message must contain '[Resumen previo]', got: {first_msg.content!r}"
    assert (
        summary_text in first_msg.content
    ), "Gate 2 overlay must include the persisted summary text."

    # Remaining messages = messages[cursor:] = messages[15:] = 6 messages
    tail_messages = overlay_messages[1:]
    assert tail_messages == messages[cursor:], (
        f"Gate 2 overlay tail must be messages[cursor:] = messages[{cursor}:], "
        f"got {len(tail_messages)} messages, expected {len(messages) - cursor}."
    )


# ---------------------------------------------------------------------------
# S1-T2.3c — messages key NOT in Command delta after compaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_key_not_in_command_delta():
    """After compaction, Command.update must NOT contain 'messages'.

    REQ-S1-7: messages list must NOT be persisted via Command — that would
    corrupt the add_messages reducer history. Only scalar fields are persisted.

    Spec: REQ-S1-7, Scenario S1-F
    """
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    async def handler(req):
        return _make_response_mock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(return_value="RESUMEN_TEST"),
    ):
        result = await mw.awrap_model_call(request, handler)

    assert hasattr(result, "command"), "Expected ExtendedModelResponse with command"
    update = result.command.update
    assert "messages" not in update, (
        f"'messages' key must NOT appear in Command.update. "
        f"Current update keys: {list(update.keys())}. "
        "REQ-S1-7: persisting messages would corrupt add_messages reducer history."
    )


# ---------------------------------------------------------------------------
# S1-T2.3d — exception path logs error (not warning)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_exception_logs_error():
    """Exception in compaction path must emit logger.error (not warning).

    REQ-S2-6: upgrade from logger.warning to logger.error with exc_info=True.
    The original handler must still be called (fail-open preserved).

    Spec: REQ-S2-6, Scenario S2-C
    """
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    handler_called = {"called": False}

    async def handler(req):
        handler_called["called"] = True
        return _make_response_mock()

    with (
        patch(
            "agent.middleware.summarize._summarize_messages",
            new=AsyncMock(side_effect=RuntimeError("LLM unavailable")),
        ),
        patch("agent.middleware.summarize.logger") as mock_logger,
    ):
        await mw.awrap_model_call(request, handler)

    # logger.error must be called (not warning)
    assert mock_logger.error.called, (
        "REQ-S2-6: exception in SummarizeMiddleware must call logger.error, not logger.warning. "
        "Upgrade from warning to error with exc_info=True."
    )
    # logger.warning must NOT be called (it was the old behavior)
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called after upgrade to logger.error."

    # Fail-open: original handler must still be called
    assert handler_called[
        "called"
    ], "SummarizeMiddleware must still call the original handler after an exception (fail-open)."


# ---------------------------------------------------------------------------
# S1-T2.3e — Gate 2 does NOT persist (no Command emitted on Gate 2 path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_does_not_persist_cursor():
    """Gate 2 must NOT persist a cursor change — overlay only, no Command emitted.

    ADR-2 (post-C1-fix): Gate 2 = request.override ONLY. Persisting the advanced
    cursor in Gate 2 freezes new_since at 0 on the next turn (because Command.update
    writes the advanced cursor to the checkpoint), so Gate 3 never re-fires and the
    summarizer LLM is called exactly once per conversation lifetime. After 15 turns
    with +2 msgs/turn, 26/51 messages become permanently invisible (neither in the
    stale summary nor in the final overlay). Gate 2 MUST return the plain ModelResponse
    from handler, NOT an ExtendedModelResponse with Command.

    Overlay completeness: summary_msg + messages[cursor:] must cover all checkpoint
    messages — no raw message is dropped.

    Spec: ADR-2, REQ-RG-3, Scenario S1-E
    """
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)

    cursor = 15
    summary_text = "Resumen existente."
    messages = _human_messages(21)
    request = _make_request(
        messages,
        extra_state={
            "last_summarized_msg_count": cursor,
            "conversation_summary": summary_text,
        },
    )

    plain_response = _make_response_mock()
    captured_overlay: list = []

    async def handler(req):
        captured_overlay.extend(req.state.get("messages", []))
        return plain_response

    mock_summarize = AsyncMock(return_value="SHOULD_NOT_BE_CALLED")

    with patch("agent.middleware.summarize._summarize_messages", new=mock_summarize):
        with patch("shared.config.get_settings") as mock_settings:
            mock_settings.return_value.SUMMARIZE_NEW_MSG_THRESHOLD = 10
            result = await mw.awrap_model_call(request, handler)

    # Gate 2 must NOT emit a Command — cursor stays stable in the checkpoint so
    # new_since continues accumulating on subsequent turns.
    assert not hasattr(result, "command") or result is plain_response, (
        "Gate 2 must NOT return ExtendedModelResponse with command. "
        "Persisting the cursor here causes summarizer starvation: new_since stays 0 "
        "every subsequent turn and Gate 3 never re-fires. "
        "ADR-2: Gate 2 = request.override only, no persist."
    )

    # Overlay completeness: summary_msg + messages[cursor:] covers all checkpoint messages.
    # First element is the SystemMessage summary; remainder is messages[cursor:].
    assert len(captured_overlay) > 0, "Gate 2 must pass an overlay to handler"
    tail_in_overlay = [m for m in captured_overlay if not isinstance(m, SystemMessage)]
    expected_tail = messages[cursor:]
    assert tail_in_overlay == expected_tail, (
        f"Gate 2 overlay tail must be messages[cursor:] = messages[{cursor}:], "
        f"got {len(tail_in_overlay)} messages, expected {len(expected_tail)}. "
        "No raw message must be dropped — overlay completeness invariant."
    )
