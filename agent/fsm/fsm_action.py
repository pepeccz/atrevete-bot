"""
FSMAction - Prescriptive action specification for v5.0 architecture.

This module defines the FSMAction system that allows the FSM to prescribe
EXACTLY what actions the conversational agent should take, removing tool
decision-making power from the LLM.

Key components:
- FSMAction: Prescriptive action specification (tools + response template)
- ToolCall: Single tool call specification with args
- ActionType: Types of actions FSM can prescribe

Usage:
    action = FSMAction(
        action_type=ActionType.CALL_TOOLS_SEQUENCE,
        tool_calls=[ToolCall(name="search_services", args={"query": "todos"})],
        response_template="Services: {% for s in services %}{{ s.name }}{% endfor %}",
        allow_llm_creativity=True
    )
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ActionType(str, Enum):
    """Types of actions FSM can prescribe."""

    CALL_TOOLS_SEQUENCE = "call_tools_sequence"
    """Execute multiple tools in sequence, then format response with results."""

    GENERATE_RESPONSE = "generate_response"
    """Generate response without tool calls (e.g., ask clarifying question)."""

    NO_ACTION = "no_action"
    """No action needed (fallback for unexpected states)."""


@dataclass
class ToolCall:
    """
    Specification for a single tool call.

    The FSM prescribes exact tool name and arguments based on collected_data.
    No LLM decision-making involved.

    Attributes:
        name: Tool name (e.g., "search_services", "find_next_available")
        args: Tool arguments dict (built from FSM collected_data)
        required: If True, fail fast on error; if False, log and continue

    Example:
        >>> ToolCall(
        ...     name="find_next_available",
        ...     args={"stylist_id": "uuid-123", "duration_minutes": 60},
        ...     required=True
        ... )
    """

    name: str
    args: dict[str, Any]
    required: bool = True


@dataclass
class FSMAction:
    """
    Prescriptive action specification from FSM.

    This dataclass tells the conversational agent EXACTLY what to do,
    removing tool decision power from the LLM. The FSM controls:
    - Which tools to call (if any)
    - Tool arguments (from collected_data)
    - Response template structure
    - Whether to allow LLM creativity in formatting

    The LLM is relegated to:
    - Intent extraction (NLU)
    - Response formatting (natural language generation)

    Attributes:
        action_type: Type of action to perform
        tool_calls: List of tools to execute (if action_type=CALL_TOOLS_SEQUENCE)
        response_template: Jinja2 template for response structure
        template_vars: Variables to inject into template (beyond tool results)
        allow_llm_creativity: If True, LLM can rephrase template naturally;
                              if False, use template exactly (strict mode)

    Example (prescriptive tool call + creative formatting):
        >>> FSMAction(
        ...     action_type=ActionType.CALL_TOOLS_SEQUENCE,
        ...     tool_calls=[
        ...         ToolCall(
        ...             name="find_next_available",
        ...             args={"stylist_id": "uuid", "duration_minutes": 60}
        ...         )
        ...     ],
        ...     response_template=(
        ...         "Horarios disponibles:\\n"
        ...         "{% for slot in slots %}"
        ...         "{{ loop.index }}. {{ slot.date }} a las {{ slot.time }}\\n"
        ...         "{% endfor %}"
        ...         "¿Cuál prefieres?"
        ...     ),
        ...     allow_llm_creativity=True  # LLM can add personality
        ... )

    Example (generate response without tools):
        >>> FSMAction(
        ...     action_type=ActionType.GENERATE_RESPONSE,
        ...     response_template="¿Para qué día te gustaría la cita?",
        ...     allow_llm_creativity=True
        ... )
    """

    action_type: ActionType
    tool_calls: list[ToolCall] = field(default_factory=list)
    response_template: Optional[str] = None
    template_vars: dict[str, Any] = field(default_factory=dict)
    allow_llm_creativity: bool = True

    def __post_init__(self):
        """Validate FSMAction consistency."""
        # Validate CALL_TOOLS_SEQUENCE has tools
        if self.action_type == ActionType.CALL_TOOLS_SEQUENCE and not self.tool_calls:
            raise ValueError(
                f"action_type={ActionType.CALL_TOOLS_SEQUENCE} requires non-empty tool_calls"
            )

        # Validate GENERATE_RESPONSE has template
        if self.action_type == ActionType.GENERATE_RESPONSE and not self.response_template:
            raise ValueError(
                f"action_type={ActionType.GENERATE_RESPONSE} requires response_template"
            )

        # Validate tool_calls only for CALL_TOOLS_SEQUENCE
        if self.action_type != ActionType.CALL_TOOLS_SEQUENCE and self.tool_calls:
            raise ValueError(
                f"action_type={self.action_type} should not have tool_calls "
                f"(only {ActionType.CALL_TOOLS_SEQUENCE} allows tools)"
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize FSMAction to dict for logging/debugging.

        Returns:
            Dict representation with all fields
        """
        return {
            "action_type": self.action_type.value,
            "tool_calls": [
                {"name": tc.name, "args": tc.args, "required": tc.required}
                for tc in self.tool_calls
            ],
            "response_template": self.response_template,
            "template_vars": self.template_vars,
            "allow_llm_creativity": self.allow_llm_creativity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FSMAction":
        """
        Deserialize FSMAction from dict.

        Args:
            data: Dict with FSMAction fields

        Returns:
            FSMAction instance
        """
        return cls(
            action_type=ActionType(data["action_type"]),
            tool_calls=[
                ToolCall(name=tc["name"], args=tc["args"], required=tc.get("required", True))
                for tc in data.get("tool_calls", [])
            ],
            response_template=data.get("response_template"),
            template_vars=data.get("template_vars", {}),
            allow_llm_creativity=data.get("allow_llm_creativity", True),
        )
