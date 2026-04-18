"""
agent.core — E1 capability-contract scaffolding.

Reusable primitives for synthetic state delivery and future resolvers
(negation, digit selection, appointment management).

E1 additions:
  - Capability ABC — the 7-property contract every conversational capability must satisfy.
  - Resolver registry + P10 telemetry helper (resolvers.py).
  - ToolResponse Pydantic model + AST imperative-lint companion (tool_response.py).
  Zero in-runtime callers in E1; first concrete implementations are in E2.
"""

from agent.core.capability import Capability
from agent.core.resolvers import (
    Resolver,
    StatePatch,
    get,
    get_ordered,
    invoke_with_telemetry,
    register,
    registered_names,
    unregister,
)
from agent.core.status_line import build_status_line
from agent.core.state_delivery import (
    SYNTHETIC_TOOL_CALL_ID_PREFIX,
    build_synthetic_state_delivery,
    deliver_state_update,
)
from agent.core.tool_response import (
    FORBIDDEN_IMPERATIVES,
    ToolResponse,
    assert_no_imperative_errors,
)

__all__ = [
    # E1: Capability ABC
    "Capability",
    # E1: Resolver registry + telemetry
    "Resolver",
    "StatePatch",
    "get",
    "get_ordered",
    "invoke_with_telemetry",
    "register",
    "registered_names",
    "unregister",
    # E1: StatusLine pre-turn HumanMessage builder
    "build_status_line",
    # E1: ToolResponse Pydantic + AST linter
    "FORBIDDEN_IMPERATIVES",
    "ToolResponse",
    "assert_no_imperative_errors",
    # Pre-E1: synthetic state delivery
    "SYNTHETIC_TOOL_CALL_ID_PREFIX",
    "build_synthetic_state_delivery",
    "deliver_state_update",
]
