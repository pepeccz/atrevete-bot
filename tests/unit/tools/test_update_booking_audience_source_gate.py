"""Unit tests — update_booking audience-SOURCE gate (cold guess vs loyal echo).

The deterministic gate at the update_booking boundary: a GENDERED service (a
principal in a multi-audience dimension whose own audience is set, e.g.
"Corte de Mujer") resolved with audience=None is rejected with `audience_required`
UNLESS the customer has a legitimate audience SOURCE:
  (a) memory backing — the service name is echoed in typical_services, or any
      remembered service / agent_notes infers the same audience, OR
  (b) a prior appointment carrying that audience.

This closes the residual ~16.7% where the model passes services=["corte de mujer"]
straight into update_booking, WITHOUT breaking the cliente-leal Q1 contract (loyal
customer "lo de siempre" → Corte de Mujer must NOT be re-asked).

The Q1 suite (tests/unit/test_agent/test_memory_service_audience_pinning.py) tests
`_resolve_service_ids_strict` DIRECTLY and never goes through update_booking, so it
is unaffected by this gate and stays green unchanged.

Function-level tests are pure (mocked session); end-to-end update_booking tests are
DB-gated and skip cleanly without Postgres.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from agent.tools._booking_helpers import (
    _memory_backs_audience,
    gendered_service_without_audience_source,
)

# --- mocked-session scaffolding -------------------------------------------------


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _SeqSession:
    """Async session stub returning canned results in call order."""

    def __init__(self, results: list):
        self._queue = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._queue.pop(0)


def _cut_resolved_row(name: str = "Corte de Mujer", audience: str = "adult_female"):
    return (uuid4(), name, audience, {"service_type": "principal", "dimension": "cut"})


def _cut_principals():
    return [
        ("cut", "Corte de Mujer", "adult_female"),
        ("cut", "Corte de Hombre", "adult_male"),
        ("cut", "Corte de Niña", "child_female"),
        ("cut", "Corte de Niño", "child_male"),
        ("cut", "Corte de Bebé", None),
        ("cut", "Corte de Flequillo", None),
    ]


# ---------------------------------------------------------------------------
# _memory_backs_audience — pure
# ---------------------------------------------------------------------------


def test_memory_backs_none_when_no_memory():
    assert _memory_backs_audience("adult_female", "Corte de Mujer", None) is False
    assert _memory_backs_audience("adult_female", "Corte de Mujer", {}) is False


def test_memory_backs_exact_service_name_echo():
    mem = {"typical_services": ["Corte de Mujer"]}
    assert _memory_backs_audience("adult_female", "Corte de Mujer", mem) is True


def test_memory_backs_via_audience_inference_from_remembered_name():
    # Remembered "Tinte de Mujer" (different service) still infers adult_female.
    mem = {"typical_services": ["Peinado de Mujer"]}
    assert _memory_backs_audience("adult_female", "Corte de Mujer", mem) is True


def test_memory_backs_via_agent_notes():
    mem = {"agent_notes": "Cliente habitual, siempre corte de mujer."}
    assert _memory_backs_audience("adult_female", "Corte de Mujer", mem) is True


def test_memory_does_not_back_wrong_audience():
    mem = {"typical_services": ["Corte de Hombre"]}
    assert _memory_backs_audience("adult_female", "Corte de Mujer", mem) is False


# ---------------------------------------------------------------------------
# gendered_service_without_audience_source — mocked session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_guess_returns_family():
    """COLD: gendered service, no memory, no customer → returns the family (ask)."""
    session = _SeqSession([_Result([_cut_resolved_row()]), _Result(_cut_principals())])
    out = await gendered_service_without_audience_source(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert out is not None
    dimension, candidates = out
    assert dimension == "cut"
    assert "Corte de Mujer" in candidates


@pytest.mark.asyncio
async def test_loyal_echo_memory_source_returns_none():
    """LOYAL: memory typical_services has the gendered service → allow (no gate)."""
    session = _SeqSession([_Result([_cut_resolved_row()]), _Result(_cut_principals())])
    out = await gendered_service_without_audience_source(
        session,
        [str(uuid4())],
        customer_memories={"typical_services": ["Corte de Mujer"]},
        customer_id=None,
    )
    assert out is None


@pytest.mark.asyncio
async def test_prior_appointment_source_returns_none():
    """LOYAL via source (b): prior appointment carries the audience → allow."""
    prior_service_id = uuid4()
    session = _SeqSession(
        [
            _Result([_cut_resolved_row()]),  # resolved rows
            _Result(_cut_principals()),  # principal spread
            _Result([([prior_service_id],)]),  # appt.service_ids arrays
            _Result([(prior_service_id,)]),  # services matching the audience
        ]
    )
    out = await gendered_service_without_audience_source(
        session, [str(uuid4())], customer_memories=None, customer_id=str(uuid4())
    )
    assert out is None


@pytest.mark.asyncio
async def test_single_audience_dimension_not_gendered_returns_none():
    """Regression guard: a principal in a single-audience dimension is not gendered."""
    resolved = (uuid4(), "Mechas", "adult_female", {"service_type": "principal", "dimension": "hl"})
    principals = [("hl", "Mechas", "adult_female")]  # only one audience in the dimension
    session = _SeqSession([_Result([resolved]), _Result(principals)])
    out = await gendered_service_without_audience_source(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert out is None


@pytest.mark.asyncio
async def test_null_audience_principal_returns_none():
    """A neutral principal (own audience None, e.g. Manicura) is not 'gendered'."""
    resolved = (uuid4(), "Manicura", None, {"service_type": "principal", "dimension": "manicure"})
    principals = [("manicure", "Manicura", None), ("manicure", "Manicura de Hombre", "adult_male")]
    session = _SeqSession([_Result([resolved]), _Result(principals)])
    out = await gendered_service_without_audience_source(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert out is None


@pytest.mark.asyncio
async def test_variant_service_returns_none():
    """A non-principal (variant) is never gendered-audience."""
    resolved = (uuid4(), "Mechas Babylights", "adult_female", {"service_type": "variant"})
    session = _SeqSession([_Result([resolved])])
    out = await gendered_service_without_audience_source(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert out is None


# ---------------------------------------------------------------------------
# End-to-end through update_booking (DB-gated — skips cleanly without Postgres)
# ---------------------------------------------------------------------------


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
async def cut_family(db_session):
    """Seed the real-shaped 'cut' audience family (gendered principals, no neutral parent)."""
    from sqlalchemy import delete

    from database.models import Service, ServiceCategory

    rows = [
        ("Corte de Mujer SrcTest", "adult_female"),
        ("Corte de Hombre SrcTest", "adult_male"),
        ("Corte de Niña SrcTest", "child_female"),
    ]
    names = [n for n, _ in rows]
    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()
    for name, aud in rows:
        db_session.add(
            Service(
                id=uuid4(),
                name=name,
                category=ServiceCategory.HAIRDRESSING,
                duration_minutes=35,
                is_active=True,
                audience=aud,
                metadata_={
                    "service_type": "principal",
                    "dimension": "cut_src_test",
                    "parent_service_name": None,
                },
            )
        )
    await db_session.flush()
    # _update_booking_impl opens its own session via get_async_session(); under
    # READ COMMITTED it only sees committed rows, so a bare flush() leaves the
    # seeded services invisible. Commit so the tool's session can resolve them.
    await db_session.commit()
    yield {"names": names}
    await db_session.execute(delete(Service).where(Service.name.in_(names)))
    await db_session.flush()
    await db_session.commit()


@pytest.mark.asyncio
async def test_update_booking_cold_guess_fires_audience_required(db_session, cut_family):
    """COLD: services=['Corte de Mujer SrcTest'], audience=None, no memory → audience_required."""
    from agent.tools.update_booking import _update_booking_impl

    raw = await _update_booking_impl(
        services=["Corte de Mujer SrcTest"],
        stylist_name=None,
        no_preference_stylist=False,
        date_iso=None,
        audience=None,
        customer_id=None,
        customer_memories=None,
    )
    data = json.loads(raw)
    assert data["next_step"] == "audience_required", data


@pytest.mark.asyncio
async def test_update_booking_loyal_echo_no_gate(db_session, cut_family):
    """LOYAL: same input but memory backs it → must NOT fire audience_required (Q1 behavior)."""
    from agent.tools.update_booking import _update_booking_impl

    raw = await _update_booking_impl(
        services=["Corte de Mujer SrcTest"],
        stylist_name=None,
        no_preference_stylist=False,
        date_iso=None,
        audience=None,
        customer_id=None,
        customer_memories={"typical_services": ["Corte de Mujer SrcTest"]},
    )
    data = json.loads(raw)
    assert data.get("next_step") != "audience_required", data


@pytest.mark.asyncio
async def test_update_booking_explicit_audience_no_gate(db_session, cut_family):
    """EXPLICIT: audience param set → gate bypassed entirely."""
    from agent.tools.update_booking import _update_booking_impl

    raw = await _update_booking_impl(
        services=["Corte de Mujer SrcTest"],
        stylist_name=None,
        no_preference_stylist=False,
        date_iso=None,
        audience="adult_female",
        customer_id=None,
        customer_memories=None,
    )
    data = json.loads(raw)
    assert data.get("next_step") != "audience_required", data
