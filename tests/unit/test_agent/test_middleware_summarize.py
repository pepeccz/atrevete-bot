"""SummarizeMiddleware — unit tests.

T1: summary written into state when compaction occurs.
T2: short conversation leaves request unchanged (no conversation_summary key).
T3: exception in summarizer leaves request unchanged (no conversation_summary key).

Extended (cursor / idempotency / model resolver):
T2-cursor : cursor=None, 21 msgs → LLM called 1x, cursor=11, summary set (first run)
T3b       : cursor=15, 21 msgs, new_since=6 < 10 → LLM NOT called, cursor unchanged
T4        : cursor=11, 21 msgs, new_since=10 >= 10 → LLM called 1x, cursor=11
T5        : LLM raises → original messages preserved, cursor unchanged
T6        : SUMMARIZER_MODEL empty → uses get_llm()
T7        : SUMMARIZER_MODEL set → uses override model
T8        : state delta contains messages + conversation_summary + last_summarized_msg_count
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

# ---------------------------------------------------------------------------
# Task 1.1 — Config fields exist
# ---------------------------------------------------------------------------


def test_settings_has_summarize_new_msg_threshold():
    """Settings.SUMMARIZE_NEW_MSG_THRESHOLD defaults to 10."""
    from shared.config import Settings

    s = Settings()
    assert s.SUMMARIZE_NEW_MSG_THRESHOLD == 10


def test_settings_has_summarizer_model_default_empty():
    """Settings.SUMMARIZER_MODEL defaults to empty string."""
    from shared.config import Settings

    s = Settings()
    assert s.SUMMARIZER_MODEL == ""


# ---------------------------------------------------------------------------
# Task 1.3 — get_summarizer_llm helper
# ---------------------------------------------------------------------------


def test_get_summarizer_llm_returns_default_llm_when_model_empty():
    """get_summarizer_llm() returns same instance as get_llm() when SUMMARIZER_MODEL is empty."""
    from agent.llm import get_summarizer_llm

    with patch("agent.llm.get_settings") as mock_settings:
        mock_settings.return_value.SUMMARIZER_MODEL = ""
        mock_settings.return_value.LLM_MODEL = "openai/gpt-4.1-mini"
        mock_settings.return_value.OPENROUTER_API_KEY = "sk-test"
        mock_settings.return_value.SITE_URL = "https://test.com"
        mock_settings.return_value.SITE_NAME = "Test"

        llm = get_summarizer_llm()
        assert llm is not None
        # When SUMMARIZER_MODEL is empty, it delegates to get_llm() which uses LLM_MODEL
        assert llm.model_name == "openai/gpt-4.1-mini"


def test_get_summarizer_llm_uses_override_model_when_set():
    """get_summarizer_llm() uses SUMMARIZER_MODEL when non-empty."""
    from agent.llm import get_summarizer_llm

    with patch("agent.llm.get_settings") as mock_settings:
        mock_settings.return_value.SUMMARIZER_MODEL = "openai/gpt-4.1-nano"
        mock_settings.return_value.LLM_MODEL = "openai/gpt-4.1-mini"
        mock_settings.return_value.OPENROUTER_API_KEY = "sk-test"
        mock_settings.return_value.SITE_URL = "https://test.com"
        mock_settings.return_value.SITE_NAME = "Test"

        llm = get_summarizer_llm()
        assert llm.model_name == "openai/gpt-4.1-nano"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def _make_request(messages: list, extra_state: dict | None = None) -> MagicMock:
    """Build a ModelRequest mock with the given messages in state."""
    state: dict = {"messages": messages, **(extra_state or {})}
    req = MagicMock()
    req.state = state

    # override() must return a new mock that carries the overridden state
    def _override(**kw):
        new_req = MagicMock()
        new_req.state = kw.get("state", state)
        new_req.override = MagicMock(side_effect=lambda **kw2: _make_request(kw2.get("state", {}).get("messages", [])))
        return new_req

    req.override = MagicMock(side_effect=_override)
    return req


def _human_messages(n: int) -> list:
    return [HumanMessage(content=f"msg {i}") for i in range(n)]


# ---------------------------------------------------------------------------
# T1: summary written on compaction (21 messages > window of 20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_written_to_state_on_compaction():
    """SummarizeMiddleware writes conversation_summary into state when window exceeded."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(return_value="RESUMEN_X"),
    ):
        await mw.awrap_model_call(request, handler)

    assert captured_state.get("conversation_summary") == "RESUMEN_X"


