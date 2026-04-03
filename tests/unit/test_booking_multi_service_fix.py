"""
Unit tests for booking-multi-service-fix requirements.

Covers:
- 4.1: No standalone _HAIR_DENSITY_HINT_MAP / _HAIR_LENGTH_HINT_MAP (removed) —
       clarification dedup + axis-based resolution tested instead
- 4.2: _resolve_user_clarification_selection() with all 3 axes (audience, hair_density, hair_length)
- 4.3: Clarification dedup — replace-by-axis behavior in extract_service_fields Shape 2
- 4.4: search_services schema has hair_density / hair_length params — threaded to resolve_candidates
- 4.5: Cancel/escalate handled by intent_router upstream (booking-mode-restrictor-cleanup Item 2)
       _check_special_intents, _CANCEL_PHRASES, _SOFT_CANCEL_PHRASES removed from BookingMode.

REQ-MSF-1, REQ-MSF-2, REQ-MSF-3, REQ-MSF-4
"""

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode
from agent.modes.tool_extractors import (
    _resolve_user_clarification_selection,
    extract_service_fields,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_clarification_messages(question: str) -> list[dict]:
    """Build a messages list where the last assistant message asked a numbered clarification."""
    return [
        {"role": "user", "content": "quiero mechas"},
        {
            "role": "assistant",
            "content": (f"{question}\n1. Normal\n2. Largo/Denso\n"),
        },
    ]


# =============================================================================
# 4.1: Verify _HAIR_DENSITY_HINT_MAP / _HAIR_LENGTH_HINT_MAP are NOT present as
#      standalone module-level dicts (they were intentionally not added — the
#      resolution is done via _resolve_user_clarification_selection label matching).
# =============================================================================


class TestHintMapsNotPresent:
    """REQ-MSF-1: No rogue standalone hint maps — clarification resolution uses
    _resolve_user_clarification_selection() which does label/value text matching.

    These tests guard against accidental re-introduction of standalone hint maps
    that could conflict with the existing label-based resolution pipeline.
    """

    def test_hair_density_hint_map_not_in_tool_extractors(self):
        """_HAIR_DENSITY_HINT_MAP must NOT exist in tool_extractors module."""
        import agent.modes.tool_extractors as te

        assert not hasattr(te, "_HAIR_DENSITY_HINT_MAP"), (
            "_HAIR_DENSITY_HINT_MAP found in tool_extractors — "
            "the design chose label/value matching over a hint map; "
            "do NOT re-add a standalone map."
        )

    def test_hair_length_hint_map_not_in_tool_extractors(self):
        """_HAIR_LENGTH_HINT_MAP must NOT exist in tool_extractors module."""
        import agent.modes.tool_extractors as te

        assert not hasattr(te, "_HAIR_LENGTH_HINT_MAP"), (
            "_HAIR_LENGTH_HINT_MAP found in tool_extractors — "
            "the design chose label/value matching over a hint map."
        )

    def test_audience_hint_map_is_imported_from_shared(self):
        """AUDIENCE_HINT_MAP is the canonical audience resolver — imported from shared."""
        import agent.modes.tool_extractors as te
        from shared.audience_maps import AUDIENCE_HINT_MAP

        # tool_extractors imports and uses AUDIENCE_HINT_MAP from shared.audience_maps
        assert hasattr(
            te, "AUDIENCE_HINT_MAP"
        ), "AUDIENCE_HINT_MAP must be imported from shared.audience_maps in tool_extractors"
        assert te.AUDIENCE_HINT_MAP is AUDIENCE_HINT_MAP


# =============================================================================
# 4.2: _resolve_user_clarification_selection() — all 3 axes
# =============================================================================


class TestResolveUserClarificationSelectionAllAxes:
    """REQ-MSF-1: _resolve_user_clarification_selection handles audience, hair_density, hair_length."""

    def _make_audience_pending(self) -> dict:
        return {
            "axis": "audience",
            "question_hint": "¿El corte es para caballero, dama, niño, niña o bebé?",
            "options": [
                {
                    "label": "Caballero",
                    "value": "adult_male",
                    "service_name": "Corte Caballero",
                    "service_id": "cc-1",
                    "duration_minutes": 30,
                },
                {
                    "label": "Dama",
                    "value": "adult_female",
                    "service_name": "Corte de Dama",
                    "service_id": "cd-1",
                    "duration_minutes": 40,
                },
            ],
        }

    def _make_hair_density_pending(self) -> dict:
        return {
            "axis": "hair_density",
            "question_hint": "¿Tenés pelo normal o muy denso/largo?",
            "options": [
                {
                    "label": "Normal",
                    "value": "normal",
                    "service_name": "Mechas",
                    "service_id": "m-1",
                    "duration_minutes": 90,
                },
                {
                    "label": "Largo/Denso",
                    "value": "extra",
                    "service_name": "Mechas XL",
                    "service_id": "m-2",
                    "duration_minutes": 120,
                },
            ],
        }

    def _make_hair_length_pending(self) -> dict:
        return {
            "axis": "hair_length",
            "question_hint": "¿Tenés el pelo corto/medio o largo?",
            "options": [
                {
                    "label": "Corto/Medio",
                    "value": "short_medium",
                    "service_name": "Cortar",
                    "service_id": "cs-1",
                    "duration_minutes": 40,
                },
                {
                    "label": "Largo",
                    "value": "long",
                    "service_name": "Cortar Largo",
                    "service_id": "cl-1",
                    "duration_minutes": 50,
                },
            ],
        }

    # ── audience axis ─────────────────────────────────────────────────────────

    def test_audience_numeric_selection_resolves(self):
        """User replies '1' → resolves audience clarification to first option."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_audience_pending()]
        messages = _make_clarification_messages("¿El corte es para caballero o dama?")

        result = _resolve_user_clarification_selection("1", ctx, messages)

        assert result is True
        assert ctx.service_name == "Corte Caballero"
        assert ctx.service_id == "cc-1"
        assert ctx.pending_clarifications == []

    def test_audience_text_label_resolves(self):
        """User replies 'dama' → resolves audience clarification by label text."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_audience_pending()]
        messages = _make_clarification_messages("¿Es para caballero o dama?")

        result = _resolve_user_clarification_selection("dama", ctx, messages)

        assert result is True
        assert ctx.service_name == "Corte de Dama"
        assert ctx.service_id == "cd-1"
        assert ctx.pending_clarifications == []

    def test_audience_no_match_returns_false(self):
        """Unrecognized reply → returns False, context unchanged."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_audience_pending()]
        messages = _make_clarification_messages("¿Caballero o dama?")

        result = _resolve_user_clarification_selection("me da igual", ctx, messages)

        assert result is False
        assert len(ctx.pending_clarifications) == 1  # not consumed

    # ── hair_density axis ─────────────────────────────────────────────────────

    def test_hair_density_numeric_selection_normal(self):
        """User replies '1' → resolves to 'normal' hair density (Mechas)."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        messages = _make_clarification_messages("¿Pelo normal o denso?")

        result = _resolve_user_clarification_selection("1", ctx, messages)

        assert result is True
        assert ctx.service_name == "Mechas"
        assert ctx.service_id == "m-1"
        assert ctx.pending_clarifications == []

    def test_hair_density_numeric_selection_extra(self):
        """User replies '2' → resolves to 'extra' hair density (Mechas XL)."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        messages = _make_clarification_messages("¿Pelo normal o denso?")

        result = _resolve_user_clarification_selection("2", ctx, messages)

        assert result is True
        assert ctx.service_name == "Mechas XL"
        assert ctx.service_id == "m-2"
        assert ctx.pending_clarifications == []

    def test_hair_density_label_text_normal(self):
        """User replies 'normal' → resolves via label text matching."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        messages = _make_clarification_messages("¿Normal o largo/denso?")

        result = _resolve_user_clarification_selection("normal", ctx, messages)

        assert result is True
        assert ctx.service_name == "Mechas"
        assert ctx.pending_clarifications == []

    def test_hair_density_label_text_largo(self):
        """User replies 'largo' → resolves via label substring match (Largo/Denso)."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        messages = _make_clarification_messages("¿Normal o largo/denso?")

        result = _resolve_user_clarification_selection("largo", ctx, messages)

        assert result is True
        assert ctx.service_name == "Mechas XL"
        assert ctx.pending_clarifications == []

    # ── hair_length axis ─────────────────────────────────────────────────────

    def test_hair_length_numeric_short(self):
        """User replies '1' → resolves to short_medium hair length."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_length_pending()]
        messages = _make_clarification_messages("¿Pelo corto o largo?")

        result = _resolve_user_clarification_selection("1", ctx, messages)

        assert result is True
        assert ctx.service_name == "Cortar"
        assert ctx.service_id == "cs-1"
        assert ctx.pending_clarifications == []

    def test_hair_length_numeric_long(self):
        """User replies '2' → resolves to long hair length."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_length_pending()]
        messages = _make_clarification_messages("¿Pelo corto o largo?")

        result = _resolve_user_clarification_selection("2", ctx, messages)

        assert result is True
        assert ctx.service_name == "Cortar Largo"
        assert ctx.service_id == "cl-1"
        assert ctx.pending_clarifications == []

    def test_hair_length_label_text_corto(self):
        """User replies 'corto' → resolves via label text matching (Corto/Medio)."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_length_pending()]
        messages = _make_clarification_messages("¿Corto/medio o largo?")

        result = _resolve_user_clarification_selection("corto", ctx, messages)

        assert result is True
        assert ctx.service_name == "Cortar"
        assert ctx.pending_clarifications == []

    def test_hair_length_label_text_largo(self):
        """User replies 'largo' → resolves via label text matching."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_length_pending()]
        messages = _make_clarification_messages("¿Corto/medio o largo?")

        result = _resolve_user_clarification_selection("largo", ctx, messages)

        assert result is True
        assert ctx.service_name == "Cortar Largo"
        assert ctx.pending_clarifications == []

    # ── guard: no clarification_needed list presented ─────────────────────────

    def test_returns_false_when_no_clarification_presented(self):
        """Guard: if assistant didn't present a numbered list, don't resolve."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        messages = [
            {"role": "user", "content": "quiero mechas"},
            {
                "role": "assistant",
                "content": "¿Tenés preferencia de estilista?",
            },  # No numbered list
        ]

        result = _resolve_user_clarification_selection("1", ctx, messages)

        assert result is False
        assert len(ctx.pending_clarifications) == 1

    def test_returns_false_when_service_already_resolved(self):
        """Guard: don't overwrite an already-resolved service_id."""
        ctx = BookingContext()
        ctx.pending_clarifications = [self._make_hair_density_pending()]
        ctx.service_id = "already-resolved"  # Already set
        messages = _make_clarification_messages("¿Normal o denso?")

        result = _resolve_user_clarification_selection("1", ctx, messages)

        assert result is False
        assert ctx.service_id == "already-resolved"


