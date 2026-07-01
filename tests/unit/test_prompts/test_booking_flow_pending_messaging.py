"""
T3 RED — booking_flow.md pending-messaging content tests.

Verifies that booking_flow.md encodes a conditional confirmation branch keyed on
the `appointment_status` field returned by book() (S1-R6, S1-R7, D-N4).

Tests 1 and 3 FAIL before T4 (the R-42 line does not yet reference appointment_status).
Test 2 is a regression guard that passes both before and after T4.

After T4: all 3 tests pass.
"""
from __future__ import annotations

from pathlib import Path

BOOKING_FLOW_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "agent"
    / "prompts"
    / "shared"
    / "booking_flow.md"
)


def test_booking_flow_contains_pending_appointment_status_branch():
    """booking_flow.md must reference 'appointment_status' AND '48h' for pending branch (S1-R6).

    FAILS before T4: the current R-42 line mentions neither 'appointment_status' nor
    a 48h-specific pending instruction.
    """
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    assert "appointment_status" in text, (
        "booking_flow.md must reference 'appointment_status' so Maite can branch "
        "her copy on pending vs confirmed status"
    )
    assert "48h" in text, (
        "booking_flow.md must mention 48h timing for the pending confirmation branch (S1-R6)"
    )


def test_booking_flow_confirmed_branch_exists():
    """booking_flow.md must retain confirmation language for ≤48h CONFIRMED bookings (S1-R7).

    Regression guard: passes before AND after T4.
    The ≤48h confirmed path must keep its current 'confirmada' copy.
    """
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")
    has_confirmed_language = "confirmada" in text or "confirma" in text
    assert has_confirmed_language, (
        "booking_flow.md must retain confirmation language for ≤48h CONFIRMED bookings "
        "(S1-R7 — current confirmed behavior must remain intact)"
    )


def test_booking_flow_prohibits_unconditional_confirmed_claim_in_turno_b():
    """The R-42 rule must be conditional on appointment_status, not unconditional.

    FAILS before T4: the current R-42 line says 'no digas confirmada' but does NOT
    encode the positive conditional branch (what to say for each status). After T4,
    the R-42 line itself references appointment_status, making the instruction conditional.
    """
    text = BOOKING_FLOW_PATH.read_text(encoding="utf-8")

    # R-42 anchor must be present
    assert "[→R-42]" in text, "booking_flow.md must contain the [→R-42] rule anchor"

    # Locate the R-42 line(s) and verify they reference appointment_status
    r42_lines = [line for line in text.splitlines() if "R-42" in line]
    assert r42_lines, "booking_flow.md must have at least one line with R-42"

    r42_block = " ".join(r42_lines)
    assert "appointment_status" in r42_block, (
        "The R-42 rule must reference 'appointment_status' so the confirmation instruction "
        "is conditional (pending vs confirmed), not a blanket prohibition"
    )