@pytest.mark.asyncio
async def test_messages_compacted_on_compaction():
    """SummarizeMiddleware reduces message count below window when compaction occurs."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(return_value="RESUMEN_X"),
    ):
        await mw.awrap_model_call(request, handler)

    # keep_tail=10 + 1 SystemMessage summary = 11 total, well below 21
    assert len(captured_state.get("messages", [])) < 21


# ---------------------------------------------------------------------------
# T2: short conversation — handler receives original request unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_summary_key_for_short_conversation():
    """SummarizeMiddleware does NOT inject conversation_summary for short conversations."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    # Exactly window (20) messages — should NOT trigger compaction
    messages = _human_messages(20)
    request = _make_request(messages)

    received_request = None

    async def handler(req):
        nonlocal received_request
        received_request = req
        return MagicMock()

    await mw.awrap_model_call(request, handler)

    # Handler must have received the ORIGINAL request unchanged
    assert received_request is request
    assert "conversation_summary" not in received_request.state


# ---------------------------------------------------------------------------
# T3: exception in summarizer — handler receives original request (no key injected)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_summary_key_on_summarizer_exception():
    """SummarizeMiddleware does NOT inject conversation_summary when summarizer raises."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    received_request = None

    async def handler(req):
        nonlocal received_request
        received_request = req
        return MagicMock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(side_effect=RuntimeError("LLM unavailable")),
    ):
        await mw.awrap_model_call(request, handler)

    # Handler must receive the original request (fallback path)
    assert received_request is request
    assert "conversation_summary" not in received_request.state


# ---------------------------------------------------------------------------
# Phase 2 RED tests — cursor / idempotency / model resolver
# ---------------------------------------------------------------------------


# T2-cursor: cursor=None, 21 messages → first run, compaction fires
@pytest.mark.asyncio
async def test_cursor_set_after_first_compaction():
    """T2-cursor: cursor=None + 21 msgs → LLM called 1x, cursor=11, summary set."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages, extra_state={"last_summarized_msg_count": None})

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    mock_summarize = AsyncMock(return_value="PRIMER_RESUMEN")
    with patch("agent.middleware.summarize._summarize_messages", new=mock_summarize):
        await mw.awrap_model_call(request, handler)

    mock_summarize.assert_called_once()
    assert captured_state.get("conversation_summary") == "PRIMER_RESUMEN"
    # Post-trim cursor = 1 SystemMessage + 10 tail = 11
    assert captured_state.get("last_summarized_msg_count") == 11


# T3b: cursor=15, total=21, new_since=6 < threshold → idempotency gate holds
@pytest.mark.asyncio
async def test_idempotency_gate_skips_llm_when_few_new_messages():
    """T3b: cursor=15, 21 msgs, new_since=6 < 10 → LLM NOT called, cursor unchanged."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages, extra_state={"last_summarized_msg_count": 15})

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    mock_summarize = AsyncMock(return_value="SHOULD_NOT_BE_CALLED")
    with patch("agent.middleware.summarize._summarize_messages", new=mock_summarize):
        with patch("shared.config.get_settings") as mock_settings:
            mock_settings.return_value.SUMMARIZE_NEW_MSG_THRESHOLD = 10
            await mw.awrap_model_call(request, handler)

    mock_summarize.assert_not_called()
    # cursor must remain unchanged (handler receives original state)
    assert captured_state.get("last_summarized_msg_count") == 15


# T4: cursor=11, total=21, new_since=10 >= threshold → compaction fires
@pytest.mark.asyncio
async def test_threshold_crossing_triggers_compaction():
    """T4: cursor=11, 21 msgs, new_since=10 >= 10 → LLM called 1x, cursor=11."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages, extra_state={"last_summarized_msg_count": 11})

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    mock_summarize = AsyncMock(return_value="SEGUNDO_RESUMEN")
    with patch("agent.middleware.summarize._summarize_messages", new=mock_summarize):
        await mw.awrap_model_call(request, handler)

    mock_summarize.assert_called_once()
    # cursor resets to post-trim length = 11
    assert captured_state.get("last_summarized_msg_count") == 11


