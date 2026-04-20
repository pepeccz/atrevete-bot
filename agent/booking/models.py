"""
Booking domain models — Pydantic models for the booking capability.

Design refs: design §6 Q1
Requirements: R34–R38
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


def _family_key(
    metadata_: dict | None, audience: str | None
) -> tuple[str, str] | None:
    """Return the audience-family key for a service, or None if not groupable.

    The key is `(dimension, service_type="principal")`. Services without audience,
    without a metadata dimension, or that are variants (service_type != "principal")
    return None — they have no sibling family in the audience-disambiguation sense.
    """
    if not audience:
        return None
    if not metadata_:
        return None
    service_type = metadata_.get("service_type")
    dimension = metadata_.get("dimension")
    if service_type != "principal" or not dimension:
        return None
    return (dimension, "principal")


class ServiceCatalogEntry(BaseModel):
    """Represents a single service from the catalog with audience disambiguation metadata.

    Expands the previous flat list[str] return from _load_service_names() to carry
    audience and sibling information needed by BookingInvariantMiddleware.

    Attributes:
        name: Exact service name as stored in the DB (e.g. "Corte Caballero").
        audience: Audience tag from the DB (e.g. "adult_female", "adult_male", "child").
            None for services that have no audience variants.
        siblings: Names of other active services in the same `(dimension, principal)`
            family (per `metadata_.dimension` + `metadata_.service_type="principal"`).
            Includes self when audience is set and the service is a principal with
            a declared dimension. Empty list otherwise.
        has_audience_siblings: True when siblings is non-empty. Computed from siblings.
    """

    name: str
    audience: str | None = None
    siblings: list[str] = Field(default_factory=list)
    has_audience_siblings: bool = Field(default=False)

    @model_validator(mode="after")
    def _compute_has_siblings(self) -> ServiceCatalogEntry:
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
