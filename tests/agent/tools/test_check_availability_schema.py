"""Schema contract tests for check_availability tool.

R3 — audience Literal must use snake_case English values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

CANONICAL_AUDIENCE_VALUES = [
    "adult_female",
    "adult_male",
    "child_female",
    "child_male",
    "baby",
    "unisex",
]

UPPERCASE_SPANISH_VALUES = [
    "MUJER",
    "HOMBRE",
    "NINO",
    "BEBE",
]


@pytest.mark.parametrize("audience_value", CANONICAL_AUDIENCE_VALUES)
def test_check_availability_audience_literal_accepts_canonical_values(audience_value):
    """check_availability.args_schema must accept canonical snake_case English values.

    RED: fails for all canonical values because the Literal currently only accepts
    uppercase Spanish values (MUJER, HOMBRE, NINO, BEBE).
    """
    from agent.tools.check_availability import check_availability

    # model_validate should NOT raise for canonical values
    instance = check_availability.args_schema.model_validate(
        {
            "service_ids": [],
            "stylist_id": None,
            "date_iso": "2026-04-29",
            "audience": audience_value,
        }
    )
    assert instance.audience == audience_value


@pytest.mark.parametrize("audience_value", UPPERCASE_SPANISH_VALUES)
def test_check_availability_audience_literal_rejects_uppercase_spanish(audience_value):
    """check_availability.args_schema must REJECT uppercase Spanish values.

    RED: fails because the Literal currently ACCEPTS these values.
    """
    from agent.tools.check_availability import check_availability

    with pytest.raises(ValidationError):
        check_availability.args_schema.model_validate(
            {
                "service_ids": [],
                "stylist_id": None,
                "date_iso": "2026-04-29",
                "audience": audience_value,
            }
        )


def test_check_availability_schema_exposes_only_exact_day_fields():
    """Fallback controls must stay out of the exact-day tool schema."""
    from agent.tools.check_availability import check_availability

    schema = check_availability.args_schema.model_json_schema()
    properties = schema.get("properties", {})

    assert set(properties) == {"service_ids", "stylist_id", "date_iso", "audience"}
    assert "requested_date_iso" not in properties
    assert "strategy" not in properties
    assert "search_days" not in properties
    assert "max_options" not in properties
