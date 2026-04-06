"""
Tests for availability_tools module — verifies simplified v5.0 schema.

Checks:
- CheckAvailabilitySchema has the new fields (service_name, date, stylist_name, time_range)
- find_next_available was removed (merged into check_availability AUTO-SEARCH logic)
- Old schema fields (service_category, service_duration_minutes) are gone
"""

import inspect

import pytest

from agent.tools.availability_tools import CheckAvailabilitySchema


def test_schema_has_service_names():
    """CheckAvailabilitySchema has service_names field (list[str])."""
    fields = CheckAvailabilitySchema.model_fields
    assert "service_names" in fields, "service_names field is missing from CheckAvailabilitySchema"


def test_schema_service_names_is_list():
    """service_names field accepts a list of strings."""
    schema = CheckAvailabilitySchema(service_names=["Cortar", "Cultura de Color"], date="2026-04-10")
    assert schema.service_names == ["Cortar", "Cultura de Color"]


def test_schema_service_names_single():
    """service_names field works with a single service (list of 1)."""
    schema = CheckAvailabilitySchema(service_names=["Cortar"], date="2026-04-10")
    assert schema.service_names == ["Cortar"]


def test_schema_has_date():
    """CheckAvailabilitySchema has date field."""
    fields = CheckAvailabilitySchema.model_fields
    assert "date" in fields, "date field is missing from CheckAvailabilitySchema"


def test_schema_has_stylist_name():
    """CheckAvailabilitySchema has stylist_name field (replaces stylist_id)."""
    fields = CheckAvailabilitySchema.model_fields
    assert "stylist_name" in fields, "stylist_name field is missing from CheckAvailabilitySchema"


def test_schema_has_time_range():
    """CheckAvailabilitySchema has time_range field."""
    fields = CheckAvailabilitySchema.model_fields
    assert "time_range" in fields, "time_range field is missing from CheckAvailabilitySchema"


def test_no_find_next_available():
    """find_next_available was removed — merged into check_availability AUTO-SEARCH."""
    import agent.tools.availability_tools as module

    assert not hasattr(module, "find_next_available"), (
        "find_next_available should not exist — it was merged into check_availability AUTO-SEARCH"
    )


def test_no_old_schema_fields():
    """Old fields service_category and service_duration_minutes are gone from schema."""
    import agent.tools.availability_tools as module

    source = inspect.getsource(module)
    assert "service_category" not in CheckAvailabilitySchema.model_fields, (
        "service_category should not be a schema field in the simplified architecture"
    )
    assert "service_duration_minutes" not in CheckAvailabilitySchema.model_fields, (
        "service_duration_minutes should not be a schema field — duration is resolved internally"
    )
