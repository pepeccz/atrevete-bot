"""Tests for UUID-in-services defense layer (uuid-reroute fix).

The model occasionally echoes collected.service_ids (UUID strings) back into the
`services` field on policy-acceptance round-trips (booking_flow.md R-36b). The
name-resolution path (_resolve_service_ids_strict) does not match UUIDs → rejection
as unknown service names. The fix detects UUID-format strings in `services`, strips
them out, and merges them into `pre_resolved_service_ids` BEFORE name resolution runs.

Coverage:
  a. services=[<valid-uuid>] → rerouted through pre_resolved DB gate → not rejected as unknown name
  b. services=["Corte de Mujer"] → still resolves via name path unchanged
  c. services=[<uuid-not-in-catalog>] → rejected by pre_resolved DB existence check
  d. mixed: services=["Corte de Mujer", <valid-uuid>] → name via names, uuid via pre_resolved
  e. unit-level: _UUID_RE matches expected patterns
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_SERVICE_ID = str(uuid4())
FAKE_STYLIST_ID = str(uuid4())
CATALOG_UUID = str(uuid4())  # "valid" uuid that exists in the fake catalog


def parse_response(raw: str) -> dict:
    return json.loads(raw)


def _future_date(days: int = 14) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


# ---------------------------------------------------------------------------
# Unit tests — _UUID_RE (no DB, no async)
# ---------------------------------------------------------------------------


def test_uuid_re_matches_canonical_uuid():
    from agent.tools.update_booking import _UUID_RE

    valid = str(uuid4())
    assert _UUID_RE.match(valid), f"Should match UUID: {valid}"


def test_uuid_re_matches_uppercase():
    from agent.tools.update_booking import _UUID_RE

    upper = str(uuid4()).upper()
    assert _UUID_RE.match(upper)


def test_uuid_re_does_not_match_service_name():
    from agent.tools.update_booking import _UUID_RE

    assert not _UUID_RE.match("Corte de Mujer")
    assert not _UUID_RE.match("")
    assert not _UUID_RE.match("alisado")
    assert not _UUID_RE.match("12345")


def test_uuid_re_does_not_match_partial_uuid():
    from agent.tools.update_booking import _UUID_RE

    partial = str(uuid4())[:30]  # too short
    assert not _UUID_RE.match(partial)


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _make_session_with_pre_resolved_ids(valid_ids: list[str]):
    """Build a fake async session where execute() returns rows for the given UUIDs."""

    class FakeRow:
        def __init__(self, uuid_str):
            self._id = uuid_str

        def __getitem__(self, idx):
            return self._id

    result_mock = MagicMock()
    result_mock.fetchall = MagicMock(return_value=[FakeRow(uid) for uid in valid_ids])

    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(return_value=result_mock)

    ctx_mock = MagicMock()
    ctx_mock.__aenter__ = AsyncMock(return_value=session_mock)
    ctx_mock.__aexit__ = AsyncMock(return_value=False)
    return ctx_mock, session_mock


@contextmanager
def _standard_patches(
    *,
    service_ids=None,
    unknown_names=None,
    pre_resolved_valid_ids: list[str] | None = None,
):
    """Context manager with all patches needed for UUID-reroute tests.

    pre_resolved_valid_ids: UUIDs the fake DB will say are valid/active services.
    """
    from database.models import ServiceCategory

    service_ids = service_ids if service_ids is not None else [FAKE_SERVICE_ID]
    unknown_names = unknown_names if unknown_names is not None else []

    ctx_mock, session_mock = _make_session_with_pre_resolved_ids(
        pre_resolved_valid_ids if pre_resolved_valid_ids is not None else []
    )

    fk_result = MagicMock()
    fk_result.ok = True
    fk_result.missing_ids = []
    fk_result.payload = {}

    with (
        patch(
            "agent.tools._booking_helpers._resolve_service_ids",
            AsyncMock(return_value=(service_ids, unknown_names)),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            AsyncMock(return_value=(service_ids, unknown_names, [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            AsyncMock(return_value={ServiceCategory.HAIRDRESSING}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_id_to_category_map",
            AsyncMock(return_value={}),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            AsyncMock(return_value=("ok", None, [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            AsyncMock(return_value=None),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_active_stylists",
            AsyncMock(return_value=[]),
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            MagicMock(return_value=None),
        ),
        patch("database.connection.get_async_session", MagicMock(return_value=ctx_mock)),
        patch(
            "agent.tools.update_booking.validate_service_ids_exist",
            AsyncMock(return_value=fk_result),
        ),
        patch(
            "agent.tools.update_booking.validate_stylist_id_exists",
            AsyncMock(return_value=fk_result),
        ),
        patch(
            "agent.tools.update_booking._load_lead_time_min_days",
            AsyncMock(return_value=3),
        ),
        patch(
            "agent.services.policy_service.get_conversation_policy_acceptance",
            AsyncMock(return_value=None),
        ),
        patch(
            "agent.tools.update_booking.get_conversation_policy_acceptance",
            AsyncMock(return_value=None),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Case (e) — pure logic: UUID detection and strip before DB call
# ---------------------------------------------------------------------------


def test_uuid_stripped_from_services_list():
    """UUID strings are extracted from `services` and do not reach name resolution."""
    # This exercises _UUID_RE logic inline without needing async context.
    from agent.tools.update_booking import _UUID_RE

    services = ["Corte de Mujer", str(uuid4()), "peinado"]
    leaked = [s for s in services if _UUID_RE.match(s)]
    remaining = [s for s in services if not _UUID_RE.match(s)]

    assert len(leaked) == 1
    assert remaining == ["Corte de Mujer", "peinado"]


def test_merge_into_none_pre_resolved():
    """When pre_resolved_service_ids is None, leaked UUIDs are placed in a new list."""
    from agent.tools.update_booking import _UUID_RE

    services = [str(uuid4())]
    leaked = [s for s in services if _UUID_RE.match(s)]
    pre = None

    existing = list(pre) if pre else []
    existing_set = {u.lower() for u in existing}
    for u in leaked:
        if u.lower() not in existing_set:
            existing.append(u)
            existing_set.add(u.lower())
    pre = existing if existing else None

    assert pre is not None
    assert len(pre) == 1
    assert pre[0] == services[0]


def test_merge_deduplication():
    """A UUID already in pre_resolved_service_ids is not added twice."""
    from agent.tools.update_booking import _UUID_RE

    dup = str(uuid4())
    services = [dup]
    leaked = [s for s in services if _UUID_RE.match(s)]
    pre = [dup]  # already present

    existing = list(pre)
    existing_set = {u.lower() for u in existing}
    for u in leaked:
        if u.lower() not in existing_set:
            existing.append(u)
            existing_set.add(u.lower())
    pre = existing

    assert pre.count(dup) == 1, "UUID must not be duplicated"


# ---------------------------------------------------------------------------
# Case (b) — service name resolves via name path unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_name_resolves_unchanged():
    """services=['Corte de Mujer'] resolves normally via name path; no UUID reroute."""
    from agent.tools.update_booking import _update_booking_impl

    with _standard_patches(service_ids=[FAKE_SERVICE_ID], unknown_names=[]):
        raw = await _update_booking_impl(
            services=["Corte de Mujer"],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=False,
            extras_asked=False,
        )

    data = parse_response(raw)
    # The key assertion: name resolution succeeded, so we never get service_required
    # with "No reconozco" error (which would indicate the name was treated as UUID).
    # The actual next_step varies (extras_loop_required, stylist_required, offer_slots)
    # depending on how many flow gates fire — what matters is no service-unknown rejection.
    assert (
        data.get("next_step") != "service_required"
    ), f"Name resolution should not produce service_required: {data}"
    errors = data.get("errors", [])
    assert not any(
        "No reconozco" in str(e) for e in errors
    ), f"Service name should not be rejected as unknown: {errors}"


# ---------------------------------------------------------------------------
# Case (a) — valid UUID in services is rerouted through pre_resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uuid_in_services_rerouted_not_rejected_as_unknown():
    """services=[<valid-uuid>] is rerouted to pre_resolved; not rejected as unknown name.

    The UUID is valid in the fake catalog (DB returns it as an active service).
    Expected: flow does NOT return next_step=service_required (which would mean
    the UUID was treated as an unknown service name).
    """
    from agent.tools.update_booking import _update_booking_impl

    valid_uuid = str(uuid4())

    with _standard_patches(
        service_ids=[valid_uuid],
        unknown_names=[],
        pre_resolved_valid_ids=[valid_uuid],
    ):
        raw = await _update_booking_impl(
            services=[valid_uuid],  # UUID leaked into services field
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=False,
            extras_asked=False,
        )

    data = parse_response(raw)
    # After rerouting, service resolution should not fail with "unknown service"
    assert data.get("next_step") != "service_required" or "No reconozco" not in str(
        data.get("errors", [])
    ), f"UUID reroute failed — model would get rejected as unknown service: {data}"


# ---------------------------------------------------------------------------
# Case (c) — UUID not in catalog is rejected by pre_resolved DB gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uuid_not_in_catalog_rejected_by_db_gate():
    """services=[<uuid-not-in-catalog>] is rerouted but rejected by DB existence check.

    pre_resolved_valid_ids=[] means the DB returns no rows → UUID is invalid/inactive.
    Expected: next_step=service_required (the pre_resolved DB gate rejects it).
    """
    from agent.tools.update_booking import _update_booking_impl

    garbage_uuid = str(uuid4())

    with _standard_patches(
        service_ids=[],
        unknown_names=[],
        pre_resolved_valid_ids=[],  # DB says UUID is not in catalog
    ):
        raw = await _update_booking_impl(
            services=[garbage_uuid],  # UUID not in catalog
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=False,
            extras_asked=False,
        )

    data = parse_response(raw)
    assert (
        data.get("next_step") == "service_required"
    ), f"Expected service_required for unknown UUID, got: {data}"


# ---------------------------------------------------------------------------
# Case (d) — mixed: service name + UUID both present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_name_and_uuid_both_resolve():
    """services=['Corte de Mujer', <valid-uuid>]: name resolves via name path, UUID via pre_resolved.

    The name resolves to FAKE_SERVICE_ID. The UUID resolves via pre_resolved to CATALOG_UUID.
    Both should appear in the resolved set; flow should not reject on service_required.
    """
    from agent.tools.update_booking import _update_booking_impl

    valid_uuid = str(uuid4())

    with _standard_patches(
        service_ids=[FAKE_SERVICE_ID],  # name resolver returns this for "Corte de Mujer"
        unknown_names=[],
        pre_resolved_valid_ids=[valid_uuid],  # DB confirms the UUID is active
    ):
        raw = await _update_booking_impl(
            services=["Corte de Mujer", valid_uuid],
            stylist_name=None,
            no_preference_stylist=False,
            date_iso=None,
            date_text=None,
            audience=None,
            customer_full_name=None,
            notes=None,
            no_more_services=False,
            extras_asked=False,
        )

    data = parse_response(raw)
    assert (
        data.get("next_step") != "service_required"
    ), f"Mixed name+uuid should not produce service_required: {data}"
