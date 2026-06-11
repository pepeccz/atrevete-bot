"""Unit tests for agent/middleware/_persistence.py — coercion table + guards.

S1-T2.1 RED: write tests first, then implement the helper.
S1-T2.2 GREEN: helper implemented; all tests pass.

Spec: REQ-S1-1 through REQ-S1-5, Scenarios S1-A through S1-D
Design: ADR-1 coercion table
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response() -> MagicMock:
    """Return a minimal ModelResponse-like mock."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Coercion: UUID (stdlib)
# ---------------------------------------------------------------------------


def test_uuid_stdlib_coerced_to_str():
    """REQ-S1-2 / Scenario S1-A: stdlib uuid.UUID is coerced to str."""
    from agent.middleware._persistence import persist_to_checkpoint

    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    response = _make_response()
    result = persist_to_checkpoint(response, {"customer_id": uid})

    assert hasattr(result, "command"), "Expected ExtendedModelResponse with command"
    update = result.command.update
    assert isinstance(update["customer_id"], str), "UUID must be coerced to str"
    assert update["customer_id"] == str(uid)


# ---------------------------------------------------------------------------
# Coercion: asyncpg pgproto UUID (if asyncpg is installed)
# ---------------------------------------------------------------------------


def test_asyncpg_pgproto_uuid_coerced_to_str():
    """REQ-S1-2 / Scenario S1-A: asyncpg pgproto UUID is coerced to str."""
    pytest.importorskip("asyncpg")
    import asyncpg.pgproto.pgproto as _pgproto  # type: ignore[import]

    from agent.middleware._persistence import persist_to_checkpoint

    uid_str = "12345678-1234-5678-1234-567812345678"
    # asyncpg pgproto UUID constructor accepts a str UUID
    pgproto_uid = _pgproto.UUID(uid_str)

    response = _make_response()
    result = persist_to_checkpoint(response, {"customer_id": pgproto_uid})

    update = result.command.update
    assert isinstance(update["customer_id"], str), "asyncpg pgproto UUID must be coerced to str"
    assert update["customer_id"] == uid_str


# ---------------------------------------------------------------------------
# Coercion: datetime → ISO 8601
# ---------------------------------------------------------------------------


def test_datetime_coerced_to_iso():
    """REQ-S1-3 / Scenario S1-B: datetime is coerced to ISO 8601 string."""
    from agent.middleware._persistence import persist_to_checkpoint

    dt = datetime.datetime(2026, 6, 1, 10, 30, 0, tzinfo=datetime.UTC)
    response = _make_response()
    result = persist_to_checkpoint(response, {"last_visit": dt})

    update = result.command.update
    assert isinstance(update["last_visit"], str), "datetime must be coerced to str"
    assert update["last_visit"] == "2026-06-01T10:30:00+00:00"


def test_date_coerced_to_iso():
    """datetime.date is also coerced to ISO 8601 string."""
    from agent.middleware._persistence import persist_to_checkpoint

    d = datetime.date(2026, 6, 1)
    response = _make_response()
    result = persist_to_checkpoint(response, {"appt_date": d})

    update = result.command.update
    assert isinstance(update["appt_date"], str)
    assert update["appt_date"] == "2026-06-01"


# ---------------------------------------------------------------------------
# Coercion: nested dict datetime (one level deep)
# ---------------------------------------------------------------------------


def test_nested_dict_datetime_coerced():
    """REQ-S1-4 / Scenario S1-C: datetime inside a nested dict is coerced."""
    from agent.middleware._persistence import persist_to_checkpoint

    dt = datetime.datetime(2026, 6, 1, 10, 30, 0, tzinfo=datetime.UTC)
    memories = {"last_visit": dt, "visit_count": 3, "preferred_stylist_name": "Ana"}
    response = _make_response()
    result = persist_to_checkpoint(response, {"customer_memories": memories})

    update = result.command.update
    coerced_memories = update["customer_memories"]
    assert isinstance(coerced_memories["last_visit"], str), "nested datetime must be coerced"
    assert coerced_memories["last_visit"] == "2026-06-01T10:30:00+00:00"
    assert coerced_memories["visit_count"] == 3, "int passthrough must be preserved"
    assert coerced_memories["preferred_stylist_name"] == "Ana", "str passthrough must be preserved"


