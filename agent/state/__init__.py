"""
Agent State module — v6.0 mode-based architecture.

Exports the core state types, reducers, and factory functions used by
the LangGraph conversation graph and all agent nodes.
"""

from agent.state.schemas import (
    ConversationMode,
    ConversationState,
    append_unique_list,
    create_initial_state,
    merge_dicts,
    preserve_if_none,
    transition_mode,
)

__all__ = [
    # Main state type
    "ConversationState",
    # Mode type alias
    "ConversationMode",
    # Factory function
    "create_initial_state",
    # Mode transition helper
    "transition_mode",
    # Reducer functions (exported for testing and custom reducers)
    "preserve_if_none",
    "merge_dicts",
    "append_unique_list",
]
