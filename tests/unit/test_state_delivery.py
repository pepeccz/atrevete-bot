"""
Unit tests for agent/core/state_delivery.py — synthetic state-delivery helper.

TDD cycle: C6.2 — helper module (isolated, no wiring).
Covers R1, R2, R4, R5, R6, S2, S3, S4, S5, S7.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_build_response_fn(response: dict | None = None, raise_exc: Exception | None = None):
    """Return a build_response_fn stub.

    If raise_exc is set, the fn raises that exception.
    If response is set, the fn returns that dict.
    Otherwise returns a default valid dict.
    """

    def _fn(ctx: dict, success: bool = True, validation_errors=None) -> dict:
        if raise_exc is not None:
            raise raise_exc
        return response if response is not None else {
            "success": True,
            "collected": ["servicios: Corte Señora"],
            "missing": ["estilista", "fecha/hora", "nombre"],
            "next_step": "Falta: estilista",
            "errors": [],
        }

    return _fn


_SAMPLE_BOOKING_CONTEXT: dict[str, Any] = {
    "last_services": ["Corte Señora"],
    "service_audience_hint": "adult_female",
}


# ---------------------------------------------------------------------------
# C6.2: build_synthetic_state_delivery
# ---------------------------------------------------------------------------


class TestBuildSyntheticStateDelivery:
    """R1, S2, S3: build_synthetic_state_delivery returns [AIMessage, ToolMessage]."""

    def test_returns_list_of_two_messages(self):
        """R1: Must return exactly [AIMessage, ToolMessage]."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response={"success": True, "next_step": "Falta: estilista"},
        )
        assert len(result) == 2
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)

    def test_aimessage_has_empty_content(self):
        """R7, S8: AIMessage content must be empty string (renderer transparency)."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response={"success": True},
        )
        ai_msg = result[0]
        assert ai_msg.content == "", (
            f"AIMessage content must be '' for renderer transparency, got {ai_msg.content!r}"
        )

    def test_aimessage_has_tool_call(self):
        """R1: AIMessage must carry exactly one tool_call matching tool_name and tool_args."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response={"success": True},
        )
        ai_msg = result[0]
        assert len(ai_msg.tool_calls) == 1
        tc = ai_msg.tool_calls[0]
        assert tc["name"] == "update_booking"
        assert tc["args"] == {"services": ["Corte Señora"]}

    def test_toolmessage_content_is_json_of_response(self):
        """R1: ToolMessage content must be JSON of tool_response."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        response = {"success": True, "next_step": "Falta: estilista", "missing": ["estilista"]}
        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response=response,
        )
        tool_msg = result[1]
        parsed = json.loads(tool_msg.content)
        assert parsed == response

    def test_tool_call_ids_match(self):
        """R1: AIMessage tool_call id and ToolMessage tool_call_id must match."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response={"success": True},
        )
        ai_msg, tool_msg = result
        assert ai_msg.tool_calls[0]["id"] == tool_msg.tool_call_id

    def test_explicit_tool_call_id_respected(self):
        """R1: Explicit tool_call_id is preserved."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        explicit_id = "synth-audience-t3-aabbccdd1234"
        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            tool_response={"success": True},
            tool_call_id=explicit_id,
        )
        ai_msg, tool_msg = result
        assert ai_msg.tool_calls[0]["id"] == explicit_id
        assert tool_msg.tool_call_id == explicit_id


# ---------------------------------------------------------------------------
# C6.2: tool_call_id convention (R2, S3)
# ---------------------------------------------------------------------------


class TestToolCallIdConvention:
    """R2, S3: tool_call_id prefix and uniqueness."""

    def test_generated_id_starts_with_synth_prefix(self):
        """R2: auto-generated tool_call_id starts with 'synth-'."""
        from agent.core.state_delivery import (
            SYNTHETIC_TOOL_CALL_ID_PREFIX,
            build_synthetic_state_delivery,
        )

        result = build_synthetic_state_delivery(
            tool_name="update_booking",
            tool_args={},
            tool_response={},
            # No explicit tool_call_id — let the helper generate one
        )
        tool_call_id = result[0].tool_calls[0]["id"]
        assert tool_call_id.startswith(SYNTHETIC_TOOL_CALL_ID_PREFIX), (
            f"Expected id starting with 'synth-', got {tool_call_id!r}"
        )

    def test_generated_id_contains_context_label(self):
        """S3: generated tool_call_id contains context_label substring."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)
        before = dict(ctx)

        def _build_fn(c, success=True, validation_errors=None):
            return {"success": True, "next_step": "Falta: estilista"}

        result = deliver_state_update(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            build_response_fn=_build_fn,
            booking_context=ctx,
            context_label="audience-t3",
        )
        assert len(result) == 2
        tool_call_id = result[0].tool_calls[0]["id"]
        assert "audience-t3" in tool_call_id, (
            f"Expected 'audience-t3' in tool_call_id, got {tool_call_id!r}"
        )

    def test_generated_ids_unique_across_calls(self):
        """S3: No two calls produce identical tool_call_ids."""
        from agent.core.state_delivery import build_synthetic_state_delivery

        ids = set()
        for _ in range(5):
            result = build_synthetic_state_delivery(
                tool_name="update_booking",
                tool_args={},
                tool_response={},
            )
            ids.add(result[0].tool_calls[0]["id"])
        assert len(ids) == 5, f"Expected 5 unique IDs, got {len(ids)}: {ids}"


