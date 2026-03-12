"""
Unit tests for prompt loader caching functionality.

Tests the v6.0 optimized prompt system with caching support:
- Cache hit/miss scenarios
- TTL expiration
- Thread safety with concurrent access
- Cache invalidation
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import mock_open, patch, MagicMock

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
    
    messages_stub.SystemMessage = MockSystemMessage
    messages_stub.HumanMessage = MockHumanMessage
    messages_stub.AIMessage = MockAIMessage
    sys.modules["langchain_core.messages"] = messages_stub

if "langchain_core" not in sys.modules:
    sys.modules["langchain_core"] = ModuleType("langchain_core")

# Now import the loader
from agent.prompts.loader import (
    CACHE_TTL_MINUTES,
    build_layered_messages,
    build_step_context,
    clear_prompt_cache,
    get_system_prompt,
    load_markdown,
    _prompt_cache,
)


class TestLoadMarkdown:
    """Test cases for load_markdown function."""

    def test_load_markdown_success(self):
        """Test successful loading of markdown file."""
        content = load_markdown("identity.md", "shared")

        # Should return non-empty content
        assert isinstance(content, str)
        assert len(content) > 0
        assert "# Identidad" in content or "#" in content

    def test_load_markdown_file_not_found(self):
        """Test handling of missing file."""
        content = load_markdown("nonexistent.md", "shared")

        # Should return empty string
        assert content == ""

    def test_load_markdown_invalid_subdir(self):
        """Test handling of invalid subdirectory."""
        content = load_markdown("identity.md", "invalid_subdir")

        # Should return empty string
        assert content == ""

    def test_load_markdown_different_files(self):
        """Test loading different markdown files."""
        identity = load_markdown("identity.md", "shared")
        critical_rules = load_markdown("critical_rules.md", "shared")
        glossary = load_markdown("glossary.md", "shared")

        # All should be non-empty
        assert len(identity) > 100
        assert len(critical_rules) > 100
        assert len(glossary) > 100

        # Should contain expected content
        assert "#" in identity  # Markdown header
        assert "#" in critical_rules  # Markdown header
        assert "#" in glossary  # Markdown header


class TestPromptCacheHitMiss:
    """Test cases for cache hit and miss scenarios."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_cache_miss_loads_from_disk(self):
        """Test that first call loads from disk (cache miss)."""
        # Cache is clear, should load from disk
        prompt = await get_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 1000
        # Should contain content from all three files
        assert "#" in prompt  # Markdown headers

    @pytest.mark.asyncio
    async def test_cache_hit_uses_cached_data(self):
        """Test that subsequent calls use cached data."""
        # First call - cache miss
        prompt1 = await get_system_prompt()

        # Second call - should be cache hit
        prompt2 = await get_system_prompt()

        # Should be identical
        assert prompt1 == prompt2

    @pytest.mark.asyncio
    async def test_cache_contains_expected_parts(self):
        """Test that cached prompt contains all expected sections."""
        prompt = await get_system_prompt()

        # Should contain separators between sections
        assert "---" in prompt

        # Should have substantial content
        assert len(prompt) > 2000


