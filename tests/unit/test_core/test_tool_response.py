"""Unit tests for agent.core.tool_response — ToolResponse Pydantic + AST linter (R7, R8, R9)."""
from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

from agent.core.tool_response import (
    FORBIDDEN_IMPERATIVES,
    ToolResponse,
    assert_no_imperative_errors,
)

# ---------------------------------------------------------------------------
# R7 — ToolResponse: field construction and status literal enforcement
# ---------------------------------------------------------------------------

_VALID_BASE = {
    "status": "ok",
    "collected": ["servicio"],
    "missing": [],
    "next_step": "confirmar",
    "errors": [],
}


def test_valid_construction_all_fields():
    """All fields accessible; payload defaults to {} when omitted."""
    tr = ToolResponse(**_VALID_BASE)
    assert tr.status == "ok"
    assert tr.collected == ["servicio"]
    assert tr.missing == []
    assert tr.next_step == "confirmar"
    assert tr.errors == []
    assert tr.payload == {}


def test_payload_defaults_to_empty_dict():
    tr = ToolResponse(**_VALID_BASE)
    assert tr.payload == {}


@pytest.mark.parametrize("status", ["ok", "partial", "rejected", "complete"])
def test_valid_statuses_accepted(status):
    tr = ToolResponse(**{**_VALID_BASE, "status": status})
    assert tr.status == status


@pytest.mark.parametrize("status", ["invalid", "done", "error", "pending"])
def test_invalid_statuses_rejected(status):
    with pytest.raises(ValidationError):
        ToolResponse(**{**_VALID_BASE, "status": status})


# ---------------------------------------------------------------------------
# R7 — extra fields are forbidden
# ---------------------------------------------------------------------------


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ToolResponse(**_VALID_BASE, unexpected_field="oops")


# ---------------------------------------------------------------------------
# R8 — imperative verb validator on errors list
# ---------------------------------------------------------------------------

# All 14 forbidden imperatives (bare form, lowercase = canonical)
_FORBIDDEN_FORMS = [
    "pregunta",
    "muestra",
    "llama",
    "debes",
    "dile",
    "pide",
    "confirma",
    "verifica",
    "comprueba",
    "escribe",
    "indica",
    "proporciona",
    "completa",
    "selecciona",
]


@pytest.mark.parametrize("verb", _FORBIDDEN_FORMS)
def test_bare_imperative_rejected(verb):
    """Bare imperative (lowercase) at start of error string → ValidationError."""
    with pytest.raises(ValidationError):
        ToolResponse(**{**_VALID_BASE, "errors": [verb]})


@pytest.mark.parametrize("verb", _FORBIDDEN_FORMS)
def test_capitalized_imperative_with_continuation_rejected(verb):
    """Capitalized imperative with trailing text → ValidationError."""
    with pytest.raises(ValidationError):
        ToolResponse(**{**_VALID_BASE, "errors": [verb.capitalize() + " al cliente el nombre"]})


@pytest.mark.parametrize(
    "safe_error",
    [
        "El cliente no proporcionó el nombre",
        "Falta selector de slot",
        "No se encontró disponibilidad",
        "",
        "   ",
    ],
)
def test_safe_error_strings_accepted(safe_error):
    """Non-imperative error strings must NOT raise."""
    tr = ToolResponse(**{**_VALID_BASE, "errors": [safe_error]})
    assert safe_error in tr.errors


def test_empty_errors_list_accepted():
    tr = ToolResponse(**{**_VALID_BASE, "errors": []})
    assert tr.errors == []


def test_forbidden_imperatives_frozenset_has_14_entries():
    assert len(FORBIDDEN_IMPERATIVES) == 14


# ---------------------------------------------------------------------------
# R9 — assert_no_imperative_errors AST helper
# ---------------------------------------------------------------------------


def test_assert_no_imperative_errors_detects_violation(tmp_path):
    """Synthetic file with errors=['Pregunta al cliente'] → 1 violation returned."""
    src = textwrap.dedent("""\
        def my_tool():
            return dict(
                status="ok",
                errors=["Pregunta al cliente el nombre"],
            )
    """)
    p = tmp_path / "tool_under_test.py"
    p.write_text(src, encoding="utf-8")

    violations = assert_no_imperative_errors(p)
    assert len(violations) == 1
    assert "Pregunta" in violations[0]
    assert str(p) in violations[0]


def test_assert_no_imperative_errors_clean_file(tmp_path):
    """Clean file returns empty list."""
    src = textwrap.dedent("""\
        def my_tool():
            return dict(
                status="ok",
                errors=["Falta el nombre del cliente"],
            )
    """)
    p = tmp_path / "clean_tool.py"
    p.write_text(src, encoding="utf-8")

    violations = assert_no_imperative_errors(p)
    assert violations == []


def test_assert_no_imperative_errors_multiple_violations(tmp_path):
    """Multiple imperative errors in the same file → multiple violations."""
    src = textwrap.dedent("""\
        def tool_a():
            return dict(errors=["Pregunta al cliente"])

        def tool_b():
            return dict(errors=["Muestra el calendario"])
    """)
    p = tmp_path / "multi_violation.py"
    p.write_text(src, encoding="utf-8")

    violations = assert_no_imperative_errors(p)
    assert len(violations) == 2
