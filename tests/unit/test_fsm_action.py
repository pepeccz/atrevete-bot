"""
Unit tests for FSMAction system (v5.0 prescriptive architecture).

Tests:
- FSMAction dataclass creation and validation
- ToolCall specification
- ActionType enum
- Serialization/deserialization
- Validation rules
"""

import pytest

from agent.fsm.fsm_action import ActionType, FSMAction, ToolCall


class TestToolCall:
    """Test ToolCall dataclass."""

    def test_tool_call_creation(self):
        """Test creating a ToolCall with all fields."""
        tc = ToolCall(
            name="search_services",
            args={"query": "corte", "limit": 5},
            required=True,
        )

        assert tc.name == "search_services"
        assert tc.args == {"query": "corte", "limit": 5}
        assert tc.required is True

    def test_tool_call_defaults(self):
        """Test ToolCall with default required=True."""
        tc = ToolCall(name="find_next_available", args={"stylist_id": "uuid-123"})

        assert tc.required is True  # Default


class TestActionType:
    """Test ActionType enum."""

    def test_action_types_exist(self):
        """Test all ActionType enum values exist."""
        assert ActionType.CALL_TOOLS_SEQUENCE == "call_tools_sequence"
        assert ActionType.GENERATE_RESPONSE == "generate_response"
        assert ActionType.NO_ACTION == "no_action"

    def test_action_type_string_values(self):
        """Test ActionType values are strings (for JSON serialization)."""
        for action_type in ActionType:
            assert isinstance(action_type.value, str)


class TestFSMAction:
    """Test FSMAction dataclass."""

    def test_fsm_action_call_tools_sequence(self):
        """Test creating FSMAction with CALL_TOOLS_SEQUENCE."""
        action = FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(name="search_services", args={"query": "todos"}),
                ToolCall(name="find_next_available", args={"stylist_id": "uuid-123"}),
            ],
            response_template="Services: {% for s in services %}{{ s.name }}{% endfor %}",
            allow_llm_creativity=True,
        )

        assert action.action_type == ActionType.CALL_TOOLS_SEQUENCE
        assert len(action.tool_calls) == 2
        assert action.tool_calls[0].name == "search_services"
        assert action.response_template is not None
        assert action.allow_llm_creativity is True

    def test_fsm_action_generate_response(self):
        """Test creating FSMAction with GENERATE_RESPONSE (no tools)."""
        action = FSMAction(
            action_type=ActionType.GENERATE_RESPONSE,
            response_template="¿Para qué día te gustaría la cita?",
            template_vars={"stylist_name": "Ana"},
            allow_llm_creativity=True,
        )

        assert action.action_type == ActionType.GENERATE_RESPONSE
        assert action.tool_calls == []  # No tools
        assert action.response_template is not None
        assert action.template_vars == {"stylist_name": "Ana"}

    def test_fsm_action_no_action(self):
        """Test creating FSMAction with NO_ACTION (fallback)."""
        action = FSMAction(action_type=ActionType.NO_ACTION)

        assert action.action_type == ActionType.NO_ACTION
        assert action.tool_calls == []
        assert action.response_template is None
        assert action.template_vars == {}

    def test_fsm_action_defaults(self):
        """Test FSMAction with default field values."""
        action = FSMAction(
            action_type=ActionType.GENERATE_RESPONSE,
            response_template="Test",
        )

        assert action.tool_calls == []  # Default empty list
        assert action.template_vars == {}  # Default empty dict
        assert action.allow_llm_creativity is True  # Default True


