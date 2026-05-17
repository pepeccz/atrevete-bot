"""State schema contract tests — Scenarios A-E (Spec: S1–S5).

Tests:
  T1 — SLOT_REGISTRY is a tuple of exactly 6 values in the correct order
  T2 — All 6 _slot_* fields in AgentState are typed NotRequired[str]
  T3 — conversation_summary is typed NotRequired[str | None]
  T4 — _validate_registry() raises RuntimeError on drift (extra TypedDict field)
"""

from __future__ import annotations

import typing
from typing import NotRequired, TypedDict

import pytest

# ---------------------------------------------------------------------------
# T1 — SLOT_REGISTRY tuple contract (Scenario A)
# ---------------------------------------------------------------------------

class TestSlotRegistry:
    def test_slot_registry_is_tuple(self) -> None:
        """SLOT_REGISTRY must be a tuple, not a list or set."""
        import agent.state as state

        assert isinstance(state.SLOT_REGISTRY, tuple)

    def test_slot_registry_has_six_entries(self) -> None:
        """SLOT_REGISTRY must contain exactly 6 entries."""
        import agent.state as state

        assert len(state.SLOT_REGISTRY) == 6

    def test_slot_registry_exact_values_and_order(self) -> None:
        """SLOT_REGISTRY must match the canonical order defined in the spec."""
        import agent.state as state

        expected = (
            "_slot_today",
            "_slot_customer",
            "_slot_upcoming_appointments",
            "_slot_business_hours",
            "_slot_availability",
            "_slot_catalog",
        )
        assert state.SLOT_REGISTRY == expected


# ---------------------------------------------------------------------------
# T2 — AgentState _slot_* fields typed NotRequired[str] (Scenario B)
# ---------------------------------------------------------------------------

EXPECTED_SLOT_KEYS = (
    "_slot_today",
    "_slot_customer",
    "_slot_upcoming_appointments",
    "_slot_business_hours",
    "_slot_availability",
    "_slot_catalog",
)


class TestAgentStateSlotFields:
    def test_all_slot_fields_exist_in_agent_state(self) -> None:
        """All 6 _slot_* keys must be declared in AgentState."""
        import agent.state as state

        hints = typing.get_type_hints(state.AgentState, include_extras=True)
        for key in EXPECTED_SLOT_KEYS:
            assert key in hints, f"AgentState missing field: {key}"

    def test_slot_fields_typed_not_required_str(self) -> None:
        """Each _slot_* field must be typed NotRequired[str]."""
        import agent.state as state

        hints = typing.get_type_hints(state.AgentState, include_extras=True)
        for key in EXPECTED_SLOT_KEYS:
            assert hints[key] == NotRequired[str], (
                f"AgentState.{key} expected NotRequired[str], got {hints[key]}"
            )

    def test_no_extra_slot_fields_in_agent_state(self) -> None:
        """AgentState must NOT have _slot_* keys beyond the registry (no orphans)."""
        import agent.state as state

        hints = typing.get_type_hints(state.AgentState, include_extras=True)
        declared_slots = {k for k in hints if k.startswith("_slot_")}
        expected_slots = set(EXPECTED_SLOT_KEYS)
        assert declared_slots == expected_slots, (
            f"Extra/missing _slot_* fields: declared={declared_slots}, expected={expected_slots}"
        )


# ---------------------------------------------------------------------------
# T3 — conversation_summary is NotRequired[str | None] (Scenario C)
# ---------------------------------------------------------------------------

class TestConversationSummaryType:
    def test_conversation_summary_is_not_required_str_or_none(self) -> None:
        """conversation_summary must be NotRequired[str | None]."""
        import agent.state as state

        hints = typing.get_type_hints(state.AgentState, include_extras=True)
        assert hints["conversation_summary"] == NotRequired[str | None], (
            f"Expected NotRequired[str | None], got {hints['conversation_summary']}"
        )


# ---------------------------------------------------------------------------
# T4 — _validate_registry() raises RuntimeError on drift (Scenarios D + E)
# ---------------------------------------------------------------------------

class TestValidateRegistryDrift:
    """Tests for the boot-time drift guard."""

    def _run_validator(
        self,
        registry: tuple[str, ...],
        typeddict_class: type,
    ) -> None:
        """Re-implement the _validate_registry logic locally so we can inject
        arbitrary registries and TypedDicts without monkeypatching."""
        declared = {
            k
            for k in typing.get_type_hints(typeddict_class, include_extras=True)
            if k.startswith("_slot_")
        }
        registered = set(registry)
        if declared != registered:
            only_declared = declared - registered
            only_registered = registered - declared
            raise RuntimeError(
                f"SLOT_REGISTRY drift: declared={only_declared}, registered={only_registered}"
            )

    def test_drift_detected_when_typeddict_has_extra_slot_field(self) -> None:
        """Extra _slot_* field in TypedDict not in SLOT_REGISTRY → RuntimeError."""

        class _FakeState(TypedDict):
            _slot_today: NotRequired[str]
            _slot_fake: NotRequired[str]  # extra field not in registry

        reduced_registry: tuple[str, ...] = ("_slot_today",)

        with pytest.raises(RuntimeError, match="SLOT_REGISTRY drift"):
            self._run_validator(reduced_registry, _FakeState)

    def test_drift_detected_when_registry_has_extra_entry(self) -> None:
        """Extra entry in SLOT_REGISTRY not declared in TypedDict → RuntimeError."""

        class _FakeState(TypedDict):
            _slot_today: NotRequired[str]

        extended_registry: tuple[str, ...] = ("_slot_today", "_slot_missing")

        with pytest.raises(RuntimeError, match="SLOT_REGISTRY drift"):
            self._run_validator(extended_registry, _FakeState)

    def test_no_drift_when_registry_matches_typeddict(self) -> None:
        """No error when registry and TypedDict are in sync."""

        class _SyncState(TypedDict):
            _slot_today: NotRequired[str]
            _slot_customer: NotRequired[str]

        registry: tuple[str, ...] = ("_slot_today", "_slot_customer")

        # Must not raise
        self._run_validator(registry, _SyncState)

    def test_actual_validate_registry_raises_on_injected_drift(self) -> None:
        """Call agent.state._validate_registry() with a patched SLOT_REGISTRY to force drift."""
        import agent.state as state_module

        original = state_module.SLOT_REGISTRY
        try:
            # Remove one entry from registry to create drift
            state_module.SLOT_REGISTRY = original[1:]  # type: ignore[assignment]
            with pytest.raises(RuntimeError, match="SLOT_REGISTRY drift"):
                state_module._validate_registry()
        finally:
            state_module.SLOT_REGISTRY = original  # type: ignore[assignment]
