"""
Failure injection tests for the prompt-consistency invariant guard.

Verifies that `check_first_availability_position()` correctly detects
synthetic divergent text fed directly to the pure checker (no file I/O, no
DB) — mirrors `tests/integration/test_service_catalog_integrity_failures.py`.

These tests must PASS immediately (the checker exists and works); they are
NOT gated by Stream B's glossary.md reconciliation (that's
test_prompt_consistency_invariants.py, the green guard, which is expected
to fail until B3 — see xfail marker there).
"""

from __future__ import annotations

from tests.integration._prompt_consistency_invariants import (
    CHECKERS,
    check_first_availability_position,
)

# ---------------------------------------------------------------------------
# Synthetic text fixtures
# ---------------------------------------------------------------------------

_R24_RECONCILED_FIRST = (
    "[R24] **Lista numerada de estilistas**: cuando `next_step=stylist_required`, "
    "presenta: `0)` `payload.first_available_label`, `1)`, `2)`… nombres de "
    "`payload.stylists` en orden."
)

_R24_MISSING_POSITION_ZERO = (
    "[R24] **Lista numerada de estilistas**: cuando `next_step=stylist_required`, "
    "presenta los nombres de `payload.stylists` en orden, seguido de "
    "`payload.first_available_label` al final."
)

_GLOSSARY_SAYS_LAST = (
    'La opción "primera con disponibilidad" va SIEMPRE al final de la lista, '
    "después de todos los nombres reales de estilistas."
)

_GLOSSARY_RECONCILED_FIRST = (
    'La opción "primera con disponibilidad" va SIEMPRE en la posición 0, ANTES '
    "de los nombres reales de estilistas (coherente con R24)."
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_p1_detects_r24_missing_position_zero() -> None:
    """P1: checker flags R24 text that doesn't place first_available_label at position 0."""
    violations = check_first_availability_position(
        _R24_MISSING_POSITION_ZERO, _GLOSSARY_RECONCILED_FIRST
    )
    assert violations, "Expected at least one P1 violation but got none"
    locations = [v.location for v in violations]
    assert "critical_rules.md R24" in locations, f"Got: {locations}"


def test_p1_detects_glossary_still_says_last() -> None:
    """P1: checker flags glossary.md text still stating the option goes last
    (the historical divergence this invariant guards against)."""
    violations = check_first_availability_position(_R24_RECONCILED_FIRST, _GLOSSARY_SAYS_LAST)
    assert violations, "Expected at least one P1 violation but got none"
    locations = [v.location for v in violations]
    assert "glossary.md" in locations, f"Got: {locations}"


def test_p1_detects_both_files_diverging() -> None:
    """P1: when R24 lacks position-0 AND glossary says 'last', both are flagged."""
    violations = check_first_availability_position(_R24_MISSING_POSITION_ZERO, _GLOSSARY_SAYS_LAST)
    assert len(violations) == 2, f"Expected 2 violations, got: {violations}"


def test_p1_reconciled_texts_produce_zero_violations() -> None:
    """P1 (triangulation): once both files agree on option-0-first, zero violations.

    Proves the checker does not false-positive on the reconciled target state
    that Stream B (B3) will produce.
    """
    violations = check_first_availability_position(
        _R24_RECONCILED_FIRST, _GLOSSARY_RECONCILED_FIRST
    )
    assert violations == [], f"Expected no violations, got: {violations}"


def test_p1_registered_in_checkers() -> None:
    """P1 must be registered in the CHECKERS registry (extensibility contract)."""
    assert "P1" in CHECKERS
    assert CHECKERS["P1"] is check_first_availability_position
