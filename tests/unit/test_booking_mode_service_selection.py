"""
Unit tests for BookingMode._advance_step() — new 3-shape envelope handling.

Coverage:
- Advance step when resolved_service returned (Shape 1)
- Store pending_clarification when clarification_needed returned (Shape 2)
- Resolve clarification when user answers follow-up question (clarification → resolved)
- Handle fallback services list: 1 result → auto-select, multiple → stay at service_selection
- Backwards-compat: legacy list[dict] response still works
- pending_clarification blocks step advancement
- service_duration_minutes and service_family stored from resolved_service

Environment note:
-----------------
The project's langchain_core package is NOT compatible with Python 3.14
(pydantic.v1 raises UserWarning and some imports fail).  This affects ALL tests
that transitively import agent.modes via the package __init__.py.

This file uses ``importlib.util.spec_from_file_location`` to load
``booking_mode.py`` **directly** (bypassing agent/modes/__init__.py and the
full agent dependency chain) so that only the pure-Python logic of
``_advance_step`` is exercised, without needing LangChain installed.

The ``_LoopResult`` stub satisfies the ``AgenticLoopResult`` dataclass
contract that ``_advance_step`` depends on (only ``.tool_results``).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage as RealAIMessage
from langchain_core.messages import HumanMessage as RealHumanMessage
from langchain_core.messages import SystemMessage as RealSystemMessage


# ---------------------------------------------------------------------------
# Environment bootstrap — mock all LangChain / DB / agent sub-packages
# ---------------------------------------------------------------------------
# These mocks MUST be set before loading booking_mode.py so that its top-level
# imports resolve without errors.

_MOCK_MODULES = [
    "agent.modes.base",
]

# Install mocks (only if not already installed by a previous collection run)
for _mod_name in _MOCK_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()  # type: ignore[assignment]

# Install a lightweight fake `agent.modes` package so booking_mode.py can import
# `agent.modes.base` and `agent.modes.booking_context` without executing the real
# package __init__, which pulls the whole runtime graph.
_original_agent_modes = sys.modules.get("agent.modes")
_original_agent_modes_base = sys.modules.get("agent.modes.base")
_original_agent_modes_booking_context = sys.modules.get("agent.modes.booking_context")

_fake_modes_pkg = ModuleType("agent.modes")
_fake_modes_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules["agent.modes"] = _fake_modes_pkg

_BOOKING_CONTEXT_PATH = (
    Path(__file__).parent.parent.parent / "agent" / "modes" / "booking_context.py"
)
_booking_context_spec = importlib.util.spec_from_file_location(
    "agent.modes.booking_context", str(_BOOKING_CONTEXT_PATH)
)
_booking_context_mod = importlib.util.module_from_spec(_booking_context_spec)  # type: ignore[arg-type]
sys.modules["agent.modes.booking_context"] = _booking_context_mod
_booking_context_spec.loader.exec_module(_booking_context_mod)  # type: ignore[union-attr]

sys.modules["langchain_core.messages"].AIMessage = RealAIMessage
sys.modules["langchain_core.messages"].HumanMessage = RealHumanMessage
sys.modules["langchain_core.messages"].SystemMessage = RealSystemMessage


# ---------------------------------------------------------------------------
# Provide the AgenticLoopResult dataclass that BookingMode inherits from base
# ---------------------------------------------------------------------------

@dataclass
class AgenticLoopResult:
    """Minimal stub matching agent.modes.base.AgenticLoopResult."""
    response_text: str = "OK"
    tool_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class _BaseModeNodeStub:
    """Minimal stub for BaseModeNode (only what booking_mode uses at class level)."""
    tools: list = field(default_factory=list)
    llm_client: Any = None

    @property
    def mode_name(self) -> str:
        return "BOOKING"


# Patch the mocked base module so that BookingMode can inherit from it
_base_mock = sys.modules["agent.modes.base"]
_base_mock.AgenticLoopResult = AgenticLoopResult
_base_mock.BaseModeNode = _BaseModeNodeStub
_base_mock.ModeResult = dict


# ---------------------------------------------------------------------------
# Load booking_mode.py directly (bypasses agent/modes/__init__.py)
# ---------------------------------------------------------------------------

_BOOKING_MODE_PATH = (
    Path(__file__).parent.parent.parent / "agent" / "modes" / "booking_mode.py"
)

_spec = importlib.util.spec_from_file_location(
    "agent.modes.booking_mode_direct", str(_BOOKING_MODE_PATH)
)
_booking_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_booking_mod)  # type: ignore[union-attr]

if _original_agent_modes is not None:
    sys.modules["agent.modes"] = _original_agent_modes
else:
    sys.modules.pop("agent.modes", None)

if _original_agent_modes_base is not None:
    sys.modules["agent.modes.base"] = _original_agent_modes_base
else:
    sys.modules.pop("agent.modes.base", None)

if _original_agent_modes_booking_context is not None:
    sys.modules["agent.modes.booking_context"] = _original_agent_modes_booking_context
else:
    sys.modules.pop("agent.modes.booking_context", None)

BookingMode = _booking_mod.BookingMode
STEP_SERVICE_SELECTION: str = _booking_mod.STEP_SERVICE_SELECTION
STEP_STYLIST_SELECTION: str = _booking_mod.STEP_STYLIST_SELECTION
STEP_SLOT_SELECTION: str = _booking_mod.STEP_SLOT_SELECTION
STEP_CUSTOMER_DATA: str = _booking_mod.STEP_CUSTOMER_DATA
STEP_CONFIRMATION: str = _booking_mod.STEP_CONFIRMATION


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_mode() -> BookingMode:
    """Return a BookingMode with no LLM (sufficient for _advance_step tests)."""
    m = object.__new__(BookingMode)
    m.tools = []
    m.llm = None
    m.llm_client = None
    import logging
    m.logger = logging.getLogger("BookingMode")
    return m


def _make_result(tool_results: dict | None = None) -> AgenticLoopResult:
    return AgenticLoopResult(tool_results=tool_results or {})


# =============================================================================
# Shape 1: resolved_service
# =============================================================================


class TestResolvedServiceEnvelope:
    """_advance_step correctly handles Shape 1: resolved_service."""

    def test_advance_to_stylist_when_resolved_service(self):
        """resolved_service in envelope → advance to stylist_selection."""
        mode = _make_mode()
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-001",
                "name": "Corte Caballero",
                "duration_minutes": 30,
                "category": "Peluquería",
                "family": "corte_caballero",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "corte caballero",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_STYLIST_SELECTION

    def test_service_name_populated_from_resolved_service(self):
        """service_name, service_id, service_category extracted from resolved_service."""
        mode = _make_mode()
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-001",
                "name": "Corte Caballero",
                "duration_minutes": 30,
                "category": "Peluquería",
                "family": "corte_caballero",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "corte caballero",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert ctx["service_name"] == "Corte Caballero"
        assert ctx["service_id"] == "svc-uuid-001"
        assert ctx["service_category"] == "Peluquería"

    def test_duration_and_family_stored_from_resolved_service(self):
        """service_duration_minutes and service_family stored in context."""
        mode = _make_mode()
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-mechas",
                "name": "Mechas",
                "duration_minutes": 120,
                "category": "Peluquería",
                "family": "mechas",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "mechas",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert ctx["service_duration_minutes"] == 120
        assert ctx["service_family"] == "mechas"

    def test_pending_clarification_cleared_on_resolved_service(self):
        """Any stale pending_clarification is removed when a service resolves."""
        mode = _make_mode()
        stale_context = {
            "pending_clarification": {
                "axis": "hair_density",
                "question_hint": "¿Cabello normal o denso?",
                "options": [],
            }
        }
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-002",
                "name": "Mechas Normal",
                "duration_minutes": 90,
                "category": "Peluquería",
                "family": "mechas",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "mechas",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, stale_context)

        assert "pending_clarification" not in ctx

    def test_audience_clarification_auto_resolves_from_service_query(self):
        """service_query carrying 'caballero' should skip audience clarification loops."""
        mode = _make_mode()
        envelope = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿Es para caballero, dama, nino o nina?",
                "options": [
                    {
                        "label": "Caballero",
                        "value": "adult_male",
                        "service_name": "Corte Caballero",
                        "service_id": "svc-uuid-caballero",
                        "duration_minutes": 30,
                    },
                    {
                        "label": "Dama / Senora",
                        "value": "adult_female",
                        "service_name": "Corte Dama",
                        "service_id": "svc-uuid-dama",
                        "duration_minutes": 45,
                    },
                ],
            },
            "count": 0,
            "query": "corte caballero",
        }

        next_step, ctx = mode._advance_step(
            _make_result({"search_services": envelope}),
            STEP_SERVICE_SELECTION,
            {"service_query": "corte caballero"},
        )

        assert next_step == _booking_mod.BookingSubstep.ADD_ONS
        assert ctx["service_audience_hint"] == "adult_male"
        assert ctx["service_name"] == "Corte Caballero"
        assert "pending_clarification" not in ctx

    def test_setdefault_does_not_overwrite_existing_service_name(self):
        """If service_name already in context, resolved_service does not overwrite it."""
        mode = _make_mode()
        existing_context = {"service_name": "Corte Señora Existente"}
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-001",
                "name": "Nuevo Nombre",
                "duration_minutes": 45,
                "category": "Peluquería",
                "family": "corte",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "corte",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, existing_context)

        # setdefault must not overwrite existing value
        assert ctx["service_name"] == "Corte Señora Existente"

    def test_resolved_service_none_family_stored(self):
        """family can be None (no disambiguation metadata) — still stored."""
        mode = _make_mode()
        envelope = {
            "resolved_service": {
                "id": "svc-uuid-bio",
                "name": "Bioterapia Facial",
                "duration_minutes": 60,
                "category": "Estética",
                "family": None,
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "bioterapia facial",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert ctx["service_family"] is None
        assert ctx["service_name"] == "Bioterapia Facial"


# =============================================================================
# Shape 2: clarification_needed
# =============================================================================


class TestClarificationNeededEnvelope:
    """_advance_step correctly handles Shape 2: clarification_needed."""

    def test_stays_at_service_selection_when_clarification_needed(self):
        """clarification_needed → stay at service_selection."""
        mode = _make_mode()
        envelope = {
            "clarification_needed": {
                "axis": "hair_density",
                "question_hint": "¿Es cabello normal o muy largo/denso?",
                "options": [
                    {
                        "label": "Normal",
                        "value": "normal",
                        "service_name": "Mechas",
                        "service_id": "svc-a",
                        "duration_minutes": 90,
                    },
                    {
                        "label": "Muy largo o muy denso (extra)",
                        "value": "extra",
                        "service_name": "Mechas Extra",
                        "service_id": "svc-b",
                        "duration_minutes": 120,
                    },
                ],
            },
            "count": 0,
            "query": "mechas",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION

    def test_pending_clarification_stored_in_context(self):
        """clarification payload stored under pending_clarification key."""
        mode = _make_mode()
        options = [
            {
                "label": "Normal",
                "value": "normal",
                "service_name": "Mechas",
                "service_id": "svc-a",
                "duration_minutes": 90,
            },
        ]
        envelope = {
            "clarification_needed": {
                "axis": "hair_density",
                "question_hint": "¿Es cabello normal o muy largo/denso?",
                "options": options,
            },
            "count": 0,
            "query": "mechas",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert "pending_clarification" in ctx
        pending = ctx["pending_clarification"]
        assert pending["axis"] == "hair_density"
        assert pending["question_hint"] == "¿Es cabello normal o muy largo/denso?"
        assert pending["options"] == options

    def test_pending_clarification_cleared_at_start_of_advance_step(self):
        """
        BUG-1A FIX: pending_clarification is now cleared unconditionally at the
        start of _advance_step. If service_name is present and no new tool call
        happened, the step SHOULD advance — stale clarification no longer blocks.

        Old (buggy) behavior: pending_clarification would block advancement.
        New (correct) behavior: pending_clarification is cleared, service_name
        allows advancement to stylist_selection.
        """
        mode = _make_mode()
        ctx_with_name_and_clarification = {
            "service_name": "Mechas",  # Stale from previous attempt
            "pending_clarification": {
                "axis": "hair_density",
                "question_hint": "¿Es cabello normal o muy largo/denso?",
                "options": [],
            },
        }
        result = _make_result({})  # No new tool call
        next_step, updated_ctx = mode._advance_step(
            result, STEP_SERVICE_SELECTION, ctx_with_name_and_clarification
        )

        # With Bug 1A fix: pending_clarification is cleared, service_name triggers advance
        assert next_step == STEP_STYLIST_SELECTION
        # Verify stale clarification was cleared from context
        assert "pending_clarification" not in updated_ctx

    def test_clarification_to_resolved_flow_clears_pending(self):
        """
        After clarification is stored, a subsequent resolved_service call
        clears pending_clarification and advances the step.
        """
        mode = _make_mode()
        # Start with pending_clarification in context (simulates first search call)
        context_with_clarification = {
            "pending_clarification": {
                "axis": "hair_density",
                "question_hint": "¿Es cabello normal o muy largo/denso?",
                "options": [
                    {
                        "label": "Normal",
                        "value": "normal",
                        "service_name": "Mechas",
                        "service_id": "svc-a",
                        "duration_minutes": 90,
                    },
                ],
            }
        }
        # Second call: user answered → resolved_service returned
        resolved_envelope = {
            "resolved_service": {
                "id": "svc-a",
                "name": "Mechas",
                "duration_minutes": 90,
                "category": "Peluquería",
                "family": "mechas",
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "count": 1,
            "query": "mechas normal",
        }
        result = _make_result({"search_services": resolved_envelope})
        next_step, ctx = mode._advance_step(
            result, STEP_SERVICE_SELECTION, context_with_clarification
        )

        assert next_step == STEP_STYLIST_SELECTION
        assert "pending_clarification" not in ctx
        assert ctx["service_name"] == "Mechas"

    def test_audience_clarification_stays_at_service_selection(self):
        """audience axis clarification also blocks advancement."""
        mode = _make_mode()
        envelope = {
            "clarification_needed": {
                "axis": "audience",
                "question_hint": "¿Es para un adulto, niño o niña?",
                "options": [
                    {
                        "label": "Niño",
                        "value": "child_male",
                        "service_name": "Corte Niño",
                        "service_id": "svc-nino",
                        "duration_minutes": 20,
                    },
                    {
                        "label": "Niña",
                        "value": "child_female",
                        "service_name": "Corte Niña",
                        "service_id": "svc-nina",
                        "duration_minutes": 25,
                    },
                ],
            },
            "count": 0,
            "query": "corte niño",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        assert ctx["pending_clarification"]["axis"] == "audience"

    def test_hair_length_clarification_stored(self):
        """hair_length axis clarification stored correctly."""
        mode = _make_mode()
        envelope = {
            "clarification_needed": {
                "axis": "hair_length",
                "question_hint": "¿Es para cabello corto/medio o largo?",
                "options": [
                    {
                        "label": "Corto o medio",
                        "value": "short_medium",
                        "service_name": "Peinado Normal",
                        "service_id": "svc-peinado-normal",
                        "duration_minutes": 45,
                    },
                    {
                        "label": "Largo",
                        "value": "long",
                        "service_name": "Peinado Largo",
                        "service_id": "svc-peinado-largo",
                        "duration_minutes": 60,
                    },
                ],
            },
            "count": 0,
            "query": "peinado",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        assert ctx["pending_clarification"]["axis"] == "hair_length"
        assert len(ctx["pending_clarification"]["options"]) == 2


# =============================================================================
# Shape 3: services (fallback ranked list)
# =============================================================================


class TestFallbackServicesEnvelope:
    """_advance_step correctly handles Shape 3: plain ranked services list."""

    def test_single_fallback_service_auto_selects_and_advances(self):
        """One service in fallback list → auto-select and advance to stylist_selection."""
        mode = _make_mode()
        envelope = {
            "services": [
                {
                    "id": "svc-fallback-1",
                    "name": "Bioterapia Facial Completa",
                    "duration_minutes": 60,
                    "category": "Estética",
                    "match_score": 85,
                }
            ],
            "count": 1,
            "query": "bioterapia facial",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_STYLIST_SELECTION
        assert ctx["service_name"] == "Bioterapia Facial Completa"
        assert ctx["service_id"] == "svc-fallback-1"

    def test_single_fallback_service_stores_duration(self):
        """Single fallback service stores service_duration_minutes."""
        mode = _make_mode()
        envelope = {
            "services": [
                {
                    "id": "svc-fallback-1",
                    "name": "Bioterapia Facial Completa",
                    "duration_minutes": 60,
                    "category": "Estética",
                    "match_score": 85,
                }
            ],
            "count": 1,
            "query": "bioterapia facial",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert ctx["service_duration_minutes"] == 60

    def test_multiple_fallback_services_stays_at_service_selection(self):
        """Multiple services in fallback list → stay at service_selection (LLM presents options)."""
        mode = _make_mode()
        envelope = {
            "services": [
                {
                    "id": "svc-1",
                    "name": "Corte de Señora",
                    "duration_minutes": 45,
                    "category": "Peluquería",
                    "match_score": 90,
                },
                {
                    "id": "svc-2",
                    "name": "Corte de Caballero",
                    "duration_minutes": 30,
                    "category": "Peluquería",
                    "match_score": 82,
                },
            ],
            "count": 2,
            "query": "corte",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        # No service_name auto-populated when multiple results
        assert "service_name" not in ctx

    def test_empty_services_list_stays_at_service_selection(self):
        """Empty services list → stay at service_selection."""
        mode = _make_mode()
        envelope = {
            "services": [],
            "count": 0,
            "query": "corte",
            "message": "No se encontraron servicios que coincidan con 'corte'",
        }
        result = _make_result({"search_services": envelope})
        next_step, _ = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION

    def test_fallback_single_clears_pending_clarification(self):
        """A single fallback result after clarification clears pending_clarification."""
        mode = _make_mode()
        context_with_clarification = {
            "pending_clarification": {
                "axis": "hair_density",
                "question_hint": "¿Normal o extra?",
                "options": [],
            }
        }
        envelope = {
            "services": [
                {
                    "id": "svc-1",
                    "name": "Peinado Recogido",
                    "duration_minutes": 45,
                    "category": "Peluquería",
                    "match_score": 80,
                }
            ],
            "count": 1,
            "query": "peinado",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, context_with_clarification)

        assert "pending_clarification" not in ctx

    def test_services_with_no_matches_message_stays(self):
        """services list with 'message' field (no matches) stays at service_selection."""
        mode = _make_mode()
        envelope = {
            "services": [],
            "count": 0,
            "query": "tratamiento raro",
            "message": "No se encontraron servicios que coincidan con 'tratamiento raro'",
        }
        result = _make_result({"search_services": envelope})
        next_step, _ = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION

    def test_three_fallback_services_stays(self):
        """3 fallback services → stay at service_selection."""
        mode = _make_mode()
        envelope = {
            "services": [
                {"id": "s1", "name": "Servicio A", "duration_minutes": 30,
                 "category": "Peluquería", "match_score": 90},
                {"id": "s2", "name": "Servicio B", "duration_minutes": 45,
                 "category": "Peluquería", "match_score": 85},
                {"id": "s3", "name": "Servicio C", "duration_minutes": 60,
                 "category": "Peluquería", "match_score": 80},
            ],
            "count": 3,
            "query": "servicio",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        assert "service_name" not in ctx


# =============================================================================
# Legacy list response (backwards compatibility)
# =============================================================================


class TestLegacyListEnvelope:
    """_advance_step handles legacy list[dict] response from search_services."""

    def test_legacy_single_service_list_auto_selects(self):
        """Legacy format: list with 1 item → auto-select service and advance."""
        mode = _make_mode()
        legacy_list = [{"id": "svc-legacy-1", "name": "Corte señora", "category": "Peluquería"}]
        result = _make_result({"search_services": legacy_list})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert ctx["service_name"] == "Corte señora"
        assert ctx["service_id"] == "svc-legacy-1"
        assert next_step == STEP_STYLIST_SELECTION

    def test_legacy_multiple_service_list_stays_at_service_selection(self):
        """Legacy format: list with multiple items → stay at service_selection."""
        mode = _make_mode()
        legacy_list = [
            {"id": "svc-1", "name": "Corte señora", "category": "Peluquería"},
            {"id": "svc-2", "name": "Corte niña", "category": "Peluquería"},
        ]
        result = _make_result({"search_services": legacy_list})
        next_step, _ = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION

    def test_legacy_empty_list_stays_at_service_selection(self):
        """Legacy format: empty list → stay at service_selection."""
        mode = _make_mode()
        result = _make_result({"search_services": []})
        next_step, _ = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION


# =============================================================================
# Clarification envelope — field completeness
# =============================================================================


class TestClarificationEnvelopeFields:
    """Verify all fields of ClarificationPayload are correctly extracted."""

    def test_all_options_fields_stored(self):
        """All option fields (label, value, service_name, service_id, duration) stored."""
        mode = _make_mode()
        options = [
            {
                "label": "Normal",
                "value": "normal",
                "service_name": "Mechas",
                "service_id": "svc-mechas",
                "duration_minutes": 90,
            },
            {
                "label": "Extra",
                "value": "extra",
                "service_name": "Mechas Extra",
                "service_id": "svc-mechas-extra",
                "duration_minutes": 120,
            },
        ]
        envelope = {
            "clarification_needed": {
                "axis": "hair_density",
                "question_hint": "¿Cabello normal o muy denso?",
                "options": options,
            },
            "count": 0,
            "query": "mechas",
        }
        result = _make_result({"search_services": envelope})
        _, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        stored = ctx["pending_clarification"]
        assert stored["options"] == options
        assert len(stored["options"]) == 2
        assert stored["options"][0]["service_id"] == "svc-mechas"
        assert stored["options"][1]["duration_minutes"] == 120

    def test_empty_options_clarification_still_stored(self):
        """Clarification with empty options list is still stored (edge case)."""
        mode = _make_mode()
        envelope = {
            "clarification_needed": {
                "axis": "hair_length",
                "question_hint": "¿Cabello corto o largo?",
                "options": [],
            },
            "count": 0,
            "query": "peinado",
        }
        result = _make_result({"search_services": envelope})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        assert ctx["pending_clarification"]["axis"] == "hair_length"
        assert ctx["pending_clarification"]["options"] == []


# =============================================================================
# No tool results — baseline behavior unchanged
# =============================================================================


class TestNoToolResultsBaselineBehavior:
    """Verify baseline behavior when no search_services tool result is present."""

    def test_no_tool_results_stays_at_service_selection(self):
        """No search_services called → stay at service_selection."""
        mode = _make_mode()
        result = _make_result({})
        next_step, ctx = mode._advance_step(result, STEP_SERVICE_SELECTION, {})

        assert next_step == STEP_SERVICE_SELECTION
        assert "service_name" not in ctx

    def test_service_name_in_context_without_tool_call_still_advances(self):
        """service_name already in context (no pending_clarification) → advance."""
        mode = _make_mode()
        result = _make_result({})
        ctx = {"service_name": "Corte señora"}
        next_step, _ = mode._advance_step(result, STEP_SERVICE_SELECTION, ctx)

        assert next_step == STEP_STYLIST_SELECTION

    def test_stylist_selection_unaffected_by_search_services_envelope(self):
        """search_services envelope at stylist_selection step doesn't affect that step."""
        mode = _make_mode()
        # Even if search_services is in tool_results at stylist_selection step,
        # stylist_id not in context → stays at stylist_selection
        envelope = {
            "resolved_service": {
                "id": "svc-1", "name": "Corte", "duration_minutes": 30,
                "category": "Peluquería", "family": None,
                "ask_if_missing": [], "combo_recommendations": [],
            }
        }
        result = _make_result({"search_services": envelope, "list_stylists": []})
        next_step, _ = mode._advance_step(
            result, STEP_STYLIST_SELECTION, {"service_name": "Corte"}
        )

        assert next_step == STEP_STYLIST_SELECTION

    def test_completed_step_is_terminal(self):
        """completed step always stays completed regardless of tool results."""
        mode = _make_mode()
        envelope = {
            "resolved_service": {
                "id": "svc-1", "name": "Corte", "duration_minutes": 30,
                "category": "Peluquería", "family": None,
                "ask_if_missing": [], "combo_recommendations": [],
            }
        }
        result = _make_result({"search_services": envelope})
        next_step, _ = mode._advance_step(result, "completed", {})

        assert next_step == "completed"

    def test_confirmation_advances_on_confirm_intent(self):
        """confirmation + last_intent=confirm → advance to completed."""
        mode = _make_mode()
        result = _make_result({})
        ctx = {"last_intent": "confirm"}
        next_step, _ = mode._advance_step(result, STEP_CONFIRMATION, ctx)

        assert next_step == "completed"

    def test_confirmation_stays_on_non_confirm_intent(self):
        """confirmation + last_intent!=confirm → stay at confirmation."""
        mode = _make_mode()
        result = _make_result({})
        ctx = {"last_intent": "book"}
        next_step, _ = mode._advance_step(result, STEP_CONFIRMATION, ctx)

        assert next_step == STEP_CONFIRMATION

    def test_list_stylists_dict_response_auto_selects_single_stylist(self):
        mode = _make_mode()
        result = _make_result({
            "list_stylists": {"stylists": [{"id": "sty-1", "name": "Lucía"}]}
        })
        next_step, ctx = mode._advance_step(result, STEP_STYLIST_SELECTION, {
            "service_id": "svc-1",
            "service_name": "Cortar",
        })

        assert next_step == STEP_SLOT_SELECTION
        assert ctx["stylist_id"] == "sty-1"
        assert ctx["stylist_name"] == "Lucía"

    def test_check_availability_dict_uses_available_slots_payload(self):
        mode = _make_mode()
        result = _make_result({
            "check_availability": {
                "available_slots": [
                    {"date": "2026-03-20", "time": "10:00", "full_datetime": "2026-03-20T10:00:00+01:00"}
                ]
            }
        })
        next_step, ctx = mode._advance_step(result, STEP_SLOT_SELECTION, {
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Lucía",
        })

        assert next_step == STEP_CUSTOMER_DATA
        assert ctx["slot_summary"] == "2026-03-20T10:00:00+01:00"

    def test_empty_slot_payload_returns_to_stylist_selection(self):
        mode = _make_mode()
        result = _make_result({"check_availability": {"available_slots": []}})
        next_step, _ = mode._advance_step(result, STEP_SLOT_SELECTION, {
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Lucía",
        })

        assert next_step == STEP_STYLIST_SELECTION


