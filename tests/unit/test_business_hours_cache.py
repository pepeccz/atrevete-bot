"""Unit tests for agent/prompts/business_hours.py — hours cache (O2).

RED phase: these tests fail until _hours_cache is wired into
load_business_hours_snapshot and invalidate_business_hours_cache is added.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_hours_cache_hit_no_second_db_call(monkeypatch):
    """Two calls within TTL must NOT issue a second DB query.

    RED: fails until _hours_cache is wired into load_business_hours_snapshot.
    """
    from agent.prompts import business_hours as bh_mod

    call_count = {"n": 0}

    async def fake_load_hours() -> dict:
        call_count["n"] += 1
        return {"lunes": "09:00-18:00"}

    bh_mod._hours_cache.invalidate()
    monkeypatch.setattr(bh_mod, "_load_hours_snapshot", fake_load_hours)

    r1 = await bh_mod.load_business_hours_snapshot()
    r2 = await bh_mod.load_business_hours_snapshot()

    assert r1 == r2 == {"lunes": "09:00-18:00"}
    assert call_count["n"] == 1, (
        "DB loader must be called ONCE within TTL — second call must use cached value"
    )


@pytest.mark.asyncio
async def test_hours_cache_evicted_after_invalidate(monkeypatch):
    """invalidate_business_hours_cache must force a re-load on next call.

    RED: fails until invalidate_business_hours_cache() is added.
    """
    from agent.prompts import business_hours as bh_mod
    from agent.prompts.business_hours import invalidate_business_hours_cache

    call_count = {"n": 0}

    async def fake_load_hours() -> dict:
        call_count["n"] += 1
        return {"lunes": f"call_{call_count['n']}"}

    bh_mod._hours_cache.invalidate()
    monkeypatch.setattr(bh_mod, "_load_hours_snapshot", fake_load_hours)

    await bh_mod.load_business_hours_snapshot()
    assert call_count["n"] == 1

    invalidate_business_hours_cache()

    await bh_mod.load_business_hours_snapshot()
    assert call_count["n"] == 2, "Loader must re-run after invalidate_business_hours_cache()"


def test_invalidate_business_hours_cache_is_importable():
    """invalidate_business_hours_cache must be a callable exported from business_hours.

    RED: fails until the function is added.
    """
    from agent.prompts.business_hours import invalidate_business_hours_cache

    assert callable(invalidate_business_hours_cache)


def test_hours_cache_object_is_module_level():
    """_hours_cache must be a module-level _TtlCache instance.

    RED: fails until _hours_cache is declared in business_hours.py.
    """
    import agent.prompts.business_hours as bh_mod
    from agent.prompts.loader import _TtlCache

    assert hasattr(bh_mod, "_hours_cache"), "_hours_cache must be a module-level attribute"
    assert isinstance(bh_mod._hours_cache, _TtlCache), "_hours_cache must be a _TtlCache instance"
