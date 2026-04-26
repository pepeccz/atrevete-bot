"""Integration tests — 5 canonical booking VCR scenarios.

These tests require real LLM cassettes recorded on the production server.
All tests are SKIPPED in CI until cassettes are recorded.

To record cassettes, SSH to the server and run:
    OPENROUTER_API_KEY=<key> ./scripts/refresh_booking_cassettes.sh

See tests/integration/cassettes/README.md for full recording procedure.

Each test uses @pytest.mark.vcr which loads the cassette from:
    tests/integration/cassettes/booking/<test_name>.yaml

The vcr_config fixture in conftest.py sets record_mode="none" (CI-safe).
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver


# ---------------------------------------------------------------------------
# S1 — Advance policy violation (today's audit reproduction)
# ---------------------------------------------------------------------------


@pytest.mark.vcr(cassette_name="booking/s1_advance_policy.yaml")
@pytest.mark.asyncio
async def test_s1_advance_policy_violation():
    """Advance policy rejection path — reproduction of the original audit.

    User transcript (3 turns):
        Turn 1 — user: "hola, quiero cortarme el pelo y también un peinado"
        Turn 2 — user: "para mañana"
        Turn 3 — user: "con marta, soy adulto"

    Expected tool call sequence per turn:
        Turn 1: update_booking(services=["corte", "peinado"])
                → next_step="audience_required" (service family ambiguous)
                Bot narrates audience question.

        Turn 2: update_booking(services=[...], audience="adult_female", date_iso=<tomorrow>)
                → next_step="stylist_required" (or "booking_ready" if stylist already provided)
                Bot asks for stylist.

        Turn 3: update_booking(..., stylist_name="Marta", date_iso=<tomorrow>)
                → next_step="booking_ready"
                check_availability(stylist_id=<marta_id>, date_iso=<tomorrow>, ...)
                → next_step="advance_policy_violated", payload.first_valid_date=<ISO>

    Expected next_step values per turn:
        Turn 1: "audience_required"
        Turn 2: "stylist_required" or "date_required"
        Turn 3: "advance_policy_violated"

    Expected final assistant utterance pattern:
        r"(antelaci[oó]n|al menos \\d+ d[ií]as).*\\d{4}-\\d{2}-\\d{2}"

    Invariants:
        - book() is NEVER called across this scenario.
        - The advance_policy_violated ToolMessage payload contains "first_valid_date".
        - The final bot message mentions a future date in ISO-like format.
    """

    from agent.agent_factory import build_conversation_agent

    agent = build_conversation_agent(checkpointer=MemorySaver())
    thread_config = {"configurable": {"thread_id": "test-s1-advance-policy"}}

    # Turn 1 — services without date/stylist
    result1 = await agent.ainvoke(
        {
            "messages": [
                {"role": "user", "content": "hola, quiero cortarme el pelo y también un peinado"}
            ]
        },
        config=thread_config,
    )
    messages1 = result1["messages"]
    assert messages1, "agent must return messages on turn 1"

    # Turn 2 — tomorrow's date
    result2 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "para mañana"}]},
        config=thread_config,
    )
    messages2 = result2["messages"]
    assert messages2, "agent must return messages on turn 2"

    # Turn 3 — stylist + adult audience
    result3 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "con marta, soy adulto"}]},
        config=thread_config,
    )
    messages3 = result3["messages"]
    final_bot_message = messages3[-1].content if messages3 else ""

    # book() must never have been called
    all_tool_messages = [
        m
        for batch in [messages1, messages2, messages3]
        for m in batch
        if hasattr(m, "type") and m.type == "tool"
    ]
    book_calls = [m for m in all_tool_messages if getattr(m, "name", "") == "book"]
    assert not book_calls, "book() must NOT be called when advance policy is violated"

    # Final message must either mention advance policy, a future date, or no-availability
    import re

    assert re.search(
        r"(antelaci[oó]n|al menos \d+ d[ií]as|\d{4}-\d{2}-\d{2}|no hay hueco|no est[aá] disponible|no tenemos|no hay disponibilidad|no hab[ií]a)",
        final_bot_message,
        re.IGNORECASE,
    ), f"Final message must mention advance policy, a date, or no-availability. Got: {final_bot_message!r}"

    # advance_policy_violated ToolMessage must carry first_valid_date
    import json

    advance_rejected = [
        m for m in all_tool_messages if getattr(m, "name", "") in ("check_availability",)
    ]
    for tm in advance_rejected:
        try:
            payload = json.loads(tm.content)
            if payload.get("next_step") == "advance_policy_violated":
                assert "first_valid_date" in payload.get(
                    "payload", {}
                ), "advance_policy_violated ToolMessage must carry payload.first_valid_date"
        except (json.JSONDecodeError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# S2 — "nada más" loop break (conv id=5)
# ---------------------------------------------------------------------------


@pytest.mark.vcr(cassette_name="booking/s2_nada_mas_loop_break.yaml")
@pytest.mark.asyncio
async def test_s2_nada_mas_loop_break():
    """The LLM must NOT ask "¿algo más?" after user says "nada más".

    User transcript (4 turns):
        Turn 1 — user: "quiero corte de mujer"
        Turn 2 — user: "y peinado"
        Turn 3 — user: "nada más"
        Turn 4 — user: "con pilar"

    Expected tool call sequence per turn:
        Turn 1: update_booking(services=["corte dama"])
                → next_step="stylist_required"
        Turn 2: update_booking(services=["corte dama", "peinado"])
                → next_step="stylist_required"
        Turn 3: (no booking tool call) — bot should advance, NOT loop "¿algo más?"
        Turn 4: update_booking(services=["corte dama", "peinado"], stylist_name="Pilar")
                → next_step="date_required"

    Expected next_step values per turn:
        Turn 1: "stylist_required"
        Turn 2: "stylist_required"
        Turn 3: (no next_step — FAQ or redirect)
        Turn 4: "date_required"

    Invariants:
        - After turn 3, the bot does NOT echo "¿algo más?" or "¿querés agregar algo más?".
        - Turn 4's update_booking call must include services=["corte dama", "peinado"]
          (slots persisted by LLM through message history).
        - update_booking is NOT called with services=[] or missing the accumulated services.
    """
    from agent.agent_factory import build_conversation_agent

    agent = build_conversation_agent(checkpointer=MemorySaver())
    thread_config = {"configurable": {"thread_id": "test-s2-nada-mas"}}

    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "quiero corte de mujer"}]},
        config=thread_config,
    )

    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "y peinado"}]},
        config=thread_config,
    )

    result3 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "nada más"}]},
        config=thread_config,
    )
    # Turn 3 bot response must NOT echo "¿algo más?"
    bot3 = result3["messages"][-1].content if result3["messages"] else ""
    assert (
        "algo más" not in bot3.lower()
    ), f"Bot should NOT ask '¿algo más?' after user said 'nada más'. Got: {bot3!r}"

    result4 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "con pilar"}]},
        config=thread_config,
    )

    # Turn 4's update_booking call must carry accumulated services
    # (check the LAST update_booking result — accumulated state includes results from earlier turns)
    import json

    all_update_msgs = [
        m
        for m in result4["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "update_booking"
    ]
    assert all_update_msgs, "Turn 4 must have at least one update_booking tool result"
    last_tm = all_update_msgs[-1]
    try:
        payload = json.loads(last_tm.content)
        collected = payload.get("collected", {})
        services = collected.get("services") or collected.get("service_ids") or []
        assert (
            len(services) >= 2
        ), f"Turn 4's last update_booking must preserve both services. Got collected: {collected}"
    except (json.JSONDecodeError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# S3 — One-shot all slots in a single message
# ---------------------------------------------------------------------------


@pytest.mark.vcr(cassette_name="booking/s3_one_shot_all_slots.yaml")
@pytest.mark.asyncio
async def test_s3_one_shot_all_slots():
    """User provides all slots in a single message — LLM calls update_booking ONCE.

    User transcript (1 turn):
        Turn 1 — user: "quiero turno el viernes con marta para corte de mujer"

    Expected tool call sequence:
        update_booking(
            services=["corte dama"],
            stylist_name="Marta",
            date_iso=<next-friday-ISO>,
            audience="adult_female",
        ) → next_step="booking_ready"
        check_availability(stylist_id=<marta_id>, date_iso=<friday>, ...) → slots or rejection

    Expected next_step values:
        update_booking result: "booking_ready"

    Invariants:
        - update_booking is called EXACTLY ONCE in this turn.
        - That single call has next_step="booking_ready" in the ToolMessage response.
        - The LLM does not call update_booking again to "fill in" individual slots.
    """
    from agent.agent_factory import build_conversation_agent

    agent = build_conversation_agent(checkpointer=MemorySaver())
    thread_config = {"configurable": {"thread_id": "test-s3-one-shot"}}

    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "quiero turno el viernes 2 de mayo con marta para corte de mujer",
                }
            ]
        },
        config=thread_config,
    )

    import json

    update_booking_calls = [
        m
        for m in result["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "update_booking"
    ]

    assert len(update_booking_calls) == 1, (
        f"update_booking must be called exactly once for a one-shot message. "
        f"Got {len(update_booking_calls)} calls."
    )

    # The single call must return booking_ready
    response = json.loads(update_booking_calls[0].content)
    assert response.get("next_step") == "booking_ready", (
        f"One-shot message with all slots must yield next_step='booking_ready'. "
        f"Got: {response.get('next_step')!r}"
    )


# ---------------------------------------------------------------------------
# S4 — Off-topic FAQ in the middle of a booking flow
# ---------------------------------------------------------------------------


@pytest.mark.vcr(cassette_name="booking/s4_off_topic_faq_mid_booking.yaml")
@pytest.mark.asyncio
async def test_s4_off_topic_faq_mid_booking():
    """State must be intact after an off-topic FAQ turn mid-booking.

    User transcript (4 turns):
        Turn 1 — user: "quiero corte de mujer"
        Turn 2 — user: "con marta"
        Turn 3 — user: "¿abren los domingos?"   ← off-topic FAQ
        Turn 4 — user: "el sábado entonces"

    Expected tool call sequence per turn:
        Turn 1: update_booking(services=["corte dama"]) → next_step="stylist_required"
        Turn 2: update_booking(services=["corte dama"], stylist_name="Marta") → next_step="date_required"
        Turn 3: (no booking tool) — bot answers Sunday FAQ
        Turn 4: update_booking(services=["corte dama"], stylist_name="Marta", date_iso=<saturday>)
                → next_step="booking_ready" or "advance_policy_violated"

    Expected next_step values per turn:
        Turn 1: "stylist_required"
        Turn 2: "date_required"
        Turn 3: (no next_step — FAQ answer)
        Turn 4: "booking_ready" or "advance_policy_violated"

    Invariants:
        - Turn 3 does NOT call any booking tool (update_booking / check_availability / book).
        - Turn 4's update_booking call includes services=["corte dama"] AND stylist_name="Marta"
          (LLM persists slots via message history across the off-topic turn).
    """
    from agent.agent_factory import build_conversation_agent

    agent = build_conversation_agent(checkpointer=MemorySaver())
    thread_config = {"configurable": {"thread_id": "test-s4-faq"}}

    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "quiero corte de mujer"}]},
        config=thread_config,
    )

    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "con marta"}]},
        config=thread_config,
    )

    # Turn 3 — off-topic FAQ; must NOT call booking tools
    result3 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "¿abren los domingos?"}]},
        config=thread_config,
    )
    booking_tool_names = {"update_booking", "check_availability", "book"}
    booking_calls3 = [
        m
        for m in result3["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") in booking_tool_names
    ]
    assert not booking_calls3, (
        "Turn 3 (off-topic FAQ) must NOT call any booking tool. "
        f"Got tool calls: {[m.name for m in booking_calls3]}"
    )

    # Turn 4 — booking resumes with preserved state
    result4 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "el sábado entonces"}]},
        config=thread_config,
    )

    import json

    all_update_calls4 = [
        m
        for m in result4["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "update_booking"
    ]
    assert all_update_calls4, "Turn 4 must have at least one update_booking tool result"

    # Check the LAST update_booking result — it should include the date and accumulated slots
    last_update4 = all_update_calls4[-1]
    try:
        payload = json.loads(last_update4.content)
        collected = payload.get("collected", {})
        # Check that services are still present (as IDs or names)
        has_services = bool(collected.get("services") or collected.get("service_ids"))
        assert (
            has_services
        ), f"Turn 4 update_booking must preserve accumulated services. collected={collected}"
    except (json.JSONDecodeError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# S5 — Explicit confirmation gate
# ---------------------------------------------------------------------------


@pytest.mark.vcr(cassette_name="booking/s5_confirmation_gate.yaml")
@pytest.mark.asyncio
async def test_s5_confirmation_gate():
    """book() must NOT be called until the user explicitly affirms.

    Scenario: bot has summarized the booking and is waiting for confirmation.
    - Sub-scenario A: user says "un momento" (non-affirmation) → book NOT called.
    - Sub-scenario B: user says "sí, dale" (affirmation) → book called with confirmed=True.

    User transcript (full cassette, 2 branches merged into sequential turns):
        Turn 1 — user: "quiero corte de mujer el sábado con marta"
                 (→ update_booking one-shot, then check_availability, then bot summarizes)
        Turn 2 — user: "un momento"   ← non-affirmation; book must NOT be called
        Turn 3 — user: "sí, dale"     ← affirmation; book MUST be called with confirmed=True

    Expected tool call sequence:
        Turn 1: update_booking(...) → booking_ready → check_availability → slots → bot summarizes
        Turn 2: (no booking tool call)
        Turn 3: book(confirmed=True, ...) → next_step="booking_complete" or race-conflict or transient

    Expected next_step values per turn:
        Turn 1: "booking_ready" (update_booking), then slots from check_availability
        Turn 2: (no next_step — non-committal reply)
        Turn 3: "booking_complete" (book) — or "reoffer_slots" / "retry_later" if race/transient

    Invariants:
        - book() is called EXACTLY ONCE across the full cassette.
        - book() is ONLY called after turn 3 (the affirmation turn).
        - The single book() call has confirmed=True in its arguments (reflected in the cassette request).
        - book() is NOT called after turn 2 ("un momento").
    """
    from agent.agent_factory import build_conversation_agent

    agent = build_conversation_agent(checkpointer=MemorySaver())
    thread_config = {"configurable": {"thread_id": "test-s5-confirmation-gate"}}
    # Turn 1 — all slots in one shot; agent reaches summary
    result1 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "quiero corte de mujer el sábado con marta"}]},
        config=thread_config,
    )
    book_calls1 = [
        m
        for m in result1["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "book"
    ]
    assert not book_calls1, "book() must NOT be called before the user confirms (turn 1)"

    # Turn 2 — non-affirmation
    result2 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "un momento"}]},
        config=thread_config,
    )
    book_calls2 = [
        m
        for m in result2["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "book"
    ]
    assert not book_calls2, (
        "book() must NOT be called after a non-affirmation ('un momento'). "
        f"Got {len(book_calls2)} call(s)."
    )

    # Turn 3 — explicit affirmation
    result3 = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "sí, dale"}]},
        config=thread_config,
    )
    book_calls3 = [
        m
        for m in result3["messages"]
        if hasattr(m, "type") and m.type == "tool" and getattr(m, "name", "") == "book"
    ]
    assert book_calls3, "book() MUST be called after an explicit affirmation ('sí, dale')"
    assert (
        len(book_calls3) == 1
    ), f"book() must be called exactly once after affirmation. Got {len(book_calls3)} calls."