# ---------------------------------------------------------------------------
# Coercion: passthrough types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("str_field", "hello"),
        ("int_field", 42),
        ("float_field", 3.14),
        ("bool_field", True),
        ("none_field", None),
    ],
)
def test_passthrough_types(field: str, value: object) -> None:
    """REQ-S1-1: None, str, int, float, bool pass through unchanged."""
    from agent.middleware._persistence import persist_to_checkpoint

    response = _make_response()

    if value is None:
        # Empty-dict path: {field: None} should still produce Command
        result = persist_to_checkpoint(response, {field: value})
        # None is a valid coerced value — command IS produced
        assert hasattr(result, "command")
        assert result.command.update[field] is None
    else:
        result = persist_to_checkpoint(response, {field: value})
        assert hasattr(result, "command")
        assert result.command.update[field] == value
        assert type(result.command.update[field]) is type(value)


# ---------------------------------------------------------------------------
# Empty delta: no-op (returns original response, NOT ExtendedModelResponse)
# ---------------------------------------------------------------------------


def test_empty_delta_returns_original_response():
    """REQ-S1-5 / Scenario S1-D: empty delta returns original response unchanged."""
    from agent.middleware._persistence import persist_to_checkpoint

    response = _make_response()
    result = persist_to_checkpoint(response, {})

    assert result is response, (
        "Empty delta must return the original ModelResponse object (no-op). "
        "ExtendedModelResponse must NOT be created for an empty delta."
    )


# ---------------------------------------------------------------------------
# Guard: messages key raises ValueError
# ---------------------------------------------------------------------------


def test_messages_key_raises_value_error():
    """'messages' key must raise ValueError — would corrupt add_messages reducer."""
    from agent.middleware._persistence import persist_to_checkpoint

    response = _make_response()
    with pytest.raises(ValueError, match="messages"):
        persist_to_checkpoint(response, {"messages": []})


# ---------------------------------------------------------------------------
# Guard: _slot_* key raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slot_key",
    [
        "_slot_customer",
        "_slot_availability",
        "_slot_catalog",
        "_slot_business_hours",
        "_slot_today",
    ],
)
def test_slot_key_raises_value_error(slot_key: str) -> None:
    """Any key starting with '_slot_' must raise ValueError."""
    from agent.middleware._persistence import persist_to_checkpoint

    response = _make_response()
    with pytest.raises(ValueError, match="_slot_"):
        persist_to_checkpoint(response, {slot_key: "some content"})


# ---------------------------------------------------------------------------
# Guard: unsupported type raises TypeError
# ---------------------------------------------------------------------------


def test_unsupported_type_raises_type_error():
    """Unsupported type (e.g. object()) raises TypeError with field name."""
    from agent.middleware._persistence import persist_to_checkpoint

    class _WeirdType:
        pass

    response = _make_response()
    with pytest.raises(TypeError, match="weird_field"):
        persist_to_checkpoint(response, {"weird_field": _WeirdType()})


# ---------------------------------------------------------------------------
# ExtendedModelResponse shape
# ---------------------------------------------------------------------------


def test_persist_produces_extended_model_response():
    """Non-empty delta produces ExtendedModelResponse wrapping original response."""
    from agent.middleware._persistence import persist_to_checkpoint

    response = _make_response()
    result = persist_to_checkpoint(response, {"customer_id": "abc-123", "last_count": 5})

    assert hasattr(result, "command"), "Result must have a command attribute"
    assert (
        hasattr(result, "model_response") or result is not response
    ), "Result must be an ExtendedModelResponse, not the original response"
    update = result.command.update
    assert update["customer_id"] == "abc-123"
    assert update["last_count"] == 5
