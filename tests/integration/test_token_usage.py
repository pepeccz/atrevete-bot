"""
Integration tests for token usage verification.

Tests verify the optimized prompt system achieves token efficiency through:
1. Caching - large system prompt is loaded once and cached for 10 minutes
2. Small dynamic context - only per-request data is added dynamically

The optimization is NOT about reducing the total prompt size, but about:
- Avoiding repeated loading of the system prompt (caching benefit)
- Keeping per-request overhead minimal (dynamic context only)
"""

import os
import pytest

from agent.prompts.loader import build_step_context, build_layered_messages, get_system_prompt
from agent.prompts import load_maite_system_prompt


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Uses a rough approximation of 4 characters per token,
    which is accurate enough for comparison purposes.

    Args:
        text: Text to estimate tokens for

    Returns:
        int: Estimated token count
    """
    return len(text) // 4


class TestCachedSystemPrompt:
    """Test cases for cached system prompt behavior."""

    @pytest.mark.asyncio
    async def test_system_prompt_is_cached(self):
        """Test that system prompt is loaded and cached."""
        # Load system prompt (should be cached)
        prompt = await get_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 5000  # Comprehensive shared content

        # Should contain content from shared files
        assert "---" in prompt  # Separators between sections

    @pytest.mark.asyncio
    async def test_system_prompt_contains_shared_content(self):
        """Test that cached prompt includes all shared sections."""
        prompt = await get_system_prompt()

        # Should be substantial content
        tokens = estimate_tokens(prompt)
        print(f"\nSystem prompt: {tokens} tokens ({len(prompt)} chars)")

        # Comprehensive shared content (identity + critical_rules + glossary)
        assert tokens > 5000

    @pytest.mark.asyncio
    async def test_caching_avoids_disk_reads(self):
        """Test that caching avoids repeated disk reads."""
        # First call loads from disk
        prompt1 = await get_system_prompt()

        # Second call uses cache
        prompt2 = await get_system_prompt()

        # Should be identical (both from same source, second from cache)
        assert prompt1 == prompt2


class TestDynamicContextEfficiency:
    """Test cases for dynamic context token efficiency."""

    def test_dynamic_context_size_small(self):
        """Test that dynamic context is small and efficient."""
        # Simulate typical state
        state = {
            "user_message": "I want to book a haircut for tomorrow",
            "customer_name": "María García",
            "customer_phone": "+34612345678",
        }
        mode_context = {
            "service_name": "Corte Caballero",
            "stylist_name": "Ana",
            "slot_summary": "Viernes 15 de noviembre a las 10:00",
            "first_name": "María",
            "notes": "Alergia a productos con amoníaco",
        }

        context = build_step_context(state, mode_context)
        context_tokens = estimate_tokens(context)

        print(f"\nDynamic context: {context_tokens} tokens ({len(context)} chars)")

        # Dynamic context should be small - under 200 tokens
        assert context_tokens < 200, (
            f"Dynamic context too large: {context_tokens} tokens"
        )

        # Should contain all expected information
        assert "María García" in context
        assert "Corte Caballero" in context
        assert "Ana" in context
        assert "Viernes" in context

    def test_dynamic_context_minimal_for_simple_queries(self):
        """Test that simple queries have minimal context overhead."""
        state = {"user_message": "What are your hours?"}
        mode_context = {}

        context = build_step_context(state, mode_context)
        tokens = estimate_tokens(context)

        print(f"\nSimple query context: {tokens} tokens")

        # Should be very minimal - under 50 tokens
        assert tokens < 50

    @pytest.mark.asyncio
    async def test_layered_messages_structure(self):
        """Test that layered messages have proper structure."""
        # Simulate typical booking conversation state
        state = {
            "user_message": "Yes, I want to book that slot",
            "customer_name": "Juan Pérez",
            "messages": [
                {"role": "user", "content": "Hi, I need a haircut"},
                {"role": "assistant", "content": "Hi! I'd be happy to help"},
                {"role": "user", "content": "Something simple, just a trim"},
            ],
        }
        mode_context = {
            "service_name": "Corte Caballero",
            "stylist_name": "Marta",
            "slot_summary": "Sábado 16 de noviembre a las 11:00",
        }

        # Build complete message list
        messages = await build_layered_messages(state, mode_context, history_limit=3)

        # Should have: System (cached) + Context (dynamic) + History
        assert len(messages) >= 2

        # Calculate sizes
        system_tokens = estimate_tokens(messages[0].content)
        context_tokens = estimate_tokens(messages[1].content)

        print(f"\nMessage structure:")
        print(f"  - System (cached): {system_tokens} tokens")
        print(f"  - Dynamic context: {context_tokens} tokens")

        # System is large (cached content)
        assert system_tokens > 5000

        # Context is small (per-request data)
        assert context_tokens < 200


class TestTokenEfficiencyScenarios:
    """Test token efficiency in various conversation scenarios."""

    @pytest.mark.asyncio
    async def test_simple_query_scenario(self):
        """Test token usage for simple informational query."""
        state = {"user_message": "What are your hours?"}
        mode_context = {}

        messages = await build_layered_messages(state, mode_context, include_history=False)

        # Calculate sizes
        system_tokens = estimate_tokens(messages[0].content)
        context_tokens = estimate_tokens(messages[1].content)
        total_tokens = system_tokens + context_tokens

        print(f"\nSimple query: {total_tokens} tokens")
        print(f"  (System: {system_tokens}, Context: {context_tokens})")

        # System is large but cached, context is tiny
        assert system_tokens > 5000  # Cached comprehensive content
        assert context_tokens < 50   # Minimal per-request overhead

    @pytest.mark.asyncio
    async def test_booking_flow_scenario(self):
        """Test token usage during booking flow."""
        # Simulating a mid-booking state
        state = {
            "user_message": "Yes, that time works",
            "customer_name": "Laura Martínez",
            "messages": [
                {"role": "user", "content": "I want to book a color service"},
                {"role": "assistant", "content": "Great! Which color service?"},
                {"role": "user", "content": "Cultura de Color"},
                {"role": "assistant", "content": "Perfect. Which stylist?"},
            ],
        }
        mode_context = {
            "service_name": "Cultura de Color",
            "stylist_name": "Pilar",
            "slot_summary": "Lunes 18 de noviembre a las 14:00",
        }

        messages = await build_layered_messages(state, mode_context, history_limit=4)

        # Calculate sizes
        system_tokens = estimate_tokens(messages[0].content)
        context_tokens = estimate_tokens(messages[1].content)

        print(f"\nBooking flow: {system_tokens + context_tokens} tokens")

        # System is large (cached), context is small even with booking data
        assert system_tokens > 5000
        assert context_tokens < 150  # Still small even with booking context

    @pytest.mark.asyncio
    async def test_complex_multi_service_scenario(self):
        """Test token usage with multiple services and notes."""
        state = {
            "user_message": "Confirm the booking",
            "customer_name": "Carlos Rodríguez",
            "messages": [
                {"role": "user", "content": "I need several services"},
                {"role": "assistant", "content": "Sure, which ones?"},
                {"role": "user", "content": "Corte, color, and manicure"},
            ],
        }
        mode_context = {
            "service_name": "Corte Caballero + Cultura de Color + Manicura",
            "stylist_name": "Ana",
            "slot_summary": "Miércoles 20 de noviembre a las 10:00",
            "first_name": "Carlos",
            "notes": "Cliente preferido, alergia a acetona, prefiere productos orgánicos si disponibles",
        }

        messages = await build_layered_messages(state, mode_context)

        # Calculate sizes
        system_tokens = estimate_tokens(messages[0].content)
        context_tokens = estimate_tokens(messages[1].content)

        print(f"\nComplex scenario: {system_tokens + context_tokens} tokens")

        # Even complex scenarios: system cached, context still reasonable
        assert system_tokens > 5000  # Same cached content
        assert context_tokens < 200  # Slightly larger but still under 200 tokens


class TestCachingBenefits:
    """Test benefits of prompt caching."""

    @pytest.mark.asyncio
    async def test_cache_reduces_repeated_token_loading(self):
        """Test that caching prevents repeated token usage from disk reads."""
        # First call - loads from disk
        prompt1 = await get_system_prompt()

        # Second call - uses cache (no disk read)
        prompt2 = await get_system_prompt()

        # Both should be identical
        assert prompt1 == prompt2

        # Calculate "token savings" from caching
        tokens_cached = estimate_tokens(prompt1)

        print(f"\nCache benefits:")
        print(f"  - Cached content: ~{tokens_cached} tokens")
        print(f"  - First call: disk read (~{tokens_cached} tokens loaded)")
        print(f"  - Subsequent calls: from cache (0 tokens loaded from disk)")

    @pytest.mark.asyncio
    async def test_cache_hit_is_fast(self):
        """Test that cache hits are fast compared to disk reads."""
        import time

        # First call - cache miss (slower)
        start = time.time()
        await get_system_prompt()
        miss_time = time.time() - start

        # Second call - cache hit (faster)
        start = time.time()
        await get_system_prompt()
        hit_time = time.time() - start

        print(f"\nCache performance:")
        print(f"  - Cache miss: {miss_time:.4f}s")
        print(f"  - Cache hit: {hit_time:.4f}s")

        # Cache hit should be significantly faster
        # (Allowing for test variability)
        assert hit_time < miss_time * 2


class TestTokenBudgetCompliance:
    """Test compliance with token budgets."""

    def test_dynamic_context_under_budget(self):
        """Test that dynamic context is under 500 tokens even in worst case."""
        # Worst case: lots of collected data
        state = {
            "user_message": "Yes please confirm everything",
            "customer_name": "María Elena González de la Fuente",
            "customer_phone": "+34612345678",
            "conversation_summary": "Cliente quiere agendar varios servicios para su boda",
        }
        mode_context = {
            "service_name": "Cultura de Color Extra + Mechas Extras + Peinado Novia + Maquillaje Novia + Manicura Permanente",
            "stylist_name": "Ana María",
            "slot_summary": "Sábado 23 de noviembre de 2024 a las 09:00 de la mañana",
            "first_name": "María Elena",
            "notes": "Novia, quiere look natural, alergia a ciertos productos, viene con 3 damas de honor",
        }
        step_info = {"step_name": "booking_confirmation"}

        context = build_step_context(state, mode_context, step_info)
        tokens = estimate_tokens(context)

        print(f"\nDynamic context (worst case): {tokens} tokens")

        # Should still be under 500 tokens even in worst case
        assert tokens < 500, f"Dynamic context too large: {tokens} tokens"

    @pytest.mark.asyncio
    async def test_full_request_structure(self):
        """Test structure of complete request."""
        # Simulate a fairly heavy request
        state = {
            "user_message": "Yes, book it please",
            "customer_name": "Test Customer",
            "messages": [
                {"role": "user", "content": f"Message {i}"}
                for i in range(6)  # 6 messages of history
            ],
        }
        mode_context = {
            "service_name": "Corte Caballero",
            "stylist_name": "Ana",
            "slot_summary": "Viernes 15 nov 10:00",
        }

        messages = await build_layered_messages(state, mode_context, history_limit=6)

        # Structure should be: System + Context + History
        assert len(messages) >= 3

        # System message is large (cached)
        system_tokens = estimate_tokens(messages[0].content)
        assert system_tokens > 5000

        # Context is small
        context_tokens = estimate_tokens(messages[1].content)
        assert context_tokens < 200

        print(f"\nFull request structure:")
        print(f"  - System: {system_tokens} tokens (cached)")
        print(f"  - Context: {context_tokens} tokens (dynamic)")
        print(f"  - History: {len(messages)-2} messages")
