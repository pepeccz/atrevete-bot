"""
Tests for update_booking tool — slot_index resolution (T-07) and
audience ambiguity signal (T1 RED phase).

Covers:
1. slot_index=0 (0-based) is rejected (1-based expected) — actually 1-based design, slot_index=1 valid
2. slot_index=5 with 3 offered_slots → error (out of range)
3. slot_index=None → no slot resolution, other fields still work
4. slot_index=1 with no offered_slots in context → error
5. _find_audience_siblings_for_signal helper (T1 RED — helper not yet defined)
6. update_booking audience ambiguity detection (T1 RED — detection block not yet added)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.booking_data_tools import update_booking

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OFFERED_SLOTS = [
    {
        "stylist_name": "Laura",
        "stylist_id": "uuid-laura",
        "start_time": "2026-04-20T10:00:00",
        "end_time": "2026-04-20T11:00:00",
        "date": "2026-04-20",
        "time": "10:00",
    },
    {
        "stylist_name": "Carmen",
        "stylist_id": "uuid-carmen",
        "start_time": "2026-04-20T11:00:00",
        "end_time": "2026-04-20T12:00:00",
        "date": "2026-04-20",
        "time": "11:00",
    },
    {
        "stylist_name": "Ana",
        "stylist_id": "uuid-ana",
        "start_time": "2026-04-20T14:00:00",
        "end_time": "2026-04-20T15:00:00",
        "date": "2026-04-20",
        "time": "14:00",
    },
]


async def _call_update_booking(**kwargs):
    """Invoke the underlying tool function directly, bypassing LangChain wrapping."""
    return await update_booking.coroutine(**kwargs)


# ---------------------------------------------------------------------------
# T-07 Scenario 1: valid slot_index=1 → selected_slot in patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_valid_resolves_selected_slot():
    """slot_index=1 with valid offered_slots → selected_slot appears in patch."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True, f"Expected success, got errors: {result.get('errors')}"
    patch = result["_booking_context_patch"]
    assert "selected_slot" in patch, "selected_slot should be in the patch"

    selected = patch["selected_slot"]
    assert selected["stylist_name"] == "Laura"
    assert selected["stylist_id"] == "uuid-laura"
    assert selected["start_time"] == "2026-04-20T10:00:00"
    assert selected["date"] == "2026-04-20"
    assert selected["time"] == "10:00"


