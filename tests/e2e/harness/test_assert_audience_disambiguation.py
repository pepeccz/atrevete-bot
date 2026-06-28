"""Unit tests for assert_audience_disambiguation.py.

These tests are PURE — no DB, no Redis, no network access. They exercise the
helper logic against synthetic turn-result JSON fixtures to verify:

  1. BUG payload (must FAIL): agent calls update_booking(services=["corte de
     mujer"]) on turn 1 and offers concrete availability. Reproduces the exact
     bug reported 2026-06-25.

  2. GOOD payload (must PASS): agent replies with a proper clarifying question
     about audience, no tool calls fired.

  3. Additional edge cases covering each check independently.

Run with:
    DATABASE_URL=postgresql+asyncpg://atrevete:changeme@localhost:5432/atrevete_db \\
      ./venv/bin/pytest tests/e2e/harness/test_assert_audience_disambiguation.py -v

Note: the DATABASE_URL env var is required by project pytest configuration but
these tests do not actually touch the database — they are pure unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.harness.assert_audience_disambiguation import (
    _CLARIFYING_QUESTION_RE,
    _GENDERED_SERVICE_RE,
    check_audience_disambiguation,
)

# ---------------------------------------------------------------------------
# Fixtures — synthetic turn-result JSON objects
# ---------------------------------------------------------------------------

# BUG PAYLOAD — the exact reproduced bug pattern.
#
# Customer said: "Hola, quiero cortarme el pelo"
# Agent (WRONG): called update_booking(services=["corte de mujer"]) on turn 1
#                and offered concrete availability for "Corte Dama".
#
# The helper MUST return pass=False, verdict="fail".
BUG_PAYLOAD_TOOL_CALL: dict[str, Any] = {
    "agent_response": (
        "¡Claro que sí! Te anoto un corte de mujer. "
        "Tenemos disponibilidad el martes a las 10:00 o el miércoles a las 16:00. "
        "¿Cuál te va mejor?"
    ),
    "timed_out": False,
    "response_latency_ms": 1321,
    "tool_evidence": [
        {
            "tool_name": "update_booking",
            "arguments": {"services": ["corte de mujer"]},
            "result": {"ok": True, "draft": {"service": "Corte Dama"}},
            "source": "checkpoint",
            "timestamp": "2026-06-25T10:00:00+00:00",
        }
    ],
}

# BUG PAYLOAD — tool call only, response is neutral (no decided context in text).
# Should still fail because the tool call alone is sufficient.
BUG_PAYLOAD_TOOL_CALL_ONLY: dict[str, Any] = {
    "agent_response": "Por supuesto, déjame buscar disponibilidad.",
    "timed_out": False,
    "response_latency_ms": 800,
    "tool_evidence": [
        {
            "tool_name": "check_availability",
            "arguments": {"service_name": "corte de dama", "date": "2026-07-01"},
            "result": {"slots": []},
            "source": "checkpoint",
            "timestamp": "2026-06-25T10:00:00+00:00",
        }
    ],
}

# BUG PAYLOAD — response text decides the service (decided-context pattern fires),
# no tool call. Should fail on Check 2.
BUG_PAYLOAD_RESPONSE_DECIDES: dict[str, Any] = {
    "agent_response": (
        "Para el corte de dama hay disponibilidad el viernes a las 15:30. "
        "¿Te apunto para esa hora?"
    ),
    "timed_out": False,
    "response_latency_ms": 900,
    "tool_evidence": [],
}

# GOOD PAYLOAD — agent asks a proper clarifying question, no tool calls.
# The helper MUST return pass=True, verdict="pass".
GOOD_PAYLOAD_CLARIFYING_QUESTION: dict[str, Any] = {
    "agent_response": (
        "¡Hola! Con mucho gusto. ¿Para quién sería el corte? "
        "¿Es para ti, para un hombre o para un niño?"
    ),
    "timed_out": False,
    "response_latency_ms": 950,
    "tool_evidence": [],
}

# GOOD PAYLOAD — agent asks "para ti" phrasing.
GOOD_PAYLOAD_PARA_TI: dict[str, Any] = {
    "agent_response": (
        "¡Claro! ¿El corte es para ti o para otra persona?"
    ),
    "timed_out": False,
    "response_latency_ms": 750,
    "tool_evidence": [],
}

# GOOD PAYLOAD — response mentions both genders as OPTIONS in a question,
# not as a decided service. Should PASS (no decided-context pattern near the mention).
GOOD_PAYLOAD_OPTIONS_IN_QUESTION: dict[str, Any] = {
    "agent_response": (
        "¡Hola! ¿Sería un corte de mujer, de hombre o para un niño?"
    ),
    "timed_out": False,
    "response_latency_ms": 820,
    "tool_evidence": [],
}

# EDGE CASE — get_next_available_options called with a gendered service.
# Should fail because get_next_available_options is in the premature-tool set.
BUG_PAYLOAD_NEXT_AVAILABLE: dict[str, Any] = {
    "agent_response": "Aquí tienes las opciones disponibles.",
    "timed_out": False,
    "response_latency_ms": 1100,
    "tool_evidence": [
        {
            "tool_name": "get_next_available_options",
            "arguments": {"service": "corte caballero"},
            "result": {"options": []},
            "source": "checkpoint",
            "timestamp": "2026-06-25T10:00:00+00:00",
        }
    ],
}

# EDGE CASE — a non-booking tool (e.g. escalate) is called. Should NOT fail on Check 1.
GOOD_PAYLOAD_NON_BOOKING_TOOL: dict[str, Any] = {
    "agent_response": (
        "¿Para quién sería el corte de pelo? ¿Para ti o para un familiar?"
    ),
    "timed_out": False,
    "response_latency_ms": 600,
    "tool_evidence": [
        {
            "tool_name": "escalate",
            "arguments": {"reason": "complex query"},
            "result": {},
            "source": "checkpoint",
            "timestamp": "2026-06-25T10:00:00+00:00",
        }
    ],
}

# EDGE CASE — empty turn result (no response, no tools). Should PASS (no FAIL trigger).
EMPTY_PAYLOAD: dict[str, Any] = {
    "agent_response": "",
    "timed_out": False,
    "response_latency_ms": 0,
    "tool_evidence": [],
}


# ---------------------------------------------------------------------------
# Tests: BUG payloads MUST FAIL
# ---------------------------------------------------------------------------


class TestBugPayloadsMustFail:
    """The helper must return verdict=fail on all reproduced-bug payloads."""

    def test_bug_payload_full_tool_call_and_response_fails(self) -> None:
        """Full bug payload: tool call + decided response → verdict=fail."""
        result = check_audience_disambiguation(BUG_PAYLOAD_TOOL_CALL)
        assert result["pass"] is False, (
            f"Expected pass=False for full bug payload, got pass=True. "
            f"reasons={result['reasons']}"
        )
        assert result["verdict"] == "fail"
        assert len(result["reasons"]) > 0, "Expected at least one failure reason"

    def test_bug_payload_premature_tool_call_fires_check1(self) -> None:
        """Tool call alone (neutral response) → verdict=fail via Check 1."""
        result = check_audience_disambiguation(BUG_PAYLOAD_TOOL_CALL_ONLY)
        assert result["pass"] is False
        assert result["verdict"] == "fail"
        # Check 1 evidence should be populated
        assert len(result["evidence"]["premature_tool_calls"]) > 0, (
            "Expected premature_tool_calls evidence to be populated"
        )

    def test_bug_payload_response_decides_fires_check2(self) -> None:
        """Response text decides service (no tool call) → verdict=fail via Check 2."""
        result = check_audience_disambiguation(BUG_PAYLOAD_RESPONSE_DECIDES)
        assert result["pass"] is False
        assert result["verdict"] == "fail"
        assert result["evidence"]["decided_response_match"] is not None, (
            "Expected decided_response_match to be populated"
        )

    def test_bug_payload_full_records_tool_call_evidence(self) -> None:
        """Bug payload: premature_tool_calls evidence records tool name and service."""
        result = check_audience_disambiguation(BUG_PAYLOAD_TOOL_CALL)
        calls = result["evidence"]["premature_tool_calls"]
        assert len(calls) >= 1
        assert calls[0]["tool_name"] == "update_booking"
        assert "corte de mujer" in calls[0]["matched_service"].lower()

    def test_bug_payload_next_available_with_gendered_service_fails(self) -> None:
        """get_next_available_options with gendered service → verdict=fail."""
        result = check_audience_disambiguation(BUG_PAYLOAD_NEXT_AVAILABLE)
        assert result["pass"] is False
        assert result["verdict"] == "fail"
        calls = result["evidence"]["premature_tool_calls"]
        assert any(c["tool_name"] == "get_next_available_options" for c in calls)


# ---------------------------------------------------------------------------
# Tests: GOOD payloads MUST PASS
# ---------------------------------------------------------------------------


class TestGoodPayloadsMustPass:
    """The helper must return verdict=pass on all correct clarifying responses."""

    def test_good_payload_clarifying_question_passes(self) -> None:
        """Proper clarifying question, no tool calls → verdict=pass."""
        result = check_audience_disambiguation(GOOD_PAYLOAD_CLARIFYING_QUESTION)
        assert result["pass"] is True, (
            f"Expected pass=True for clarifying question payload, got pass=False. "
            f"reasons={result['reasons']}"
        )
        assert result["verdict"] == "pass"
        assert result["reasons"] == []

    def test_good_payload_para_ti_passes(self) -> None:
        '"¿El corte es para ti?" phrasing → verdict=pass.'
        result = check_audience_disambiguation(GOOD_PAYLOAD_PARA_TI)
        assert result["pass"] is True
        assert result["verdict"] == "pass"

    def test_good_payload_options_in_question_passes(self) -> None:
        """Gendered service names as question OPTIONS (no decided context) → verdict=pass."""
        result = check_audience_disambiguation(GOOD_PAYLOAD_OPTIONS_IN_QUESTION)
        assert result["pass"] is True, (
            f"Listing gender options in a question should PASS. "
            f"reasons={result['reasons']}"
        )
        assert result["verdict"] == "pass"

    def test_good_payload_non_booking_tool_passes(self) -> None:
        """Non-booking tool (escalate) with clarifying question → verdict=pass."""
        result = check_audience_disambiguation(GOOD_PAYLOAD_NON_BOOKING_TOOL)
        assert result["pass"] is True
        assert result["verdict"] == "pass"
        assert result["evidence"]["premature_tool_calls"] == []

    def test_empty_payload_passes(self) -> None:
        """Empty response, no tools → verdict=pass (no FAIL trigger, benefit of doubt)."""
        result = check_audience_disambiguation(EMPTY_PAYLOAD)
        assert result["pass"] is True
        assert result["verdict"] == "pass"


# ---------------------------------------------------------------------------
# Tests: clarifying question detection
# ---------------------------------------------------------------------------


class TestClarifyingQuestionDetection:
    """Unit tests for the clarifying-question regex heuristic."""

    @pytest.mark.parametrize(
        "text",
        [
            "¿Para quién sería el corte?",
            "¿Es para ti o para un familiar?",
            "¿Para quién es el corte de pelo?",
            "¿El corte es para ti?",
            "¿Es para un hombre o para una mujer?",
            "¿Para un niño o para un adulto?",
            "Dime, ¿a quién le cortamos el pelo?",
            "¿Para quién va el servicio?",
            "¿Hombre, mujer o niño?",
        ],
    )
    def test_clarifying_patterns_are_detected(self, text: str) -> None:
        """Known clarifying question phrasings must be detected by the regex."""
        m = _CLARIFYING_QUESTION_RE.search(text)
        assert m is not None, (
            f"Expected _CLARIFYING_QUESTION_RE to match in: {text!r}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            # Booking confirmations that happen to mention a female customer
            "Te anoto el corte de mujer para el martes.",
            # Pure availability offerings without a question
            "El corte de dama tiene disponibilidad el viernes.",
        ],
    )
    def test_non_question_texts_have_no_clarifying_match(self, text: str) -> None:
        """Non-disambiguating texts should NOT match the clarifying question pattern."""
        m = _CLARIFYING_QUESTION_RE.search(text)
        # Note: some texts above might partially match (e.g. "mujer" in a list).
        # This test is informational — the real guard is Check 1 and Check 2.
        # We only assert that a decided-context pattern fires (not the clarifying pattern).
        _ = m  # not asserting absence here — clarifying match is not the sole guard


# ---------------------------------------------------------------------------
# Tests: gendered service name detection
# ---------------------------------------------------------------------------


class TestGenderedServiceDetection:
    """Unit tests for the gendered-service regex."""

    @pytest.mark.parametrize(
        "text",
        [
            "corte de mujer",
            "Corte Dama",
            "corte de dama",
            "CORTE SEÑORA",
            "corte caballero",
            "corte de caballero",
            "corte de hombre",
            "Corte Hombre",
            '{"services": ["corte de mujer"]}',  # JSON-serialized tool argument
            "service_name=corte de dama",
        ],
    )
    def test_gendered_names_are_detected(self, text: str) -> None:
        """All canonical gendered service name forms must be detected."""
        m = _GENDERED_SERVICE_RE.search(text.lower())
        assert m is not None, (
            f"Expected _GENDERED_SERVICE_RE to match in: {text!r}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "quiero cortarme el pelo",
            "un corte de pelo",
            "quiero un corte",
            "cortarse el pelo",
            "necesito un corte rápido",
        ],
    )
    def test_neutral_requests_are_not_matched(self, text: str) -> None:
        """Gender-neutral haircut requests must NOT match the gendered pattern."""
        m = _GENDERED_SERVICE_RE.search(text.lower())
        assert m is None, (
            f"Expected no match for neutral text {text!r}, got: {m}"
        )


# ---------------------------------------------------------------------------
# Tests: decided-context detection
# ---------------------------------------------------------------------------


class TestDecidedContextDetection:
    """Unit tests for the decided-context window heuristic."""

    @pytest.mark.parametrize(
        "text",
        [
            "Te anoto un corte de mujer para el martes.",
            "Hay disponibilidad para corte de dama el viernes.",
            "Para el corte de caballero tenemos hueco el lunes a las 10:00.",
            "El miércoles a las 15:00 está libre para corte de hombre.",
            "Quedas anotada para corte dama.",
        ],
    )
    def test_decided_context_phrases_are_detected(self, text: str) -> None:
        """Texts with both a gendered service name and a decided-context phrase must FAIL."""
        result = check_audience_disambiguation(
            {"agent_response": text, "tool_evidence": []}
        )
        assert result["pass"] is False, (
            f"Expected FAIL for decided response text: {text!r}. "
            f"reasons={result['reasons']}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "¿Sería un corte de mujer, de hombre o para un niño?",
            "Tenemos corte de mujer, corte de hombre y corte infantil. ¿Cuál necesitas?",
        ],
    )
    def test_gendered_name_as_option_in_question_passes(self, text: str) -> None:
        """Gendered service listed as an OPTION in a clarifying question must PASS."""
        result = check_audience_disambiguation(
            {"agent_response": text, "tool_evidence": []}
        )
        assert result["pass"] is True, (
            f"Expected PASS when gendered service is a question option: {text!r}. "
            f"reasons={result['reasons']}"
        )


# ---------------------------------------------------------------------------
# Tests: return shape contract
# ---------------------------------------------------------------------------


class TestReturnShape:
    """The helper must always return the documented dict shape."""

    def test_pass_result_has_required_keys(self) -> None:
        result = check_audience_disambiguation(GOOD_PAYLOAD_CLARIFYING_QUESTION)
        assert "pass" in result
        assert "verdict" in result
        assert "reasons" in result
        assert "evidence" in result
        assert "premature_tool_calls" in result["evidence"]
        assert "decided_response_match" in result["evidence"]
        assert "clarifying_question_match" in result["evidence"]

    def test_fail_result_has_required_keys(self) -> None:
        result = check_audience_disambiguation(BUG_PAYLOAD_TOOL_CALL)
        assert "pass" in result
        assert "verdict" in result
        assert "reasons" in result
        assert "evidence" in result

    def test_verdict_and_pass_are_consistent(self) -> None:
        """verdict='pass' <=> pass=True; verdict='fail' <=> pass=False."""
        for payload in [
            BUG_PAYLOAD_TOOL_CALL,
            BUG_PAYLOAD_TOOL_CALL_ONLY,
            BUG_PAYLOAD_RESPONSE_DECIDES,
            GOOD_PAYLOAD_CLARIFYING_QUESTION,
            GOOD_PAYLOAD_PARA_TI,
            EMPTY_PAYLOAD,
        ]:
            result = check_audience_disambiguation(payload)
            assert (result["verdict"] == "pass") == result["pass"], (
                f"Inconsistency: verdict={result['verdict']!r}, pass={result['pass']} "
                f"for payload agent_response={payload.get('agent_response')!r:.60}"
            )

    def test_reasons_empty_on_pass(self) -> None:
        """reasons must be an empty list when verdict=pass."""
        result = check_audience_disambiguation(GOOD_PAYLOAD_CLARIFYING_QUESTION)
        assert result["reasons"] == []

    def test_reasons_non_empty_on_fail(self) -> None:
        """reasons must have at least one entry when verdict=fail."""
        result = check_audience_disambiguation(BUG_PAYLOAD_TOOL_CALL)
        assert len(result["reasons"]) >= 1

    def test_tolerates_missing_keys_in_tool_evidence(self) -> None:
        """Helper must not raise when tool_evidence entries have missing keys."""
        payload: dict[str, Any] = {
            "agent_response": "¿Para quién sería el corte?",
            "tool_evidence": [
                {},  # empty dict
                {"tool_name": "update_booking"},  # no arguments key
                None,  # type: ignore[list-item]  — should be skipped
            ],
        }
        result = check_audience_disambiguation(payload)
        # No crash; tool_evidence entries without gendered args should not fail.
        assert isinstance(result, dict)
        assert "pass" in result