# ---------------------------------------------------------------------------
# C6.2: deliver_state_update — happy path (R1, S1)
# ---------------------------------------------------------------------------


class TestDeliverStateUpdateHappyPath:
    """R1, S1: deliver_state_update returns [AIMessage, ToolMessage] on success."""

    def test_returns_two_messages_on_success(self):
        """R1, S1: Happy path returns exactly 2 messages."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)
        result = deliver_state_update(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            build_response_fn=_make_build_response_fn(),
            booking_context=ctx,
            context_label="audience-t3",
        )
        assert len(result) == 2
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)

    def test_toolmessage_reflects_build_response(self):
        """R1: ToolMessage content equals JSON of build_response_fn output."""
        from agent.core import deliver_state_update

        expected_response = {
            "success": True,
            "collected": ["servicios: Corte Señora"],
            "missing": ["estilista"],
            "next_step": "Falta: estilista",
            "errors": [],
        }
        ctx = dict(_SAMPLE_BOOKING_CONTEXT)
        result = deliver_state_update(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            build_response_fn=_make_build_response_fn(response=expected_response),
            booking_context=ctx,
        )
        parsed = json.loads(result[1].content)
        assert parsed == expected_response


# ---------------------------------------------------------------------------
# C6.2: purity — input dict not mutated (R6, S2)
# ---------------------------------------------------------------------------


class TestDeliverStateUpdatePurity:
    """R6, S2: booking_context must NOT be mutated by deliver_state_update."""

    def test_input_dict_not_mutated_on_success(self):
        """R6: Original booking_context equality preserved after successful call."""
        from agent.core import deliver_state_update

        ctx = {"last_services": ["Corte Señora"], "service_audience_hint": "adult_female"}
        original = dict(ctx)

        deliver_state_update(
            tool_name="update_booking",
            tool_args={"services": ["Corte Señora"]},
            build_response_fn=_make_build_response_fn(),
            booking_context=ctx,
        )
        assert ctx == original, (
            f"Input dict was mutated. Before: {original!r}, after: {ctx!r}"
        )

    def test_input_dict_not_mutated_on_failure(self):
        """R6: Original booking_context equality preserved even when build_response_fn raises."""
        from agent.core import deliver_state_update

        ctx = {"last_services": ["Corte"], "service_audience_hint": "adult_female"}
        original = dict(ctx)

        deliver_state_update(
            tool_name="update_booking",
            tool_args={},
            build_response_fn=_make_build_response_fn(raise_exc=RuntimeError("boom")),
            booking_context=ctx,
        )
        assert ctx == original


# ---------------------------------------------------------------------------
# C6.2: graceful failure (R1, S4)
# ---------------------------------------------------------------------------


class TestDeliverStateUpdateGracefulFailure:
    """R1, S4: Returns [] on build_response_fn exception or non-dict return."""

    def test_build_response_fn_raises_returns_empty(self, caplog):
        """S4: If build_response_fn raises, returns [] and logs warning."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)
        with caplog.at_level(logging.WARNING, logger="agent.core.state_delivery"):
            result = deliver_state_update(
                tool_name="update_booking",
                tool_args={},
                build_response_fn=_make_build_response_fn(raise_exc=ValueError("bad")),
                booking_context=ctx,
                context_label="audience-t3",
            )
        assert result == [], f"Expected [], got {result!r}"
        assert any("delivered" in r.message or "build_response" in r.message.lower()
                   for r in caplog.records), (
            f"Expected warning log about delivery failure. Records: {[r.message for r in caplog.records]}"
        )

    def test_build_response_fn_returns_non_dict_returns_empty(self, caplog):
        """S4: If build_response_fn returns a non-dict, returns []."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        def _bad_fn(c, success=True, validation_errors=None):
            return "not a dict"  # type: ignore

        with caplog.at_level(logging.WARNING, logger="agent.core.state_delivery"):
            result = deliver_state_update(
                tool_name="update_booking",
                tool_args={},
                build_response_fn=_bad_fn,
                booking_context=ctx,
            )
        assert result == [], f"Expected [], got {result!r}"

    def test_build_response_fn_returns_none_returns_empty(self, caplog):
        """S4: If build_response_fn returns None, returns []."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        def _none_fn(c, success=True, validation_errors=None):
            return None  # type: ignore

        with caplog.at_level(logging.WARNING, logger="agent.core.state_delivery"):
            result = deliver_state_update(
                tool_name="update_booking",
                tool_args={},
                build_response_fn=_none_fn,
                booking_context=ctx,
            )
        assert result == []


# ---------------------------------------------------------------------------
# C6.2: feature flag bypass (R4, S5)
# ---------------------------------------------------------------------------


