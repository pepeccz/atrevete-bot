"""
Unit tests for agent/services/customer_memory_service.py (TASK-2).

23 tests covering:
- read_customer_memories: Store hit, Store miss→PG hit, both miss, exceptions
- write_customer_memories: Store+PG success, Store fail→PG called, PG fail, no Store
- _merge_preferences: pure-function tests (no mocking needed)
"""

from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from agent.services.customer_memory_service import (
    _merge_preferences,
    read_customer_memories,
    write_customer_memories,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_store_item(value: dict) -> MagicMock:
    """Create a mock Store Item with a .value attribute."""
    item = MagicMock()
    item.value = value
    return item


# ============================================================================
# read_customer_memories — Store hit
# ============================================================================


class TestReadCustomerMemoriesStoreHit:
    async def test_read_store_hit(self):
        """Store returns Item → return item.value dict."""
        prefs = {"visit_count": 3, "preferred_stylist_name": "Pilar"}
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(return_value=_make_store_item(prefs))

        with patch("agent.services.customer_memory_service.get_store", return_value=mock_store):
            result = await read_customer_memories("+34612345678")

        assert result == prefs
        mock_store.aget.assert_called_once_with(
            namespace=("customers", "+34612345678"),
            key="preferences",
        )


# ============================================================================
# read_customer_memories — Store miss, PG fallback
# ============================================================================


class TestReadCustomerMemoriesStoreMissPgHit:
    async def test_read_store_miss_pg_hit(self):
        """Store returns None → fall back to PG metadata_['memories']."""
        pg_memories = {"visit_count": 2, "preferred_stylist_name": "Laura"}
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(return_value=None)

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            # scalar_one_or_none is SYNC in SQLAlchemy 2.0 (result of execute, not a coroutine)
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value={"memories": pg_memories})
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        assert result == pg_memories

    async def test_read_store_miss_pg_miss(self):
        """Store returns None, PG metadata has no 'memories' key → return None."""
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(return_value=None)

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value={"other_key": "data"})
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        assert result is None

    async def test_read_both_miss(self):
        """Store None, PG row is None → return None."""
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(return_value=None)

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value=None)
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        assert result is None


# ============================================================================
# read_customer_memories — exception handling
# ============================================================================


class TestReadCustomerMemoriesExceptions:
    async def test_read_store_exception_falls_back_to_pg(self):
        """Store raises ConnectionError → PG fallback hit, no raise."""
        pg_memories = {"visit_count": 1}
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(side_effect=ConnectionError("Redis down"))

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value={"memories": pg_memories})
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        # Must not raise, must return PG fallback
        assert result == pg_memories

    async def test_read_store_exception_pg_also_fails(self):
        """Both Store and PG raise → return None, no raise."""
        mock_store = AsyncMock()
        mock_store.aget = AsyncMock(side_effect=ConnectionError("Redis down"))

        @asynccontextmanager
        async def _session_ctx():
            raise RuntimeError("DB down")
            yield  # pragma: no cover

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        assert result is None

    async def test_read_store_none_context(self):
        """get_store() returns None (no graph context) → skip Store, try PG."""
        pg_memories = {"visit_count": 5}

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none = MagicMock(return_value={"memories": pg_memories})
            session.execute = AsyncMock(return_value=result_mock)
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=None),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            result = await read_customer_memories("+34612345678")

        assert result == pg_memories


# ============================================================================
# write_customer_memories — success paths
# ============================================================================


class TestWriteCustomerMemoriesSuccess:
    async def test_write_success_store_and_pg_called(self):
        """Both Store and PG writes succeed; verify correct args."""
        mock_store = AsyncMock()
        mock_store.aput = AsyncMock()

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()
            session.execute = AsyncMock()
            session.commit = AsyncMock()
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                side_effect=lambda: _session_ctx(),
            ),
        ):
            await write_customer_memories(
                "+34612345678",
                {"service_names": ["CORTE LARGO"], "stylist_name": "Pilar"},
                None,
            )

        mock_store.aput.assert_called_once()
        call_kwargs = mock_store.aput.call_args
        assert call_kwargs.kwargs["namespace"] == ("customers", "+34612345678")
        assert call_kwargs.kwargs["key"] == "preferences"
        value = call_kwargs.kwargs["value"]
        assert value["visit_count"] == 1
        assert "CORTE LARGO" in value["typical_services"]

    async def test_write_store_fails_pg_still_called(self):
        """Store write raises → PG write still attempted."""
        mock_store = AsyncMock()
        mock_store.aput = AsyncMock(side_effect=ConnectionError("Redis down"))

        pg_executed = []

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()

            async def _execute(stmt):
                pg_executed.append(True)

            session.execute = AsyncMock(side_effect=_execute)
            session.commit = AsyncMock()
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                return_value=_session_ctx(),
            ),
        ):
            await write_customer_memories("+34612345678", {"service_names": []}, None)

        assert len(pg_executed) >= 1

    async def test_write_pg_fails_no_raise(self):
        """PG raises → returns None, no raise."""
        mock_store = AsyncMock()
        mock_store.aput = AsyncMock()

        @asynccontextmanager
        async def _session_ctx():
            raise RuntimeError("DB down")
            yield  # pragma: no cover

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=mock_store),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                return_value=_session_ctx(),
            ),
        ):
            # Must not raise
            await write_customer_memories("+34612345678", {"service_names": []}, None)

    async def test_write_no_store_context(self):
        """get_store() returns None → only PG write attempted."""
        pg_executed = []

        @asynccontextmanager
        async def _session_ctx():
            session = AsyncMock()

            async def _execute(stmt):
                pg_executed.append(True)

            session.execute = AsyncMock(side_effect=_execute)
            session.commit = AsyncMock()
            yield session

        with (
            patch("agent.services.customer_memory_service.get_store", return_value=None),
            patch(
                "agent.services.customer_memory_service.get_async_session",
                return_value=_session_ctx(),
            ),
        ):
            await write_customer_memories("+34612345678", {"service_names": []}, None)

        assert len(pg_executed) >= 1


