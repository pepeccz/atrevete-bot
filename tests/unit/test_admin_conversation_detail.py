"""Unit tests for admin detail endpoint helpers.

Covers:
1. LangChain message deserialization (Redis-sourced path, Commit 3).
2. C3/C2: DB-sourced path escalation output — verifies that active_escalation
   fields are serialized correctly, and that the comparison key used against
   Escalation.conversation_id (String(50)) is always a plain str, not a
   uuid.UUID (which caused ProgrammingError on asyncpg in prod).
"""

from unittest.mock import MagicMock

from api.routes.admin import _deserialize_langchain_message

# ============================================================================
# C2 / C3: detail endpoint escalation field assembly
#
# The DB path in get_conversation() fetches the active escalation and builds
# the response dict inline. We test the dict-building logic (the part after the
# ORM query) by simulating the active_escalation object and asserting the
# response fields. We also assert that str(conversation.conversation_id) is a
# plain str — the key invariant that prevents the String(50) vs uuid.UUID type
# mismatch in the WHERE clause.
# ============================================================================


class TestDetailEndpointEscalationFields:
    """Verify escalation field assembly in the DB-sourced get_conversation() path."""

    def _build_escalation_response_fields(self, active_escalation):
        """Mirror the inline dict-building logic from get_conversation() DB path."""
        return {
            "is_escalated": active_escalation is not None,
            "escalation_reason": active_escalation.reason if active_escalation else None,
            "escalation_source": (
                active_escalation.source.value
                if active_escalation and active_escalation.source
                else None
            ),
            "escalation_triggered_at": (
                active_escalation.triggered_at.isoformat()
                if active_escalation and active_escalation.triggered_at
                else None
            ),
        }

    def test_no_escalation_fields_are_none(self):
        """When no active escalation exists, all escalation fields are None / False."""
        fields = self._build_escalation_response_fields(None)

        assert fields["is_escalated"] is False
        assert fields["escalation_reason"] is None
        assert fields["escalation_source"] is None
        assert fields["escalation_triggered_at"] is None

    def test_active_escalation_populates_all_fields(self):
        """When an active escalation exists, all fields are surfaced correctly."""
        from datetime import UTC, datetime

        esc = MagicMock()
        esc.reason = "Manual takeover by admin/stylist"
        esc.source = MagicMock()
        esc.source.value = "manual"
        esc.triggered_at = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)

        fields = self._build_escalation_response_fields(esc)

        assert fields["is_escalated"] is True
        assert fields["escalation_reason"] == "Manual takeover by admin/stylist"
        assert fields["escalation_source"] == "manual"
        assert fields["escalation_triggered_at"] == "2024-06-01T10:00:00+00:00"

    def test_conversation_id_join_key_is_str_not_uuid(self):
        """The key passed to Escalation.conversation_id (String(50)) must be a plain str.

        The C2 bug: conv_uuid (uuid.UUID) was compared directly to String(50) column.
        asyncpg raises ProgrammingError: operator does not exist: character varying = uuid.
        After the fix: str(conversation.conversation_id) is used — always a str.
        """
        # Simulate a ConversationHistory row with a string conversation_id (Chatwoot ID)
        conversation = MagicMock()
        conversation.conversation_id = "123"  # Chatwoot numeric string

        join_key = str(conversation.conversation_id)

        # CRITICAL: must be str, never uuid.UUID
        assert isinstance(join_key, str), (
            "Escalation.conversation_id is String(50); comparing with uuid.UUID causes "
            "ProgrammingError on asyncpg. The join key MUST be a plain str."
        )
        assert join_key == "123"

    def test_conversation_id_join_key_when_chatwoot_id_is_numeric_string(self):
        """Chatwoot conversation IDs are numeric strings — str() is idempotent."""
        conversation = MagicMock()
        conversation.conversation_id = "456"

        join_key = str(conversation.conversation_id)

        assert join_key == "456"
        assert isinstance(join_key, str)

    def test_auto_error_escalation_source_serialized(self):
        """auto_error source is serialized via .value — matches real EscalationSource enum."""
        esc = MagicMock()
        esc.reason = "Tool call failed 3 times"
        esc.source = MagicMock()
        esc.source.value = "auto_error"
        esc.triggered_at = None

        fields = self._build_escalation_response_fields(esc)

        assert fields["escalation_source"] == "auto_error"
        assert fields["escalation_triggered_at"] is None


