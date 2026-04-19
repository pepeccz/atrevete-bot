"""BookingInvariantMiddleware — pre-tool precondition gate for the booking flow.

Intercepts tool calls via ``wrap_tool_call`` / ``awrap_tool_call`` before execution and
enforces booking-flow invariants. When a precondition fails, returns a structured
``ToolMessage`` with an error code and Spanish description; the LLM reads this as a tool
result and self-corrects on the next turn.

Precondition matrix (design §5.2):

  update_booking(services=[...])
    - Any service has audience siblings AND no service_audience_hint → AUDIENCE_REQUIRED

  update_booking(stylist_name=...)
    - last_services empty or absent → SERVICES_REQUIRED_BEFORE_STYLIST

  check_availability
    - pending_disambiguations non-empty → DISAMBIGUATION_PENDING

  book
    - confirmed != True → CONFIRMATION_REQUIRED

  All other tools: pass through unchanged.

Mode guard (design §5.2):
  - If ``state.get("current_mode") != mode_name``, all tool calls pass through unchanged.

Error handling (fail-open):
  - Any exception in the middleware itself logs and passes through. The downstream tool
    will still validate its own inputs.

Observability (design §9):
  - ``booking_invariant.rejected`` {tool, code, state_context} on every rejection.
  - ``booking_invariant.passed`` {tool} on every pass.

Design refs: design §5.2, §9
Requirements: R9–R15
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from agent.booking.models import ServiceCatalogEntry

logger = logging.getLogger(__name__)

# Tool names covered by the precondition matrix
_UPDATE_BOOKING = "update_booking"
_CHECK_AVAILABILITY = "check_availability"
_BOOK = "book"


def _make_rejection(tool_call_id: str, code: str, message: str) -> ToolMessage:
    """Create a structured rejection ToolMessage."""
    import json
    content = json.dumps({"error": code, "message": message}, ensure_ascii=False)
    return ToolMessage(content=content, tool_call_id=tool_call_id)


class BookingInvariantMiddleware(AgentMiddleware):
    """Pre-tool precondition gate for the BOOKING flow.

    Args:
        get_state_fn: Zero-arg callable returning the current ConversationState dict.
            Called on each tool invocation — reflects latest state (mid-loop mutations).
        get_catalog_fn: Zero-arg callable returning ``list[ServiceCatalogEntry]``.
            Used for ambiguity checks (R15 — no extra DB calls per invocation).
        mode_name: Mode this middleware guards (default: ``"BOOKING"``).
    """

    def __init__(
        self,
        get_state_fn: Callable[[], dict],
        get_catalog_fn: Callable[[], list[ServiceCatalogEntry]],
        mode_name: str = "BOOKING",
    ) -> None:
        super().__init__()
        self._get_state_fn = get_state_fn
        self._get_catalog_fn = get_catalog_fn
        self._mode_name = mode_name

    # ── Public helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _is_ambiguous_service(name: str, catalog: list[ServiceCatalogEntry]) -> bool:
        """Return True if the service has audience siblings in the catalog.

        Uses the pre-loaded catalog (R15 — O(n) in-memory, no DB hit).

        Args:
            name: Exact service name to check.
            catalog: Expanded service catalog entries.

        Returns:
            True when the service entry has ``has_audience_siblings == True``.
        """
        for entry in catalog:
            if entry.name == name:
                return entry.has_audience_siblings
        return False

    # ── Precondition checks ─────────────────────────────────────────────────

    def _check(
        self,
        tool_call: dict[str, Any],
        bc: dict[str, Any],
        catalog: list[ServiceCatalogEntry],
    ) -> str | None:
        """Evaluate preconditions for ``tool_call`` against booking context.

        Returns:
            Error code string if any precondition fails, else None.
        """
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args") or {}

        if tool_name == _UPDATE_BOOKING:
            # Precondition 1: audience required for ambiguous services
            services = args.get("services")
            if services:
                hint = bc.get("service_audience_hint")
                if not hint:
                    for svc in services:
                        if self._is_ambiguous_service(svc, catalog):
                            return f"AUDIENCE_REQUIRED:{svc}"

            # Precondition 2: services required before stylist
            stylist = args.get("stylist_name")
            if stylist is not None:
                existing_services = bc.get("last_services")
                if not existing_services:
                    return "SERVICES_REQUIRED_BEFORE_STYLIST"

        elif tool_name == _CHECK_AVAILABILITY:
            pending = bc.get("pending_disambiguations") or []
            if pending:
                return "DISAMBIGUATION_PENDING"

        elif tool_name == _BOOK:
            confirmed = bc.get("confirmed")
            if not confirmed:
                return "CONFIRMATION_REQUIRED"

        return None

    def _build_rejection_message(self, code: str, bc: dict[str, Any]) -> str:
        """Return a Spanish description for the given error code."""
        if code.startswith("AUDIENCE_REQUIRED:"):
            svc = code.split(":", 1)[1]
            return (
                f"El servicio '{svc}' tiene variantes de audiencia. "
                "Antes de llamar update_booking, preguntá: "
                "¿es para señora, caballero, niño o bebé?"
            )
        if code == "SERVICES_REQUIRED_BEFORE_STYLIST":
            services = bc.get("last_services") or []
            return (
                f"Estilista recibido antes de registrar servicios. "
                f"services={services}. Registrá los servicios primero."
            )
        if code == "DISAMBIGUATION_PENDING":
            pending = bc.get("pending_disambiguations") or []
            families = [p.get("family", "?") for p in pending]
            return (
                f"Hay disambiguaciones pendientes: {families}. "
                "Resolvé la audiencia antes de verificar disponibilidad."
            )
        if code == "CONFIRMATION_REQUIRED":
            return (
                "El cliente no confirmó la reserva todavía. "
                "confirmed=False en booking_context. "
                "Mostrá el resumen y pedí confirmación primero."
            )
        return f"Precondición fallida: {code}"

    def _enforce(
        self,
        request: ToolCallRequest,
        handler: Callable | None,
    ) -> ToolMessage | None:
        """Run precondition checks. Returns rejection ToolMessage or None on pass."""
        try:
            state = self._get_state_fn()
        except Exception as exc:
            logger.error(
                "booking_invariant.error",
                extra={"booking_invariant.phase": "get_state_fn", "exception": str(exc)},
                exc_info=True,
            )
            return None  # fail-open

        # Mode guard
        if state.get("current_mode") != self._mode_name:
            return None

        try:
            catalog = self._get_catalog_fn()
        except Exception as exc:
            logger.error(
                "booking_invariant.error",
                extra={"booking_invariant.phase": "get_catalog_fn", "exception": str(exc)},
                exc_info=True,
            )
            return None  # fail-open

        bc = state.get("booking_context") or {}
        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        tool_call_id = tool_call.get("id", "")
        _conv_id = state.get("conversation_id")
        _turn = state.get("total_message_count", 0)

        try:
            error_code = self._check(tool_call, bc, catalog)
        except Exception as exc:
            logger.error(
                "booking_invariant.error",
                extra={
                    "booking_invariant.phase": "check",
                    "booking_invariant.tool": tool_name,
                    "booking_invariant.conversation_id": _conv_id,
                    "booking_invariant.turn": _turn,
                    "exception": str(exc),
                },
                exc_info=True,
            )
            return None  # fail-open

        if error_code:
            message = self._build_rejection_message(error_code, bc)
            # Normalize code (strip payload after :)
            code_key = error_code.split(":")[0]
            logger.debug(
                "booking_invariant.rejected",
                extra={
                    "booking_invariant.conversation_id": _conv_id,
                    "booking_invariant.turn": _turn,
                    "booking_invariant.tool": tool_name,
                    "booking_invariant.code": code_key,
                    "booking_invariant.state_context": list(bc.keys()),
                },
            )
            return _make_rejection(tool_call_id, code_key, message)

        logger.debug(
            "booking_invariant.passed",
            extra={
                "booking_invariant.conversation_id": _conv_id,
                "booking_invariant.turn": _turn,
                "booking_invariant.tool": tool_name,
            },
        )
        return None  # pass through

    # ── AgentMiddleware interface ────────────────────────────────────────────

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        """Sync parity — required by AgentMiddleware parity contract (REQ-1)."""
        rejection = self._enforce(request, handler)
        if rejection is not None:
            return rejection
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        """Async path — primary entry point under ``create_agent.ainvoke``."""
        rejection = self._enforce(request, handler)
        if rejection is not None:
            return rejection
        return await handler(request)


__all__ = ["BookingInvariantMiddleware"]
