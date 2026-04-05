"""
Unit tests for agent/prompts/loader.py.

Tests the v6.0 prompt loading system:
- load_markdown: file loading
- get_system_prompt + caching (TTL via _TtlCache)
- clear_prompt_cache: invalidation
- load_mode_overlay: per-mode dispatch
- build_layered_messages: structure and content
- _build_simple_dynamic_context: minimal context building

T-41 architecture guards:
- test_no_build_step_context: build_step_context removed from loader
- test_catalog_integration: build_catalog_markdown called in build_layered_messages
"""

import asyncio
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub modules before importing the loader
if "agent.state.schemas" not in sys.modules:
    schemas_stub = ModuleType("agent.state.schemas")
    schemas_stub.ConversationState = dict
    sys.modules["agent.state.schemas"] = schemas_stub

if "langchain_core.messages" not in sys.modules:
    messages_stub = ModuleType("langchain_core.messages")

    class MockSystemMessage:
        def __init__(self, content=""):
            self.content = content

    class MockHumanMessage:
        def __init__(self, content=""):
            self.content = content

    class MockAIMessage:
        def __init__(self, content=""):
            self.content = content

    class MockToolMessage:
        def __init__(self, content=""):
            self.content = content

    messages_stub.SystemMessage = MockSystemMessage
    messages_stub.HumanMessage = MockHumanMessage
    messages_stub.AIMessage = MockAIMessage
    messages_stub.ToolMessage = MockToolMessage
    sys.modules["langchain_core.messages"] = messages_stub

if "langchain_core" not in sys.modules:
    sys.modules["langchain_core"] = ModuleType("langchain_core")

# Now import the loader — only what actually exists
from agent.prompts.loader import (
    _TtlCache,
    _base_prompt_cache,
    _build_simple_dynamic_context,
    _overlay_caches,
    build_layered_messages,
    clear_prompt_cache,
    get_system_prompt,
    load_markdown,
    load_mode_overlay,
)


# =============================================================================
# T-41: Architecture guards
# =============================================================================


class TestPromptLoaderArchitectureGuards:
    """T-41: Verify removed functions are gone and catalog integration is correct."""

    def test_no_build_step_context(self):
        """T-41: build_step_context must NOT exist in agent.prompts.loader.

        This function was removed in the v6.0 architecture — each mode builds
        its own dynamic context via _build_dynamic_context() (BookingMode,
        AppointmentManagementMode) or uses _build_simple_dynamic_context().
        """
        import inspect
        import agent.prompts.loader as _loader

        assert not hasattr(_loader, "build_step_context"), (
            "build_step_context found in agent.prompts.loader — "
            "it was removed in v6.0; each mode builds its own dynamic context"
        )

    def test_catalog_integration(self):
        """T-41: build_catalog_markdown must be called inside build_layered_messages.

        The catalog (services, stylists, business hours) is injected as a
        second SystemMessage in the layered prompt chain.
        """
        import inspect
        import agent.prompts.loader as _loader

        src = inspect.getsource(_loader.build_layered_messages)
        assert "build_catalog_markdown" in src, (
            "build_catalog_markdown not called in build_layered_messages — "
            "catalog injection is required for the layered prompt chain"
        )


# =============================================================================
# load_markdown tests
# =============================================================================


class TestLoadMarkdown:
    """Test cases for load_markdown function."""

    def test_load_markdown_success(self):
        """Successful loading of a shared markdown file."""
        content = load_markdown("identity.md", "shared")

        assert isinstance(content, str)
        assert len(content) > 0
        assert "#" in content

    def test_load_markdown_file_not_found(self):
        """Missing file returns empty string."""
        content = load_markdown("nonexistent.md", "shared")

        assert content == ""

    def test_load_markdown_invalid_subdir(self):
        """Invalid subdirectory returns empty string."""
        content = load_markdown("identity.md", "invalid_subdir")

        assert content == ""

    def test_load_markdown_different_files(self):
        """Loading different shared markdown files returns non-empty content."""
        identity = load_markdown("identity.md", "shared")
        critical_rules = load_markdown("critical_rules.md", "shared")
        glossary = load_markdown("glossary.md", "shared")

        assert len(identity) > 100
        assert len(critical_rules) > 100
        assert len(glossary) > 100


