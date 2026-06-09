"""T10 — I1: Unit tests for FK existence validators in _booking_validators.py.

Spec: REQ-I1 / SC-I1-A through SC-I1-D

TDD: This file is written before the implementation of validate_service_ids_exist()
and validate_stylist_id_exists(). Tests will fail (RED) until T11 adds the functions.

Uses AsyncMock to inject a mock session for unit-level tests (no live DB needed).
This matches the injectable session pattern used throughout the project.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_session_with_ids(found_ids: list) -> AsyncMock:
    """Build a mock async SQLAlchemy session that returns `found_ids` from SELECT."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(str(fid),) for fid in found_ids]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def _make_stylist_session(found: bool) -> AsyncMock:
    """Build a mock session for stylist validation — returns one row or None."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("some-id",) if found else None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


# ---------------------------------------------------------------------------
# validate_service_ids_exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_service_ids_exist_empty_list() -> None:
    """SC-I1-D guard: empty service_ids list returns ok=True (no DB round-trip)."""
    from agent.tools._booking_validators import validate_service_ids_exist

    mock_session = AsyncMock()

    result = await validate_service_ids_exist(mock_session, [])

    assert result.ok is True
    assert result.missing_ids == []
    assert result.error_code is None
    # Empty list must NOT execute a DB query (no SELECT needed)
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_validate_service_ids_exist_all_valid() -> None:
    """SC-I1-A: All valid service IDs → ok=True, missing_ids empty."""
    from agent.tools._booking_validators import validate_service_ids_exist

    svc_id = uuid4()
    session = _make_session_with_ids([svc_id])

    result = await validate_service_ids_exist(session, [svc_id])

    assert result.ok is True
    assert result.missing_ids == []
    assert result.error_code is None
    assert result.error_message is None


@pytest.mark.asyncio
async def test_validate_service_ids_exist_all_invalid() -> None:
    """SC-I1-B: All invalid service IDs → ok=False, missing_ids equals input."""
    from agent.tools._booking_validators import validate_service_ids_exist

    fake_ids = [uuid4(), uuid4()]
    # Session returns empty result (nothing found)
    session = _make_session_with_ids([])

    result = await validate_service_ids_exist(session, fake_ids)

    assert result.ok is False
    assert set(result.missing_ids) == set(fake_ids)
    assert result.error_code is not None
    assert result.error_message is not None
    # Error message must name the missing IDs (for LLM recovery)
    for fid in fake_ids:
        assert str(fid) in result.error_message


@pytest.mark.asyncio
async def test_validate_service_ids_exist_mixed() -> None:
    """SC-I1-C: Mixed valid + invalid → ok=False, missing_ids contains ONLY invalid."""
    from agent.tools._booking_validators import validate_service_ids_exist

    valid_id = uuid4()
    fake_id = uuid4()
    # Session returns only the valid_id as found
    session = _make_session_with_ids([valid_id])

    result = await validate_service_ids_exist(session, [valid_id, fake_id])

    assert result.ok is False
    assert fake_id in result.missing_ids
    assert valid_id not in result.missing_ids
    # Error message names the invalid one but NOT the valid one
    assert str(fake_id) in result.error_message
    assert str(valid_id) not in result.error_message


@pytest.mark.asyncio
async def test_validate_service_ids_error_message_instructs_llm() -> None:
    """Error message must contain 'catalog' reference so LLM can recover via R4/R5."""
    from agent.tools._booking_validators import validate_service_ids_exist

    fake_id = uuid4()
    session = _make_session_with_ids([])

    result = await validate_service_ids_exist(session, [fake_id])

    assert result.error_message is not None
    # Must instruct LLM to re-read the catalog (per design spec)
    assert "catalog" in result.error_message.lower() or "<catalog>" in result.error_message


# ---------------------------------------------------------------------------
# validate_stylist_id_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_stylist_id_exists_valid() -> None:
    """Valid stylist ID → ok=True."""
    from agent.tools._booking_validators import validate_stylist_id_exists

    sty_id = uuid4()
    session = _make_stylist_session(found=True)

    result = await validate_stylist_id_exists(session, sty_id)

    assert result.ok is True
    assert result.missing_ids == []
    assert result.error_code is None


@pytest.mark.asyncio
async def test_validate_stylist_id_exists_invalid() -> None:
    """Non-existent stylist ID → ok=False, error_code set, error_message names the ID."""
    from agent.tools._booking_validators import validate_stylist_id_exists

    fake_id = uuid4()
    session = _make_stylist_session(found=False)

    result = await validate_stylist_id_exists(session, fake_id)

    assert result.ok is False
    assert result.error_code is not None
    assert result.error_message is not None
    assert str(fake_id) in result.error_message
