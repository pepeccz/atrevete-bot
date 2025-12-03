"""
Tests for import structure and module exports.

This module validates that all public exports are correctly defined
and accessible from their respective modules. Ensures v5.0 architecture
classes are properly exported.

Coverage:
- agent.fsm module exports (including v5.0 additions)
- agent.routing module exports
- agent.state module exports
- No circular import issues
"""

import pytest


class TestFSMModuleExports:
    """Test agent.fsm module exports."""

    def test_fsm_exports_booking_fsm(self):
        """Verify BookingFSM is exported from fsm module."""
        from agent.fsm import BookingFSM
        assert BookingFSM is not None

    def test_fsm_exports_booking_state(self):
        """Verify BookingState enum is exported."""
        from agent.fsm import BookingState
        assert BookingState is not None
        # Verify it's an enum
        assert hasattr(BookingState, "IDLE")
        assert hasattr(BookingState, "SERVICE_SELECTION")

    def test_fsm_exports_intent_models(self):
        """Verify Intent and IntentType are exported."""
        from agent.fsm import Intent, IntentType
        assert Intent is not None
        assert IntentType is not None

    def test_fsm_exports_fsm_result(self):
        """Verify FSMResult is exported."""
        from agent.fsm import FSMResult
        assert FSMResult is not None

    def test_fsm_exports_collected_data(self):
        """Verify CollectedData TypedDict is exported."""
        from agent.fsm import CollectedData
        assert CollectedData is not None

    def test_fsm_exports_v5_action_type(self):
        """Verify ActionType enum is exported (v5.0 addition)."""
        from agent.fsm import ActionType
        assert ActionType is not None
        # Verify it has expected enum members
        assert hasattr(ActionType, "CALL_TOOLS_SEQUENCE")
        assert hasattr(ActionType, "RESPOND_ONLY")

    def test_fsm_exports_v5_fsm_action(self):
        """Verify FSMAction dataclass is exported (v5.0 addition)."""
        from agent.fsm import FSMAction
        assert FSMAction is not None
        # Verify it's a dataclass
        assert hasattr(FSMAction, "__dataclass_fields__")

    def test_fsm_exports_v5_tool_call(self):
        """Verify ToolCall dataclass is exported (v5.0 addition)."""
        from agent.fsm import ToolCall
        assert ToolCall is not None
        # Verify it's a dataclass
        assert hasattr(ToolCall, "__dataclass_fields__")

    def test_fsm_exports_extract_intent(self):
        """Verify extract_intent function is exported."""
        from agent.fsm import extract_intent
        assert extract_intent is not None
        assert callable(extract_intent)

    def test_fsm_all_exports_defined(self):
        """Verify __all__ contains all expected exports."""
        from agent import fsm

        expected_exports = {
            "ActionType",
            "BookingFSM",
            "BookingState",
            "CollectedData",
            "FSMAction",
            "FSMResult",
            "Intent",
            "IntentType",
            "ResponseGuidance",
            "SlotData",
            "ToolCall",
            "extract_intent",
        }

        actual_exports = set(fsm.__all__)
        assert actual_exports == expected_exports, (
            f"Missing exports: {expected_exports - actual_exports}, "
            f"Extra exports: {actual_exports - expected_exports}"
        )


class TestRoutingModuleExports:
    """Test agent.routing module exports."""

    def test_routing_exports_intent_router(self):
        """Verify IntentRouter is exported from routing module."""
        from agent.routing import IntentRouter
        assert IntentRouter is not None

    def test_routing_exports_booking_handler(self):
        """Verify BookingHandler is exported."""
        from agent.routing import BookingHandler
        assert BookingHandler is not None

    def test_routing_exports_non_booking_handler(self):
        """Verify NonBookingHandler is exported."""
        from agent.routing import NonBookingHandler
        assert NonBookingHandler is not None

    def test_routing_exports_response_formatter(self):
        """Verify ResponseFormatter is exported."""
        from agent.routing import ResponseFormatter
        assert ResponseFormatter is not None

    def test_routing_all_exports_defined(self):
        """Verify __all__ contains all expected exports."""
        from agent import routing

        expected_exports = {
            "IntentRouter",
            "BookingHandler",
            "NonBookingHandler",
            "ResponseFormatter",
        }

        actual_exports = set(routing.__all__)
        assert actual_exports == expected_exports, (
            f"Missing exports: {expected_exports - actual_exports}, "
            f"Extra exports: {actual_exports - expected_exports}"
        )


class TestStateModuleExports:
    """Test agent.state module exports."""

    def test_state_exports_conversation_state(self):
        """Verify ConversationState TypedDict is exported."""
        from agent.state.schemas import ConversationState
        assert ConversationState is not None

    def test_state_exports_add_message_helper(self):
        """Verify add_message helper is exported."""
        from agent.state.helpers import add_message
        assert add_message is not None
        assert callable(add_message)


