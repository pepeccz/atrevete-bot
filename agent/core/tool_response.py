"""Typed tool response per P5. The contract every capability tool returns starting in E2.

Status values:
  ok        — all required data collected, ready to proceed.
  partial   — some data collected, more needed.
  rejected  — input validation failed; errors[] explains what went wrong.
  complete  — flow finished (booking confirmed, cancellation done, etc.).

Imperative verbs in errors[] are FORBIDDEN (bug class #3906): errors describe input
problems; they must never be instructions to the LLM. 14 forbidden forms enforced
at construction time by _no_imperatives validator.

E1: module exists; zero callers in production. First adopter is BookingCapability in E2.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Forbidden imperative registry
# ---------------------------------------------------------------------------

# Spec R8 mandatory baseline (6 forms) + empirical extension from bug class #3906 (8 forms).
# All lowercase-stripped; case-insensitive at validation time.
FORBIDDEN_IMPERATIVES: frozenset[str] = frozenset(
    {
        # Spec R8 mandatory
        "pregunta",
        "muestra",
        "llama",
        "debes",
        "dile",
        "pide",
        # Extended from bug class #3906
        "confirma",
        "verifica",
        "comprueba",
        "escribe",
        "indica",
        "proporciona",
        "completa",
        "selecciona",
    }
)


# ---------------------------------------------------------------------------
# ToolResponse model
# ---------------------------------------------------------------------------


class ToolResponse(BaseModel):
    """Structured result returned by every capability tool (E2+).

    extra="forbid" prevents accidental fields from leaking into the contract.
    frozen=False allows post-construction mutation where needed (rare).
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    status: Literal["ok", "partial", "rejected", "complete"]
    collected: list[str]
    missing: list[str]
    next_step: str
    errors: list[str]
    payload: dict[str, Any] = {}

    @field_validator("errors")
    @classmethod
    def _no_imperatives(cls, v: list[str]) -> list[str]:
        """Reject error strings that begin with a forbidden imperative verb."""
        for item in v:
            stripped = item.strip()
            if not stripped:
                continue
            first = stripped.split(maxsplit=1)[0]
            if first.lower() in FORBIDDEN_IMPERATIVES:
                raise ValueError(
                    f"errors[] item starts with forbidden imperative {first!r}; "
                    f"errors must describe input problems, never LLM instructions"
                )
        return v


# ---------------------------------------------------------------------------
# AST-lint companion
# ---------------------------------------------------------------------------


def assert_no_imperative_errors(source_path: Path) -> list[str]:
    """AST scan: return 'path:line: violation' strings for imperative errors= kwargs.

    Detects errors=[...] keyword arguments in any function call and flags string
    literals that start with a FORBIDDEN_IMPERATIVES verb. Empty list = clean.

    Used in tests/integration/test_e1_scaffolding/test_imperative_lint.py as a
    pre-migration smoke test over agent/tools/*.py.
    """
    violations: list[str] = []
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "errors" or not isinstance(kw.value, (ast.List, ast.Tuple)):
                continue
            for elt in kw.value.elts:
                if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                    continue
                stripped = elt.value.strip()
                if not stripped:
                    continue
                first = stripped.split(maxsplit=1)[0]
                if first.lower() in FORBIDDEN_IMPERATIVES:
                    violations.append(
                        f"{source_path}:{elt.lineno}: "
                        f"forbidden imperative {first!r} in errors[]"
                    )
    return violations
