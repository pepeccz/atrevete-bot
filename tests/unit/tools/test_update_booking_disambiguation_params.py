"""T2.3 RED / T2.5 RED — Tests for new update_booking disambiguation parameters.

T2.3 tests:
  - variant_resolved=True bypasses variant gate (REQ-TL-1, ADR-DR-1)
  - variant_resolved=False preserves current behavior (REQ-TL-1 backward-compat)

T2.5 tests (placeholder stubs — GREEN in Slice 2b):
  - pre_resolved_service_ids bypasses resolution for known UUIDs (REQ-TL-2, ADR-DR-2)
  - UUID validation guard rejects inactive/unknown UUIDs (AR5)

All tests patch DB helpers and run without a live database.

Refs: REQ-TL-1, REQ-TL-2, ADR-DR-1, ADR-DR-2, NFR-1 (backward compat)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = uuid4()
FAKE_STYLIST_ID = uuid4()


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _make_variant_ambiguous_strict_mock(principal_uuid: str):
    """Return an AsyncMock for _resolve_service_ids_strict that fires variant_required.

    The principal itself is ambiguous (has variants) — resolver returns it in
    ambiguous_descriptors, not in resolved_ids.
    """
    return AsyncMock(
        return_value=(
            [],  # resolved_ids — empty (nothing committed when ambiguous)
            [],  # unknown_names
            [
                {
                    "status": "ambiguous",
                    "axis": "variant",
                    "service_term": "Tinte",
                    "family_label": "Tinte",
                    "candidates": ["Tinte Extra", "Tinte Completo"],
                    "question_hint": "variant_required",
                }
            ],  # ambiguous_descriptors
            [],  # partial_resolved_ids
        )
    )


def _make_clean_strict_mock(service_uuid: str):
    """Return an AsyncMock for _resolve_service_ids_strict that resolves cleanly."""
    return AsyncMock(
        return_value=(
            [service_uuid],  # resolved_ids
            [],  # unknown_names
            [],  # ambiguous_descriptors
            [],  # partial_resolved_ids
        )
    )


def _make_common_mocks(strict_mock: AsyncMock):
    """Build the standard patch dict for _update_booking_impl internals."""
    from database.models import ServiceCategory

    fake_session = AsyncMock()
    fake_cm = AsyncMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_session)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    return {
        "agent.tools._booking_helpers._resolve_service_ids": AsyncMock(
            return_value=([str(FAKE_SERVICE_ID)], [])
        ),
        "agent.tools._booking_helpers._resolve_service_ids_strict": strict_mock,
        "agent.tools._booking_helpers._resolve_service_categories": AsyncMock(
            return_value={ServiceCategory.HAIRDRESSING}
        ),
        "agent.tools._booking_helpers._resolve_service_id_to_category_map": AsyncMock(
            return_value={}
        ),
        "agent.tools._booking_helpers._resolve_audience_variants": AsyncMock(
            return_value=("ok", None, [])
        ),
        "agent.tools._booking_helpers._resolve_stylist": AsyncMock(return_value=None),
        "agent.tools._booking_helpers._resolve_active_stylists": AsyncMock(return_value=[]),
        "agent.tools._booking_helpers._validate_full_name": MagicMock(return_value=None),
        "database.connection.get_async_session": MagicMock(return_value=fake_cm),
        "agent.tools._booking_validators.is_date_closed": AsyncMock(return_value=False),
    }


# ---------------------------------------------------------------------------
# T2.3 RED — variant_resolved parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_resolved_false_preserves_variant_required():
    """T2.3 RED (backward compat): variant_resolved=False — variant gate still fires.

    Current behavior: when _resolve_service_ids_strict returns ambiguous descriptor
    with axis=variant, tool returns status=ambiguous, next_step=variant_required.
    Default variant_resolved=False MUST NOT change this behavior.
    """
    from agent.tools.update_booking import _update_booking_impl

    strict_mock = _make_variant_ambiguous_strict_mock(str(FAKE_SERVICE_ID))
    mocks = _make_common_mocks(strict_mock)

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["Tinte"],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            variant_resolved=False,  # explicit default
        )

    data = parse_response(raw)
    assert data["status"] == "ambiguous", (
        f"Expected status=ambiguous when variant_resolved=False and service has variants, "
        f"got: {data}"
    )
    assert (
        data["next_step"] == "variant_required"
    ), f"Expected next_step=variant_required, got: {data}"


@pytest.mark.asyncio
async def test_variant_resolved_true_bypasses_variant_gate():
    """T2.3 RED: variant_resolved=True — variant gate is bypassed, principal UUID committed.

    REQ-TL-1 Scenario C: update_booking(services=["Tinte"], variant_resolved=True)
    MUST NOT return status=ambiguous or next_step=variant_required.
    The principal UUID must proceed through the booking flow (past the variant gate).
    """
    from agent.tools.update_booking import _update_booking_impl

    principal_uuid = str(uuid4())
    # With variant_resolved=True, the strict mock should still fire variant, but
    # the gate-bypass logic commits the principal UUID and drops the descriptor.
    # We use the ambiguous mock to test the gate-bypass path.
    strict_mock = _make_variant_ambiguous_strict_mock(principal_uuid)
    mocks = _make_common_mocks(strict_mock)

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=["Tinte"],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            variant_resolved=True,  # bypasses variant gate
        )

    data = parse_response(raw)
    assert (
        data["status"] != "ambiguous"
    ), f"Expected status != ambiguous when variant_resolved=True, got: {data}"
    assert (
        data.get("next_step") != "variant_required"
    ), f"Expected next_step != variant_required when variant_resolved=True, got: {data}"


@pytest.mark.asyncio
async def test_variant_resolved_default_is_false():
    """T2.3 RED (NFR-1): calling _update_booking_impl without variant_resolved param
    preserves current behavior (same as variant_resolved=False).
    """
    from agent.tools.update_booking import _update_booking_impl

    strict_mock = _make_variant_ambiguous_strict_mock(str(FAKE_SERVICE_ID))
    mocks = _make_common_mocks(strict_mock)

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        # No variant_resolved kwarg — must default to False behavior
        raw = await _update_booking_impl(
            services=["Tinte"],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
        )

    data = parse_response(raw)
    assert (
        data["status"] == "ambiguous"
    ), f"Omitting variant_resolved must behave like False (gate fires), got: {data}"
    assert data["next_step"] == "variant_required"


# ---------------------------------------------------------------------------
# T2.5 RED — pre_resolved_service_ids parameter (Slice 2b placeholders)
# ---------------------------------------------------------------------------
# These are lightweight structural tests that assert the param exists and is accepted.
# Full behavioral tests for pre_resolved_service_ids live in T2.5/T2.6 (Slice 2b).


@pytest.mark.asyncio
async def test_pre_resolved_service_ids_param_accepted():
    """T2.5 stub RED: _update_booking_impl accepts pre_resolved_service_ids without error.

    Structural guard only — asserts the parameter exists and defaults to [].
    Does NOT assert UUID bypass behavior (that is T2.5/T2.6 Slice 2b).
    """
    from agent.tools.update_booking import _update_booking_impl

    # Pass pre_resolved_service_ids — should not raise TypeError
    strict_mock = _make_clean_strict_mock(str(FAKE_SERVICE_ID))
    mocks = _make_common_mocks(strict_mock)

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        # Must not raise TypeError for unknown kwarg
        raw = await _update_booking_impl(
            services=["Manicura"],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            pre_resolved_service_ids=[],  # empty list — structural test
        )

    # Just assert we got a valid JSON response, not a crash
    data = parse_response(raw)
    assert "status" in data, f"Expected valid ToolResponse, got: {data}"


# ---------------------------------------------------------------------------
# T2.5 RED — pre_resolved_service_ids bypass + AR5 UUID validation guard
# ---------------------------------------------------------------------------


def _make_common_mocks_with_pre_resolved(
    pre_resolved_uuids_active: list[str],
    extra_strict_mock: AsyncMock | None = None,
):
    """Build mocks for _update_booking_impl with pre_resolved_service_ids bypass path.

    The session mock is configured so that the UUID validation query
    (select Service.id where id in pre_resolved_uuids AND is_active=True)
    returns `pre_resolved_uuids_active` as valid active UUIDs.
    """
    from database.models import ServiceCategory

    # Build a fake fetchall result for the active-UUID validation query.
    # Each row is a 1-tuple (uuid_str,) per the design query shape.
    validation_rows = [(uuid,) for uuid in pre_resolved_uuids_active]

    fake_result = MagicMock()
    fake_result.fetchall = MagicMock(return_value=validation_rows)

    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=fake_result)

    fake_cm = AsyncMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_session)
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    strict_mock = extra_strict_mock or AsyncMock(
        return_value=(
            [],  # resolved_ids — empty (no name-based services passed)
            [],  # unknown_names
            [],  # ambiguous_descriptors
            [],  # partial_resolved_ids
        )
    )

    return {
        "agent.tools._booking_helpers._resolve_service_ids": AsyncMock(
            return_value=([str(FAKE_SERVICE_ID)], [])
        ),
        "agent.tools._booking_helpers._resolve_service_ids_strict": strict_mock,
        "agent.tools._booking_helpers._resolve_service_categories": AsyncMock(
            return_value={ServiceCategory.HAIRDRESSING}
        ),
        "agent.tools._booking_helpers._resolve_service_id_to_category_map": AsyncMock(
            return_value={}
        ),
        "agent.tools._booking_helpers._resolve_audience_variants": AsyncMock(
            return_value=("ok", None, [])
        ),
        "agent.tools._booking_helpers._resolve_stylist": AsyncMock(return_value=None),
        "agent.tools._booking_helpers._resolve_active_stylists": AsyncMock(return_value=[]),
        "agent.tools._booking_helpers._validate_full_name": MagicMock(return_value=None),
        "database.connection.get_async_session": MagicMock(return_value=fake_cm),
        "agent.tools._booking_validators.is_date_closed": AsyncMock(return_value=False),
        "_fake_session": fake_session,
    }


@pytest.mark.asyncio
async def test_pre_resolved_service_ids_valid_uuid_bypasses_resolution_and_merges():
    """T2.5 RED: a valid active UUID in pre_resolved_service_ids is merged into collected.services.

    REQ-TL-2 Scenario B: the UUID should appear in collected.services after the call.
    _resolve_service_ids_strict MUST NOT be called for it (it bypasses name resolution).
    """
    from agent.tools.update_booking import _update_booking_impl

    tinte_uuid = str(uuid4())
    # AR5: session query returns tinte_uuid as active — it passes validation.
    mocks = _make_common_mocks_with_pre_resolved([tinte_uuid])

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=[],  # no name-based services — pre_resolved carries the UUID
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            pre_resolved_service_ids=[tinte_uuid],
        )

    data = parse_response(raw)
    # Must NOT be rejected due to "no services" — pre_resolved fills the services slot
    assert (
        data["status"] != "rejected" or data.get("next_step") != "service_required"
    ), f"pre_resolved_service_ids must satisfy the services requirement, got: {data}"
    # The pre-resolved UUID must appear in collected.services
    service_ids = data.get("collected", {}).get("service_ids", [])
    assert (
        tinte_uuid in service_ids
    ), f"Expected tinte_uuid {tinte_uuid} in collected.service_ids, got: {data}"


@pytest.mark.asyncio
async def test_pre_resolved_service_ids_invalid_uuid_rejected_with_error():
    """T2.5 RED (AR5): UUID not in active catalog is rejected with explanatory error.

    REQ-TL-2 + AR5: the active-UUID validation guard must reject stale/hallucinated UUIDs
    and return status=rejected with next_step=service_required and an error message
    containing the invalid UUID.
    """
    from agent.tools.update_booking import _update_booking_impl

    bad_uuid = str(uuid4())
    # AR5: session returns empty — no active service with this UUID
    mocks = _make_common_mocks_with_pre_resolved([])  # empty = nothing active found

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            mocks["agent.tools._booking_helpers._resolve_service_ids"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            mocks["agent.tools._booking_helpers._resolve_service_ids_strict"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            mocks["agent.tools._booking_helpers._resolve_service_categories"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            mocks["agent.tools._booking_helpers._resolve_service_id_to_category_map"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            mocks["agent.tools._booking_helpers._resolve_audience_variants"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            mocks["agent.tools._booking_helpers._resolve_stylist"],
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            mocks["agent.tools._booking_helpers._resolve_active_stylists"],
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            mocks["agent.tools._booking_helpers._validate_full_name"],
        ),
        patch(
            "database.connection.get_async_session",
            mocks["database.connection.get_async_session"],
        ),
        patch(
            "agent.tools._booking_validators.is_date_closed",
            mocks["agent.tools._booking_validators.is_date_closed"],
        ),
    ):
        raw = await _update_booking_impl(
            services=[],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            pre_resolved_service_ids=[bad_uuid],
        )

    data = parse_response(raw)
    assert data["status"] == "rejected", f"Expected status=rejected for invalid UUID, got: {data}"
    assert (
        data.get("next_step") == "service_required"
    ), f"Expected next_step=service_required for invalid UUID, got: {data}"
    # Error message must mention the invalid UUID
    errors_text = " ".join(data.get("errors", []))
    assert (
        bad_uuid in errors_text
    ), f"Expected invalid UUID {bad_uuid} in error message, got errors: {data.get('errors')}"
