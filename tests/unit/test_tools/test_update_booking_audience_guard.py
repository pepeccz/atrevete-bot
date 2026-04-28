"""RED → GREEN regression test for conv_id=7 — multi-PRINCIPAL audience disambiguation.

When update_booking receives a service name that maps to multiple PRINCIPAL entries
sharing the same dimension but different audiences, it MUST return
next_step="audience_required".

Refs: design Decision 5, spec H2/U1
"""
from __future__ import annotations

import json

import pytest


async def _db_available() -> bool:
    try:
        from sqlalchemy import text
        from database.connection import get_async_session

        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
async def db_session():
    if not await _db_available():
        pytest.skip("Postgres not reachable")
    from database.connection import get_async_session

    async with get_async_session() as session:
        yield session


@pytest.fixture
async def multi_audience_cut_catalog(db_session):
    """Seed Corte de Mujer Guard + Corte de Hombre Guard — same dimension, distinct audiences."""
    from uuid import uuid4
    from sqlalchemy import delete
    from database.models import Service, ServiceCategory

    dim = "cut_guard_dim"
    services = [
        ("Corte de Mujer Guard", "adult_female"),
        ("Corte de Hombre Guard", "adult_male"),
        ("Corte de Niña Guard", "child_female"),
    ]
    names = [n for n, _ in services]

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()

    for name, aud in services:
        svc = Service(
            id=uuid4(),
            name=name,
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=40,
            is_active=True,
            audience=aud,
            metadata_={"service_type": "principal", "dimension": dim, "parent_service_name": None},
        )
        db_session.add(svc)
    await db_session.flush()

    yield {"names": names, "dimension": dim}

    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()


@pytest.mark.asyncio
async def test_update_booking_with_ambiguous_haircut_returns_audience_required(
    multi_audience_cut_catalog,
):
    """Conv_id=7 regression: calling update_booking with an ambiguous cut returns audience_required."""
    if not await _db_available():
        pytest.skip("Postgres not reachable")

    from agent.tools.update_booking import update_booking

    raw = await update_booking.ainvoke({"services": ["Corte de Mujer Guard"]})
    data = json.loads(raw)

    assert data["next_step"] == "audience_required", (
        f"Expected next_step='audience_required', got '{data['next_step']}'"
    )
    # Candidates list must be non-empty
    payload = data.get("payload", {})
    candidates = payload.get("variants") or payload.get("candidates") or payload.get("options", [])
    assert len(candidates) >= 2, f"Expected ≥2 candidates in payload, got: {payload}"