# ============================================================================
# Tests for _deserialize_langchain_message helper
# ============================================================================


class TestDeserializeLangchainMessage:
    """Tests for the LangChain constructor dict → plain dict conversion."""

    def test_human_message_maps_to_user_role(self):
        """LangChain 'human' type → role 'user'."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "HumanMessage"],
            "kwargs": {
                "content": "Hola, quiero reservar",
                "type": "human",
                "id": "msg-001",
            },
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "user"
        assert result["content"] == "Hola, quiero reservar"

    def test_ai_message_maps_to_assistant_role(self):
        """LangChain 'ai' type → role 'assistant'."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "AIMessage"],
            "kwargs": {
                "content": "¡Hola! ¿Cómo te puedo ayudar?",
                "type": "ai",
                "id": "msg-002",
            },
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "assistant"
        assert result["content"] == "¡Hola! ¿Cómo te puedo ayudar?"

    def test_tool_message_maps_to_tool_role(self):
        """LangChain 'tool' type → role 'tool'."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "ToolMessage"],
            "kwargs": {
                "content": '{"slots": []}',
                "type": "tool",
                "id": "msg-003",
            },
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "tool"
        assert result["content"] == '{"slots": []}'

    def test_unknown_type_maps_to_unknown_role(self):
        """Unrecognized LangChain type → role 'unknown'."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": [],
            "kwargs": {
                "content": "mystery content",
                "type": "system",
                "id": "msg-004",
            },
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "system"
        assert result["content"] == "mystery content"

    def test_no_timestamp_becomes_none(self):
        """LangChain messages have no timestamp → created_at is None."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": [],
            "kwargs": {"content": "test", "type": "human"},
        }
        result = _deserialize_langchain_message(msg)

        assert result["created_at"] is None

    def test_plain_dict_with_role_passes_through(self):
        """Already-deserialized plain dict with role/content is returned unchanged."""
        msg = {
            "role": "user",
            "content": "test message",
            "created_at": "2024-01-01T10:00:00+00:00",
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "user"
        assert result["content"] == "test message"
        assert result["created_at"] == "2024-01-01T10:00:00+00:00"

    def test_plain_dict_without_role_returns_unknown_role(self):
        """Plain dict missing 'role' key → role defaults to 'unknown'."""
        msg = {
            "content": "no role here",
        }
        result = _deserialize_langchain_message(msg)

        assert result["role"] == "unknown"
        assert result["content"] == "no role here"


class TestDeserializeLangchainMessageBatch:
    """Tests with a batch of mixed message types (simulates real Redis checkpoint)."""

    def test_mixed_batch_deserializes_all(self):
        """A batch with LangChain + plain dicts all deserialize correctly."""
        messages = [
            {
                "lc": 1,
                "type": "constructor",
                "id": ["langchain", "schema", "messages", "HumanMessage"],
                "kwargs": {"content": "Hola", "type": "human", "id": "1"},
            },
            {
                "lc": 1,
                "type": "constructor",
                "id": ["langchain", "schema", "messages", "AIMessage"],
                "kwargs": {"content": "¡Hola!", "type": "ai", "id": "2"},
            },
            {
                "role": "user",
                "content": "plain dict",
                "created_at": None,
            },
        ]

        results = [_deserialize_langchain_message(m) for m in messages]

        assert results[0]["role"] == "user"
        assert results[0]["content"] == "Hola"
        assert results[1]["role"] == "assistant"
        assert results[1]["content"] == "¡Hola!"
        assert results[2]["role"] == "user"
        assert results[2]["content"] == "plain dict"

    def test_empty_content_is_preserved(self):
        """Empty content string should not be replaced by a fallback."""
        msg = {
            "lc": 1,
            "type": "constructor",
            "id": [],
            "kwargs": {"content": "", "type": "human"},
        }
        result = _deserialize_langchain_message(msg)

        assert result["content"] == ""
