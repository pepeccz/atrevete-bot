"""S2-T3.2 RED — Loud fail-open logging upgrade tests.

Verifies that drift-masking except sites use logger.error (not logger.warning)
so exceptions are visible in production alerting. All tested sites are fail-open
(the exception is caught and execution continues), which is fine — but they MUST
use logger.error so they don't silently mask real problems.

Spec: REQ-S2-1 through REQ-S2-5, REQ-S2-6 (already done in summarize.py)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# S2-T3.2a — DynamicPromptMiddleware fail-open sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dynamic_prompt_catalog_failure_logs_error():
    """catalog section build failure must call logger.error, not logger.warning.

    REQ-S2-1: DynamicPromptMiddleware except sites must use logger.error.
    """
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    mw = DynamicPromptMiddleware()

    state = {"messages": [], "conversation_id": "test-conv-1"}
    request = MagicMock()
    request.state = state

    async def handler(req):
        return MagicMock()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(side_effect=RuntimeError("DB unavailable")),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
        patch("agent.middleware.dynamic_prompt.logger") as mock_logger,
    ):
        await mw.awrap_model_call(request, handler)

    assert mock_logger.error.called, (
        "REQ-S2-1: DynamicPromptMiddleware catalog build failure must call logger.error. "
        "logger.warning silently masks real errors from production alerting."
    )
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


@pytest.mark.asyncio
async def test_dynamic_prompt_hours_failure_logs_error():
    """business hours load failure must call logger.error, not logger.warning.

    REQ-S2-1: DynamicPromptMiddleware except sites must use logger.error.
    """
    from agent.middleware.dynamic_prompt import DynamicPromptMiddleware

    mw = DynamicPromptMiddleware()

    state = {"messages": [], "conversation_id": "test-conv-2"}
    request = MagicMock()
    request.state = state

    async def handler(req):
        return MagicMock()

    with (
        patch(
            "agent.middleware.dynamic_prompt.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.middleware.dynamic_prompt.load_business_hours_snapshot",
            new=AsyncMock(side_effect=RuntimeError("hours DB unavailable")),
        ),
        patch("agent.middleware.dynamic_prompt.logger") as mock_logger,
    ):
        await mw.awrap_model_call(request, handler)

    assert (
        mock_logger.error.called
    ), "REQ-S2-1: DynamicPromptMiddleware business hours failure must call logger.error."
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


# ---------------------------------------------------------------------------
# S2-T3.2b — CustomerResolveMiddleware cache GET failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_resolve_cache_get_failure_logs_error():
    """Redis cache GET failure must call logger.error, not logger.warning.

    REQ-S2-3: CustomerResolveMiddleware Redis failures must use logger.error.
    """
    from agent.middleware.customer_resolve import _get_cached_customer

    with (
        patch("agent.middleware.customer_resolve.get_redis_client") as mock_redis_factory,
        patch("agent.middleware.customer_resolve.logger") as mock_logger,
    ):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis_factory.return_value = mock_redis

        result = await _get_cached_customer("+34600000001")

    assert result is None, "cache GET failure must return None (fail-open)"
    assert mock_logger.error.called, (
        "REQ-S2-3: Redis cache GET failure must call logger.error. "
        "logger.warning masks transient Redis failures from production alerting."
    )
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


# ---------------------------------------------------------------------------
# S2-T3.2c — CustomerResolveMiddleware read_customer_memories failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_resolve_memories_failure_logs_error():
    """read_customer_memories failure must call logger.error, not logger.warning.

    REQ-S2-3: CustomerResolveMiddleware except sites must use logger.error.
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    mw = CustomerResolveMiddleware()

    import uuid

    phone = "+34600000002"
    customer_id = str(uuid.uuid4())
    state = {"messages": [], "conversation_id": "test-conv-4", "customer_phone": phone}
    request = MagicMock()
    request.state = state

    async def handler(req):
        return MagicMock()

    # Build a minimal customer dict (what _lookup_customer returns)
    customer_data = {
        "id": customer_id,
        "name": "Test User",
        "phone": phone,
        "is_returning": True,
        "notes": None,
        "policy_accepted_at": None,
        "policy_version": None,
    }

    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new=AsyncMock(return_value=customer_data),
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new=AsyncMock(),
        ),
        patch(
            "agent.middleware.customer_resolve.read_customer_memories",
            new=AsyncMock(side_effect=RuntimeError("memories DB unavailable")),
        ),
        patch("agent.middleware.customer_resolve.logger") as mock_logger,
    ):
        await mw.awrap_model_call(request, handler)

    assert mock_logger.error.called, (
        "REQ-S2-3: read_customer_memories failure must call logger.error. "
        "logger.warning masks real DB failures from production alerting."
    )
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


# ---------------------------------------------------------------------------
# S2-T3.2d — _booking_validators.py _fetch_valid_candidate_services failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_booking_validators_candidates_fetch_failure_logs_error():
    """_fetch_valid_candidate_services failure must call logger.error, not logger.warning.

    REQ-S2-5: booking validator fail-open sites must use logger.error.
    Candidates are a recovery aid, so fail-open is correct — but errors must be visible.
    """
    import uuid

    from agent.tools._booking_validators import _fetch_valid_candidate_services

    found_uuids = {uuid.uuid4()}
    session_mock = AsyncMock()
    session_mock.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))

    with patch("agent.tools._booking_validators.logger") as mock_logger:
        result = await _fetch_valid_candidate_services(session_mock, found_uuids)

    assert result == [], "fail-open: must return empty list on error"
    assert mock_logger.error.called, (
        "REQ-S2-5: _fetch_valid_candidate_services failure must call logger.error. "
        "logger.warning masks DB errors from production alerting."
    )
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