# =============================================================================
# 4.3: Clarification dedup — replace-by-axis in extract_service_fields Shape 2
# =============================================================================


class TestClarificationDedupByAxis:
    """REQ-MSF-2: Axis-based upsert prevents duplicate pending_clarifications."""

    def test_upsert_replaces_existing_same_axis(self):
        """Second clarification for same axis REPLACES the first one."""
        ctx = BookingContext()
        # First clarification for hair_density
        first_clarification = {
            "axis": "hair_density",
            "question_hint": "¿Normal o extra?",
            "options": [
                {
                    "label": "Normal",
                    "value": "normal",
                    "service_name": "Mechas",
                    "service_id": "m1",
                },
                {
                    "label": "Extra",
                    "value": "extra",
                    "service_name": "Mechas XL",
                    "service_id": "m2",
                },
            ],
        }
        extract_service_fields({"clarification_needed": first_clarification}, ctx)
        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["question_hint"] == "¿Normal o extra?"

        # Second clarification for SAME axis (LLM retry)
        second_clarification = {
            "axis": "hair_density",
            "question_hint": "¿Tenés el pelo fino o grueso?",
            "options": [
                {"label": "Fino", "value": "normal", "service_name": "Mechas", "service_id": "m1"},
                {
                    "label": "Grueso",
                    "value": "extra",
                    "service_name": "Mechas XL",
                    "service_id": "m2",
                },
            ],
        }
        extract_service_fields({"clarification_needed": second_clarification}, ctx)

        # Must have EXACTLY 1 entry (not 2)
        assert len(ctx.pending_clarifications) == 1
        # New entry replaced the old one
        assert ctx.pending_clarifications[0]["question_hint"] == "¿Tenés el pelo fino o grueso?"

    def test_different_axes_both_stored(self):
        """Two different axes → both stored (no dedup between different axes)."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "question_hint": "¿Normal o extra?",
                    "options": [
                        {
                            "label": "Normal",
                            "value": "normal",
                            "service_name": "Svc A",
                            "service_id": "a",
                        },
                        {
                            "label": "Extra",
                            "value": "extra",
                            "service_name": "Svc B",
                            "service_id": "b",
                        },
                    ],
                }
            },
            ctx,
        )
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_length",
                    "question_hint": "¿Corto o largo?",
                    "options": [
                        {
                            "label": "Corto",
                            "value": "short_medium",
                            "service_name": "Svc C",
                            "service_id": "c",
                        },
                        {
                            "label": "Largo",
                            "value": "long",
                            "service_name": "Svc D",
                            "service_id": "d",
                        },
                    ],
                }
            },
            ctx,
        )

        assert len(ctx.pending_clarifications) == 2
        axes = {pc["axis"] for pc in ctx.pending_clarifications}
        assert axes == {"hair_density", "hair_length"}

    def test_audience_axis_dedup(self):
        """Audience axis also deduped — second replaces first."""
        ctx = BookingContext()
        # First audience clarification
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "question_hint": "¿Caballero o dama?",
                    "options": [
                        {
                            "label": "Caballero",
                            "value": "adult_male",
                            "service_name": "Corte Caballero",
                            "service_id": "cc",
                        },
                        {
                            "label": "Dama",
                            "value": "adult_female",
                            "service_name": "Corte Dama",
                            "service_id": "cd",
                        },
                    ],
                }
            },
            ctx,
        )
        assert len(ctx.pending_clarifications) == 1

        # Second for SAME axis (retry)
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "question_hint": "¿Para quién es el corte?",
                    "options": [
                        {
                            "label": "Señor",
                            "value": "adult_male",
                            "service_name": "Corte Caballero",
                            "service_id": "cc",
                        },
                        {
                            "label": "Señora",
                            "value": "adult_female",
                            "service_name": "Corte Dama",
                            "service_id": "cd",
                        },
                    ],
                }
            },
            ctx,
        )

        assert len(ctx.pending_clarifications) == 1
        assert ctx.pending_clarifications[0]["question_hint"] == "¿Para quién es el corte?"

    def test_three_axis_upsert_sequence(self):
        """hair_density added, audience added, hair_density re-added → 2 entries (not 3)."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "question_hint": "¿Normal o extra? (1)",
                    "options": [
                        {"label": "N", "value": "normal", "service_name": "S1", "service_id": "s1"},
                        {"label": "E", "value": "extra", "service_name": "S2", "service_id": "s2"},
                    ],
                }
            },
            ctx,
        )
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "question_hint": "¿Caballero o dama?",
                    "options": [
                        {
                            "label": "C",
                            "value": "adult_male",
                            "service_name": "S3",
                            "service_id": "s3",
                        },
                        {
                            "label": "D",
                            "value": "adult_female",
                            "service_name": "S4",
                            "service_id": "s4",
                        },
                    ],
                }
            },
            ctx,
        )
        # Re-add hair_density (retry scenario)
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "question_hint": "¿Normal o extra? (2 — retry)",
                    "options": [
                        {"label": "N", "value": "normal", "service_name": "S1", "service_id": "s1"},
                        {"label": "E", "value": "extra", "service_name": "S2", "service_id": "s2"},
                    ],
                }
            },
            ctx,
        )

        assert len(ctx.pending_clarifications) == 2
        axes = {pc["axis"] for pc in ctx.pending_clarifications}
        assert axes == {"hair_density", "audience"}
        # hair_density entry must be the updated one
        hd_entry = next(pc for pc in ctx.pending_clarifications if pc["axis"] == "hair_density")
        assert "retry" in hd_entry["question_hint"]

    def test_dedup_preserves_order_fifo(self):
        """After upsert, replaced entry is appended (not inserted at old position)."""
        ctx = BookingContext()
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "question_hint": "HD first",
                    "options": [
                        {"label": "N", "value": "normal", "service_name": "S1", "service_id": "s1"},
                        {"label": "E", "value": "extra", "service_name": "S2", "service_id": "s2"},
                    ],
                }
            },
            ctx,
        )
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "audience",
                    "question_hint": "AUD first",
                    "options": [
                        {
                            "label": "C",
                            "value": "adult_male",
                            "service_name": "S3",
                            "service_id": "s3",
                        },
                    ],
                }
            },
            ctx,
        )
        # Replace hair_density
        extract_service_fields(
            {
                "clarification_needed": {
                    "axis": "hair_density",
                    "question_hint": "HD replaced",
                    "options": [
                        {"label": "N", "value": "normal", "service_name": "S1", "service_id": "s1"},
                        {"label": "E", "value": "extra", "service_name": "S2", "service_id": "s2"},
                    ],
                }
            },
            ctx,
        )

        assert len(ctx.pending_clarifications) == 2
        # audience was second and should remain
        assert ctx.pending_clarifications[0]["axis"] == "audience"
        # hair_density was replaced, now at end
        assert ctx.pending_clarifications[1]["axis"] == "hair_density"
        assert ctx.pending_clarifications[1]["question_hint"] == "HD replaced"


