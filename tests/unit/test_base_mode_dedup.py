"""Unit tests for BaseModeNode response deduplication and content list extraction.

Tests scenarios S4–S7 from spec: fix-booking-duplicate-response.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import BaseModeNode


class _DummyMode(BaseModeNode):
    @property
    def mode_name(self) -> str:
        return "GENERAL"

    async def handle(self, state, intent):  # pragma: no cover
        return {"last_node": "dummy"}


# ===========================================================================
# S4 & S5: _dedup_response — numbered-list block dedup
# ===========================================================================


def test_s4_doubled_numbered_list_collapsed():
    """S4: LLM returns a doubled numbered list → _dedup_response collapses it."""
    doubled = "1. A\n2. B\n\n1. A\n2. B"
    result = BaseModeNode._dedup_response(doubled)
    assert result == "1. A\n2. B"


def test_s5_single_numbered_list_unchanged():
    """S5: Single numbered list → _dedup_response returns it unchanged."""
    single = "1. A\n2. B\n3. C"
    result = BaseModeNode._dedup_response(single)
    assert result == single


def test_dedup_response_plain_text_unchanged():
    """Plain text without numbered lists is returned unchanged."""
    text = "Hola, ¿en qué te puedo ayudar hoy?"
    assert BaseModeNode._dedup_response(text) == text


def test_dedup_response_three_duplicates_collapsed_to_one():
    """Three identical blocks → collapsed to one."""
    triple = "1. A\n2. B\n\n1. A\n2. B\n\n1. A\n2. B"
    result = BaseModeNode._dedup_response(triple)
    assert result == "1. A\n2. B"


def test_dedup_response_different_blocks_both_kept():
    """Two DIFFERENT numbered-list blocks are both preserved."""
    different = "1. A\n2. B\n\n1. C\n2. D"
    result = BaseModeNode._dedup_response(different)
    assert "1. A" in result
    assert "1. C" in result


def test_dedup_response_empty_string():
    """Empty string returns empty string without errors."""
    assert BaseModeNode._dedup_response("") == ""


# ===========================================================================
# S6: Content list extraction — AIMessage with list content
# ===========================================================================


@pytest.mark.asyncio
async def test_s6_content_list_extraction_returns_clean_text():
    """S6: AIMessage.content is list of text blocks → extracted as clean string.

    When tools=[], the loop uses llm.ainvoke directly (no bind_tools).
    """
    llm = MagicMock()

    # Simulate LLM response with content as a list of blocks (Responses API format)
    response = SimpleNamespace(
        content=[{"type": "text", "text": "Hola, ¿en qué te ayudo?"}],
        tool_calls=[],
    )
    # With tools=[] the loop does: llm_with_tools = self.llm → llm.ainvoke(...)
    llm.ainvoke = AsyncMock(return_value=response)

    mode = _DummyMode(tools=[], llm_client=llm)
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[],
    )

    assert result.response_text == "Hola, ¿en qué te ayudo?"
    # No repr artifacts — square brackets from dict repr must not appear
    assert "[{" not in result.response_text
    assert "type" not in result.response_text


@pytest.mark.asyncio
async def test_s6_content_list_multiple_blocks_joined():
    """S6: Multiple text blocks in list → joined with newline."""
    llm = MagicMock()

    response = SimpleNamespace(
        content=[
            {"type": "text", "text": "Primera parte."},
            {"type": "text", "text": "Segunda parte."},
        ],
        tool_calls=[],
    )
    llm.ainvoke = AsyncMock(return_value=response)

    mode = _DummyMode(tools=[], llm_client=llm)
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[],
    )

    assert "Primera parte." in result.response_text
    assert "Segunda parte." in result.response_text


@pytest.mark.asyncio
async def test_s6_content_list_non_text_blocks_skipped():
    """S6: Non-text blocks (e.g. image) in list are ignored; only text blocks extracted."""
    llm = MagicMock()

    response = SimpleNamespace(
        content=[
            {"type": "image_url", "image_url": "https://example.com/img.png"},
            {"type": "text", "text": "Solo este texto cuenta."},
        ],
        tool_calls=[],
    )
    llm.ainvoke = AsyncMock(return_value=response)

    mode = _DummyMode(tools=[], llm_client=llm)
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[],
    )

    assert result.response_text == "Solo este texto cuenta."
    assert "image_url" not in result.response_text


# ===========================================================================
# S7: Content string extraction — AIMessage with string content
# ===========================================================================


@pytest.mark.asyncio
async def test_s7_content_string_returned_as_is():
    """S7: AIMessage.content is a string → returned unchanged (no transformation)."""
    llm = MagicMock()

    response = SimpleNamespace(
        content="Hola, ¿en qué te ayudo?",
        tool_calls=[],
    )
    # With tools=[], the loop does: llm_with_tools = self.llm → llm.ainvoke(...)
    llm.ainvoke = AsyncMock(return_value=response)

    mode = _DummyMode(tools=[], llm_client=llm)
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[],
    )

    assert result.response_text == "Hola, ¿en qué te ayudo?"


@pytest.mark.asyncio
async def test_s7_content_string_preserved_exactly():
    """S7: String content with special characters is preserved exactly."""
    llm = MagicMock()

    expected = "¡Perfecto! Tu cita está confirmada para el martes a las 10:00 hs. 💇‍♀️"
    response = SimpleNamespace(
        content=expected,
        tool_calls=[],
    )
    llm.ainvoke = AsyncMock(return_value=response)

    mode = _DummyMode(tools=[], llm_client=llm)
    result = await mode._run_agentic_loop(
        messages=[SimpleNamespace(content="hola")],
        tools=[],
    )

    assert result.response_text == expected
