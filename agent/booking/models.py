"""
Booking domain models — Pydantic models for the booking capability.

Design refs: design §6 Q1
Requirements: R34–R38
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ServiceCatalogEntry(BaseModel):
    """Represents a single service from the catalog with audience disambiguation metadata.

    Expands the previous flat list[str] return from _load_service_names() to carry
    audience and sibling information needed by BookingInvariantMiddleware.

    Attributes:
        name: Exact service name as stored in the DB (e.g. "Corte Señora").
        audience: Audience tag from the DB (e.g. "adult_female", "adult_male", "child").
            None for services that have no audience variants.
        siblings: Names of other active services that share the same base family
            (same first word) but differ in audience. Includes self when audience is set.
            Empty list for services with audience=None (no variants).
        has_audience_siblings: True when siblings is non-empty. Computed from siblings.
    """

    name: str
    audience: str | None = None
    siblings: list[str] = Field(default_factory=list)
    has_audience_siblings: bool = Field(default=False)

    @model_validator(mode="after")
    def _compute_has_siblings(self) -> "ServiceCatalogEntry":
        """Derive has_audience_siblings from the siblings list."""
        object.__setattr__(self, "has_audience_siblings", bool(self.siblings))
        return self

    model_config = {"frozen": False}


class GroundingInstruction(BaseModel):
    """Grounding instruction for the LLM — alias for GroundingDirective as a Pydantic model.

    Used in tests that import from agent.booking.models directly.
    The action field is a closed Literal set of 13 values.
    """

    action: str
    reason: str = ""
    data: dict = Field(default_factory=dict)