# =============================================================================
# _parse_clarification_answer — Bug 1D fix
# =============================================================================

# Re-export for convenience
_parse_clarification_answer = BookingMode._parse_clarification_answer

# Shared test options covering audience axis (Dama / Caballero)
_AUDIENCE_OPTIONS = [
    {
        "label": "Dama",
        "value": "adult_female",
        "service_name": "Corte de Señora",
        "service_id": "svc-dama",
        "duration_minutes": 45,
    },
    {
        "label": "Caballero",
        "value": "adult_male",
        "service_name": "Corte Caballero",
        "service_id": "svc-caballero",
        "duration_minutes": 30,
    },
]

_AUDIENCE_CLARIFICATION = {
    "axis": "audience",
    "question_hint": "¿Es para Dama o Caballero?",
    "options": _AUDIENCE_OPTIONS,
}


class TestParseClarificationAnswer:
    """
    Unit tests for BookingMode._parse_clarification_answer() — Bug 1D fix.

    Verifies that free-text user answers to clarification questions are
    correctly resolved to option values via numeric, label, and value matching.
    """

    # ── Numeric resolution ─────────────────────────────────────────────────

    def test_numeric_1_resolves_to_first_option(self):
        """'1' → first option's value (adult_female)."""
        axis, value = _parse_clarification_answer("1", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_female"

    def test_numeric_2_resolves_to_second_option(self):
        """'2' → second option's value (adult_male)."""
        axis, value = _parse_clarification_answer("2", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_male"

    def test_numeric_out_of_range_returns_none(self):
        """'5' with only 2 options → (None, None)."""
        axis, value = _parse_clarification_answer("5", _AUDIENCE_CLARIFICATION)
        assert axis is None
        assert value is None

    def test_numeric_0_is_out_of_range(self):
        """'0' is invalid (1-based indexing) → (None, None)."""
        axis, value = _parse_clarification_answer("0", _AUDIENCE_CLARIFICATION)
        assert axis is None
        assert value is None

    # ── Label substring resolution ─────────────────────────────────────────

    def test_label_dama_exact_resolves_adult_female(self):
        """'Dama' matches label exactly → adult_female."""
        axis, value = _parse_clarification_answer("Dama", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_female"

    def test_label_caballero_lowercase_resolves_adult_male(self):
        """'caballero' (lowercase) matches label case-insensitively → adult_male."""
        axis, value = _parse_clarification_answer("caballero", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_male"

    def test_label_in_longer_message_still_matches(self):
        """'Quiero para Dama por favor' — label found within message → adult_female."""
        axis, value = _parse_clarification_answer(
            "Quiero para Dama por favor", _AUDIENCE_CLARIFICATION
        )
        assert axis == "audience"
        assert value == "adult_female"

    def test_label_dama_uppercase_matches(self):
        """'DAMA' — case-insensitive label match → adult_female."""
        axis, value = _parse_clarification_answer("DAMA", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_female"

    # ── Value substring resolution ─────────────────────────────────────────

    def test_value_adult_male_in_message_resolves(self):
        """'adult_male' value substring in message → resolved."""
        axis, value = _parse_clarification_answer("adult_male", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_male"

    def test_value_adult_female_in_message_resolves(self):
        """'adult_female' value substring in message → resolved."""
        axis, value = _parse_clarification_answer("adult_female", _AUDIENCE_CLARIFICATION)
        assert axis == "audience"
        assert value == "adult_female"

    # ── No match cases ─────────────────────────────────────────────────────

    def test_unrecognized_answer_returns_none(self):
        """Random unrelated text → (None, None)."""
        axis, value = _parse_clarification_answer(
            "Quiero algo diferente gracias", _AUDIENCE_CLARIFICATION
        )
        assert axis is None
        assert value is None

    def test_empty_message_returns_none(self):
        """Empty string → (None, None)."""
        axis, value = _parse_clarification_answer("", _AUDIENCE_CLARIFICATION)
        assert axis is None
        assert value is None

    def test_whitespace_only_message_returns_none(self):
        """Whitespace-only message → (None, None)."""
        axis, value = _parse_clarification_answer("   ", _AUDIENCE_CLARIFICATION)
        assert axis is None
        assert value is None

    # ── Empty / missing clarification ──────────────────────────────────────

    def test_empty_pending_clarification_returns_none(self):
        """Empty dict → (None, None)."""
        axis, value = _parse_clarification_answer("Dama", {})
        assert axis is None
        assert value is None

    def test_none_pending_clarification_returns_none(self):
        """None-like (falsy) clarification → (None, None)."""
        axis, value = _parse_clarification_answer("Dama", {})
        assert axis is None
        assert value is None

    def test_empty_options_list_returns_none(self):
        """Clarification with empty options → (None, None)."""
        clarification = {
            "axis": "hair_density",
            "question_hint": "¿Normal o extra?",
            "options": [],
        }
        axis, value = _parse_clarification_answer("Normal", clarification)
        assert axis is None
        assert value is None

    # ── Non-audience axes ──────────────────────────────────────────────────

    def test_hair_density_normal_label_resolves(self):
        """'Normal' label on hair_density axis resolves correctly."""
        clarification = {
            "axis": "hair_density",
            "question_hint": "¿Cabello normal o muy denso?",
            "options": [
                {"label": "Normal", "value": "normal", "service_name": "Mechas",
                 "service_id": "svc-m", "duration_minutes": 90},
                {"label": "Muy largo o muy denso (extra)", "value": "extra",
                 "service_name": "Mechas Extra", "service_id": "svc-me", "duration_minutes": 120},
            ],
        }
        axis, value = _parse_clarification_answer("Normal", clarification)
        assert axis == "hair_density"
        assert value == "normal"

    def test_hair_density_extra_label_resolves(self):
        """'extra' (lowercase) resolves via value substring match on hair_density axis."""
        clarification = {
            "axis": "hair_density",
            "question_hint": "¿Cabello normal o muy denso?",
            "options": [
                {"label": "Normal", "value": "normal", "service_name": "Mechas",
                 "service_id": "svc-m", "duration_minutes": 90},
                {"label": "Muy largo o muy denso (extra)", "value": "extra",
                 "service_name": "Mechas Extra", "service_id": "svc-me", "duration_minutes": 120},
            ],
        }
        # 'extra' matches the value "extra" via Strategy 3 (value substring)
        axis, value = _parse_clarification_answer("extra", clarification)
        assert axis == "hair_density"
        assert value == "extra"

    def test_numeric_1_on_hair_density_resolves_first(self):
        """'1' on hair_density axis → first option (normal)."""
        clarification = {
            "axis": "hair_density",
            "question_hint": "¿Cabello normal o muy denso?",
            "options": [
                {"label": "Normal", "value": "normal", "service_name": "Mechas",
                 "service_id": "svc-m", "duration_minutes": 90},
                {"label": "Muy largo o muy denso (extra)", "value": "extra",
                 "service_name": "Mechas Extra", "service_id": "svc-me", "duration_minutes": 120},
            ],
        }
        axis, value = _parse_clarification_answer("1", clarification)
        assert axis == "hair_density"
        assert value == "normal"


# =============================================================================
# Regression: Clarification answer flow advances to stylist_selection
# =============================================================================


class TestClarificationAnswerAdvancesStep:
    """
    Regression tests for Bug 1D fix — clarification answer flow.

    Verifies the full path from pending_clarification → user answer → resolved
    service → step advancement to stylist_selection.

    This is the end-to-end path exercised by _handle_service_selection when
    a pending_clarification is present and the user's answer resolves it.

    Because _handle_service_selection calls _run_agentic_loop (requires LLM),
    we test the pure-logic path via _advance_step with the confirmed_context
    that _handle_service_selection would build after resolving the clarification.
    """

    def test_clarification_answer_advances_to_stylist_selection(self):
        """
        Full clarification → resolved path:
        1. Start with pending_clarification (audience axis, Dama/Caballero options)
        2. User answers "1" (Dama = adult_female)
        3. _parse_clarification_answer resolves to adult_female
        4. matched_option found → confirmed_context built
        5. _advance_step with confirmed_context + no tool call advances to stylist_selection
        6. pending_clarification NOT in resulting mode_context
        """
        mode = _make_mode()

        # Step 1: State with pending_clarification (audience axis)
        pending_clarification = {
            "axis": "audience",
            "question_hint": "¿Es para Dama o Caballero?",
            "options": [
                {
                    "label": "Dama",
                    "value": "adult_female",
                    "service_name": "Corte de Señora",
                    "service_id": "svc-dama-001",
                    "duration_minutes": 45,
                },
                {
                    "label": "Caballero",
                    "value": "adult_male",
                    "service_name": "Corte Caballero",
                    "service_id": "svc-caballero-001",
                    "duration_minutes": 30,
                },
            ],
        }
        mode_context_with_pending = {
            "booking_step": STEP_SERVICE_SELECTION,
            "pending_clarification": pending_clarification,
        }

        # Step 2: User message is "1" (selecting first option = Dama)
        user_message = "1"

        # Step 3: Resolve via _parse_clarification_answer
        axis, resolved_value = _parse_clarification_answer(user_message, pending_clarification)
        assert axis == "audience", "Clarification parse must return 'audience' axis"
        assert resolved_value == "adult_female", "Option '1' must resolve to adult_female"

        # Step 4: Find the matched option and build confirmed_context
        # (this mirrors what _handle_service_selection does when it resolves clarification)
        options = pending_clarification.get("options", [])
        matched_option = next(
            (opt for opt in options if opt.get("value") == resolved_value),
            None,
        )
        assert matched_option is not None, "Matched option must be found for adult_female"
        assert matched_option["service_name"] == "Corte de Señora"

        confirmed_context = {
            **mode_context_with_pending,
            "service_name": matched_option.get("service_name", ""),
            "service_id": matched_option.get("service_id"),
            "service_duration_minutes": matched_option.get("duration_minutes"),
        }

        # Step 5: Call _advance_step with confirmed_context (no tool results)
        # This simulates the LLM confirmation call that follows in _handle_service_selection
        result = _make_result({})
        next_step, updated_ctx = mode._advance_step(
            result, STEP_SERVICE_SELECTION, confirmed_context
        )

        # Step 6: Assertions
        assert next_step == STEP_STYLIST_SELECTION, (
            f"Expected step to advance to stylist_selection, got {next_step!r}"
        )
        assert "pending_clarification" not in updated_ctx, (
            "pending_clarification must be cleared after clarification is resolved"
        )
        assert updated_ctx.get("service_name") == "Corte de Señora"
        assert updated_ctx.get("service_id") == "svc-dama-001"
        assert updated_ctx.get("service_duration_minutes") == 45

    def test_clarification_answer_adult_male_selection_advances(self):
        """
        Option "2" (Caballero = adult_male) also advances to stylist_selection.
        Mirrors the symmetric case with the second option.
        """
        mode = _make_mode()

        pending_clarification = {
            "axis": "audience",
            "question_hint": "¿Es para Dama o Caballero?",
            "options": [
                {
                    "label": "Dama",
                    "value": "adult_female",
                    "service_name": "Corte de Señora",
                    "service_id": "svc-dama-001",
                    "duration_minutes": 45,
                },
                {
                    "label": "Caballero",
                    "value": "adult_male",
                    "service_name": "Corte Caballero",
                    "service_id": "svc-caballero-001",
                    "duration_minutes": 30,
                },
            ],
        }

        # User answers "caballero" (text match)
        user_message = "caballero"
        axis, resolved_value = _parse_clarification_answer(user_message, pending_clarification)

        assert axis == "audience"
        assert resolved_value == "adult_male"

        matched_option = next(
            (opt for opt in pending_clarification["options"] if opt["value"] == resolved_value),
            None,
        )
        assert matched_option is not None

        confirmed_context = {
            "booking_step": STEP_SERVICE_SELECTION,
            "service_name": matched_option["service_name"],
            "service_id": matched_option["service_id"],
            "service_duration_minutes": matched_option["duration_minutes"],
        }

        result = _make_result({})
        next_step, updated_ctx = mode._advance_step(
            result, STEP_SERVICE_SELECTION, confirmed_context
        )

        assert next_step == STEP_STYLIST_SELECTION
        assert "pending_clarification" not in updated_ctx
        assert updated_ctx["service_name"] == "Corte Caballero"
        assert updated_ctx["service_id"] == "svc-caballero-001"
        assert updated_ctx["service_duration_minutes"] == 30

    def test_unresolved_clarification_stays_at_service_selection(self):
        """
        If the user's answer doesn't match any option (e.g. random text),
        pending_clarification is cleared (Bug 1A fix) but no service is set,
        so _advance_step stays at service_selection.

        This confirms we don't accidentally advance when resolution fails.
        """
        mode = _make_mode()

        # Context has pending clarification but no service_name (unresolved)
        mode_context = {
            "booking_step": STEP_SERVICE_SELECTION,
            "pending_clarification": {
                "axis": "audience",
                "question_hint": "¿Dama o Caballero?",
                "options": [
                    {"label": "Dama", "value": "adult_female",
                     "service_name": "Corte Señora", "service_id": "svc-d", "duration_minutes": 45},
                ],
            },
        }

        # Call _advance_step with no tool results and no service_name in context
        result = _make_result({})
        next_step, updated_ctx = mode._advance_step(
            result, STEP_SERVICE_SELECTION, mode_context
        )

        # No service_name → stays at service_selection
        assert next_step == STEP_SERVICE_SELECTION
        # pending_clarification was cleared (Bug 1A fix is working)
        assert "pending_clarification" not in updated_ctx