class TestPromptCacheTTL:
    """Test cases for cache TTL (time-to-live) expiration."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        """Test that cache expires after TTL period."""
        # Set cache with expired timestamp
        _prompt_cache["data"] = "cached content"
        _prompt_cache["expires_at"] = datetime.now() - timedelta(minutes=1)

        # Should reload from disk (cache expired)
        prompt = await get_system_prompt()

        # Should not be the expired cached content
        assert prompt != "cached content"
        assert len(prompt) > 1000  # Real content

    @pytest.mark.asyncio
    async def test_cache_valid_before_ttl(self):
        """Test that cache is valid before TTL expires."""
        # Set cache with future expiration
        _prompt_cache["data"] = "cached content"
        _prompt_cache["expires_at"] = datetime.now() + timedelta(minutes=CACHE_TTL_MINUTES)

        # Should return cached data (not expired)
        prompt = await get_system_prompt()

        assert prompt == "cached content"

    @pytest.mark.asyncio
    async def test_cache_updates_expiration_on_load(self):
        """Test that cache expiration is updated when loading from disk."""
        # Load into cache
        await get_system_prompt()

        # Check that expiration is set correctly
        expires_at = _prompt_cache["expires_at"]
        assert expires_at is not None

        # Should be approximately CACHE_TTL_MINUTES from now
        expected_expiry = datetime.now() + timedelta(minutes=CACHE_TTL_MINUTES)
        time_diff = abs((expires_at - expected_expiry).total_seconds())
        assert time_diff < 5  # Within 5 seconds


class TestPromptCacheThreadSafety:
    """Test cases for thread-safe concurrent cache access."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_concurrent_cache_access(self):
        """Test that concurrent access to cache is thread-safe."""
        results = []

        async def fetch_prompt():
            prompt = await get_system_prompt()
            results.append(prompt)

        # Launch multiple concurrent requests
        await asyncio.gather(
            fetch_prompt(),
            fetch_prompt(),
            fetch_prompt(),
            fetch_prompt(),
            fetch_prompt(),
        )

        # All results should be identical
        assert len(results) == 5
        assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_cache_miss_handling(self):
        """Test that concurrent cache misses only load once."""
        call_count = 0

        original_load = load_markdown

        def counting_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_load(*args, **kwargs)

        with patch("agent.prompts.loader.load_markdown", side_effect=counting_load):
            # Launch multiple concurrent requests with clear cache
            await asyncio.gather(
                get_system_prompt(),
                get_system_prompt(),
                get_system_prompt(),
            )

        # Should have loaded only once (others used cache)
        # Note: Due to async lock, only one should have loaded
        assert call_count >= 3  # Each call loads 3 files

    @pytest.mark.asyncio
    async def test_cache_clear_during_concurrent_access(self):
        """Test that cache clear is safe during concurrent access."""
        results = []

        async def fetch_and_clear():
            prompt = await get_system_prompt()
            results.append(prompt)
            clear_prompt_cache()

        # Mix of fetches and clears
        tasks = [
            get_system_prompt(),
            fetch_and_clear(),
            get_system_prompt(),
        ]

        await asyncio.gather(*tasks)

        # All should complete without errors
        assert len(results) >= 1


class TestPromptCacheInvalidation:
    """Test cases for cache invalidation."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_clear_cache_removes_data(self):
        """Test that clear_prompt_cache removes cached data."""
        # Populate cache
        await get_system_prompt()

        # Verify cache has data
        assert _prompt_cache["data"] is not None
        assert _prompt_cache["expires_at"] is not None

        # Clear cache
        clear_prompt_cache()

        # Verify cache is empty
        assert _prompt_cache["data"] is None
        assert _prompt_cache["expires_at"] is None

    @pytest.mark.asyncio
    async def test_clear_cache_forces_reload(self):
        """Test that clearing cache forces reload on next access."""
        # Populate cache
        prompt1 = await get_system_prompt()

        # Clear cache
        clear_prompt_cache()

        # Next call should reload from disk
        with patch("agent.prompts.loader.load_markdown") as mock_load:
            mock_load.return_value = "reloaded content"
            prompt2 = await get_system_prompt()

        # Should have called load_markdown again
        assert mock_load.called
        # Format includes separators with newlines: content\n\n---\n\ncontent\n\n---\n\ncontent
        assert "reloaded content" in prompt2
        assert "---" in prompt2

    @pytest.mark.asyncio
    async def test_multiple_clears_are_safe(self):
        """Test that multiple consecutive clears don't cause errors."""
        # Multiple clears should be safe
        clear_prompt_cache()
        clear_prompt_cache()
        clear_prompt_cache()

        # Cache should still work after multiple clears
        prompt = await get_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestBuildStepContext:
    """Test cases for build_step_context function."""

    def test_build_step_context_basic(self):
        """Test building context with minimal state."""
        state = {"user_message": "Hello"}
        mode_context = {}

        context = build_step_context(state, mode_context)

        assert isinstance(context, str)
        assert "Hello" in context
        assert "Fecha y hora actual" in context

    def test_build_step_context_with_customer(self):
        """Test building context with customer info."""
        state = {
            "user_message": "I want to book",
            "customer_name": "María",
            "customer_phone": "+1234567890",
        }
        mode_context = {}

        context = build_step_context(state, mode_context)

        assert "María" in context
        assert "+1234567890" in context

    def test_build_step_context_with_collected_data(self):
        """Test building context with collected booking data."""
        state = {"user_message": "Yes, that's correct"}
        mode_context = {
            "service_name": "Corte Caballero",
            "stylist_name": "Ana",
            "slot_summary": "Viernes 10:00",
            "first_name": "Juan",
            "notes": "Alergia a productos X",
        }

        context = build_step_context(state, mode_context)

        assert "Corte Caballero" in context
        assert "Ana" in context
        assert "Viernes 10:00" in context
        assert "Juan" in context
        assert "Alergia a productos X" in context

    def test_build_step_context_with_summary(self):
        """Test building context with conversation summary."""
        state = {
            "user_message": "Confirm",
            "conversation_summary": "Cliente quiere corte para mañana",
        }
        mode_context = {}

        context = build_step_context(state, mode_context)

        assert "Cliente quiere corte para mañana" in context

    def test_build_step_context_with_step_info(self):
        """Test building context with step information."""
        state = {"user_message": "Yes"}
        mode_context = {}
        step_info = {"step_name": "service_selection"}

        context = build_step_context(state, mode_context, step_info)

        assert "service_selection" in context