class TestCircularImports:
    """Test for circular import issues."""

    def test_no_circular_imports_fsm_routing(self):
        """Verify no circular imports between fsm and routing."""
        # This should not raise ImportError
        from agent.fsm import BookingFSM
        from agent.routing import IntentRouter

        assert BookingFSM is not None
        assert IntentRouter is not None

    def test_no_circular_imports_routing_nodes(self):
        """Verify no circular imports between routing and nodes."""
        from agent.routing import IntentRouter
        from agent.nodes.conversational_agent import conversational_agent

        assert IntentRouter is not None
        assert conversational_agent is not None

    def test_import_order_independence(self):
        """Verify imports work in any order."""
        # Import in reverse alphabetical order
        from agent.state.schemas import ConversationState
        from agent.routing import BookingHandler
        from agent.fsm import FSMAction

        assert ConversationState is not None
        assert BookingHandler is not None
        assert FSMAction is not None


class TestCrossModuleImports:
    """Test imports across module boundaries."""

    def test_booking_handler_can_import_fsm_models(self):
        """Verify BookingHandler can import from fsm module."""
        from agent.routing.booking_handler import BookingHandler

        # BookingHandler should use these types
        from agent.fsm import FSMAction, ActionType, ToolCall

        assert BookingHandler is not None
        assert FSMAction is not None
        assert ActionType is not None
        assert ToolCall is not None

    def test_intent_router_can_import_handlers(self):
        """Verify IntentRouter can import both handlers."""
        from agent.routing.intent_router import IntentRouter

        # IntentRouter uses these handlers dynamically
        from agent.routing.booking_handler import BookingHandler
        from agent.routing.non_booking_handler import NonBookingHandler

        assert IntentRouter is not None
        assert BookingHandler is not None
        assert NonBookingHandler is not None

    def test_conversational_agent_can_import_all_deps(self):
        """Verify conversational_agent can import all dependencies."""
        from agent.nodes.conversational_agent import conversational_agent

        # All dependencies should be importable
        from agent.fsm import BookingFSM, Intent, IntentType
        from agent.routing import IntentRouter
        from agent.state.schemas import ConversationState

        assert conversational_agent is not None
        assert BookingFSM is not None
        assert Intent is not None
        assert IntentType is not None
        assert IntentRouter is not None
        assert ConversationState is not None


class TestV5ArchitectureImports:
    """Test v5.0 prescriptive architecture imports."""

    def test_v5_imports_from_fsm_action_module(self):
        """Verify v5.0 classes can be imported from fsm_action module."""
        from agent.fsm.fsm_action import ActionType, FSMAction, ToolCall

        assert ActionType is not None
        assert FSMAction is not None
        assert ToolCall is not None

    def test_v5_imports_from_fsm_module(self):
        """Verify v5.0 classes can be imported from fsm module (preferred)."""
        from agent.fsm import ActionType, FSMAction, ToolCall

        assert ActionType is not None
        assert FSMAction is not None
        assert ToolCall is not None

    def test_v5_classes_are_same_object(self):
        """Verify imports from different paths reference same objects."""
        from agent.fsm import FSMAction as FSMAction1
        from agent.fsm.fsm_action import FSMAction as FSMAction2

        # Should be the exact same class object
        assert FSMAction1 is FSMAction2

    def test_v5_action_type_enum_members(self):
        """Verify ActionType enum has all expected members."""
        from agent.fsm import ActionType

        # Check expected enum values exist
        assert hasattr(ActionType, "CALL_TOOLS_SEQUENCE")
        assert hasattr(ActionType, "RESPOND_ONLY")

        # Verify enum has exactly the members we expect (adjust as needed)
        expected_members = {"CALL_TOOLS_SEQUENCE", "RESPOND_ONLY"}
        actual_members = set(member.name for member in ActionType)
        assert actual_members == expected_members, (
            f"Unexpected ActionType members: {actual_members}"
        )

    def test_v5_fsm_action_dataclass_fields(self):
        """Verify FSMAction has expected dataclass fields."""
        from agent.fsm import FSMAction

        # Check dataclass fields
        fields = FSMAction.__dataclass_fields__
        expected_fields = {
            "action_type",
            "tool_calls",
            "response_template",
            "template_vars",
            "allow_llm_creativity",
        }

        actual_fields = set(fields.keys())
        assert actual_fields == expected_fields, (
            f"Missing fields: {expected_fields - actual_fields}, "
            f"Extra fields: {actual_fields - expected_fields}"
        )

    def test_v5_tool_call_dataclass_fields(self):
        """Verify ToolCall has expected dataclass fields."""
        from agent.fsm import ToolCall

        fields = ToolCall.__dataclass_fields__
        expected_fields = {"name", "args", "required"}

        actual_fields = set(fields.keys())
        assert actual_fields == expected_fields, (
            f"Missing fields: {expected_fields - actual_fields}, "
            f"Extra fields: {actual_fields - expected_fields}"
        )
