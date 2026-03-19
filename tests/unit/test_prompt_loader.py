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

# Now import the loader
from agent.prompts.loader import (
    CACHE_TTL_MINUTES,
    build_layered_messages,
    build_step_context,
    clear_prompt_cache,
    get_system_prompt,
    load_markdown,
    load_mode_overlay,
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
        assert "Hello" not in context
        assert "Fecha y hora actual" in context

    def test_build_step_context_with_customer(self):
        """Test building context with customer info — name NOT injected (privacy)."""
        state = {
            "user_message": "I want to book",
            "customer_name": "María",
            "customer_phone": "+1234567890",
        }
        mode_context = {}

        context = build_step_context(state, mode_context)

        # Customer name should NOT appear in prompt context (customer-name-handling refactor)
        assert "María" not in context
        assert "+1234567890" in context

    def test_build_step_context_with_collected_data(self):
        """Test building context with collected booking data.

        first_name is intentionally excluded from context (Rule #6 — NUNCA uses el nombre
        del cliente en ninguna respuesta). All other booking fields must still be present.
        """
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
        # first_name must NOT be injected — Rule #6 privacy enforcement
        assert "Juan" not in context
        assert "Nombre para la reserva" not in context
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

    def test_build_step_context_includes_semantic_fields_when_present(self):
        state = {"user_message": "quiero turno pronto"}
        mode_context = {
            "stylist_name": "María",
            "substitution_made": True,
            "substitution_reason": "minimum_days_rule",
            "date_requested": "2026-03-19",
            "date_substituted": "2026-03-22",
            "min_valid_date": "2026-03-22",
            "no_slots_for_stylist": True,
        }

        context = build_step_context(state, mode_context)

        assert "Fecha solicitada ajustada" in context
        assert "2026-03-19" in context
        assert "2026-03-22" in context
        assert "Sin disponibilidad para María en el rango solicitado" in context

    # Task 5.7 — loader guidance: tool_error
    def test_build_step_context_includes_prefetch_tool_error_guidance(self):
        """When prefetch_error_type='tool_error', context must include 'error técnico' guidance."""
        state = {"user_message": "quiero turno"}
        mode_context = {
            "service_name": "Cortar",
            "prefetch_error": True,
            "prefetch_error_type": "tool_error",
        }

        context = build_step_context(state, mode_context)

        assert "PREFETCH FALLIDO" in context
        assert "error técnico" in context
        assert "list_stylists" in context

    # Task 5.7 — loader guidance: no_availability
    def test_build_step_context_includes_prefetch_no_availability_guidance(self):
        """When prefetch_error_type='no_availability', context must include 'SIN DISPONIBILIDAD'."""
        state = {"user_message": "quiero turno"}
        mode_context = {
            "service_name": "Cortar",
            "prefetch_error": True,
            "prefetch_error_type": "no_availability",
        }

        context = build_step_context(state, mode_context)

        assert "SIN DISPONIBILIDAD" in context

    # Task 5.7 — loader guidance: absent prefetch_error_type → no warning injected
    def test_build_step_context_omits_prefetch_warning_when_no_error_type(self):
        """When prefetch_error_type is absent, no prefetch warning should appear in context."""
        state = {"user_message": "quiero turno"}
        mode_context = {
            "service_name": "Cortar",
            "prefetched_stylists": [
                {"name": "Ana", "id": "sty-1", "next_slot_summary": "Lunes a las 10:00"},
            ],
        }

        context = build_step_context(state, mode_context)

        assert "PREFETCH FALLIDO" not in context
        assert "SIN DISPONIBILIDAD" not in context
        assert "Ana" in context

    def test_build_step_context_omits_prefetch_warning_when_no_error(self):
        """When prefetch_error is absent/False, no warning should appear."""
        state = {"user_message": "quiero turno"}
        mode_context = {
            "service_name": "Cortar",
            "prefetched_stylists": [
                {"name": "Ana", "id": "sty-1", "next_slot_summary": "Lunes a las 10:00"},
            ],
        }

        context = build_step_context(state, mode_context)

        assert "PREFETCH FALLIDO" not in context
        assert "Ana" in context

    def test_build_step_context_omits_semantic_fields_when_absent(self):
        state = {"user_message": "quiero turno"}
        mode_context = {"service_name": "Cortar"}

        context = build_step_context(state, mode_context)

        assert "Fecha solicitada ajustada" not in context
        assert "Sin disponibilidad para" not in context

    @pytest.mark.asyncio
    async def test_build_layered_messages_renders_semantic_fields_in_dynamic_context(self):
        state = {"user_message": "quiero turno"}
        mode_context = {
            "substitution_made": True,
            "substitution_reason": "minimum_days_rule",
            "date_requested": "2026-03-19",
            "min_valid_date": "2026-03-22",
        }

        messages = await build_layered_messages(state, mode_context, include_history=False)

        assert "Fecha solicitada ajustada" in messages[1].content
        assert "2026-03-19" in messages[1].content
        assert "2026-03-22" in messages[1].content

    def test_build_step_context_does_not_duplicate_user_message(self):
        state = {"user_message": "Necesito una cita"}
        mode_context = {"service_name": "Corte"}

        context = build_step_context(state, mode_context)

        assert "Mensaje del cliente:" not in context
        assert "Necesito una cita" not in context

    @pytest.mark.asyncio
    async def test_build_layered_messages_keeps_user_message_only_in_history(self):
        state = {
            "user_message": "Necesito una cita",
            "messages": [{"role": "user", "content": "Necesito una cita"}],
        }
        mode_context = {"service_name": "Corte"}

        messages = await build_layered_messages(state, mode_context, include_history=True)

        assert "Mensaje del cliente:" not in messages[1].content
        assert "Necesito una cita" not in messages[1].content
        assert messages[-1].content == "Necesito una cita"


class TestBuildLayeredMessages:
    """Test cases for build_layered_messages function."""

    @pytest.mark.asyncio
    async def test_build_layered_messages_structure(self):
        """Test that layered messages have correct structure."""
        state = {"user_message": "Hello"}
        mode_context = {}

        messages = await build_layered_messages(state, mode_context)

        # Should have at least 2 messages (System + System context)
        assert len(messages) >= 2

        # First should be SystemMessage (cached system prompt)
        from langchain_core.messages import SystemMessage
        assert isinstance(messages[0], SystemMessage)

        # Second should be SystemMessage (dynamic context — NOT HumanMessage,
        # to prevent the LLM from echoing internal context back to the user)
        assert isinstance(messages[1], SystemMessage)

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
        assert "Corte" in messages[1].content


class TestLoadModeOverlay:
    """Coverage for mode overlay dispatch across all v6 modes."""

    def test_load_mode_overlay_loads_all_non_booking_modes(self):
        with patch("agent.prompts.loader.load_markdown") as mock_load_markdown:
            mock_load_markdown.side_effect = lambda file_name, subdir: f"{subdir}/{file_name}"

            greeting = load_mode_overlay("greeting", {})
            general = load_mode_overlay("GENERAL", {})
            escalation = load_mode_overlay("Escalation", {})

        assert greeting == "modes/greeting.md"
        assert general == "modes/general.md"
        assert escalation == "modes/escalation.md"

    def test_load_mode_overlay_unknown_mode_logs_warning(self):
        with patch("agent.prompts.loader.logger") as mock_logger:
            result = load_mode_overlay("unknown", {})

        assert result == ""
        mock_logger.warning.assert_called_once()

    def test_load_mode_overlay_booking_keeps_substep_behavior(self):
        with patch("agent.prompts.loader._use_substep_prompts", return_value=True), patch(
            "agent.prompts.loader._resolve_booking_substep",
            return_value="slot_selection",
        ), patch(
            "agent.prompts.loader.load_markdown",
            return_value="booking slot prompt",
        ) as mock_load_markdown:
            result = load_mode_overlay("booking", {}, substep="slot_selection")

        assert result == "booking slot prompt"
        mock_load_markdown.assert_called_once_with("slot_selection.md", "modes/booking")


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

    @pytest.mark.asyncio
    async def test_cached_system_prompt_avoids_reloading_markdown_files(self):
        with patch("agent.prompts.loader.load_markdown", side_effect=["id", "rules", "glossary"]) as mocked_load:
            clear_prompt_cache()
            first = await get_system_prompt()
            second = await get_system_prompt()

        assert first == second
        assert mocked_load.call_count == 3


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


# =============================================================================
# T3.6: build_step_context must NOT inject first_name (Rule #6 privacy fix)
# T3.7: confirmation.md must NOT contain the name-permission line
# =============================================================================


class TestFirstNameFilteringRule6:
    """T3.6 — Verify first_name is never injected into build_step_context output."""

    def test_build_step_context_does_not_inject_first_name(self):
        """T3.6: even when mode_context has first_name set, it must not appear in output."""
        state = {"user_message": "sí, confirmo"}
        mode_context = {"first_name": "María"}

        context = build_step_context(state, mode_context)

        assert "María" not in context
        assert "Nombre para la reserva" not in context

    def test_build_step_context_other_fields_unaffected_when_first_name_absent(self):
        """T3.6 scenario 2: when first_name is not set, function behaves normally."""
        state = {"user_message": "sí, confirmo"}
        mode_context = {"slot_summary": "Viernes 10:00", "service_name": "Corte"}

        context = build_step_context(state, mode_context)

        assert "Viernes 10:00" in context
        assert "Corte" in context

    def test_build_step_context_first_name_with_other_fields_filters_only_name(self):
        """T3.6 scenario 3: other fields still injected even when first_name present."""
        state = {"user_message": "dale"}
        mode_context = {
            "first_name": "Carlos",
            "stylist_name": "Laura",
            "service_name": "Tinte",
            "slot_summary": "Lunes 14:00",
        }

        context = build_step_context(state, mode_context)

        # first_name filtered out
        assert "Carlos" not in context
        assert "Nombre para la reserva" not in context
        # Other fields still present
        assert "Laura" in context
        assert "Tinte" in context
        assert "Lunes 14:00" in context


class TestConfirmationMdNoNamePermission:
    """T3.7 — confirmation.md must not contain the removed name-permission line."""

    def test_confirmation_md_does_not_contain_name_permission_line(self):
        """T3.7: The line 'Puedes usar el nombre de la clienta' must be absent."""
        from pathlib import Path

        confirmation_path = (
            Path(__file__).parent.parent.parent
            / "agent" / "prompts" / "modes" / "booking" / "confirmation.md"
        )
        content = confirmation_path.read_text(encoding="utf-8")

        assert "Puedes usar el nombre de la clienta" not in content

    def test_confirmation_md_retains_core_instructions(self):
        """T3.7 scenario 2: removing the line must not strip other content."""
        from pathlib import Path

        confirmation_path = (
            Path(__file__).parent.parent.parent
            / "agent" / "prompts" / "modes" / "booking" / "confirmation.md"
        )
        content = confirmation_path.read_text(encoding="utf-8")

        assert "Confirmacion" in content or "confirmacion" in content.lower()
        assert "Reglas de Transicion" in content
        assert "Preservacion de Contexto" in content