# T5: LLM raises → original messages preserved, cursor unchanged
@pytest.mark.asyncio
async def test_cursor_unchanged_when_summarizer_raises():
    """T5: LLM raises → original messages preserved, cursor NOT advanced."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    original_cursor = 5
    request = _make_request(messages, extra_state={"last_summarized_msg_count": original_cursor})

    received_request = None

    async def handler(req):
        nonlocal received_request
        received_request = req
        return MagicMock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(side_effect=RuntimeError("LLM down")),
    ):
        await mw.awrap_model_call(request, handler)

    # Handler must receive the original request on exception path
    assert received_request is request
    assert received_request.state.get("last_summarized_msg_count") == original_cursor
    assert received_request.state.get("messages") == messages


# T6: SUMMARIZER_MODEL empty → uses get_llm() path
@pytest.mark.asyncio
async def test_summarize_uses_default_llm_when_summarizer_model_empty():
    """T6: SUMMARIZER_MODEL='' → _summarize_messages receives default LLM."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    async def handler(req):
        return MagicMock()

    mock_get_llm = MagicMock(return_value=MagicMock())
    with patch("agent.middleware.summarize.get_summarizer_llm", return_value=mock_get_llm.return_value) as mock_resolver:
        with patch(
            "agent.middleware.summarize._summarize_messages",
            new=AsyncMock(return_value="OK"),
        ):
            with patch("shared.config.get_settings") as mock_settings:
                mock_settings.return_value.SUMMARIZE_NEW_MSG_THRESHOLD = 10
                mock_settings.return_value.SUMMARIZER_MODEL = ""
                await mw.awrap_model_call(request, handler)

    mock_resolver.assert_called_once()


# T7: SUMMARIZER_MODEL non-empty → override model reaches get_summarizer_llm
@pytest.mark.asyncio
async def test_summarize_uses_override_model_when_summarizer_model_set():
    """T7: SUMMARIZER_MODEL set → get_summarizer_llm() called (override path)."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages)

    async def handler(req):
        return MagicMock()

    with patch("agent.middleware.summarize.get_summarizer_llm") as mock_resolver:
        mock_resolver.return_value = MagicMock()
        with patch(
            "agent.middleware.summarize._summarize_messages",
            new=AsyncMock(return_value="OK"),
        ):
            await mw.awrap_model_call(request, handler)

    mock_resolver.assert_called_once()


# T8: state delta shape — all 3 keys in one atomic write
@pytest.mark.asyncio
async def test_state_delta_contains_all_three_keys():
    """T8: state delta has messages + conversation_summary + last_summarized_msg_count."""
    from agent.middleware.summarize import SummarizeMiddleware

    mw = SummarizeMiddleware(window=20, keep_tail=10)
    messages = _human_messages(21)
    request = _make_request(messages, extra_state={"last_summarized_msg_count": None})

    captured_state: dict = {}

    async def handler(req):
        captured_state.update(req.state)
        return MagicMock()

    with patch(
        "agent.middleware.summarize._summarize_messages",
        new=AsyncMock(return_value="ATOMIC_RESUMEN"),
    ):
        await mw.awrap_model_call(request, handler)

    assert "messages" in captured_state
    assert "conversation_summary" in captured_state
    assert "last_summarized_msg_count" in captured_state