class TestFeatureFlagBypass:
    """R4, S5: When STATE_DELIVERY_SYNTHETIC_ENABLED=False, returns [] unconditionally."""

    def test_feature_flag_false_returns_empty(self, caplog, monkeypatch):
        """S5: Feature flag False → [] without invoking build_response_fn."""
        monkeypatch.setenv("STATE_DELIVERY_SYNTHETIC_ENABLED", "false")

        from shared.config import Settings
        from unittest.mock import patch

        disabled_settings = Settings()
        assert disabled_settings.state_delivery_synthetic_enabled is False

        from agent.core import deliver_state_update

        call_count = 0

        def _counting_fn(c, success=True, validation_errors=None):
            nonlocal call_count
            call_count += 1
            return {"success": True}

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        with patch("agent.core.state_delivery.get_settings", return_value=disabled_settings):
            with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
                result = deliver_state_update(
                    tool_name="update_booking",
                    tool_args={},
                    build_response_fn=_counting_fn,
                    booking_context=ctx,
                    context_label="audience-t3",
                )

        assert result == [], f"Expected [] when flag disabled, got {result!r}"
        assert call_count == 0, "build_response_fn must NOT be called when flag is False"

        # Telemetry log must be emitted with delivered=False
        telemetry_records = [r for r in caplog.records if "synthetic_state_delivery" in r.message]
        assert telemetry_records, (
            "Expected 'booking.synthetic_state_delivery' log record when flag disabled. "
            f"Records: {[r.message for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# C6.2: telemetry fields (R5, S7)
# ---------------------------------------------------------------------------


class TestTelemetryFields:
    """R5, S7: booking.synthetic_state_delivery log emitted on every call with required fields."""

    def test_telemetry_emitted_on_success(self, caplog):
        """S7: All R5 fields present in telemetry log on successful delivery."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
            result = deliver_state_update(
                tool_name="update_booking",
                tool_args={"services": ["Corte Señora"]},
                build_response_fn=_make_build_response_fn(),
                booking_context=ctx,
                context_label="audience-t3",
                conversation_id="conv-123",
            )

        assert len(result) == 2
        telemetry = [r for r in caplog.records if "synthetic_state_delivery" in r.message]
        assert telemetry, (
            f"Expected 'booking.synthetic_state_delivery' log record. "
            f"Records: {[r.message for r in caplog.records]}"
        )
        record = telemetry[0]
        # R5 fields check
        assert hasattr(record, "conversation_id") or "conversation_id" in vars(record), (
            "conversation_id missing from telemetry record"
        )

    def test_telemetry_delivered_true_on_success(self, caplog):
        """R5: delivered=True in telemetry when messages returned."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
            deliver_state_update(
                tool_name="update_booking",
                tool_args={},
                build_response_fn=_make_build_response_fn(),
                booking_context=ctx,
                context_label="audience-t3",
                conversation_id="conv-abc",
            )

        telemetry = [r for r in caplog.records if "synthetic_state_delivery" in r.message]
        assert telemetry
        # Check delivered=True is in the extra fields
        record = telemetry[0]
        assert getattr(record, "delivered", None) is True, (
            f"Expected delivered=True in log extra, got {getattr(record, 'delivered', 'MISSING')}"
        )

    def test_telemetry_delivered_false_on_failure(self, caplog):
        """R5, S4: delivered=False in telemetry when build_response_fn fails."""
        from agent.core import deliver_state_update

        ctx = dict(_SAMPLE_BOOKING_CONTEXT)

        with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
            deliver_state_update(
                tool_name="update_booking",
                tool_args={},
                build_response_fn=_make_build_response_fn(raise_exc=RuntimeError("boom")),
                booking_context=ctx,
                context_label="audience-t3",
                conversation_id="conv-abc",
            )

        telemetry = [r for r in caplog.records if "synthetic_state_delivery" in r.message]
        assert telemetry
        record = telemetry[0]
        assert getattr(record, "delivered", None) is False, (
            f"Expected delivered=False in log extra, got {getattr(record, 'delivered', 'MISSING')}"
        )
        reason = getattr(record, "reason_if_not_delivered", None)
        assert reason is not None and reason != "", (
            f"Expected non-null reason_if_not_delivered when delivered=False, got {reason!r}"
        )


# ---------------------------------------------------------------------------
# C6.2: SYNTHETIC_TOOL_CALL_ID_PREFIX constant exported
# ---------------------------------------------------------------------------


class TestModuleExports:
    """R2: SYNTHETIC_TOOL_CALL_ID_PREFIX must be exported from agent.core."""

    def test_prefix_constant_exported(self):
        """R2: SYNTHETIC_TOOL_CALL_ID_PREFIX starts with 'synth-'."""
        from agent.core import SYNTHETIC_TOOL_CALL_ID_PREFIX

        assert SYNTHETIC_TOOL_CALL_ID_PREFIX == "synth-"

    def test_deliver_state_update_exported(self):
        from agent.core import deliver_state_update

        assert callable(deliver_state_update)

    def test_build_synthetic_state_delivery_exported(self):
        from agent.core import build_synthetic_state_delivery

        assert callable(build_synthetic_state_delivery)
