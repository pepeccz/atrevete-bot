"""
Tests for booking_tools module — verifies simplified v4.0 schema.

Checks:
- BookSchema has customer_phone, services, slot_index
- Old sentinel values (__RESOLVE_FROM_SLOT__, audience) are gone
- rapidfuzz import was removed
"""

import inspect

import pytest

from agent.tools.booking_tools import BookSchema
import agent.tools.booking_tools as booking_tools_module


def test_schema_has_customer_phone():
    """BookSchema has customer_phone field."""
    fields = BookSchema.model_fields
    assert "customer_phone" in fields, "customer_phone field is missing from BookSchema"


def test_schema_has_services():
    """BookSchema has services field (list of service names)."""
    fields = BookSchema.model_fields
    assert "services" in fields, "services field is missing from BookSchema"


def test_schema_has_slot_index():
    """BookSchema has slot_index field."""
    fields = BookSchema.model_fields
    assert "slot_index" in fields, "slot_index field is missing from BookSchema"


def test_schema_no_old_fields():
    """BookSchema does not have audience field."""
    fields = BookSchema.model_fields
    assert "audience" not in fields, (
        "audience field should be removed — it belonged to the old catalog-lookup approach"
    )


def test_no_resolve_from_slot_sentinel():
    """__RESOLVE_FROM_SLOT__ sentinel value was removed from the module."""
    source = inspect.getsource(booking_tools_module)
    assert "__RESOLVE_FROM_SLOT__" not in source, (
        "__RESOLVE_FROM_SLOT__ sentinel should be gone — slot data is injected by _pre_tool_call"
    )


def test_no_rapidfuzz_import():
    """rapidfuzz import was removed from booking_tools."""
    source = inspect.getsource(booking_tools_module)
    assert "rapidfuzz" not in source, (
        "rapidfuzz should not be imported — fuzzy matching was removed in v4.0"
    )
