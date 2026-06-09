"""Tests for loader.py — slot_contract.md must not be in unconditional load (AS7, F5).

F5: slot_contract.md is a developer reference. It must NOT be included in the
    assembled system prompt (token waste, no LLM-facing value at runtime).
    The file must remain on disk.
"""

from __future__ import annotations

from pathlib import Path


# Sentinel phrase unique to slot_contract.md (first meaningful line)
_SLOT_CONTRACT_SENTINEL = "Contexto dinámico (inyectado por turno)"

_SLOT_CONTRACT_PATH = (
    Path(__file__).parent.parent.parent
    / "agent" / "prompts" / "shared" / "slot_contract.md"
)


class TestLoaderExcludesSlotContract:
    """AS7 — slot_contract.md sentinel absent from assembled system prompt."""

    def test_slot_contract_file_still_exists(self) -> None:
        """slot_contract.md must remain on disk (developer reference)."""
        assert _SLOT_CONTRACT_PATH.exists(), (
            "slot_contract.md was deleted — it must remain as a developer reference"
        )

    def test_slot_contract_sentinel_absent_from_prompt(self) -> None:
        """load_system_prompt() must not include slot_contract.md content."""
        import functools

        from agent.prompts import loader

        # Clear lru_cache to avoid stale result from a previous test run
        loader.load_system_prompt.cache_clear()

        prompt = loader.load_system_prompt()

        assert _SLOT_CONTRACT_SENTINEL not in prompt, (
            f"slot_contract.md sentinel found in assembled system prompt. "
            f"Remove _read('slot_contract.md') from loader.py load list."
        )

        # Cleanup cache so other tests are not affected
        loader.load_system_prompt.cache_clear()
