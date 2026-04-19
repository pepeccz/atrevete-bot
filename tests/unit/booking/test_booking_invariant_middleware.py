"""
Tests for BookingInvariantMiddleware.

TDD RED: All tests reference agent.booking.middleware.invariants which does NOT exist yet.
Design refs: design §5.2, §6 Q1
Requirements: R9–R15
Scenarios: S10, S11, S12, S13, S14, S15, S33, S37, S38, S39, S40
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from agent.booking.middleware.invariants import BookingInvariantMiddleware
from agent.booking.models import ServiceCatalogEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    name: str,
    audience: str | None = None,
    siblings: list[str] | None = None,
) -> ServiceCatalogEntry:
    """Create a ServiceCatalogEntry with optional siblings."""
    return ServiceCatalogEntry(
        name=name,
        audience=audience,
        siblings=siblings or [],
    )


def _audience_catalog() -> list[ServiceCatalogEntry]:
    """Service catalog with audience-ambiguous services (Corte family)."""
    corte_variants = ["Corte Señora", "Corte Caballero", "Corte Niño"]
    return [
        _make_entry("Corte Señora", audience="adult_female", siblings=corte_variants),
        _make_entry("Corte Caballero", audience="adult_male", siblings=corte_variants),
        _make_entry("Corte Niño", audience="child", siblings=corte_variants),
        _make_entry("Óleo", audience=None, siblings=[]),
        _make_entry("Mechas", audience=None, siblings=[]),
    ]


def _make_tool_call(name: str, args: dict | None = None) -> dict:
    """Create a tool_call dict as LangChain would produce."""
    return {"name": name, "args": args or {}, "id": "call_test_123"}


def _make_request(tool_name: str, args: dict | None = None) -> MagicMock:
    """Build a ToolCallRequest-like mock."""
    req = MagicMock(spec=ToolCallRequest)
    req.tool_call = _make_tool_call(tool_name, args)
    req.state = {}
    return req


def _sync_handler_pass() -> MagicMock:
    """Handler that returns a success ToolMessage."""
    msg = ToolMessage(content="OK", tool_call_id="call_test_123")
    return MagicMock(return_value=msg)


def _async_handler_pass():
    """Async handler that returns a success ToolMessage."""
    async def _h(req):
        return ToolMessage(content="OK", tool_call_id="call_test_123")
    return _h


# ---------------------------------------------------------------------------
# T3.3-A: Class structure (R9)
# ---------------------------------------------------------------------------


class TestBookingInvariantMiddlewareStructure:
    """Middleware must inherit from AgentMiddleware and implement both hook variants."""

    def test_inherits_agent_middleware(self):
        catalog = _audience_catalog()
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: catalog,
        )
        assert isinstance(mw, AgentMiddleware)

    def test_has_wrap_tool_call(self):
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: [],
        )
        assert callable(getattr(mw, "wrap_tool_call", None))

    def test_has_awrap_tool_call(self):
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: [],
        )
        assert callable(getattr(mw, "awrap_tool_call", None))

    def test_default_mode_name_is_booking(self):
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: [],
        )
        assert mw._mode_name == "BOOKING"


# ---------------------------------------------------------------------------
# T3.3-B: Precondition matrix — AUDIENCE_REQUIRED (R10, S10, S11, S33, S34)
# ---------------------------------------------------------------------------


class TestAudienceRequiredPrecondition:
    """update_booking(services=[...]) with ambiguous service and no hint → AUDIENCE_REQUIRED."""

    def test_blocks_ambiguous_service_without_audience_hint(self):
        """S10: Ambiguous service without hint → AUDIENCE_REQUIRED block."""
        catalog = _audience_catalog()
        bc = {}  # no service_audience_hint
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Corte Señora"]})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        # Handler NOT called (tool blocked)
        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert "AUDIENCE_REQUIRED" in str(result.content)

    def test_rejects_message_names_ambiguous_service_family(self):
        """Rejection message references the family name for disambiguation."""
        catalog = _audience_catalog()
        bc = {}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Corte Señora"]})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        content = str(result.content)
        # Message must reference the ambiguity (family name or audience concept)
        assert "Corte" in content or "audiencia" in content or "variante" in content

    def test_passes_through_service_with_audience_hint(self):
        """S11: When service_audience_hint is set, ambiguous service is allowed through."""
        catalog = _audience_catalog()
        bc = {"service_audience_hint": "adult_female"}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Corte Señora"]})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"

    def test_passes_non_ambiguous_service_without_hint(self):
        """S33: Non-audience service (Óleo) passes through without hint."""
        catalog = _audience_catalog()
        bc = {}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Óleo"]})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"

    def test_mixed_services_blocks_on_ambiguous_one(self):
        """S37: Multi-service call — blocks when any service is ambiguous."""
        catalog = _audience_catalog()
        bc = {}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Óleo", "Corte Señora"]})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert "AUDIENCE_REQUIRED" in str(result.content)

    @pytest.mark.asyncio
    async def test_async_blocks_ambiguous_service(self):
        """Async path also blocks ambiguous service."""
        catalog = _audience_catalog()
        bc = {}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Corte Señora"]})
        called = []
        async def handler(r):
            called.append(r)
            return ToolMessage(content="OK", tool_call_id="call_test_123")

        result = await mw.awrap_tool_call(req, handler)

        assert called == []
        assert "AUDIENCE_REQUIRED" in str(result.content)


# ---------------------------------------------------------------------------
# T3.3-C: Precondition matrix — SERVICES_REQUIRED_BEFORE_STYLIST (R11, S12)
# ---------------------------------------------------------------------------


class TestServicesRequiredBeforeStylist:
    """update_booking(stylist_name=...) without services → SERVICES_REQUIRED_BEFORE_STYLIST."""

    def test_blocks_stylist_when_no_services(self):
        """S12: Stylist set before services → block."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {"last_services": []},
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("update_booking", {"stylist_name": "Pilar"})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert "SERVICES_REQUIRED_BEFORE_STYLIST" in str(result.content)

    def test_blocks_stylist_when_services_is_none(self):
        """Also blocks when last_services is None (not just empty list)."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {},  # no last_services at all
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("update_booking", {"stylist_name": "Sofía"})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert "SERVICES_REQUIRED_BEFORE_STYLIST" in str(result.content)

    def test_passes_stylist_when_services_set(self):
        """Stylist allowed when services are already set."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {"last_services": ["Óleo"], "add_more_asked": True},
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("update_booking", {"stylist_name": "Pilar"})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"


