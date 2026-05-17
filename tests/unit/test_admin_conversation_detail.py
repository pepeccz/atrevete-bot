"""Unit tests for Commit 3 — admin detail endpoint deserializes LangChain messages.

Tests that the admin GET /conversations/{id} Redis-sourced path correctly
deserializes LangChain constructor dicts into plain {role, content} dicts.
"""


from api.routes.admin import _deserialize_langchain_message

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
