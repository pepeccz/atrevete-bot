"""Capability ABC — the 7-property contract every conversational capability MUST satisfy.

E1 introduces this contract; it has zero in-runtime callers in E1.
The first concrete implementation is BookingCapability in E2.

Design note (R-T1): this ABC declares 7 abstract properties. The spec (R1) specifies 6;
the 7th — `name: str` — was added in the design phase to enable stable telemetry identity
(P10) and resolver-registry lookup per capability. Without `name` in the ABC every
concrete capability would add it informally; forcing it through the ABC keeps the
registry contract strict.

See: docs/system/01-architecture-principles.md §P7, docs/system/07-migration-plan.md §E1.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from agent.state.schemas import ConversationState

# Type alias: state_slice accepts any TypedDict subclass (a class reference, NOT an instance).
StateSlice = type


class Capability(ABC):
    """Contract every conversational capability must implement.

    All 7 properties are abstract — omitting any one raises TypeError at instantiation.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used for telemetry and registry lookup (e.g. 'booking')."""
        ...

    @property
    @abstractmethod
    def state_slice(self) -> StateSlice:
        """Reference to the TypedDict subclass this capability may mutate (NOT an instance)."""
        ...

    @property
    @abstractmethod
    def tools(self) -> list[BaseTool]:
        """Tools available to this capability's LLM loop."""
        ...

    @property
    @abstractmethod
    def prompt_overlay(self) -> Path:
        """Path to the .md file providing mode-specific LLM instructions."""
        ...

    @property
    @abstractmethod
    def pre_loop_resolvers(self) -> list[str]:
        """Ordered resolver names to run deterministically before the LLM loop."""
        ...

    @property
    @abstractmethod
    def completion_predicate(self) -> Callable[[ConversationState], bool]:
        """Pure function returning True when this capability's flow is done."""
        ...

    @property
    @abstractmethod
    def exit_edges(self) -> list[str]:
        """Mode names this capability may transition to after completion."""
        ...
