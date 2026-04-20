"""BookingInvariantMiddleware — pre-tool precondition gate for the booking flow.

Intercepts tool calls before execution and enforces booking-flow invariants.
When a precondition fails, returns a structured ToolMessage with error=True,
a code, and a Spanish description. The LLM reads this as a tool result and
self-corrects on the next turn.

Precondition matrix (design §5.2):

  book:
    - confirmed != True → CONFIRMATION_REQUIRED
    - last_services empty → SERVICES_MISSING
    - no stylist (stylist_id=None AND no_preference_stylist=False) → STYLIST_MISSING
    - selected_slot=None → SLOT_MISSING
    - customer_name empty/None → CUSTOMER_NAME_MISSING
    - pending_disambiguations non-empty → DISAMBIGUATION_PENDING

  check_availability:
    - last_services empty → SERVICES_MISSING
    - pending_disambiguations non-empty → DISAMBIGUATION_PENDING

  update_booking:
    - passes through always (REQ-20)

  All other tools: pass through unchanged.

Mode guard (design §5.2):
  - If ``state.get("current_mode") != mode_name``, all tool calls pass through unchanged.

Error handling (fail-open):
  - Any exception in the middleware itself logs and passes through.

Observability (design §9):
  - ``booking_invariant.rejected`` {tool, code, state_context} on every rejection.
  - ``booking_invariant.passed`` {tool} on every pass.

Design refs: design §5.2, §9
Requirements: R9–R20
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from langchain_core.messages import ToolMessage

from agent.booking.models import ServiceCatalogEntry

logger = logging.getLogger(__name__)

# Tool names covered by the precondition matrix
_UPDATE_BOOKING = "update_booking"
_CHECK_AVAILABILITY = "check_availability"
_BOOK = "book"

# Redis prefix for capability flags (design §6.2)
BOOKING_CAPABILITY_PREFIX = "booking:capability:"


def _make_rejection(tool_call_id: str, code: str, message: str) -> ToolMessage:
    """Create a structured rejection ToolMessage with error=True."""
    content = json.dumps({"error": True, "code": code, "message": message}, ensure_ascii=False)
    return ToolMessage(content=content, tool_call_id=tool_call_id)


def _has_stylist(bc: dict) -> bool:
    """True when a stylist has been selected (named or no-preference)."""
    return bool(bc.get("last_stylist") or bc.get("no_preference_stylist"))


class BookingInvariantMiddleware:
    """Pre-tool precondition gate for the BOOKING flow.

    Args:
        get_state_fn: Zero-arg callable returning the current ConversationState dict.
            Called on each tool invocation — reflects latest state (mid-loop mutations).
        get_catalog_fn: Zero-arg callable returning ``list[ServiceCatalogEntry]``.
            Used for ambiguity checks (R15 — no extra DB calls per invocation).
        mode_name: Mode this middleware guards (default: ``"BOOKING"``).
    """

    # Exposed as class constant so tests can reference it without instantiating
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"

    def __init__(
        self,
        get_state_fn: Callable[[], dict],
        get_catalog_fn: Callable[[], list[ServiceCatalogEntry]],
        mode_name: str = "BOOKING",
    ) -> None:
        self._get_state_fn = get_state_fn
        self._get_catalog_fn = get_catalog_fn
        self._mode_name = mode_name

    # ── Public helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _is_ambiguous_service(name: str, catalog: list[ServiceCatalogEntry]) -> bool:
        """Return True if the service has audience siblings in the catalog.

        Uses the pre-loaded catalog (R15 — O(n) in-memory, no DB hit).
        """
        for entry in catalog:
            if entry.name == name:
                return entry.has_audience_siblings
        return False

    # ── Precondition checks ─────────────────────────────────────────────────

    def _check_book(self, bc: dict, catalog: list[ServiceCatalogEntry]) -> str | None:
        """Evaluate all preconditions for ``book`` tool call.

        Priority order: most critical first.
        Returns the error code string if any precondition fails, else None.
        """
        # 1. Pending disambiguations block everything
        pending = bc.get("pending_disambiguations") or []
        if pending:
            return "DISAMBIGUATION_PENDING"

        # 2. Services must exist
        if not bc.get("last_services"):
            return "SERVICES_MISSING"

        # 3. Stylist must be set (named or no-preference)
        if not _has_stylist(bc):
            return "STYLIST_MISSING"

        # 4. Slot must be selected
        if not bc.get("selected_slot"):
            return "SLOT_MISSING"

        # 5. Customer name must be present
        if not bc.get("customer_name"):
            return "CUSTOMER_NAME_MISSING"

        # 6. Confirmation is required (last check — all data must be present first)
        if not bc.get("confirmed"):
            return self.CONFIRMATION_REQUIRED

        return None

    def _check_availability(self, bc: dict) -> str | None:
        """Evaluate preconditions for ``check_availability`` tool call."""
        # Services must exist
        if not bc.get("last_services"):
            return "SERVICES_MISSING"

        # Pending disambiguations must be resolved first
        pending = bc.get("pending_disambiguations") or []
        if pending:
            return "DISAMBIGUATION_PENDING"

        return None

    def _check(
        self,
        tool_call: Any,
        bc: dict[str, Any],
        catalog: list[ServiceCatalogEntry],
    ) -> str | None:
        """Evaluate preconditions for the given tool call.

        Supports both MagicMock (test) and dict/ToolCallRequest (prod) formats.
        Returns the error code string if any precondition fails, else None.
        """
        # Support both attribute-style (MagicMock, dataclass) and dict-style access
        if hasattr(tool_call, "name"):
            tool_name = tool_call.name
        else:
            tool_name = (tool_call or {}).get("name", "")

        if tool_name == _BOOK:
            return self._check_book(bc, catalog)

        elif tool_name == _CHECK_AVAILABILITY:
            return self._check_availability(bc)

        elif tool_name == _UPDATE_BOOKING:
            # update_booking always passes through (REQ-20)
            return None

        return None

    def _build_rejection_message(self, code: str, bc: dict[str, Any]) -> str:
        """Return a Spanish description for the given error code."""
        if code == "CONFIRMATION_REQUIRED":
            return (
                "El cliente no confirmó la reserva todavía. "
                "confirmed=False en booking_context. "
                "Mostrá el resumen y pedí confirmación primero."
            )
        if code == "SERVICES_MISSING":
            return "No hay servicios registrados. Registrá los servicios primero."
        if code == "STYLIST_MISSING":
            return "No se seleccionó estilista. Pedí que elija un estilista o sin preferencia."
        if code == "SLOT_MISSING":
            return "No se seleccionó un horario. Pedí que elija un slot disponible."
        if code == "CUSTOMER_NAME_MISSING":
            return "Falta el nombre del cliente. Pedí el nombre completo."
        if code == "DISAMBIGUATION_PENDING":
            pending = bc.get("pending_disambiguations") or []
            families = [p.get("family", "?") for p in pending]
            return (
                f"Hay disambiguaciones pendientes: {families}. "
                "Resolvé la audiencia antes de continuar."
            )
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
        return f"Precondición fallida: {code}"

    def _enforce(self, tool_call: Any) -> ToolMessage | None:
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

        # Get tool_call_id safely
        if hasattr(tool_call, "id"):
            tool_call_id = tool_call.id or ""
        else:
            tool_call_id = (tool_call or {}).get("id", "")

        # Get tool_name safely
        if hasattr(tool_call, "name"):
            tool_name = tool_call.name
        else:
            tool_name = (tool_call or {}).get("name", "")

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
            # Normalize code (strip payload after : for AUDIENCE_REQUIRED:svc)
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

    # ── Middleware interface ────────────────────────────────────────────────

    def wrap_tool_call(
        self,
        tool_call: Any,
        handler: Callable,
    ) -> Any:
        """Sync entry point — checks preconditions, calls handler if all pass."""
        rejection = self._enforce(tool_call)
        if rejection is not None:
            return rejection
        return handler(tool_call)

    async def awrap_tool_call(
        self,
        tool_call: Any,
        handler: Callable,
    ) -> Any:
        """Async entry point — checks preconditions, awaits handler if all pass."""
        rejection = self._enforce(tool_call)
        if rejection is not None:
            return rejection
        return await handler(tool_call)


__all__ = ["BookingInvariantMiddleware"]