# ---------------------------------------------------------------------------
# S2-T3.2e — AppointmentContextMiddleware DB fetch failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_context_db_failure_logs_error():
    """AppointmentContextMiddleware DB fetch failure must call logger.error.

    REQ-S2-2: DB fetch failures in middleware must use logger.error.
    The middleware is fail-open (passes empty appointments), but the failure
    must be visible in production logs.
    """
    from agent.middleware.appointment_context import AppointmentContextMiddleware

    mw = AppointmentContextMiddleware()

    import uuid

    customer_id = str(uuid.uuid4())
    state = {
        "messages": [],
        "conversation_id": "test-conv-5",
        "customer_id": customer_id,
    }
    request = MagicMock()
    request.state = state

    async def handler(req):
        return MagicMock()

    with (
        patch(
            "database.connection.get_async_session",
        ) as mock_session_ctx,
        patch("agent.middleware.appointment_context.logger") as mock_logger,
    ):
        # Make the async context manager raise on enter
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        await mw.awrap_model_call(request, handler)

    assert mock_logger.error.called, (
        "REQ-S2-2: AppointmentContextMiddleware DB fetch failure must call logger.error. "
        "It is fail-open, but the failure must not be masked from production alerting."
    )
    assert (
        not mock_logger.warning.called
    ), "logger.warning must no longer be called — upgrade to logger.error."


# ---------------------------------------------------------------------------
# S2-T3.2f — Scenario S2-A: availability_context.py silent min_days fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_availability_context_lead_time_failure_logs_error():
    """Scenario S2-A: _load_lead_time_min_days failure must call logger.error.

    ADR-3 known offender (availability_context.py:355): previously silent except
    that fell back to min_days=3 without any log output. This is a drift-masking
    site — the exception can fire from schema drift in our own DB, not just
    external outages. It must emit logger.error so production alerting can catch it.

    Spec: Scenario S2-A, REQ-S2-1, REQ-S2-2, ADR-3
    """
    # We need to trigger only the min_days path, so mock at the service level.
    # Use a minimal state that has service_ids so the middleware reaches the
    # lead_time fetch (not short-circuited by missing service_ids).
    import json
    import uuid
    from unittest.mock import patch

    service_id = str(uuid.uuid4())
    # Message must match _extract_service_ids_from_messages: name="update_booking",
    # content has collected.service_ids
    msg = MagicMock()
    msg.name = "update_booking"
    msg.content = json.dumps({"collected": {"service_ids": [service_id]}})
    state = {
        "messages": [msg],
        "conversation_id": "test-conv-s2a",
    }
    request = MagicMock()
    request.state = state

    async def handler(req):
        return MagicMock()

    from agent.middleware.availability_context import AvailabilityContextMiddleware

    mw = AvailabilityContextMiddleware()

    with (
        patch(
            "agent.services.availability_service._load_lead_time_min_days",
            new=AsyncMock(side_effect=RuntimeError("DB unavailable")),
        ),
        patch(
            "agent.middleware.availability_context.get_availability_window",
            new=AsyncMock(return_value={}),
        ),
        patch("agent.middleware.availability_context._get_redis", return_value=None),
        patch("agent.middleware.availability_context.logger") as mock_logger,
    ):
        await mw.awrap_model_call(request, handler)

    assert mock_logger.error.called, (
        "Scenario S2-A: _load_lead_time_min_days failure must call logger.error. "
        "ADR-3 known offender: previously silent min_days=3 fallback masked DB drift."
    )


# ---------------------------------------------------------------------------
# S2-T3.2g — Scenario S2-B: appointment_context.py silent service name fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_context_service_names_failure_logs_error():
    """Scenario S2-B: _get_service_names_for_middleware failure must call logger.error.

    The spec (appointment_context.py:110) names this exact site as Scenario S2-B:
    'except Exception: return "servicios"' — previously completely silent.
    The function is a helper called per-appointment; DB drift here would silently
    produce 'servicios' labels for all upcoming appointments. Must emit logger.error.

    Spec: Scenario S2-B, REQ-S2-1, REQ-S2-2
    """
    import uuid

    from agent.middleware.appointment_context import _get_service_names_for_middleware

    service_ids = [uuid.uuid4()]

    with patch("agent.middleware.appointment_context.logger") as mock_logger:
        with patch(
            "database.connection.get_async_session",
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB unavailable"))
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_session

            result = await _get_service_names_for_middleware(
                service_ids, conversation_id="test-conv-s2b"
            )

    assert result == "servicios", "fail-open: must return 'servicios' on error"
    assert mock_logger.error.called, (
        "Scenario S2-B: _get_service_names_for_middleware DB failure must call logger.error. "
        "Previously silent — masked schema drift from production alerting."
    )