# =============================================================================
# 4.4: search_services schema has hair_density / hair_length params
# =============================================================================


class TestSearchServicesSchemaExtension:
    """REQ-MSF-3: search_services tool accepts hair_density and hair_length params."""

    def test_schema_has_hair_density_field(self):
        """SearchServicesSchema must have hair_density field."""
        from agent.tools.search_services import SearchServicesSchema

        fields = SearchServicesSchema.model_fields
        assert "hair_density" in fields, "SearchServicesSchema missing hair_density field"

    def test_schema_has_hair_length_field(self):
        """SearchServicesSchema must have hair_length field."""
        from agent.tools.search_services import SearchServicesSchema

        fields = SearchServicesSchema.model_fields
        assert "hair_length" in fields, "SearchServicesSchema missing hair_length field"

    def test_hair_density_field_is_optional(self):
        """hair_density must be optional (default None)."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="mechas")
        assert schema.hair_density is None

    def test_hair_length_field_is_optional(self):
        """hair_length must be optional (default None)."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="corte")
        assert schema.hair_length is None

    def test_hair_density_accepts_normal(self):
        """hair_density='normal' must be valid."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="mechas", hair_density="normal")
        assert schema.hair_density == "normal"

    def test_hair_density_accepts_extra(self):
        """hair_density='extra' must be valid."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="mechas", hair_density="extra")
        assert schema.hair_density == "extra"

    def test_hair_length_accepts_short_medium(self):
        """hair_length='short_medium' must be valid."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="corte", hair_length="short_medium")
        assert schema.hair_length == "short_medium"

    def test_hair_length_accepts_long(self):
        """hair_length='long' must be valid."""
        from agent.tools.search_services import SearchServicesSchema

        schema = SearchServicesSchema(query="corte", hair_length="long")
        assert schema.hair_length == "long"

    def test_schema_invalid_hair_density_rejected(self):
        """Invalid hair_density value must be rejected by Pydantic validation."""
        from pydantic import ValidationError

        from agent.tools.search_services import SearchServicesSchema

        with pytest.raises(ValidationError):
            SearchServicesSchema(query="mechas", hair_density="thick")  # Invalid literal

    def test_schema_invalid_hair_length_rejected(self):
        """Invalid hair_length value must be rejected by Pydantic validation."""
        from pydantic import ValidationError

        from agent.tools.search_services import SearchServicesSchema

        with pytest.raises(ValidationError):
            SearchServicesSchema(query="corte", hair_length="muy_largo")  # Invalid literal

    def test_search_services_function_signature_accepts_params(self):
        """The search_services async function must accept hair_density and hair_length."""
        import inspect

        from agent.tools.search_services import search_services

        # LangChain @tool wraps async functions via .coroutine; sync via .func
        underlying = (
            search_services.coroutine
            if getattr(search_services, "coroutine", None) is not None
            else search_services.func
        )

        sig = inspect.signature(underlying)
        param_names = list(sig.parameters.keys())

        assert (
            "hair_density" in param_names
        ), "search_services function missing 'hair_density' parameter"
        assert (
            "hair_length" in param_names
        ), "search_services function missing 'hair_length' parameter"

    def test_search_services_passes_params_to_resolve_candidates(self):
        """Verify hair_density/hair_length are threaded to resolve_candidates() in the function body."""
        import inspect

        from agent.tools.search_services import search_services

        underlying = (
            search_services.coroutine
            if getattr(search_services, "coroutine", None) is not None
            else search_services.func
        )
        source = inspect.getsource(underlying)

        # The function body should pass hair_density and hair_length to resolve_candidates
        assert (
            "hair_density=hair_density" in source
        ), "search_services must thread hair_density to resolve_candidates()"
        assert (
            "hair_length=hair_length" in source
        ), "search_services must thread hair_length to resolve_candidates()"


# =============================================================================
# Phase 3: Mode stability — verify no new inertia guard needed
# =============================================================================


class TestPhase3ModeStability:
    """Phase 3: Verify booking inertia guard already exists in conversation_flow.py.

    The design (D5) stated that Rule 7 already handles mode stability:
    'current_mode=BOOKING and intent not in (cancel, reject, ask_info) → stay BOOKING'

    Cancel/escalate detection is now handled exclusively by intent_router.py upstream
    (Item 2 of booking-mode-restrictor-cleanup). _check_special_intents and the
    _CANCEL_PHRASES / _SOFT_CANCEL_PHRASES constants have been removed.
    """

    def test_cancel_phrases_not_in_booking_mode(self):
        """_CANCEL_PHRASES must NOT exist in booking_mode (removed by restrictor-cleanup)."""
        import agent.modes.booking_mode as bm

        assert not hasattr(bm, "_CANCEL_PHRASES"), (
            "_CANCEL_PHRASES found in booking_mode — it was intentionally removed. "
            "Cancel detection is now handled by intent_router.py upstream."
        )

    def test_soft_cancel_phrases_not_in_booking_mode(self):
        """_SOFT_CANCEL_PHRASES must NOT exist in booking_mode (removed by restrictor-cleanup)."""
        import agent.modes.booking_mode as bm

        assert not hasattr(
            bm, "_SOFT_CANCEL_PHRASES"
        ), "_SOFT_CANCEL_PHRASES found in booking_mode — it was intentionally removed."

    def test_check_special_intents_not_in_booking_mode(self):
        """_check_special_intents must NOT exist in BookingMode (removed by restrictor-cleanup)."""
        assert not hasattr(BookingMode, "_check_special_intents"), (
            "_check_special_intents found in BookingMode — it was intentionally removed. "
            "Cancel/escalate is now handled by intent_router.py."
        )

    def test_handle_has_cancel_intent_fast_path(self):
        """handle() must have a fast-path for intent_name == 'cancel' via router."""
        import inspect

        source = inspect.getsource(BookingMode.handle)
        assert 'intent_name == "cancel"' in source, (
            "BookingMode.handle() missing cancel fast-path — "
            "the router-based cancel detection must be present."
        )

    def test_handle_has_escalate_intent_fast_path(self):
        """handle() must have a fast-path for intent_name == 'escalate' via router."""
        import inspect

        source = inspect.getsource(BookingMode.handle)
        assert (
            'intent_name == "escalate"' in source
        ), "BookingMode.handle() missing escalate fast-path."

    def test_conversation_flow_has_booking_inertia_rule(self):
        """Rule 7 in conversation_flow.py: current_mode=BOOKING + non-cancel/reject/ask_info → stay."""
        import inspect

        import agent.graphs.conversation_flow as cf

        source = inspect.getsource(cf)

        # The rule looks like: if current_mode == "BOOKING" and intent_result.intent not in (...)
        assert (
            'current_mode == "BOOKING"' in source or "current_mode == 'BOOKING'" in source
        ), "No BOOKING mode inertia rule found in conversation_flow.py"
        # The specific inertia guard for non-cancel/reject intents
        assert (
            '"cancel"' in source and '"reject"' in source
        ), "Cancel/reject exit conditions missing from BOOKING inertia guard"

    def test_intent_router_has_booking_context_narrowing(self):
        """Intent router has booking-context narrowing for reject intent."""
        import inspect

        from agent.routing.intent_router import classify_by_keywords

        source = inspect.getsource(classify_by_keywords)

        # Booking-context narrowing: downgrade reject for no-preference phrases
        assert (
            "BOOKING" in source or "booking" in source.lower()
        ), "classify_by_keywords has no BOOKING context narrowing"
