"""
RED test for B.3.1 — AST lint gate.

Imports scripts.check_booking_state_writes.scan and asserts zero violations.
Must FAIL (ImportError) before B.3.4 creates the module, and then fail again
(AssertionError) once the module exists but violations remain.
"""

from __future__ import annotations


def test_ast_lint_no_direct_booking_context_writes() -> None:
    """Assert the AST lint script reports zero direct booking_context mutations."""
    from scripts.check_booking_state_writes import scan  # noqa: PLC0415

    violations = scan()
    assert (
        violations == []
    ), f"Direct booking_context mutations found ({len(violations)} violations):\n" + "\n".join(
        violations
    )
