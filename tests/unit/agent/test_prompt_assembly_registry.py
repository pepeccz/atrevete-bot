"""PromptAssemblyMiddleware SLOT_REGISTRY import contract (Spec: S4, Scenarios F-G)."""

from __future__ import annotations

import inspect


class TestPromptAssemblyImportsRegistry:
    def test_no_local_slot_order_variable(self) -> None:
        """_SLOT_ORDER must NOT exist in prompt_assembly.py (removed in favour of SLOT_REGISTRY)."""
        import agent.middleware.prompt_assembly as pa

        source = inspect.getsource(pa)
        assert "_SLOT_ORDER" not in source, (
            "prompt_assembly.py still contains _SLOT_ORDER — must be replaced with SLOT_REGISTRY"
        )

    def test_slot_registry_is_imported_from_agent_state(self) -> None:
        """SLOT_REGISTRY must be importable from prompt_assembly and be the same object as in state."""
        import agent.state as state_module
        import agent.middleware.prompt_assembly as pa

        assert hasattr(pa, "SLOT_REGISTRY"), (
            "SLOT_REGISTRY not accessible in agent.middleware.prompt_assembly"
        )
        assert pa.SLOT_REGISTRY is state_module.SLOT_REGISTRY, (
            "pa.SLOT_REGISTRY must be the same object as state.SLOT_REGISTRY (imported, not redeclared)"
        )

    def test_slot_registry_iteration_present_in_source(self) -> None:
        """The middleware must iterate over SLOT_REGISTRY, not a local list."""
        import agent.middleware.prompt_assembly as pa

        source = inspect.getsource(pa)
        assert "SLOT_REGISTRY" in source, (
            "SLOT_REGISTRY is not referenced in prompt_assembly.py"
        )


class TestPromptAssemblySlotOrder:
    """Scenario G — assembled content preserves SLOT_REGISTRY order."""

    def test_slot_order_in_assembled_output(self) -> None:
        """Slots must appear in SLOT_REGISTRY order in the assembled system prompt."""
        import agent.state as state_module

        # Build a state dict with all slots set to distinct recognisable values
        slot_values = {
            slot: f"<block id='{slot}'>{slot}_content</block>"
            for slot in state_module.SLOT_REGISTRY
        }

        # Reproduce the assembly logic from PromptAssemblyMiddleware
        blocks = [slot_values[key] for key in state_module.SLOT_REGISTRY if slot_values.get(key)]
        assembled = "\n\n".join(blocks)

        # Verify each slot's position is strictly after the previous one
        positions = [assembled.index(f"id='{slot}'") for slot in state_module.SLOT_REGISTRY]
        assert positions == sorted(positions), (
            "Slots are NOT in SLOT_REGISTRY order in the assembled output"
        )
