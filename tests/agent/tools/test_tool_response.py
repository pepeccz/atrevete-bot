"""Tests for ToolResponse Pydantic model — Phase 1.3/1.4."""

import json

import pytest
from pydantic import ValidationError

from agent.tools.schemas import ToolResponse

# ---------------------------------------------------------------------------
# Basic model validation
# ---------------------------------------------------------------------------


class TestToolResponseValidation:
    def test_valid_ok(self):
        tr = ToolResponse(status="ok")
        assert tr.status == "ok"
        assert tr.payload == {}
        assert tr.next_step is None
        assert tr.errors == []

    def test_valid_partial(self):
        tr = ToolResponse(status="partial", errors=["faltan datos"])
        assert tr.status == "partial"

    def test_valid_rejected(self):
        tr = ToolResponse(status="rejected", errors=["servicio no disponible"])
        assert tr.status == "rejected"

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            ToolResponse(status="unknown")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ToolResponse(status="ok", unknown_field="bad")

    def test_payload_defaults_to_empty_dict(self):
        tr = ToolResponse(status="ok")
        assert tr.payload == {}

    def test_errors_defaults_to_empty_list(self):
        tr = ToolResponse(status="ok")
        assert tr.errors == []


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestToolResponseSerialization:
    def test_model_dump_json_is_valid_json(self):
        tr = ToolResponse(status="ok", payload={"slot": "10:00"}, next_step="confirm")
        raw = tr.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["status"] == "ok"
        assert parsed["next_step"] == "confirm"

    def test_model_dump_json_contains_all_fields(self):
        tr = ToolResponse(status="rejected", errors=["no hay turnos"])
        parsed = json.loads(tr.model_dump_json())
        assert set(parsed.keys()) == {"status", "collected", "missing", "payload", "next_step", "errors"}


# ---------------------------------------------------------------------------
# Non-imperative error lint
# ---------------------------------------------------------------------------

IMPERATIVE_VERBS = ["Debes", "Tienes que", "Haz", "Pregunta", "Envía", "Usa", "Llama"]


@pytest.mark.parametrize("verb", IMPERATIVE_VERBS)
def test_validate_errors_raises_on_imperative_verb(verb):
    bad_error = f"{verb} algo al cliente"
    with pytest.raises(AssertionError):
        ToolResponse.validate_errors_non_imperative([bad_error])


def test_validate_errors_passes_on_clean_errors():
    clean = ["servicio no disponible", "fecha fuera de rango"]
    ToolResponse.validate_errors_non_imperative(clean)  # must not raise


def test_validate_errors_case_insensitive():
    with pytest.raises(AssertionError):
        ToolResponse.validate_errors_non_imperative(["debes confirmar el turno"])


def test_validate_errors_empty_list_passes():
    ToolResponse.validate_errors_non_imperative([])  # must not raise


def test_validate_errors_reports_offending_strings():
    bad = ["Debes ir al salón", "otro error limpio"]
    with pytest.raises(AssertionError, match="Debes ir al salón"):
        ToolResponse.validate_errors_non_imperative(bad)
