"""Tests for agent/booking/schemas.py field descriptions — Task 1.3 (booking-prompts-audit-fix).

Spec:
- Every field in schemas.py MUST carry Field(description=...) with a non-empty string.
- Every response class MUST have a class-level docstring.
- ServiceSelectionResponse MUST NOT have a suggested_audience field.
- AudienceTag MUST have exactly 6 values.
"""

from __future__ import annotations

import pytest

from agent.booking.schemas import (
    AudienceResponse,
    ConfirmationResponse,
    DateResponse,
    NameResponse,
    NotesResponse,
    ServiceSelectionResponse,
    SlotResponse,
    StylistResponse,
)

ALL_SCHEMAS = [
    ServiceSelectionResponse,
    AudienceResponse,
    StylistResponse,
    DateResponse,
    SlotResponse,
    NameResponse,
    NotesResponse,
    ConfirmationResponse,
]


@pytest.mark.parametrize("schema_class", ALL_SCHEMAS, ids=lambda c: c.__name__)
def test_all_fields_have_non_empty_description(schema_class):
    """Every field in each schema must carry a non-empty Field(description=...)."""
    json_schema = schema_class.model_json_schema()
    properties = json_schema.get("properties", {})
    assert properties, f"{schema_class.__name__} has no properties in JSON schema"
    for field_name, field_schema in properties.items():
        description = field_schema.get("description", "")
        assert description, (
            f"{schema_class.__name__}.{field_name} has no description in JSON schema. "
            f"Add Field(description='...') to this field."
        )


@pytest.mark.parametrize("schema_class", ALL_SCHEMAS, ids=lambda c: c.__name__)
def test_all_schemas_have_docstring(schema_class):
    """Every response schema class must have a class-level docstring."""
    assert schema_class.__doc__, f"{schema_class.__name__} has no docstring"
    assert schema_class.__doc__.strip(), f"{schema_class.__name__} docstring is empty/whitespace"


def test_service_selection_response_has_no_suggested_audience():
    """ServiceSelectionResponse MUST NOT have a suggested_audience field (spec: no collapse)."""
    assert not hasattr(
        ServiceSelectionResponse, "suggested_audience"
    ) or "suggested_audience" not in ServiceSelectionResponse.model_fields, (
        "ServiceSelectionResponse must not contain suggested_audience"
    )


def test_service_selection_response_schema_has_no_suggested_audience():
    """suggested_audience must not appear in the JSON schema properties."""
    props = ServiceSelectionResponse.model_json_schema().get("properties", {})
    assert "suggested_audience" not in props


def test_audience_response_accepts_baby():
    """AudienceResponse must accept 'baby' as inferred_audience after AudienceTag update."""
    r = AudienceResponse(message="para el bebé", inferred_audience="baby")
    assert r.inferred_audience == "baby"
