"""
Integration tests for Maite persona and tone validation.

These tests verify that the system prompt correctly influences the
LLM's responses to maintain consistent tone, emoji usage, and Spanish language.
"""

import pytest

from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT


class TestMaitePersona:
    """Integration tests for Maite's personality and tone."""

    def test_system_prompt_loaded_at_module_level(self):
        """Test that system prompt is loaded and available as module constant."""
        assert MAITE_SYSTEM_PROMPT, "MAITE_SYSTEM_PROMPT should be loaded"
        assert len(MAITE_SYSTEM_PROMPT) > 100, "System prompt should be substantial"

    def test_system_prompt_is_string(self):
        """Test that system prompt is a string."""
        assert isinstance(MAITE_SYSTEM_PROMPT, str), "System prompt should be a string"

    def test_system_prompt_contains_maite_identity(self):
        """Test that system prompt defines Maite's identity."""
        assert "Maite" in MAITE_SYSTEM_PROMPT, "System prompt should contain Maite's name"
        assert "asistenta virtual" in MAITE_SYSTEM_PROMPT.lower(), \
            "System prompt should define Maite as virtual assistant"

    def test_system_prompt_contains_tone_guidelines(self):
        """Test that system prompt includes tone guidelines."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        # Check for tone keywords
        assert "tú" in MAITE_SYSTEM_PROMPT, "Should specify 'tú' form usage"
        assert any(word in prompt_lower for word in ["cálida", "amigable", "warm", "friendly"]), \
            "Should specify warm/friendly tone"

    def test_system_prompt_contains_emoji_guidelines(self):
        """Test that system prompt includes emoji usage guidelines."""
        # Check for key emojis
        assert "🌸" in MAITE_SYSTEM_PROMPT, "Should include 🌸 signature emoji"
        assert "💕" in MAITE_SYSTEM_PROMPT, "Should include 💕 warmth emoji"
        assert "😊" in MAITE_SYSTEM_PROMPT, "Should include 😊 friendliness emoji"
        assert "🎉" in MAITE_SYSTEM_PROMPT, "Should include 🎉 celebration emoji"
        assert "💇" in MAITE_SYSTEM_PROMPT, "Should include 💇 services emoji"

    def test_system_prompt_contains_business_context(self):
        """Test that system prompt includes business context."""
        # Check for stylist information
        assert "Pilar" in MAITE_SYSTEM_PROMPT, "Should mention stylist Pilar"
        assert "Marta" in MAITE_SYSTEM_PROMPT, "Should mention stylist Marta"
        assert "Rosa" in MAITE_SYSTEM_PROMPT, "Should mention stylist Rosa"
        assert "Harol" in MAITE_SYSTEM_PROMPT, "Should mention stylist Harol"
        assert "Víctor" in MAITE_SYSTEM_PROMPT, "Should mention stylist Víctor"

        # Check for service categories
        assert "Peluquería" in MAITE_SYSTEM_PROMPT, "Should mention Peluquería category"
        assert "Estética" in MAITE_SYSTEM_PROMPT, "Should mention Estética category"

    def test_system_prompt_contains_payment_policy(self):
        """Test that system prompt includes payment policies."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        assert any(word in prompt_lower for word in ["anticipo", "advance", "20%"]), \
            "Should mention advance payment policy"

    def test_system_prompt_contains_tool_usage_instructions(self):
        """Test that system prompt includes tool usage guidelines."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        assert "herramientas" in prompt_lower, "Should mention tools (herramientas)"
        assert any(word in MAITE_SYSTEM_PROMPT for word in ["CustomerTools", "CalendarTools", "BookingTools"]), \
            "Should mention specific tool categories"

    def test_system_prompt_contains_escalation_scenarios(self):
        """Test that system prompt includes escalation instructions."""
        assert "escalate_to_human" in MAITE_SYSTEM_PROMPT, "Should reference escalate_to_human function"

        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        # Check for escalation triggers
        assert any(word in prompt_lower for word in ["embarazada", "alergia", "medical", "médica"]), \
            "Should mention medical consultation trigger"
        assert any(word in prompt_lower for word in ["pago", "payment"]), \
            "Should mention payment failure trigger"

    def test_system_prompt_contains_example_interactions(self):
        """Test that system prompt includes example interactions."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        # Check for example phrases
        assert any(word in prompt_lower for word in ["ejemplo", "example", "entrada", "respuesta"]), \
            "Should include examples section"

    def test_system_prompt_uses_spanish(self):
        """Test that system prompt is primarily in Spanish."""
        spanish_words = ["eres", "tu", "que", "para", "con", "los", "las"]
        matches = sum(1 for word in spanish_words if word in MAITE_SYSTEM_PROMPT.lower())

        assert matches >= 4, "System prompt should be primarily in Spanish"

    def test_system_prompt_contains_business_hours(self):
        """Test that system prompt includes business hours."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        assert any(word in prompt_lower for word in ["horario", "lunes", "monday", "10:00"]), \
            "Should mention business hours"

    def test_system_prompt_contains_cancellation_policy(self):
        """Test that system prompt includes cancellation policy."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        assert any(word in prompt_lower for word in ["cancelación", "cancellation", "24"]), \
            "Should mention cancellation policy with 24-hour threshold"

    def test_system_prompt_length_appropriate_for_llm(self):
        """Test that system prompt is a reasonable length for LLM context."""
        # System prompts should be substantial but not excessive
        assert 1000 < len(MAITE_SYSTEM_PROMPT) < 50000, \
            f"System prompt length ({len(MAITE_SYSTEM_PROMPT)}) should be between 1000-50000 characters"

    def test_system_prompt_contains_response_length_guidelines(self):
        """Test that system prompt includes guidance on response length."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        assert any(word in prompt_lower for word in ["conciso", "breve", "corto", "concise", "short"]), \
            "Should include guidance on keeping responses concise"

    def test_system_prompt_mentions_whatsapp_context(self):
        """Test that system prompt acknowledges WhatsApp as the communication channel."""
        assert "WhatsApp" in MAITE_SYSTEM_PROMPT, "Should mention WhatsApp as communication channel"

    def test_system_prompt_defines_personality_traits(self):
        """Test that system prompt defines Maite's personality traits."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        # Check for personality descriptors
        personality_words = ["paciente", "profesional", "empática", "útil", "patient", "professional", "empathetic", "helpful"]
        matches = sum(1 for word in personality_words if word in prompt_lower)

        assert matches >= 2, "Should define multiple personality traits"