@pytest.mark.asyncio
async def test_slot_index_valid_last_slot_resolves():
    """slot_index=3 (last slot) resolves Ana correctly."""
    result = await _call_update_booking(
        slot_index=3,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    selected = patch["selected_slot"]
    assert selected["stylist_name"] == "Ana"
    assert selected["stylist_id"] == "uuid-ana"


@pytest.mark.asyncio
async def test_slot_index_syncs_last_stylist_when_empty():
    """When last_stylist is not set, slot resolution also sets it from slot data."""
    result = await _call_update_booking(
        slot_index=2,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert (
        patch.get("last_stylist") == "Carmen"
    ), "last_stylist should be synced from slot when not previously set"


@pytest.mark.asyncio
async def test_slot_index_does_not_overwrite_existing_last_stylist():
    """When last_stylist is already set, slot resolution does NOT overwrite it."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={
            "offered_slots": _OFFERED_SLOTS,
            "last_stylist": "Laura",  # already set
        },
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    # last_stylist should NOT appear in patch (no overwrite)
    assert (
        "last_stylist" not in patch
    ), "last_stylist should not be overwritten if already set in context"


# ---------------------------------------------------------------------------
# T-07 Scenario 2: out-of-range slot_index → error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_out_of_range_returns_error():
    """slot_index=5 with only 3 offered_slots → error, no selected_slot in patch."""
    result = await _call_update_booking(
        slot_index=5,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "fuera de rango" in result["errors"][0]
    assert "selected_slot" not in result.get("_booking_context_patch", {})


@pytest.mark.asyncio
async def test_slot_index_zero_out_of_range():
    """slot_index=0 is out of range (1-based), should return error."""
    result = await _call_update_booking(
        slot_index=0,
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "fuera de rango" in result["errors"][0]


# ---------------------------------------------------------------------------
# T-07 Scenario 3: slot_index=None → no slot resolution, other fields work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_none_does_not_resolve():
    """slot_index=None → slot_index branch is skipped, other fields still applied."""
    result = await _call_update_booking(
        slot_index=None,
        notes="alergia al polvo",
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert "selected_slot" not in patch, "slot_index=None should not produce a selected_slot"
    assert patch.get("notes") == "alergia al polvo", "notes should still be applied"


@pytest.mark.asyncio
async def test_slot_index_none_no_context_still_succeeds():
    """slot_index=None with empty context → no errors, tool succeeds."""
    result = await _call_update_booking(
        slot_index=None,
        _current_context={},
    )

    assert result["success"] is True
    assert "selected_slot" not in result["_booking_context_patch"]


# ---------------------------------------------------------------------------
# T-07 Scenario 4: no offered_slots in context → error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_with_no_offered_slots_returns_error():
    """slot_index=1 but no offered_slots in context → error."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={},  # no offered_slots key
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "check_availability" in result["errors"][0]
    assert "selected_slot" not in result.get("_booking_context_patch", {})


@pytest.mark.asyncio
async def test_slot_index_with_empty_offered_slots_returns_error():
    """slot_index=1 with offered_slots=[] → error (empty list)."""
    result = await _call_update_booking(
        slot_index=1,
        _current_context={"offered_slots": []},
    )

    assert result["success"] is False
    assert len(result["errors"]) > 0
    assert "check_availability" in result["errors"][0]


# ---------------------------------------------------------------------------
# Additional: slot_index + other fields in same call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_index_combined_with_notes():
    """slot_index and notes in same call → both applied."""
    result = await _call_update_booking(
        slot_index=2,
        notes="prefiero corte suave",
        _current_context={"offered_slots": _OFFERED_SLOTS},
    )

    assert result["success"] is True
    patch = result["_booking_context_patch"]
    assert patch["selected_slot"]["stylist_name"] == "Carmen"
    assert patch["notes"] == "prefiero corte suave"


# ===========================================================================
# T1 RED — Audience ambiguity signal (helper + detection block)
#
# These tests FAIL on master because:
#   - _find_audience_siblings_for_signal() does not exist yet (ImportError)
#   - update_booking detection block is not yet added
# After Batch B (T3 + T4), all 6 tests must PASS.
# ===========================================================================


# ---------------------------------------------------------------------------
# Helper: _find_audience_siblings_for_signal
# ---------------------------------------------------------------------------


class TestFindAudienceSiblingsForSignal:
    """Unit tests for the private helper _find_audience_siblings_for_signal.

    Expected RED: ImportError / AttributeError — function does not exist yet.
    After T3 (Batch B), all 3 pass.
    """

    @pytest.mark.asyncio
    async def test_find_audience_siblings_positive(self):
        """DB has multiple 'Corte*' services with audience set; helper returns siblings.

        Expected RED: ImportError — _find_audience_siblings_for_signal not yet defined.
        """
        from agent.tools.booking_data_tools import _find_audience_siblings_for_signal

        # Build a mock Service for "Corte Caballero" (audience set, cut principal)
        svc = MagicMock()
        svc.id = "uuid-corte-caballero"
        svc.name = "Corte Caballero"
        svc.audience = "adult_male"
        svc.metadata_ = {"service_type": "principal", "dimension": "cut"}

        # DB rows returned — siblings in the (cut, principal) family
        cut_metadata = {"service_type": "principal", "dimension": "cut"}
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("uuid-cortar", "Cortar", "adult_female", cut_metadata),
            ("uuid-corte-nina", "Corte Niña", "child_female", cut_metadata),
            ("uuid-corte-nino", "Corte Niño", "child_male", cut_metadata),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.tools.booking_data_tools.get_async_session",
            return_value=mock_session,
        ):
            siblings = await _find_audience_siblings_for_signal(svc)

        assert isinstance(siblings, list), f"Expected list, got {type(siblings)}"
        assert set(siblings) == {
            "Cortar",
            "Corte Niña",
            "Corte Niño",
        }, f"Expected full cut-principal family for 'Corte Caballero', got {siblings!r}"

    @pytest.mark.asyncio
    async def test_find_audience_siblings_no_siblings(self):
        """Only single variant exists; helper returns [].

        Expected RED: ImportError — _find_audience_siblings_for_signal not yet defined.
        """
        from agent.tools.booking_data_tools import _find_audience_siblings_for_signal

        svc = MagicMock()
        svc.id = "uuid-tinte"
        svc.name = "Tinte Completo"
        svc.audience = "adult_female"
        svc.metadata_ = {"service_type": "principal", "dimension": "color"}

        # DB returns rows in OTHER dimensions or without principal service_type
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (
                "uuid-other",
                "Cortar",
                "adult_female",
                {"service_type": "principal", "dimension": "cut"},
            ),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.tools.booking_data_tools.get_async_session",
            return_value=mock_session,
        ):
            siblings = await _find_audience_siblings_for_signal(svc)

        assert siblings == [], f"Expected [] for no-sibling case, got {siblings!r}"

    @pytest.mark.asyncio
    async def test_find_audience_siblings_audience_null(self):
        """Resolved service has audience=None; caller decision means this returns [].

        When the queried service itself has audience=None, siblings with audience=None
        are filtered out (the query filters audience IS NOT NULL).
        Expected RED: ImportError — _find_audience_siblings_for_signal not yet defined.
        """
        from agent.tools.booking_data_tools import _find_audience_siblings_for_signal

        # Service with audience=None (unisex/no-audience service)
        svc = MagicMock()
        svc.id = "uuid-lavado"
        svc.name = "Lavado Completo"
        svc.audience = None
        svc.metadata_ = {"service_type": "principal", "dimension": "wash"}

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.tools.booking_data_tools.get_async_session",
            return_value=mock_session,
        ):
            siblings = await _find_audience_siblings_for_signal(svc)

        assert (
            siblings == []
        ), f"Expected [] for audience=None service (no audience siblings), got {siblings!r}"

    @pytest.mark.asyncio
    async def test_find_siblings_for_cortar_returns_full_cut_family(self):
        """Regression: 'Cortar' (adult_female) must find its 3 cut-principal siblings.

        This is the production bug we are fixing — naive split()[0] matching returns
        [] because 'cortar' != 'corte'. Dimension-based grouping must find the family.
        """
        from agent.tools.booking_data_tools import _find_audience_siblings_for_signal

        svc = MagicMock()
        svc.id = "uuid-cortar"
        svc.name = "Cortar"
        svc.audience = "adult_female"
        svc.metadata_ = {"service_type": "principal", "dimension": "cut"}

        cut_meta = {"service_type": "principal", "dimension": "cut"}
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("uuid-corte-nina", "Corte Niña", "child_female", cut_meta),
            ("uuid-corte-nino", "Corte Niño", "child_male", cut_meta),
            ("uuid-corte-caballero", "Corte Caballero", "adult_male", cut_meta),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.tools.booking_data_tools.get_async_session",
            return_value=mock_session,
        ):
            siblings = await _find_audience_siblings_for_signal(svc)

        assert set(siblings) == {
            "Corte Niña",
            "Corte Niño",
            "Corte Caballero",
        }, f"Expected full cut-principal family for 'Cortar', got {siblings!r}"

    @pytest.mark.asyncio
    async def test_find_siblings_excludes_variants(self):
        """Variants (service_type='variant') MUST NOT appear in principal siblings."""
        from agent.tools.booking_data_tools import _find_audience_siblings_for_signal

        svc = MagicMock()
        svc.id = "uuid-cortar"
        svc.name = "Cortar"
        svc.audience = "adult_female"
        svc.metadata_ = {"service_type": "principal", "dimension": "cut"}

        cut_principal = {"service_type": "principal", "dimension": "cut"}
        cut_variant = {
            "service_type": "variant",
            "dimension": "cut",
            "parent_service_name": "Corte Caballero",
        }
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("uuid-corte-caballero", "Corte Caballero", "adult_male", cut_principal),
            # A variant in the SAME dimension with audience — must be excluded
            ("uuid-barba", "Barba", "adult_male", cut_variant),
        ]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "agent.tools.booking_data_tools.get_async_session",
            return_value=mock_session,
        ):
            siblings = await _find_audience_siblings_for_signal(svc)

        assert "Barba" not in siblings, f"Variant should not appear as sibling: {siblings!r}"
        assert "Corte Caballero" in siblings, f"Principal sibling missing: {siblings!r}"


