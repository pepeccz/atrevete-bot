"""T8.b — sentinel: middleware stack order in agent_factory.

R-IDs: R17
"""
from __future__ import annotations

from agent.middleware.appointment_context import AppointmentContextMiddleware
from agent.middleware.availability_context import AvailabilityContextMiddleware
from agent.middleware.customer_resolve import CustomerResolveMiddleware
from agent.middleware.disclosure import DisclosureMiddleware
from agent.middleware.dynamic_prompt import DynamicPromptMiddleware
from agent.middleware.prompt_assembly import PromptAssemblyMiddleware
from agent.middleware.summarize import SummarizeMiddleware
from agent.agent_factory import build_conversation_agent  # noqa: F401


EXPECTED_MIDDLEWARE_CLASSES = [
    DisclosureMiddleware,
    CustomerResolveMiddleware,
    AppointmentContextMiddleware,
    DynamicPromptMiddleware,
    AvailabilityContextMiddleware,  # injected after DynamicPrompt (ADR-1)
    PromptAssemblyMiddleware,
    SummarizeMiddleware,
]


def test_middleware_stack_order() -> None:
    """The middleware list in agent_factory must have exactly 7 entries in the expected order."""
    import agent.agent_factory as factory_module
    import inspect, ast, pathlib

    source = pathlib.Path(factory_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the middleware=[...] list in the build_conversation_agent function
    middleware_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "create_agent":
                for kw in node.keywords:
                    if kw.arg == "middleware" and isinstance(kw.value, ast.List):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                                middleware_names.append(elt.func.id)

    expected_names = [cls.__name__ for cls in EXPECTED_MIDDLEWARE_CLASSES]
    assert middleware_names == expected_names, (
        f"Middleware stack mismatch.\n"
        f"Expected: {expected_names}\n"
        f"Got:      {middleware_names}"
    )
