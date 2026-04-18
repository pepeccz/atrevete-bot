"""Tests for agent.core.capability — Capability ABC (R1, R2).

Design note: the Capability ABC has 7 abstract properties (not 6 as in the spec).
The 7th is `name: str`, added in design phase (R-T1) to enable stable telemetry
and registry lookup. Tests here verify all 7 properties.
"""
from collections.abc import Callable
from pathlib import Path

import pytest

from agent.core.capability import Capability

# ---------------------------------------------------------------------------
# Helpers — a fully-compliant concrete implementation
# ---------------------------------------------------------------------------


def _make_full_capability(**overrides):
    """Return a concrete Capability subclass with all 7 properties implemented.

    Pass keyword arguments to override individual property return values.
    """
    defaults = {
        "name": "test_capability",
        "state_slice": dict,
        "tools": [],
        "prompt_overlay": Path("/tmp/overlay.md"),
        "pre_loop_resolvers": [],
        "completion_predicate": lambda s: False,
        "exit_edges": ["GENERAL"],
    }
    values = {**defaults, **overrides}

    class _TestCapability(Capability):
        @property
        def name(self) -> str:
            return values["name"]

        @property
        def state_slice(self) -> type:
            return values["state_slice"]

        @property
        def tools(self) -> list:
            return values["tools"]

        @property
        def prompt_overlay(self) -> Path:
            return values["prompt_overlay"]

        @property
        def pre_loop_resolvers(self) -> list[str]:
            return values["pre_loop_resolvers"]

        @property
        def completion_predicate(self) -> Callable:
            return values["completion_predicate"]

        @property
        def exit_edges(self) -> list[str]:
            return values["exit_edges"]

    return _TestCapability


# ---------------------------------------------------------------------------
# R1 — Capability ABC: concrete subclass with all fields instantiates
# ---------------------------------------------------------------------------


def test_concrete_subclass_with_all_fields_instantiates():
    """R1: A subclass implementing all 7 abstract properties must instantiate without error."""
    cls = _make_full_capability()
    instance = cls()
    assert isinstance(instance, Capability)


def test_all_properties_accessible_on_instance():
    """R1: All 7 abstract properties must be accessible on a concrete instance."""
    cls = _make_full_capability()
    instance = cls()

    assert instance.name == "test_capability"
    assert instance.state_slice is dict
    assert instance.tools == []
    assert instance.prompt_overlay == Path("/tmp/overlay.md")
    assert instance.pre_loop_resolvers == []
    assert callable(instance.completion_predicate)
    assert instance.exit_edges == ["GENERAL"]


def test_direct_instantiation_of_capability_raises():
    """Capability is abstract — direct instantiation must raise TypeError."""
    with pytest.raises(TypeError):
        Capability()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# R2 — Capability ABC: missing any field raises TypeError at instantiation
# ---------------------------------------------------------------------------

_ABSTRACT_FIELDS = [
    "name",
    "state_slice",
    "tools",
    "prompt_overlay",
    "pre_loop_resolvers",
    "completion_predicate",
    "exit_edges",
]


@pytest.mark.parametrize("omit_field", _ABSTRACT_FIELDS)
def test_missing_field_raises_typeerror(omit_field: str):
    """R2: Omitting any single abstract property must raise TypeError on instantiation.

    Parametrised over all 7 abstract properties — 7 test cases.
    """

    # Build a mapping of all field implementations EXCEPT the one we're omitting.
    field_methods = {
        "name": ("name", lambda self: "test"),
        "state_slice": ("state_slice", lambda self: dict),
        "tools": ("tools", lambda self: []),
        "prompt_overlay": ("prompt_overlay", lambda self: Path("/tmp/x.md")),
        "pre_loop_resolvers": ("pre_loop_resolvers", lambda self: []),
        "completion_predicate": ("completion_predicate", lambda self: (lambda s: False)),
        "exit_edges": ("exit_edges", lambda self: ["GENERAL"]),
    }

    # Build namespace with all properties except the omitted one
    namespace = {}
    for field, (attr_name, method) in field_methods.items():
        if field == omit_field:
            continue  # deliberately omit this one
        namespace[attr_name] = property(method)

    # Dynamically construct the subclass
    IncompleteCapability = type(f"_Missing_{omit_field}", (Capability,), namespace)

    with pytest.raises(TypeError):
        IncompleteCapability()
