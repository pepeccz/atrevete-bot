"""T1.1 RED — booking_flow.md included in load_system_prompt().

Asserts that load_system_prompt() contains "Flujo de reserva" and
all 7 step anchors from the booking_flow.md script.
"""


def test_includes_booking_flow():
    """load_system_prompt() must contain 'Flujo de reserva' and all 7 step anchors."""
    from agent.prompts.loader import load_system_prompt

    # Clear lru_cache so the test sees the latest state of the file system.
    load_system_prompt.cache_clear()

    prompt = load_system_prompt()

    assert "Flujo de reserva" in prompt, (
        "System prompt must include 'Flujo de reserva' heading from booking_flow.md"
    )

    # All 7 step anchors must be present.
    step_anchors = [
        "Paso 1",
        "Paso 2",
        "Paso 3",
        "Paso 4",
        "Paso 5",
        "Paso 6",
        "Paso 7",
    ]
    for anchor in step_anchors:
        assert anchor in prompt, (
            f"System prompt must contain step anchor '{anchor}' from booking_flow.md"
        )
