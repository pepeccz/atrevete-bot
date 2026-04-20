"""Parity guardrail: every AgentMiddleware subclass in agent/middleware/ that overrides
either variant of a hook pair (tool-call or model-call) MUST override both variants.

LangChain 1.2.x composes BOTH wrap_tool_call and awrap_tool_call into the async dispatch
chain whenever EITHER is overridden. The unoverridden base raises NotImplementedError at
runtime under ainvoke. This test catches the defect at collection time.

Opt-out: set ``_allow_single_variant: ClassVar[bool] = True`` on the class AND include a
non-empty class docstring explaining why single-variant is acceptable (REQ-6).
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from langchain.agents.middleware import AgentMiddleware

# ---------------------------------------------------------------------------
# Eagerly import all submodules so __subclasses__() is populated at collection
# ---------------------------------------------------------------------------
import agent.middleware as _middleware_pkg

for _mod_info in pkgutil.iter_modules(_middleware_pkg.__path__):
    importlib.import_module(f"agent.middleware.{_mod_info.name}")

# ---------------------------------------------------------------------------
# Hook pairs subject to parity enforcement (REQ-1, REQ-2)
# ---------------------------------------------------------------------------

_HOOK_PAIRS = [
    ("wrap_tool_call", "awrap_tool_call"),
    ("wrap_model_call", "awrap_model_call"),
]


def _overrides(cls: type, name: str) -> bool:
    """Return True iff *cls* defines *name* in its own __dict__ (not inherited)."""
    return name in cls.__dict__


def _collect_all_subclasses(base: type) -> list[type]:
    """Recursively collect all subclasses of *base*."""
    result: list[type] = []
    for sub in base.__subclasses__():
        result.append(sub)
        result.extend(_collect_all_subclasses(sub))
    return result


def _collect_cases() -> list[tuple[type, str, str]]:
    """Yield (cls, sync_name, async_name) for each class that overrides either hook."""
    cases: list[tuple[type, str, str]] = []
    for cls in _collect_all_subclasses(AgentMiddleware):
        for sync_name, async_name in _HOOK_PAIRS:
            if _overrides(cls, sync_name) or _overrides(cls, async_name):
                cases.append((cls, sync_name, async_name))
    return cases


# ---------------------------------------------------------------------------
# Parametrized parity test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,sync_name,async_name",
    _collect_cases(),
    ids=[f"{c.__name__}::{s}" for c, s, _ in _collect_cases()],
)
def test_middleware_hook_parity(cls: type, sync_name: str, async_name: str) -> None:
    """Both variants of a hook pair must be overridden, or the class must opt out.

    Opt-out: set ``_allow_single_variant: ClassVar[bool] = True`` AND provide
    a non-empty class docstring explaining why single-variant is acceptable.
    """
    if getattr(cls, "_allow_single_variant", False):
        # REQ-6: opt-out requires a justification docstring
        assert cls.__doc__ and cls.__doc__.strip(), (
            f"{cls.__name__} sets _allow_single_variant=True but has no docstring. "
            "Add a docstring explaining why single-variant is acceptable."
        )
        return

    has_sync = _overrides(cls, sync_name)
    has_async = _overrides(cls, async_name)
    assert has_sync and has_async, (
        f"{cls.__name__} overrides {sync_name!r} XOR {async_name!r}. "
        "Both variants must be implemented, or set "
        "_allow_single_variant: ClassVar[bool] = True with a docstring explaining why."
    )