# ---------------------------------------------------------------------------
# T3.3-D: Precondition matrix — DISAMBIGUATION_PENDING (R12, S13)
# ---------------------------------------------------------------------------


class TestDisambiguationPending:
    """check_availability with pending disambiguations → DISAMBIGUATION_PENDING."""

    def test_blocks_availability_when_disambiguation_pending(self):
        """S13: Pending disambiguations block check_availability."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {
                "pending_disambiguations": [{"family": "Óleo", "variants": ["Óleo Corto", "Óleo Largo"], "resolved_as": None}],
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
            },
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("check_availability", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert "DISAMBIGUATION_PENDING" in str(result.content)

    def test_passes_availability_when_no_pending_disambiguation(self):
        """check_availability allowed when no pending disambiguations."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {
                "pending_disambiguations": [],
                "last_services": ["Óleo"],
                "last_stylist": "Pilar",
            },
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("check_availability", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"


# ---------------------------------------------------------------------------
# T3.3-E: Precondition matrix — CONFIRMATION_REQUIRED (R13, R14, S14, S15)
# ---------------------------------------------------------------------------


class TestConfirmationRequired:
    """book() without confirmed=True → CONFIRMATION_REQUIRED."""

    def test_blocks_book_when_not_confirmed(self):
        """S14: book() blocked when confirmed=False."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {"confirmed": False},
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert "CONFIRMATION_REQUIRED" in str(result.content)

    def test_blocks_book_when_confirmed_absent(self):
        """book() blocked when confirmed key not present at all (defaults False)."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {},  # no confirmed key
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_not_called()
        assert "CONFIRMATION_REQUIRED" in str(result.content)

    def test_passes_book_when_confirmed(self):
        """S15: book() allowed when confirmed=True."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {"confirmed": True},
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"

    @pytest.mark.asyncio
    async def test_async_blocks_book_when_not_confirmed(self):
        """Async path also blocks book when not confirmed."""
        state = {
            "current_mode": "BOOKING",
            "booking_context": {"confirmed": False},
        }
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        called = []
        async def handler(r):
            called.append(r)
            return ToolMessage(content="OK", tool_call_id="call_test_123")

        result = await mw.awrap_tool_call(req, handler)

        assert called == []
        assert "CONFIRMATION_REQUIRED" in str(result.content)


# ---------------------------------------------------------------------------
# T3.3-F: Mode guard — non-BOOKING modes pass through (design §5.2)
# ---------------------------------------------------------------------------


class TestModeGuardInvariant:
    """Outside BOOKING mode, all tool calls pass through unchanged."""

    def test_passthrough_outside_booking_mode(self):
        state = {"current_mode": "GREETING", "booking_context": {}}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"

    def test_passthrough_when_mode_none(self):
        state = {"current_mode": None, "booking_context": {}}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {"confirmed": True})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()


# ---------------------------------------------------------------------------
# T3.3-G: Unknown tools pass through (R14)
# ---------------------------------------------------------------------------


class TestUnknownToolsPassThrough:
    """Tools not in the precondition matrix pass through unchanged."""

    def test_manage_appointments_passes_through(self):
        state = {"current_mode": "BOOKING", "booking_context": {}}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("manage_appointments", {"action": "list"})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"

    def test_escalate_passes_through(self):
        state = {"current_mode": "BOOKING", "booking_context": {}}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("escalate", {})
        handler = _sync_handler_pass()

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once()
        assert result.content == "OK"


# ---------------------------------------------------------------------------
# T3.3-H: Observability — log events (design §9)
# ---------------------------------------------------------------------------


class TestInvariantObservability:
    """Middleware emits booking_invariant.rejected and booking_invariant.passed."""

    def test_logs_rejected_event_on_block(self):
        from unittest.mock import patch

        catalog = _audience_catalog()
        bc = {}
        state = {"current_mode": "BOOKING", "booking_context": bc}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: catalog,
        )
        req = _make_request("update_booking", {"services": ["Corte Señora"]})
        handler = _sync_handler_pass()

        with patch("agent.booking.middleware.invariants.logger") as mock_logger:
            mw.wrap_tool_call(req, handler)

        all_calls = (
            mock_logger.debug.call_args_list
            + mock_logger.info.call_args_list
            + mock_logger.warning.call_args_list
        )
        rejected_calls = [c for c in all_calls if "booking_invariant.rejected" in str(c)]
        assert len(rejected_calls) >= 1

    def test_logs_passed_event_on_success(self):
        from unittest.mock import patch

        state = {"current_mode": "BOOKING", "booking_context": {"confirmed": True}}
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: state,
            get_catalog_fn=lambda: [],
        )
        req = _make_request("book", {})
        handler = _sync_handler_pass()

        with patch("agent.booking.middleware.invariants.logger") as mock_logger:
            mw.wrap_tool_call(req, handler)

        all_calls = (
            mock_logger.debug.call_args_list
            + mock_logger.info.call_args_list
        )
        passed_calls = [c for c in all_calls if "booking_invariant.passed" in str(c)]
        assert len(passed_calls) >= 1


# ---------------------------------------------------------------------------
# T3.3-I: _is_ambiguous_service helper (design §5.2)
# ---------------------------------------------------------------------------


class TestIsAmbiguousService:
    """_is_ambiguous_service uses ServiceCatalogEntry.has_audience_siblings."""

    def test_ambiguous_service_returns_true(self):
        catalog = _audience_catalog()
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: catalog,
        )
        assert mw._is_ambiguous_service("Corte Señora", catalog) is True

    def test_non_ambiguous_service_returns_false(self):
        catalog = _audience_catalog()
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: catalog,
        )
        assert mw._is_ambiguous_service("Óleo", catalog) is False

    def test_unknown_service_returns_false(self):
        """Unknown service (not in catalog) does not crash and returns False."""
        catalog = _audience_catalog()
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: catalog,
        )
        assert mw._is_ambiguous_service("Tatuaje", catalog) is False

    def test_empty_catalog_returns_false(self):
        mw = BookingInvariantMiddleware(
            get_state_fn=lambda: {},
            get_catalog_fn=lambda: [],
        )
        assert mw._is_ambiguous_service("Corte Señora", []) is False