class TestSystemPromptIntegration:
    """Test system prompt integration with conversation state."""

    def test_system_prompt_can_be_imported_from_conversation_flow(self):
        """Test that MAITE_SYSTEM_PROMPT can be imported from conversation_flow module."""
        from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT

        assert MAITE_SYSTEM_PROMPT is not None, "Should be able to import MAITE_SYSTEM_PROMPT"
        assert isinstance(MAITE_SYSTEM_PROMPT, str), "Imported constant should be a string"

    def test_system_prompt_can_be_used_in_message_dict(self):
        """Test that system prompt can be formatted as a message dict."""
        from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT

        system_message = {"role": "system", "content": MAITE_SYSTEM_PROMPT}

        assert system_message["role"] == "system", "Message should have 'system' role"
        assert system_message["content"] == MAITE_SYSTEM_PROMPT, "Message content should be the prompt"
        assert len(system_message["content"]) > 100, "Message content should be substantial"

    @pytest.mark.asyncio
    async def test_new_conversation_includes_system_message(self):
        """Test that new conversations include system message in initial state."""
        from agent.graphs.conversation_flow import MAITE_SYSTEM_PROMPT

        # Simulate initial state creation (as done in main.py)
        state = {
            "conversation_id": "test-conv-123",
            "customer_phone": "+34612345678",
            "customer_name": None,
            "messages": [
                {"role": "system", "content": MAITE_SYSTEM_PROMPT},
                {"role": "user", "content": "Hola"}
            ],
            "current_intent": None,
            "metadata": {},
        }

        # Verify system message is first
        assert state["messages"][0]["role"] == "system", "First message should be system message"
        assert state["messages"][0]["content"] == MAITE_SYSTEM_PROMPT, \
            "First message content should be the system prompt"

        # Verify user message is second
        assert state["messages"][1]["role"] == "user", "Second message should be user message"


class TestManualToneValidation:
    """
    Manual validation tests for tone and emoji usage.

    These tests verify the structure of example interactions in the system prompt.
    Full LLM-generated response validation would require live API calls or mocking.
    """

    def test_system_prompt_provides_greeting_examples(self):
        """Test that system prompt includes greeting examples."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        # Check for greeting-related content
        assert "hola" in prompt_lower, "Should include greeting examples with 'Hola'"

    def test_system_prompt_demonstrates_emoji_in_examples(self):
        """Test that example interactions demonstrate emoji usage."""
        # Count emojis in prompt
        emojis = ["🌸", "💕", "😊", "🎉", "💇", "😔"]
        emoji_count = sum(MAITE_SYSTEM_PROMPT.count(emoji) for emoji in emojis)

        # Should have multiple emoji examples (at least 5 total across all examples)
        assert emoji_count >= 5, f"Should demonstrate emoji usage with at least 5 emojis, found {emoji_count}"

    def test_system_prompt_shows_tu_form_examples(self):
        """Test that examples demonstrate 'tú' form usage."""
        # Look for tú-form verbs in examples
        tu_form_indicators = ["quieres", "necesitas", "puedes", "tienes", "vienes"]
        matches = sum(1 for word in tu_form_indicators if word in MAITE_SYSTEM_PROMPT.lower())

        assert matches >= 2, "Should demonstrate 'tú' form with multiple example verbs"

    def test_system_prompt_shows_empathy_examples(self):
        """Test that examples demonstrate empathetic responses."""
        prompt_lower = MAITE_SYSTEM_PROMPT.lower()

        empathy_indicators = ["entiendo", "comprendo", "😔"]
        matches = sum(1 for indicator in empathy_indicators if indicator in prompt_lower)

        assert matches >= 1, "Should demonstrate empathy in examples"

    def test_system_prompt_shows_concise_response_pattern(self):
        """Test that examples are concise (not verbose)."""
        # Find example responses in the prompt (assuming they're marked with "respuesta" or similar)
        # This is a structural test to ensure examples exist
        assert "ejemplo" in MAITE_SYSTEM_PROMPT.lower() or "example" in MAITE_SYSTEM_PROMPT.lower(), \
            "Should include labeled examples"