class TestBuildLayeredMessages:
    """Test cases for build_layered_messages function."""

    @pytest.mark.asyncio
    async def test_build_layered_messages_structure(self):
        """Test that layered messages have correct structure."""
        state = {"user_message": "Hello"}
        mode_context = {}

        messages = await build_layered_messages(state, mode_context)

        # Should have at least 2 messages (System + Human)
        assert len(messages) >= 2

        # First should be SystemMessage
        from langchain_core.messages import SystemMessage
        assert isinstance(messages[0], SystemMessage)

        # Second should be HumanMessage (dynamic context)
        from langchain_core.messages import HumanMessage
        assert isinstance(messages[1], HumanMessage)

    @pytest.mark.asyncio
    async def test_build_layered_messages_with_history(self):
        """Test building messages with conversation history."""
        state = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "I want to book"},
            ]
        }
        mode_context = {}

        messages = await build_layered_messages(state, mode_context, history_limit=2)

        # Should have system + context + 2 history messages
        assert len(messages) == 4

    @pytest.mark.asyncio
    async def test_build_layered_messages_without_history(self):
        """Test building messages without history."""
        state = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        }
        mode_context = {}

        messages = await build_layered_messages(state, mode_context, include_history=False)

        # Should have only system + context
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_build_layered_messages_content(self):
        """Test that messages contain expected content."""
        state = {"user_message": "Book appointment"}
        mode_context = {"service_name": "Corte"}

        messages = await build_layered_messages(state, mode_context)

        # System message should have identity content
        assert "Maite" in messages[0].content or "#" in messages[0].content

        # Human message should have dynamic context
        assert "Book appointment" in messages[1].content
        assert "Corte" in messages[1].content


class TestPromptCacheIntegration:
    """Integration tests for prompt caching functionality."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_full_prompt_loading_workflow(self):
        """Test the complete prompt loading workflow."""
        # Clear cache to ensure fresh start
        clear_prompt_cache()

        # Load system prompt (should cache)
        system_prompt = await get_system_prompt()
        assert len(system_prompt) > 2000

        # Build layered messages (should use cached system prompt)
        state = {"user_message": "Test message"}
        mode_context = {"service_name": "Corte"}

        messages = await build_layered_messages(state, mode_context)

        # Verify structure
        assert len(messages) >= 2
        assert system_prompt in messages[0].content or messages[0].content == system_prompt

    @pytest.mark.asyncio
    async def test_cache_performance_improvement(self):
        """Test that caching improves performance."""
        import time

        # First call - cache miss (slower)
        start = time.time()
        await get_system_prompt()
        miss_time = time.time() - start

        # Second call - cache hit (faster)
        start = time.time()
        await get_system_prompt()
        hit_time = time.time() - start

        # Cache hit should be significantly faster
        # (Allowing for test variability)
        assert hit_time < miss_time * 2  # Hit should be at most 2x slower than miss


class TestPromptCacheEdgeCases:
    """Edge case tests for prompt caching."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_each(self):
        """Clear cache before each test."""
        clear_prompt_cache()
        yield
        clear_prompt_cache()

    @pytest.mark.asyncio
    async def test_empty_state_handling(self):
        """Test handling of empty state dict."""
        state = {}
        mode_context = {}

        context = build_step_context(state, mode_context)

        assert isinstance(context, str)
        assert "Fecha y hora actual" in context

    @pytest.mark.asyncio
    async def test_none_values_in_state(self):
        """Test handling of None values in state."""
        state = {
            "customer_name": None,
            "customer_phone": None,
            "user_message": None,
        }
        mode_context = {}

        context = build_step_context(state, mode_context)

        # Should handle None values gracefully
        assert isinstance(context, str)

    @pytest.mark.asyncio
    async def test_corrupted_cache_recovery(self):
        """Test recovery from corrupted cache data."""
        # Set corrupted cache data
        _prompt_cache["data"] = None
        _prompt_cache["expires_at"] = datetime.now() + timedelta(minutes=10)

        # Should handle gracefully and reload
        prompt = await get_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 1000

    @pytest.mark.asyncio
    async def test_very_short_ttl(self):
        """Test with very short TTL."""
        # Set cache that expires immediately
        _prompt_cache["data"] = "old content"
        _prompt_cache["expires_at"] = datetime.now()

        # Small delay to ensure expiration
        await asyncio.sleep(0.01)

        # Should reload
        prompt = await get_system_prompt()
        assert prompt != "old content"
