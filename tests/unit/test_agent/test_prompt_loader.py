"""PR2 — booking_fsm.md replaces booking_flow.md + appointment_management_flow.md.

load_system_prompt() must contain the unified FSM document and still reference
manage_appointments for the appointment management flow.

Anchors verified against booking_fsm.md as of 2026-05-09:
    - "Reservas y Gestión de Citas — FSM" (file heading)
    - "Flujo de reserva" (booking section)
    - "Gestión de citas existentes" (appointment management section)
    - "manage_appointments" (tool reference)
    - "booking_ready" (booking_ready signal)
    - "CONFIRMATION_PROMPT" or Turno A/B language

booking_flow.md and appointment_management_flow.md are deleted in PR2.
The old step anchors (Paso 1, Paso 1.5, …, Paso 4b) no longer exist.
"""


def test_includes_booking_fsm():
    """load_system_prompt() must contain the unified FSM heading and key section markers."""
    from agent.prompts.loader import load_system_prompt

    load_system_prompt.cache_clear()
    prompt = load_system_prompt()

    assert "Reservas y Gestión de Citas — FSM" in prompt, (
        "System prompt must include the booking_fsm.md heading"
    )
    assert "Flujo de reserva" in prompt, (
        "System prompt must include 'Flujo de reserva' section from booking_fsm.md"
    )
    assert "Gestión de citas existentes" in prompt, (
        "System prompt must include 'Gestión de citas existentes' section from booking_fsm.md"
    )
    assert "booking_ready" in prompt, (
        "System prompt must contain 'booking_ready' signal reference from booking_fsm.md"
    )


def test_includes_appointment_management_flow():
    """load_system_prompt() must reference the manage_appointments tool."""
    from agent.prompts.loader import load_system_prompt

    load_system_prompt.cache_clear()
    prompt = load_system_prompt()

    assert "manage_appointments" in prompt, (
        "System prompt must reference 'manage_appointments' tool"
    )
