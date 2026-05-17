"""
Unit tests for QA run-scoped data models.

Tests cover:
- LLMTurnResponse creation and default values
- TurnRecord backward compatibility (bugs field)
- ConversationResult backward compatibility (bugs_summary field)

All tests are synchronous — no LLM, no DB, no Redis needed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.e2e.harness.redis_harness import ClassifierOutput
from tests.e2e.harness.run_models import (
    ConversationResult,
    LLMTurnResponse,
    TurnEvidence,
    TurnRecord,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_evidence(**overrides) -> TurnEvidence:
    """Factory for TurnEvidence with sensible defaults."""
    now = datetime.now(UTC)
    defaults = dict(
        turn_number=1,
        user_message="Hola, quiero un turno",
        agent_response="¡Hola! ¿Qué servicio te gustaría?",
        response_latency_ms=120,
        timed_out=False,
        raw_payloads=[],
        timestamp_sent=now,
        timestamp_received=now,
    )
    defaults.update(overrides)
    return TurnEvidence(**defaults)


def _make_classification(**overrides) -> ClassifierOutput:
    """Factory for ClassifierOutput with sensible defaults."""
    defaults = dict(
        intent="booking",
        confidence=0.95,
    )
    defaults.update(overrides)
    return ClassifierOutput(**defaults)


# =============================================================================
# LLMTurnResponse
# =============================================================================


class TestLLMTurnResponse:
    """Tests for the LLMTurnResponse dataclass."""

    def test_creation_with_required_fields(self):
        resp = LLMTurnResponse(
            reply="Hola, quiero un corte",
            should_stop=False,
            stop_reason="",
            confidence=0.85,
        )
        assert resp.reply == "Hola, quiero un corte"
        assert resp.should_stop is False
        assert resp.stop_reason == ""
        assert resp.confidence == 0.85

    def test_default_bugs_is_empty_list(self):
        resp = LLMTurnResponse(
            reply="Sí, perfecto",
            should_stop=False,
            stop_reason="",
            confidence=0.9,
        )
        assert resp.bugs == []

    def test_default_milestone_reached_is_none(self):
        resp = LLMTurnResponse(
            reply="Dale",
            should_stop=False,
            stop_reason="",
            confidence=0.8,
        )
        assert resp.milestone_reached is None

    def test_default_flow_status_is_in_progress(self):
        resp = LLMTurnResponse(
            reply="Ok",
            should_stop=False,
            stop_reason="",
            confidence=0.7,
        )
        assert resp.flow_status == "in_progress"

    def test_default_reasoning_trace_is_empty_string(self):
        resp = LLMTurnResponse(
            reply="Listo",
            should_stop=False,
            stop_reason="",
            confidence=0.6,
        )
        assert resp.reasoning_trace == ""

    def test_creation_with_all_fields(self):
        bugs = [{"type": "re_asked", "description": "Bot re-asked name after user already provided it"}]
        resp = LLMTurnResponse(
            reply="Quiero un turno para mañana",
            should_stop=True,
            stop_reason="booking_complete",
            confidence=0.99,
            bugs=bugs,
            milestone_reached="appointment_confirmed",
            flow_status="complete",
            reasoning_trace="User confirmed booking; all slots filled.",
        )
        assert resp.reply == "Quiero un turno para mañana"
        assert resp.should_stop is True
        assert resp.stop_reason == "booking_complete"
        assert resp.confidence == 0.99
        assert resp.bugs == bugs
        assert resp.milestone_reached == "appointment_confirmed"
        assert resp.flow_status == "complete"
        assert resp.reasoning_trace == "User confirmed booking; all slots filled."

    def test_bugs_mutable_default_isolation(self):
        """Each instance must get its own list — no shared mutable default."""
        a = LLMTurnResponse(reply="a", should_stop=False, stop_reason="", confidence=0.5)
        b = LLMTurnResponse(reply="b", should_stop=False, stop_reason="", confidence=0.5)
        a.bugs.append({"type": "test", "description": "bug-in-a"})
        assert b.bugs == [], "Instances must not share the default list"
        assert a.bugs == [{"type": "test", "description": "bug-in-a"}]


# =============================================================================
# TurnRecord backward compatibility (bugs field)
# =============================================================================


class TestTurnRecordBugsField:
    """Tests for TurnRecord's bugs field (added for QA bug tracking)."""

    def test_creation_without_bugs(self):
        """TurnRecord must work WITHOUT the bugs field — backward compat."""
        record = TurnRecord(
            message="Hola",
            evidence=_make_evidence(),
            classification=_make_classification(),
        )
        assert record.message == "Hola"
        assert record.bugs == []

    def test_creation_with_bugs(self):
        bugs = [
            {"type": "ignored_preference", "description": "Bot ignored stylist preference"},
            {"type": "repeated_greeting", "description": "Repeated greeting"},
        ]
        record = TurnRecord(
            message="Quiero con Ana",
            evidence=_make_evidence(),
            classification=_make_classification(),
            bugs=bugs,
        )
        assert record.bugs == bugs

    def test_bugs_defaults_to_empty_list(self):
        record = TurnRecord(
            message="Test",
            evidence=_make_evidence(),
            classification=_make_classification(),
        )
        assert record.bugs == []
        assert isinstance(record.bugs, list)

    def test_bugs_mutable_default_isolation(self):
        """Each TurnRecord must get its own bugs list."""
        a = TurnRecord(
            message="a",
            evidence=_make_evidence(),
            classification=_make_classification(),
        )
        b = TurnRecord(
            message="b",
            evidence=_make_evidence(),
            classification=_make_classification(),
        )
        a.bugs.append({"type": "test", "description": "only-in-a"})
        assert b.bugs == []


# =============================================================================
# ConversationResult backward compatibility (bugs_summary field)
# =============================================================================


class TestConversationResultBugsSummary:
    """Tests for ConversationResult's bugs_summary field."""

    def test_creation_without_bugs_summary(self):
        """ConversationResult must work WITHOUT bugs_summary — backward compat."""
        result = ConversationResult(
            turns=[],
            outcome="success",
            milestone_reached="appointment_confirmed",
        )
        assert result.outcome == "success"
        assert result.bugs_summary == ""

    def test_creation_with_bugs_summary(self):
        summary = "Turn 2: Bot re-asked name. Turn 5: Ignored stylist preference."
        result = ConversationResult(
            turns=[],
            outcome="success",
            milestone_reached="appointment_confirmed",
            bugs_summary=summary,
        )
        assert result.bugs_summary == summary

    def test_bugs_summary_defaults_to_empty_string(self):
        result = ConversationResult(
            turns=[],
            outcome="success",
            milestone_reached="appointment_confirmed",
        )
        assert result.bugs_summary == ""
        assert isinstance(result.bugs_summary, str)

    def test_other_defaults_still_work(self):
        """Ensure adding bugs_summary didn't break existing defaults."""
        result = ConversationResult(
            turns=[],
            outcome="escalated",
            milestone_reached="",
        )
        assert result.final_state == {}
        assert result.tool_trace == []
        assert result.termination_reason == ""
        assert result.total_duration_ms == 0
        assert result.bugs_summary == ""
