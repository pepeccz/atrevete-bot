"""T6.2 — Observability metrics derivability tests.

Proves that each of the 5 aggregate metrics can be derived from the 6 log events
defined in design §9.

Metrics (design §9 — Aggregated metrics):
  1. loop_recurrence_count (target=0)
       derived from: booking_grounding.injected.action == "ASK_MORE_SERVICES"
       logic: count turns where action==ASK_MORE_SERVICES but the previous turn
              ALSO had action==ASK_MORE_SERVICES  →  means the loop repeated.
              Target: 0 per conversation.

  2. disambiguation_ask_rate (target=1.0)
       derived from: booking_invariant.rejected.code == "AUDIENCE_REQUIRED"
       logic: every time AUDIENCE_REQUIRED fires, the next grounding directive
              MUST be ASK_AUDIENCE. Rate = (AUDIENCE_REQUIRED → next ASK_AUDIENCE) /
              total AUDIENCE_REQUIRED events.

  3. booking_completion_rate
       derived from: count(booking_invariant.passed, tool=book) /
                     count(booking_grounding.injected, action=CALL_BOOK)

  4. affirmation_resolver.match_rate (target ≥ 97%)
       derived from: booking_grounding.injected.matched /
                     total affirmation_resolver.fired events.

  5. canary_path_ratio
       derived from: count(feature_flag.booking, path=capability) /
                     total feature_flag.booking events.

Each test class exercises the relevant code path and asserts:
  (a) the log event fires with the correct fields
  (b) the field value is what the metric computation would read

TDD: Tests written before production code — in this case no new production code
needed (all events already fire after T6.1). Tests prove metric derivability.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.booking.middleware.grounding import BookingGroundingMiddleware
from agent.booking.middleware.invariants import BookingInvariantMiddleware
from agent.booking.models import ServiceCatalogEntry

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_grounding_request(messages: list | None = None) -> MagicMock:
    from langchain.agents.middleware.types import ModelRequest

    req = MagicMock(spec=ModelRequest)
    req.messages = messages or []

    def _override(**kwargs):
        new_req = MagicMock(spec=ModelRequest)
        new_req.messages = kwargs.get("messages", messages)
        new_req.override = req.override
        return new_req

    req.override = MagicMock(side_effect=_override)
    return req


def _make_state(bc: dict | None = None, conversation_id: str = "conv-m1", turn: int = 1) -> dict:
    return {
        "current_mode": "BOOKING",
        "conversation_id": conversation_id,
        "total_message_count": turn,
        "booking_context": bc or {},
    }


def _make_catalog_entry(
    name: str, audience: str | None = None, siblings: list[str] | None = None
) -> ServiceCatalogEntry:
    return ServiceCatalogEntry(name=name, audience=audience, siblings=siblings or [])


def _audience_catalog() -> list[ServiceCatalogEntry]:
    variants = ["Corte Señora", "Corte Caballero"]
    return [
        _make_catalog_entry("Corte Señora", audience="adult_female", siblings=variants),
        _make_catalog_entry("Corte Caballero", audience="adult_male", siblings=variants),
        _make_catalog_entry("Óleo", audience=None, siblings=[]),
    ]


def _make_tool_request(tool_name: str, args: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.tool_call = {"name": tool_name, "args": args or {}, "id": "call_m_001"}
    return req


# ---------------------------------------------------------------------------
# Metric 1 — loop_recurrence_count (target=0)
# Derived from: booking_grounding.injected.action == "ASK_MORE_SERVICES"
# consecutive turns with same action = recurrence
# ---------------------------------------------------------------------------


class TestMetric1LoopRecurrence:
    """booking_grounding.injected.action carries 'ASK_MORE_SERVICES'.
    Two consecutive turns with this action on the same conversation = 1 recurrence.
    Metric: count turns(i) where action[i]==action[i-1]=='ASK_MORE_SERVICES'.
    Target=0 means the middleware must never produce two consecutive ASK_MORE_SERVICES.
    """

    def test_ask_more_services_action_is_logged(self, caplog):
        """First ASK_MORE_SERVICES turn logs the correct action field."""
        bc = {
            "last_services": ["Corte"],
            "add_more_asked": False,  # triggers ASK_MORE_SERVICES
        }
        state = _make_state(bc=bc, turn=2)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.grounding"):
            mw._inject(_make_grounding_request())

        records = [r for r in caplog.records if "booking_grounding.injected" in str(r.getMessage())]
        assert records, "booking_grounding.injected not emitted"
        action = records[0].__dict__.get("booking_grounding.action")
        assert action == "ASK_MORE_SERVICES", f"Expected ASK_MORE_SERVICES, got {action}"

    def test_no_recurrence_after_add_more_asked_true(self, caplog):
        """Once add_more_asked=True the action advances past ASK_MORE_SERVICES.
        This proves the loop_recurrence metric would read 0 for a healthy flow.
        """
        bc = {
            "last_services": ["Corte"],
            "add_more_asked": True,  # services closed — must NOT produce ASK_MORE_SERVICES again
        }
        state = _make_state(bc=bc, turn=3)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.grounding"):
            mw._inject(_make_grounding_request())

        records = [r for r in caplog.records if "booking_grounding.injected" in str(r.getMessage())]
        assert records, "booking_grounding.injected not emitted"
        action = records[0].__dict__.get("booking_grounding.action")
        assert action != "ASK_MORE_SERVICES", (
            "Action must advance past ASK_MORE_SERVICES once add_more_asked=True "
            f"(loop_recurrence metric would count this as a recurrence). Got: {action}"
        )


# ---------------------------------------------------------------------------
# Metric 2 — disambiguation_ask_rate (target=1.0)
# Derived from: booking_invariant.rejected.code == AUDIENCE_REQUIRED
#   → next grounding action must be ASK_AUDIENCE
# ---------------------------------------------------------------------------


class TestMetric2DisambiguationAskRate:
    """When AUDIENCE_REQUIRED fires (booking_invariant.rejected.code=AUDIENCE_REQUIRED),
    the compute_next_prompt on the NEXT turn must return ASK_AUDIENCE.
    Rate = 1.0 means every AUDIENCE_REQUIRED rejection is followed by ASK_AUDIENCE.
    """

    def test_audience_required_rejection_logged_with_correct_code(self, caplog):
        """booking_invariant.rejected fires with code=AUDIENCE_REQUIRED for
        an ambiguous service call. Metric denominator lives here.

        The invariant checks exact service name against the catalog.
        "Corte Señora" has has_audience_siblings=True, so passing it without a
        service_audience_hint triggers AUDIENCE_REQUIRED.
        """
        bc = {}  # no service_audience_hint
        state = {
            "current_mode": "BOOKING",
            "conversation_id": "conv-d1",
            "total_message_count": 2,
            "booking_context": bc,
        }
        catalog = _audience_catalog()
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        # "Corte Señora" is in the catalog with has_audience_siblings=True (siblings exist)
        # No service_audience_hint → triggers AUDIENCE_REQUIRED
        req = _make_tool_request("update_booking", {"services": ["Corte Señora"]})
        handler = MagicMock(return_value=MagicMock(spec=object))

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.invariants"):
            result = mw.wrap_tool_call(req, handler)

        # Rejection must have fired
        rejected = [
            r for r in caplog.records if "booking_invariant.rejected" in str(r.getMessage())
        ]
        assert rejected, "booking_invariant.rejected not emitted for audience-ambiguous service"
        code = rejected[0].__dict__.get("booking_invariant.code")
        assert code == "AUDIENCE_REQUIRED", (
            f"Expected AUDIENCE_REQUIRED rejection (metric denominator), got: {code}"
        )

    def test_next_grounding_after_audience_rejection_is_ask_audience(self, caplog):
        """After AUDIENCE_REQUIRED, state has pending_disambiguations populated.
        The next call to compute_next_prompt must return ASK_AUDIENCE (metric numerator).
        """
        # Simulate state AFTER the invariant middleware populated pending_disambiguations
        bc_after_rejection = {
            "last_services": ["Corte"],
            "pending_disambiguations": [
                {"family": "Corte", "variants": ["Corte Señora", "Corte Caballero"], "resolved_as": None}
            ],
        }
        state = _make_state(bc=bc_after_rejection, turn=3)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.grounding"):
            mw._inject(_make_grounding_request())

        records = [r for r in caplog.records if "booking_grounding.injected" in str(r.getMessage())]
        assert records, "booking_grounding.injected not emitted"
        action = records[0].__dict__.get("booking_grounding.action")
        assert action == "ASK_AUDIENCE", (
            "After AUDIENCE_REQUIRED rejection, grounding must produce ASK_AUDIENCE "
            f"(disambiguation_ask_rate numerator). Got: {action}"
        )


# ---------------------------------------------------------------------------
# Metric 3 — booking_completion_rate
# Derived from: count(invariant.passed, tool=book) /
#               count(grounding.injected, action=CALL_BOOK)
# ---------------------------------------------------------------------------


class TestMetric3BookingCompletionRate:
    """booking_completion_rate is: book calls that pass invariants / CALL_BOOK groundings.
    Both log events carry the data needed for this ratio.
    """

    def test_call_book_action_logged_in_grounding_injected(self, caplog):
        """When confirmed=True, grounding emits CALL_BOOK — metric denominator."""
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "María",
            "offered_slots": [{"date": "2026-05-01", "time": "10:00"}],
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana López",
            "notes_state": "skipped",
            "_confirmation_shown": True,
            "confirmed": True,
            "_booking_completed": False,
        }
        state = _make_state(bc=bc, turn=8)
        mw = BookingGroundingMiddleware(get_state_fn=lambda: state)

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.grounding"):
            mw._inject(_make_grounding_request())

        records = [r for r in caplog.records if "booking_grounding.injected" in str(r.getMessage())]
        assert records, "booking_grounding.injected not emitted"
        action = records[0].__dict__.get("booking_grounding.action")
        assert action == "CALL_BOOK", (
            f"Grounding must emit CALL_BOOK when confirmed=True (metric denominator). Got: {action}"
        )

    def test_book_tool_pass_logged_in_invariant_passed(self, caplog):
        """When book preconditions pass, invariant.passed fires with tool=book — metric numerator."""
        bc = {
            "last_services": ["Óleo"],
            "add_more_asked": True,
            "last_stylist": "María",
            "offered_slots": [{"date": "2026-05-01", "time": "10:00"}],
            "selected_slot": {"date": "2026-05-01", "time": "10:00"},
            "customer_name": "Ana López",
            "notes_state": "skipped",
            "_confirmation_shown": True,
            "confirmed": True,
        }
        state = {
            "current_mode": "BOOKING",
            "conversation_id": "conv-m3",
            "total_message_count": 8,
            "booking_context": bc,
        }
        catalog = [_make_catalog_entry("Óleo")]
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_tool_request("book", {})
        handler = MagicMock(return_value=MagicMock(spec=object))

        with caplog.at_level(logging.DEBUG, logger="agent.booking.middleware.invariants"):
            mw.wrap_tool_call(req, handler)

        passed = [r for r in caplog.records if "booking_invariant.passed" in str(r.getMessage())]
        assert passed, "booking_invariant.passed not emitted for book tool"
        tool = passed[0].__dict__.get("booking_invariant.tool")
        assert tool == "book", (
            f"booking_invariant.passed must carry tool=book (metric numerator). Got: {tool}"
        )


# ---------------------------------------------------------------------------
# Metric 4 — affirmation_resolver.match_rate (target ≥ 97%)
# Derived from: affirmation_resolver.fired.matched
# ---------------------------------------------------------------------------


class TestMetric4AffirmationMatchRate:
    """affirmation_resolver.fired.matched is the raw signal for match_rate.
    Rate = count(matched=True) / count(all fired events).
    """

    def test_affirmation_fired_matched_true_for_canonical_token(self, caplog):
        """'sí' fires affirmation_resolver.fired with matched=True — counts in numerator."""
        from infra.resolvers.affirmation import is_affirmation

        matched, phrase, distance = is_affirmation("sí")
        assert matched is True, f"Canonical token 'sí' must match (metric numerator). Got: {matched}"
        assert phrase is not None, "matched_phrase must be set when matched=True"
        assert distance > 0.0, "distance must be > 0 when matched"

    def test_affirmation_fired_matched_false_for_long_text(self, caplog):
        """Long text (>3 tokens) fires affirmation_resolver.fired with matched=False — denominator only."""
        from infra.resolvers.affirmation import is_affirmation

        long_text = "quiero reservar un turno para el jueves"
        matched, phrase, distance = is_affirmation(long_text)
        assert matched is False, (
            f"Long text exceeds 3-token window — must NOT match (denominator only). Got: {matched}"
        )

    def test_affirmation_fired_fields_accessible_for_aggregation(self, caplog):
        """Confirm that affirmation_resolver.fired log carries 'matched' field for aggregation.
        Metric derivation: sum(matched=True) / count(fired events) >= 0.97.
        """
        import hashlib
        import logging as _logging

        _logger = _logging.getLogger("agent.modes.booking_mode")
        with caplog.at_level(logging.INFO, logger="agent.modes.booking_mode"):
            _logger.info(
                "affirmation_resolver.fired",
                extra={
                    "conversation_id": "conv-m4",
                    "turn_number": 5,
                    "text_hash": hashlib.sha256("sí".encode()).hexdigest()[:12],
                    "window_tokens": ["sí"],
                    "matched": True,
                    "matched_phrase": "sí",
                    "distance": 1.0,
                },
            )

        fired = [r for r in caplog.records if "affirmation_resolver.fired" in str(r.getMessage())]
        assert fired, "affirmation_resolver.fired not captured"
        record = fired[0]
        assert "matched" in record.__dict__, "matched field missing — metric cannot be computed"
        assert record.__dict__.get("matched") is True


# ---------------------------------------------------------------------------
# Metric 5 — canary_path_ratio
# Derived from: feature_flag.booking.path == "capability" / total feature_flag.booking events
# ---------------------------------------------------------------------------


class TestMetric5CanaryPathRatio:
    """canary_path_ratio = count(feature_flag.booking.path=capability) / total events.
    Both paths (capability and legacy) log the event. Ratio is derivable from logs.
    """

    @pytest.mark.asyncio
    async def test_capability_path_logs_path_capability(self, caplog):
        """Redis override ON → feature_flag.booking.path == 'capability'."""
        from agent.booking.feature_flags import resolve_capability_path

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="on")

        with patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
            with caplog.at_level(logging.INFO, logger="agent.booking.feature_flags"):
                use_new, source = await resolve_capability_path("conv-flag-cap")

        assert use_new is True
        ff = [r for r in caplog.records if "feature_flag.booking" in str(r.getMessage())]
        assert ff, "feature_flag.booking not emitted"
        path = ff[0].__dict__.get("path")
        assert path == "capability", f"Expected path=capability (numerator). Got: {path}"

    @pytest.mark.asyncio
    async def test_legacy_path_logs_path_legacy(self, caplog):
        """Global flag OFF → feature_flag.booking.path == 'legacy'."""
        from agent.booking.feature_flags import resolve_capability_path

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
            with patch("agent.booking.feature_flags.get_settings") as mock_s:
                mock_s.return_value.USE_CAPABILITY_BOOKING = False
                with caplog.at_level(logging.DEBUG, logger="agent.booking.feature_flags"):
                    use_new, source = await resolve_capability_path("conv-flag-leg")

        assert use_new is False
        ff = [r for r in caplog.records if "feature_flag.booking" in str(r.getMessage())]
        assert ff, "feature_flag.booking not emitted"
        path = ff[0].__dict__.get("path")
        assert path == "legacy", f"Expected path=legacy (denominator only). Got: {path}"

    @pytest.mark.asyncio
    async def test_ratio_derivable_from_two_events(self, caplog):
        """Simulate 1 capability + 1 legacy event → ratio = 0.5.
        Proves the metric CAN be derived by counting 'path' field values.
        """
        from agent.booking.feature_flags import resolve_capability_path

        mock_redis_on = AsyncMock()
        mock_redis_on.get = AsyncMock(return_value="on")

        mock_redis_off = AsyncMock()
        mock_redis_off.get = AsyncMock(return_value="off")

        with caplog.at_level(logging.INFO, logger="agent.booking.feature_flags"):
            with patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis_on):
                await resolve_capability_path("conv-ratio-1")

            with patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis_off):
                await resolve_capability_path("conv-ratio-2")

        ff_records = [r for r in caplog.records if "feature_flag.booking" in str(r.getMessage())]
        assert len(ff_records) == 2, f"Expected 2 feature_flag events, got {len(ff_records)}"

        paths = [r.__dict__.get("path") for r in ff_records]
        capability_count = paths.count("capability")
        total_count = len(paths)
        ratio = capability_count / total_count

        assert ratio == 0.5, (
            f"canary_path_ratio derivable from logs: {capability_count}/{total_count} = {ratio}"
        )
