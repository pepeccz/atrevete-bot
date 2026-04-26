"""Tool protocol schema for MVP v7 agent tools.

All tools return ToolResponse serialized as JSON string via LangChain tool protocol.
errors[] must never start with imperative verbs (P5-aligned lint enforced in tests).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# P5: errors must never start with these imperative verbs (case-insensitive).
_IMPERATIVE_VERBS: tuple[str, ...] = (
    "debes",
    "tienes que",
    "haz",
    "pregunta",
    "envía",
    "usa",
    "llama",
)


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "partial", "rejected"]
    collected: dict[str, Any] = {}
    missing: list[str] = []
    next_step: str | None = (
        None  # str keeps compat with non-booking tools; booking tools use NextStep values
    )
    payload: dict[str, Any] = {}
    errors: list[str] = []

    @classmethod
    def validate_errors_non_imperative(cls, errors: list[str]) -> None:
        """Raise AssertionError listing any error strings that start with imperative verbs.

        Used in tests and optionally at tool return time to enforce P5 (no imperative tone).
        """
        offending = [e for e in errors if e.strip().lower().startswith(_IMPERATIVE_VERBS)]
        if offending:
            raise AssertionError(f"errors[] contains imperative verb(s): {offending}")