# ---------------------------------------------------------------------------
# Detection block in update_booking
# ---------------------------------------------------------------------------


class TestUpdateBookingAudienceAmbiguity:
    """Detection guard tests for the _audience_ambiguity patch key in update_booking.

    Expected RED: _audience_ambiguity key does not exist yet (detection block missing).
    After T4 (Batch B), all 3 pass.
    """

    @pytest.mark.asyncio
    async def test_update_booking_emits_ambiguity_when_service_has_audience_and_no_hint(self):
        """Tool response patch contains _audience_ambiguity when service has audience and no hint.

        Preconditions:
        - Service "Corte Señora" resolved with audience="adult_female"
        - _current_context has NO service_audience_hint
        - At least 1 sibling returned by _find_audience_siblings_for_signal

        Expected patch: contains _audience_ambiguity with family, resolved_as,
        resolved_audience, variants. success=True always.
        Expected RED: _audience_ambiguity not in patch (detection block missing).
        """
        # Mock resolved service with audience set
        mock_svc = MagicMock()
        mock_svc.name = "Corte Señora"
        mock_svc.audience = "adult_female"
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 45

        # Mock sibling discovery — helper returns at least 1 sibling
        siblings = ["Corte Caballero", "Corte Niño"]

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=siblings,
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Corte Señora"],
                _current_context={},  # no service_audience_hint
            )

        assert result["success"] is True, (
            f"Tool must always return success=True for informational signal. "
            f"Got errors: {result.get('errors')}"
        )
        ctx_patch = result["_booking_context_patch"]
        assert "_audience_ambiguity" in ctx_patch, (
            f"Expected '_audience_ambiguity' in patch when service has audience and no hint. "
            f"Patch keys: {list(ctx_patch.keys())}"
        )
        ambiguity = ctx_patch["_audience_ambiguity"]
        assert "family" in ambiguity, f"Missing 'family' key in _audience_ambiguity: {ambiguity!r}"
        assert "resolved_as" in ambiguity, f"Missing 'resolved_as' in {ambiguity!r}"
        assert "resolved_audience" in ambiguity, f"Missing 'resolved_audience' in {ambiguity!r}"
        assert "variants" in ambiguity, f"Missing 'variants' in {ambiguity!r}"
        assert (
            len(ambiguity["variants"]) >= 2
        ), f"variants must contain resolved service + siblings (≥2). Got {ambiguity['variants']!r}"
        assert ambiguity["resolved_as"] == "Corte Señora"
        assert ambiguity["resolved_audience"] == "adult_female"

    @pytest.mark.asyncio
    async def test_update_booking_suppresses_ambiguity_when_hint_set(self):
        """When ctx has service_audience_hint, patch does NOT have _audience_ambiguity.

        Expected RED: test may accidentally pass if key is simply absent even in
        positive case — but assertion in previous test will catch that. This test
        explicitly confirms suppression when hint IS set.
        """
        mock_svc = MagicMock()
        mock_svc.name = "Corte Señora"
        mock_svc.audience = "adult_female"
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 45

        # Even if siblings exist, hint is already set → no ambiguity signal
        siblings = ["Corte Caballero", "Corte Niño"]

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=siblings,
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Corte Señora"],
                _current_context={"service_audience_hint": "adult_female"},  # hint already set
            )

        assert result["success"] is True
        ctx_patch = result["_booking_context_patch"]
        assert "_audience_ambiguity" not in ctx_patch, (
            f"Expected NO '_audience_ambiguity' in patch when service_audience_hint is set. "
            f"Patch: {ctx_patch!r}"
        )

    @pytest.mark.asyncio
    async def test_update_booking_suppresses_ambiguity_when_audience_null(self):
        """When resolved service has audience=None, no _audience_ambiguity in patch.

        Unisex services (audience=None) do not trigger the disambiguation signal.
        Expected RED: if detection block is absent, key will also be absent —
        but this test documents the INTENT (even when block is added).
        The positive test (emits_ambiguity) confirms the block fires when it should.
        """
        mock_svc = MagicMock()
        mock_svc.name = "Lavado Completo"
        mock_svc.audience = None  # unisex, no audience
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 30

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=[],  # helper returns [] for audience=None services
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Lavado Completo"],
                _current_context={},  # no hint, but service has audience=None
            )

        assert result["success"] is True
        ctx_patch = result["_booking_context_patch"]
        assert "_audience_ambiguity" not in ctx_patch, (
            f"Expected NO '_audience_ambiguity' in patch when service.audience is None. "
            f"Patch: {ctx_patch!r}"
        )


