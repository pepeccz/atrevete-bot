"""TDD tests: T1 — Fix escalate tool runtime bugs.

Covers AS5 (source kwarg forwarded), AS6 (EscalationResult.success attribute),
AS7 (empty customer_phone does not abort), E2 (missing conversation_id is handled gracefully).
"""

from __future__ import annotations

import pytest

from agent.services.escalation_service import EscalationResult

# ---------------------------------------------------------------------------
# AS5 — source kwarg forwarded to perform_escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_kwarg_forwarded():
    """AS5: escalate tool must pass source= kwarg when calling perform_escalation."""
    from unittest.mock import patch

    mock_result = EscalationResult(success=True, user_message="Con mucho gusto te paso con alguien.")
    captured_kwargs: dict = {}

    async def fake_perform_escalation(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        side_effect=fake_perform_escalation,
    ):
        from agent.tools.escalation_tools import escalate

        await escalate.coroutine(
            reason="medical_consultation",
            state={"conversation_id": "42", "customer_phone": "+34611000001"},
        )

    assert "source" in captured_kwargs, (
        f"perform_escalation was called without source= kwarg. Got: {captured_kwargs}"
    )
    assert captured_kwargs["source"], "source kwarg must be a non-empty string"


# ---------------------------------------------------------------------------
# AS6 — EscalationResult.success attribute access (not dict .get)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_result_attribute_access():
    """AS6: escalate tool processes EscalationResult dataclass (not dict) correctly."""
    from unittest.mock import patch

    mock_result = EscalationResult(success=True, user_message="Te transfiero con el equipo.")

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        return_value=mock_result,
    ):
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="manual_request",
            state={"conversation_id": "99", "customer_phone": "+34611000002"},
        )

    assert isinstance(result, str), f"Expected str, got {type(result)}"
    # Success path must return a positive message (not an error)
    assert "error" not in result.lower() and "no pude" not in result.lower(), (
        f"Expected success message, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# AS7 — Empty customer_phone does not abort escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_phone_does_not_abort():
    """AS7: escalate must proceed (not return early) when customer_phone is empty."""
    from unittest.mock import patch

    mock_result = EscalationResult(success=True, user_message="Transferido.")
    called = []

    async def fake_perform_escalation(**kwargs):
        called.append(kwargs)
        return mock_result

    with patch(
        "agent.tools.escalation_tools.perform_escalation",
        side_effect=fake_perform_escalation,
    ):
        from agent.tools.escalation_tools import escalate

        result = await escalate.coroutine(
            reason="manual_request",
            state={"conversation_id": "77", "customer_phone": ""},
        )

    assert called, (
        "perform_escalation was never called — empty phone guard is still blocking escalation"
    )
    # Must not return the 'incomplete state' error from the old phone guard
    assert "incompleto" not in result.lower(), (
        f"Got 'incompleto' error — empty phone guard still active. result={result!r}"
    )


# ---------------------------------------------------------------------------
# E2 — Missing conversation_id returns graceful error (existing guard preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_on_missing_conversation_id():
    """E2: when both conversation_id and customer_phone are absent, return graceful error string."""
    from agent.tools.escalation_tools import escalate

    result = await escalate.coroutine(reason="manual_request", state={})

    assert isinstance(result, str), f"Expected str error, got {type(result)}"
    # Must indicate some problem — not raise an exception
    assert len(result) > 0, "Empty result string"