# =============================================================================
# get_system_prompt + caching tests
# =============================================================================


class TestPromptCacheHitMiss:
    """Test cache hit/miss scenarios via get_system_prompt."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_cache_miss_loads_from_disk(self):
        """First call (cache miss) loads from disk and returns non-empty string."""
        prompt = await get_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 1000
        assert "#" in prompt

    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_content(self):
        """Second call returns the same content as the first (cache hit)."""
        prompt1 = await get_system_prompt()
        prompt2 = await get_system_prompt()

        assert prompt1 == prompt2

    @pytest.mark.asyncio
    async def test_cached_prompt_avoids_reloading_markdown(self):
        """After caching, load_markdown is not called again on second access."""
        with patch(
            "agent.prompts.loader.load_markdown",
            side_effect=["id content", "rules content", "glossary content"],
        ) as mocked_load:
            clear_prompt_cache()
            first = await get_system_prompt()
            second = await get_system_prompt()

        assert first == second
        assert mocked_load.call_count == 3  # 3 files, only once


# =============================================================================
# clear_prompt_cache tests
# =============================================================================


class TestClearPromptCache:
    """Test cache invalidation via clear_prompt_cache."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_clear_forces_reload(self):
        """After clear, the next get_system_prompt loads from disk again."""
        await get_system_prompt()

        clear_prompt_cache()

        with patch("agent.prompts.loader.load_markdown") as mock_load:
            mock_load.return_value = "reloaded content"
            prompt = await get_system_prompt()

        assert mock_load.called
        assert "reloaded content" in prompt

    def test_multiple_clears_are_safe(self):
        """Multiple consecutive clears do not raise errors."""
        clear_prompt_cache()
        clear_prompt_cache()
        clear_prompt_cache()


# =============================================================================
# load_mode_overlay tests
# =============================================================================


class TestLoadModeOverlay:
    """Coverage for mode overlay dispatch across all v6 modes."""

    @pytest.mark.asyncio
    async def test_load_mode_overlay_loads_all_non_booking_modes(self):
        with patch("agent.prompts.loader.load_markdown") as mock_load_markdown:
            mock_load_markdown.side_effect = lambda file_name, subdir: f"{subdir}/{file_name}"

            greeting = await load_mode_overlay("greeting", {})
            general = await load_mode_overlay("GENERAL", {})
            escalation = await load_mode_overlay("Escalation", {})

        assert greeting == "modes/greeting.md"
        assert general == "modes/general.md"
        assert escalation == "modes/escalation.md"

    @pytest.mark.asyncio
    async def test_load_mode_overlay_unknown_mode_logs_warning(self):
        with patch("agent.prompts.loader.logger") as mock_logger:
            result = await load_mode_overlay("unknown", {})

        assert result == ""
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_mode_overlay_none_returns_empty(self):
        """None mode_name returns empty string without error."""
        result = await load_mode_overlay(None, {})

        assert result == ""


# =============================================================================
# build_layered_messages tests
# =============================================================================