class TestUpdateBookingAudienceAmbiguitySignaledInResponse:
    """Regression tests: response sent to the LLM must signal audience ambiguity
    on the SAME turn it is detected. After B.3 consolidation, the ctx mirror was
    removed and _build_response stopped seeing _audience_ambiguity, causing the
    bot to skip the audience disambiguation step in production (conv_id=5,
    2026-04-21 01:52 UTC).
    """

    @pytest.mark.asyncio
    async def test_response_missing_includes_audiencia_when_ambiguity_patched(self):
        """When update_booking patches _audience_ambiguity, response['missing']
        must contain 'audiencia' and next_step must describe the ambiguity —
        otherwise the LLM has no visible signal and proceeds as if fully resolved.
        """
        mock_svc = MagicMock()
        mock_svc.name = "Cortar"
        mock_svc.audience = "adult_female"
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 45

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=["Corte Caballero", "Corte Niño"],
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Cortar"],
                _current_context={},
            )

        assert result["success"] is True
        assert (
            "_audience_ambiguity" in result["_booking_context_patch"]
        ), "Pre-condition: patch must contain _audience_ambiguity for this regression test"
        assert "audiencia" in result["missing"], (
            f"Regression: response['missing'] must include 'audiencia' when "
            f"ambiguity is patched. Got missing={result['missing']!r}"
        )
        assert (
            "ambigua" in result["next_step"].lower() or "variante" in result["next_step"].lower()
        ), (
            f"Regression: next_step must describe the ambiguity so the LLM asks the "
            f"customer. Got next_step={result['next_step']!r}"
        )


