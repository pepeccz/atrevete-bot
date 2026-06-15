"""T8.b — sentinel: middleware stack order in agent_factory.

R-IDs: R17
"""

from __future__ import annotations

import ast
import pathlib

from agent.agent_factory import build_conversation_agent  # noqa: F401
from agent.middleware.appointment_context import AppointmentContextMiddleware
from agent.middleware.availability_context import AvailabilityContextMiddleware
from agent.middleware.customer_resolve import CustomerResolveMiddleware
from agent.middleware.disclosure import DisclosureMiddleware
from agent.middleware.dynamic_prompt import DynamicPromptMiddleware
from agent.middleware.prompt_assembly import PromptAssemblyMiddleware
from agent.middleware.response_groundedness import ResponseGroundednessMiddleware
from agent.middleware.summarize import SummarizeMiddleware

EXPECTED_MIDDLEWARE_CLASSES = [
    DisclosureMiddleware,
    CustomerResolveMiddleware,
    AppointmentContextMiddleware,
    DynamicPromptMiddleware,
    AvailabilityContextMiddleware,  # injected after DynamicPrompt (ADR-1)
    PromptAssemblyMiddleware,
    SummarizeMiddleware,
    ResponseGroundednessMiddleware,  # J5: post-hoc groundedness scan (LOG-ONLY)
]


def _extract_list_assignment(tree: ast.AST, var_name: str) -> list[str]:
    """Find `var_name = [Call(), Call(), ...]` and return the call names in order."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    return [
                        elt.func.id
                        for elt in node.value.elts
                        if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name)
                    ]
    return []


def test_middleware_stack_order() -> None:
    """The base middleware list in agent_factory must contain exactly the 8 expected
    entries in the documented order. LLMTraceMiddleware is opt-in via flag and tracked
    separately in test_agent_factory_trace.py (ADR-3).

    NOTE: ResponseGroundednessMiddleware (J5) was added as entry 8 — log-only post-hoc
    groundedness scan. This updates the expected count from 7 to 8.
    """
    import agent.agent_factory as factory_module

    source = pathlib.Path(factory_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    middleware_names = _extract_list_assignment(tree, "base_middleware")

    expected_names = [cls.__name__ for cls in EXPECTED_MIDDLEWARE_CLASSES]
    assert middleware_names == expected_names, (
        f"Middleware stack mismatch.\n"
        f"Expected: {expected_names}\n"
        f"Got:      {middleware_names}"
    )
