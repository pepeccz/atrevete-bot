"""Tests for Change J1/J3 validators wired into update_booking.

Change J: hallucination-tolerant-architecture-bundle. REQ-J1, REQ-J3.

Tests written BEFORE implementation (TDD RED phase).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

SERVICE_ID = str(uuid4())
STYLIST_ID = str(uuid4())
SLOT_ISO = "2026-07-15T10:00:00+00:00"  # Far future to clear advance policy gate


def _make_offered_slot(start_iso: str, stylist_id: str | None = None) -> dict:
    return {
        "start_iso": start_iso,
        "stylist_id": stylist_id,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=14)).isoformat(),
        "turn_index": 0,
    }


# ---------------------------------------------------------------------------
# T6: _update_booking_impl accepts recently_offered_slots parameter
# ---------------------------------------------------------------------------


def test_update_booking_impl_accepts_recently_offered_slots():
    """_update_booking_impl must accept recently_offered_slots parameter."""
    # Import the module directly via sys.modules to bypass the @tool wrapper
    import importlib

    ub_mod = importlib.import_module("agent.tools.update_booking")

    impl_fn = getattr(ub_mod, "_update_booking_impl", None)
    assert impl_fn is not None, "_update_booking_impl must exist in update_booking module"

    sig = inspect.signature(impl_fn)
    assert (
        "recently_offered_slots" in sig.parameters
    ), "_update_booking_impl must accept recently_offered_slots parameter"


def test_update_booking_module_imports_slot_validators():
    """validate_slot_in_offered must be imported in the update_booking module's source."""
    import importlib

    ub_mod = importlib.import_module("agent.tools.update_booking")

    # Check the module source references validate_slot_in_offered
    import inspect as _inspect

    try:
        source = _inspect.getsource(ub_mod._update_booking_impl)
        assert (
            "validate_slot_in_offered" in source
        ), "validate_slot_in_offered must be called in _update_booking_impl"
    except (TypeError, OSError):
        pytest.skip("Cannot read source")


def test_update_booking_module_imports_service_validators():
    """validate_service_ids_exist must be present in update_booking module namespace."""
    import importlib

    ub_mod = importlib.import_module("agent.tools.update_booking")

    # It should be accessible as a module-level name
    # Even with the @tool wrapper, the module dict has it
    assert (
        "validate_service_ids_exist" in ub_mod.__dict__
    ), "validate_service_ids_exist must be in update_booking module namespace"


# ---------------------------------------------------------------------------
# T6: slot_iso not in recently_offered_slots → error with reoffer_slots hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_booking_slot_not_in_offered_slots_returns_error():
    """slot_iso not in recently_offered_slots → error with reoffer_slots hint."""
    import importlib

    ub_mod = importlib.import_module("agent.tools.update_booking")
    _update_booking_impl = ub_mod._update_booking_impl

    # State with no matching slot offered
    offered = [_make_offered_slot("2026-06-10T11:00:00+00:00")]

    with (
        patch.object(
            ub_mod,
            "validate_slot_in_offered",
            return_value=MagicMock(
                ok=False,
                error_code="slot_not_offered",
                error_message="El hueco no está entre los huecos ofrecidos.",
            ),
        ),
        patch.object(
            ub_mod,
            "validate_service_ids_exist",
            new=AsyncMock(return_value=MagicMock(ok=True)),
        ),
        patch.object(
            ub_mod,
            "validate_stylist_id_exists",
            new=AsyncMock(return_value=MagicMock(ok=True)),
        ),
        patch("database.connection.get_async_session") as mock_ctx,
        patch("agent.tools.update_booking.get_settings") as mock_settings,
        # Patch internal helpers via their module
        patch(
            "agent.tools._booking_helpers._resolve_service_ids_strict",
            new=AsyncMock(return_value=([SERVICE_ID], [], [], [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_service_categories",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_audience_variants",
            new=AsyncMock(return_value=(None, None, [])),
        ),
        patch(
            "agent.tools._booking_helpers._resolve_stylist",
            new=AsyncMock(return_value=STYLIST_ID),
        ),
        patch(
            "agent.tools._booking_helpers._validate_full_name",
            return_value=("María", "García"),
        ),
        # Patch is_date_closed so the date gate doesn't fail
        patch(
            "agent.tools._booking_validators.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            new=AsyncMock(return_value=False),
        ),
        # Patch lead time to 1 day so far-future date passes
        patch(
            "agent.tools.update_booking._load_lead_time_min_days",
            new=AsyncMock(return_value=1),
        ),
    ):
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            return_value=MagicMock(policy_accepted_at=datetime.now(UTC), policy_version="1.0")
        )
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        settings_obj = MagicMock()
        settings_obj.POLICY_VERSION = "1.0"
        settings_obj.POLICY_URL = "https://example.com"
        mock_settings.return_value = settings_obj

        result_json = await _update_booking_impl(
            services=["Corte Dama"],
            stylist_name="Ana",
            no_preference_stylist=False,
            date_iso="2026-07-15",
            audience=None,
            slot_iso=SLOT_ISO,
            notes_asked=True,
            extras_asked=True,
            customer_known=True,
            customer_full_name="María García",
            recently_offered_slots=offered,
            customer_id=str(uuid4()),
        )

    result = json.loads(result_json)
    assert (
        result.get("next_step") == "reoffer_slots"
    ), f"Expected reoffer_slots next_step, got: {result}"