class TestUpdateBookingPendingDisambiguationsShape:
    """Phase 2 RED → GREEN: writer must emit pending_disambiguations as list[dict].

    Expected RED on master: writer uses ``_audience_ambiguity`` (scalar dict).
    Turns GREEN after Phase 2 rename + shape migration.
    """

    @pytest.mark.asyncio
    async def test_writer_emits_pending_disambiguations_as_list(self):
        """update_booking must write patch['pending_disambiguations'] as list[dict],
        not as a scalar dict under '_audience_ambiguity'.

        Acceptance:
        - 'pending_disambiguations' key is present in the patch.
        - Value is a list with at least one item.
        - First item has required keys: family, resolved_as, resolved_audience, variants.
        - '_audience_ambiguity' key must NOT be present (old name fully removed).
        """
        mock_svc = MagicMock()
        mock_svc.name = "Corte Señora"
        mock_svc.audience = "adult_female"
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 45

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=["Corte Caballero", "Corte Niño"],
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Corte Señora"],
                _current_context={},
            )

        ctx_patch = result["_booking_context_patch"]

        assert "_audience_ambiguity" not in ctx_patch, (
            f"Old key '_audience_ambiguity' must NOT be present after Phase 2 rename. "
            f"Patch keys: {list(ctx_patch.keys())}"
        )
        assert "pending_disambiguations" in ctx_patch, (
            f"Expected 'pending_disambiguations' in patch after Phase 2 rename. "
            f"Patch keys: {list(ctx_patch.keys())}"
        )
        disambiguations = ctx_patch["pending_disambiguations"]
        assert isinstance(disambiguations, list), (
            f"pending_disambiguations must be list[dict], got {type(disambiguations)!r}: "
            f"{disambiguations!r}"
        )
        assert len(disambiguations) >= 1, (
            f"pending_disambiguations must contain at least one item. Got {disambiguations!r}"
        )
        item = disambiguations[0]
        for key in ("family", "resolved_as", "resolved_audience", "variants"):
            assert key in item, (
                f"pending_disambiguations[0] missing key '{key}'. Item: {item!r}"
            )

    @pytest.mark.asyncio
    async def test_clear_path_emits_empty_list(self):
        """When service_audience_hint is set, writer must clear pending_disambiguations
        to [] (empty list), not None (old clear path used None).
        """
        mock_svc = MagicMock()
        mock_svc.name = "Corte Señora"
        mock_svc.audience = "adult_female"
        mock_svc.category = MagicMock(value="cabello")
        mock_svc.duration_minutes = 45

        with (
            patch(
                "agent.tools.booking_data_tools._find_audience_siblings_for_signal",
                new_callable=AsyncMock,
                return_value=["Corte Caballero"],
            ),
            patch(
                "agent.tools.availability_tools._resolve_service_by_name",
                new_callable=AsyncMock,
                return_value=mock_svc,
            ),
            patch(
                "agent.tools.availability_tools._get_active_stylists_for_category",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await update_booking.coroutine(
                services=["Corte Señora"],
                service_audience_hint="adult_female",
                _current_context={},
            )

        ctx_patch = result["_booking_context_patch"]

        assert "_audience_ambiguity" not in ctx_patch, (
            "Old key '_audience_ambiguity' must not be present after Phase 2 rename."
        )
        assert "pending_disambiguations" in ctx_patch, (
            f"Clear path must write pending_disambiguations. Patch keys: {list(ctx_patch.keys())}"
        )
        assert ctx_patch["pending_disambiguations"] == [], (
            f"Clear path must set pending_disambiguations=[], got "
            f"{ctx_patch['pending_disambiguations']!r}"
        )