# ============================================================================
# _merge_preferences — pure function, no mocking needed
# ============================================================================


class TestMergePreferences:
    def test_merge_first_booking_visit_count(self):
        """existing=None → visit_count==1."""
        result = _merge_preferences(None, {"service_names": ["CORTE"]})
        assert result["visit_count"] == 1

    def test_merge_increments_visit_count(self):
        """existing visit_count=2 → result is 3."""
        result = _merge_preferences({"visit_count": 2}, {"service_names": []})
        assert result["visit_count"] == 3

    def test_merge_typical_services_new_prepended(self):
        """New service prepended, existing preserved."""
        existing = {"typical_services": ["TINTE"], "visit_count": 1}
        result = _merge_preferences(existing, {"service_names": ["CORTE"]})
        assert result["typical_services"][0] == "CORTE"
        assert "TINTE" in result["typical_services"]

    def test_merge_typical_services_cap_at_3(self):
        """Combined list capped at 3, oldest dropped."""
        existing = {"typical_services": ["A", "B", "C"], "visit_count": 3}
        result = _merge_preferences(existing, {"service_names": ["D"]})
        assert len(result["typical_services"]) == 3
        assert result["typical_services"][0] == "D"
        assert "A" in result["typical_services"]
        assert "B" in result["typical_services"]
        # C is dropped (oldest)
        assert "C" not in result["typical_services"]

    def test_merge_typical_services_deduplication(self):
        """Service already in list moved to position 0, no duplicates."""
        existing = {"typical_services": ["A", "B"], "visit_count": 2}
        result = _merge_preferences(existing, {"service_names": ["B"]})
        assert result["typical_services"][0] == "B"
        assert result["typical_services"].count("B") == 1

    def test_merge_no_preference_clears_stylist(self):
        """no_preference_stylist=True → both name and id are None."""
        existing = {"preferred_stylist_name": "Pilar", "preferred_stylist_id": "uuid-1", "visit_count": 2}
        result = _merge_preferences(existing, {"no_preference_stylist": True})
        assert result["preferred_stylist_name"] is None
        assert result["preferred_stylist_id"] is None
        assert result["no_preference_stylist"] is True

    def test_merge_explicit_stylist_updates_preference(self):
        """Explicit stylist name overrides existing preference."""
        existing = {"preferred_stylist_name": "Maria", "visit_count": 1}
        result = _merge_preferences(existing, {"stylist_name": "Pilar", "stylist_id": "uuid-2"})
        assert result["preferred_stylist_name"] == "Pilar"
        assert result["preferred_stylist_id"] == "uuid-2"

    def test_merge_last_stylist_always_updated(self):
        """last_stylist_name reflects the latest booking stylist."""
        existing = {"last_stylist_name": "Maria", "visit_count": 1}
        result = _merge_preferences(existing, {"stylist_name": "Pilar"})
        assert result["last_stylist_name"] == "Pilar"

    def test_merge_notes_overwrite_if_non_empty(self):
        """New non-empty notes replace existing agent_notes."""
        existing = {"agent_notes": "alergia amoniaco", "visit_count": 1}
        result = _merge_preferences(existing, {"notes": "prefiere tarde"})
        assert result["agent_notes"] == "prefiere tarde"

    def test_merge_notes_preserved_if_new_empty(self):
        """notes=None → existing agent_notes preserved."""
        existing = {"agent_notes": "alergia amoniaco", "visit_count": 1}
        result = _merge_preferences(existing, {"notes": None})
        assert result["agent_notes"] == "alergia amoniaco"

    def test_merge_time_of_day_morning(self):
        """start_time hour < 13 → 'morning'."""
        result = _merge_preferences(None, {"start_time": "2026-04-08T10:30:00+02:00"})
        assert result["typical_time_of_day"] == "morning"

    def test_merge_time_of_day_afternoon(self):
        """start_time hour >= 13 → 'afternoon'."""
        result = _merge_preferences(None, {"start_time": "2026-04-08T14:00:00+02:00"})
        assert result["typical_time_of_day"] == "afternoon"

    def test_merge_day_of_week_spanish(self):
        """Saturday booking → typical_day_of_week=='sábado'."""
        # 2026-04-11 is a Saturday
        result = _merge_preferences(None, {"start_time": "2026-04-11T10:00:00+02:00"})
        assert result["typical_day_of_week"] == "sábado"

    def test_merge_last_visit_date_from_start_time(self):
        """ISO date extracted from start_time."""
        result = _merge_preferences(None, {"start_time": "2026-04-08T10:00:00+02:00"})
        assert result["last_visit_date"] == "2026-04-08"

    def test_merge_fallback_date_if_no_start_time(self):
        """No start_time → last_visit_date == date.today().isoformat()."""
        result = _merge_preferences(None, {})
        assert result["last_visit_date"] == date.today().isoformat()