class TestBuildLayeredMessages:
    """Test the structure and content of build_layered_messages output."""

    @pytest.mark.asyncio
    async def test_build_layered_messages_structure(self):
        """Messages have at least [SystemMessage, ..., SystemMessage(dynamic)]."""
        state = {"user_message": "Hello"}
        mode_context = {}

        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            new_callable=AsyncMock,
            return_value="# Catálogo de prueba",
        ):
            messages, dyn_idx = await build_layered_messages(state, mode_context)

        assert len(messages) >= 2

        from langchain_core.messages import SystemMessage

        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[-1], SystemMessage)
        assert dyn_idx == len(messages) - 1

    @pytest.mark.asyncio
    async def test_build_layered_messages_without_history(self):
        """Without history: only system + catalog (+ optional overlay) + dynamic."""
        state = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        }
        mode_context = {}

        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            new_callable=AsyncMock,
            return_value="# Catálogo",
        ):
            messages, dyn_idx = await build_layered_messages(
                state, mode_context, include_history=False
            )

        # No history messages — only system blocks + dynamic
        assert dyn_idx == len(messages) - 1
        from langchain_core.messages import HumanMessage

        assert not any(isinstance(m, HumanMessage) for m in messages)

    @pytest.mark.asyncio
    async def test_build_layered_messages_with_history_included(self):
        """With history: history messages appear between overlays and dynamic context."""
        state = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "I want to book"},
            ]
        }
        mode_context = {}

        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            new_callable=AsyncMock,
            return_value="# Catálogo",
        ):
            messages, dyn_idx = await build_layered_messages(
                state, mode_context, include_history=True, history_limit=3
            )

        from langchain_core.messages import HumanMessage

        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        assert len(human_messages) > 0
        assert dyn_idx == len(messages) - 1

    @pytest.mark.asyncio
    async def test_dynamic_context_override_used_when_provided(self):
        """When dynamic_context_override is given, it replaces the default context."""
        state = {"user_message": "test"}
        mode_context = {}
        override_text = "OVERRIDE CONTEXT — injected by BookingMode"

        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            new_callable=AsyncMock,
            return_value="# Catálogo",
        ):
            messages, dyn_idx = await build_layered_messages(
                state,
                mode_context,
                dynamic_context_override=override_text,
                include_history=False,
            )

        assert messages[dyn_idx].content == override_text

    @pytest.mark.asyncio
    async def test_build_layered_messages_calls_catalog(self):
        """build_layered_messages must call build_catalog_markdown (T-41 integration)."""
        state = {"user_message": "test"}
        mode_context = {}

        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            new_callable=AsyncMock,
            return_value="# Catálogo mock",
        ) as mock_catalog:
            await build_layered_messages(state, mode_context)

        mock_catalog.assert_called_once()


# =============================================================================
# _build_simple_dynamic_context tests
# =============================================================================


class TestBuildSimpleDynamicContext:
    """Test the minimal dynamic context builder."""

    def test_includes_datetime(self):
        """Output always includes current date and time."""
        state = {"user_message": "Hello"}
        mode_context = {}

        context = _build_simple_dynamic_context(state, mode_context)

        assert "Fecha y hora actual" in context

    def test_includes_phone_when_present(self):
        """Customer phone is included when present in state."""
        state = {"customer_phone": "+34612345678"}
        mode_context = {}

        context = _build_simple_dynamic_context(state, mode_context)

        assert "+34612345678" in context

    def test_includes_conversation_summary(self):
        """Conversation summary is included when present."""
        state = {
            "user_message": "Confirm",
            "conversation_summary": "Cliente quiere corte para mañana",
        }
        mode_context = {}

        context = _build_simple_dynamic_context(state, mode_context)

        assert "Cliente quiere corte para mañana" in context

    def test_empty_state_does_not_raise(self):
        """Empty state is handled gracefully."""
        context = _build_simple_dynamic_context({}, {})

        assert isinstance(context, str)
        assert "Fecha y hora actual" in context

    def test_none_values_handled_gracefully(self):
        """None values in state don't raise exceptions."""
        state = {"customer_phone": None, "conversation_summary": None}

        context = _build_simple_dynamic_context(state, {})

        assert isinstance(context, str)


# =============================================================================
# _TtlCache tests
# =============================================================================


class TestTtlCache:
    """Unit tests for the _TtlCache helper."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_loader(self):
        """First access calls the loader function."""
        cache = _TtlCache(ttl_minutes=10)
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return "loaded value"

        result = await cache.get_or_load(loader)

        assert result == "loaded value"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_loader_again(self):
        """Second access uses cache, loader called only once."""
        cache = _TtlCache(ttl_minutes=10)
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return "cached value"

        await cache.get_or_load(loader)
        result = await cache.get_or_load(loader)

        assert result == "cached value"
        assert call_count == 1

    def test_invalidate_clears_cache(self):
        """After invalidate(), is_valid() returns False."""
        cache = _TtlCache(ttl_minutes=10)
        cache._data = "some data"
        from datetime import datetime, timedelta

        cache._expires_at = datetime.now() + timedelta(minutes=5)

        assert cache.is_valid()

        cache.invalidate()

        assert not cache.is_valid()