class TestFSMActionValidation:
    """Test FSMAction validation rules in __post_init__."""

    def test_call_tools_sequence_requires_tools(self):
        """Test CALL_TOOLS_SEQUENCE without tools raises ValueError."""
        with pytest.raises(ValueError, match="requires non-empty tool_calls"):
            FSMAction(
                action_type=ActionType.CALL_TOOLS_SEQUENCE,
                tool_calls=[],  # Empty - should fail
            )

    def test_generate_response_requires_template(self):
        """Test GENERATE_RESPONSE without template raises ValueError."""
        with pytest.raises(ValueError, match="requires response_template"):
            FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template=None,  # Missing - should fail
            )

    def test_generate_response_cannot_have_tools(self):
        """Test GENERATE_RESPONSE with tools raises ValueError."""
        with pytest.raises(ValueError, match="should not have tool_calls"):
            FSMAction(
                action_type=ActionType.GENERATE_RESPONSE,
                response_template="Test",
                tool_calls=[ToolCall(name="search_services", args={})],  # Should fail
            )

    def test_no_action_cannot_have_tools(self):
        """Test NO_ACTION with tools raises ValueError."""
        with pytest.raises(ValueError, match="should not have tool_calls"):
            FSMAction(
                action_type=ActionType.NO_ACTION,
                tool_calls=[ToolCall(name="search_services", args={})],  # Should fail
            )


class TestFSMActionSerialization:
    """Test FSMAction serialization (to_dict/from_dict)."""

    def test_to_dict_full(self):
        """Test serializing FSMAction with all fields."""
        action = FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(name="search_services", args={"query": "corte"}, required=True),
                ToolCall(name="find_next_available", args={"stylist_id": "uuid"}, required=False),
            ],
            response_template="Template text",
            template_vars={"key": "value"},
            allow_llm_creativity=False,
        )

        data = action.to_dict()

        assert data["action_type"] == "call_tools_sequence"
        assert len(data["tool_calls"]) == 2
        assert data["tool_calls"][0]["name"] == "search_services"
        assert data["tool_calls"][0]["args"] == {"query": "corte"}
        assert data["tool_calls"][0]["required"] is True
        assert data["tool_calls"][1]["required"] is False
        assert data["response_template"] == "Template text"
        assert data["template_vars"] == {"key": "value"}
        assert data["allow_llm_creativity"] is False

    def test_to_dict_minimal(self):
        """Test serializing FSMAction with minimal fields."""
        action = FSMAction(action_type=ActionType.NO_ACTION)

        data = action.to_dict()

        assert data["action_type"] == "no_action"
        assert data["tool_calls"] == []
        assert data["response_template"] is None
        assert data["template_vars"] == {}
        assert data["allow_llm_creativity"] is True

    def test_from_dict_full(self):
        """Test deserializing FSMAction from dict."""
        data = {
            "action_type": "call_tools_sequence",
            "tool_calls": [
                {"name": "search_services", "args": {"query": "corte"}, "required": True},
                {"name": "find_next_available", "args": {"stylist_id": "uuid"}, "required": False},
            ],
            "response_template": "Template",
            "template_vars": {"key": "value"},
            "allow_llm_creativity": False,
        }

        action = FSMAction.from_dict(data)

        assert action.action_type == ActionType.CALL_TOOLS_SEQUENCE
        assert len(action.tool_calls) == 2
        assert action.tool_calls[0].name == "search_services"
        assert action.tool_calls[0].required is True
        assert action.tool_calls[1].required is False
        assert action.response_template == "Template"
        assert action.template_vars == {"key": "value"}
        assert action.allow_llm_creativity is False

    def test_from_dict_minimal(self):
        """Test deserializing FSMAction with minimal fields."""
        data = {"action_type": "no_action"}

        action = FSMAction.from_dict(data)

        assert action.action_type == ActionType.NO_ACTION
        assert action.tool_calls == []
        assert action.response_template is None
        assert action.template_vars == {}
        assert action.allow_llm_creativity is True  # Default

    def test_roundtrip_serialization(self):
        """Test FSMAction survives to_dict → from_dict roundtrip."""
        original = FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[ToolCall(name="search_services", args={"query": "test"})],
            response_template="Test {% for x in items %}{{ x }}{% endfor %}",
            template_vars={"items": [1, 2, 3]},
            allow_llm_creativity=True,
        )

        data = original.to_dict()
        restored = FSMAction.from_dict(data)

        assert restored.action_type == original.action_type
        assert len(restored.tool_calls) == len(original.tool_calls)
        assert restored.tool_calls[0].name == original.tool_calls[0].name
        assert restored.tool_calls[0].args == original.tool_calls[0].args
        assert restored.response_template == original.response_template
        assert restored.template_vars == original.template_vars
        assert restored.allow_llm_creativity == original.allow_llm_creativity
