"""
Unit tests for strict-tools-schema-fix change.

Validates:
- CustomerData typed model (T4.1)
- QueryFilters typed model (T4.2)
- parse_filters validator all branches (T4.3)
- book() signature defaults regression fix (T4.4)
- Strict schema compliance (no additionalProperties: true) (T4.5)

No database, no LLM — pure unit tests.
"""

import inspect

import pytest
from pydantic import ValidationError

from agent.tools.booking_tools import book, BookSchema
from agent.tools.customer_tools import CustomerData, ManageCustomerSchema
from agent.tools.info_tools import QueryFilters, QueryInfoSchema


# ============================================================================
# T4.1 — CustomerData model construction and defaults
# ============================================================================


class TestCustomerDataModel:
    def test_customer_data_all_none(self):
        """CustomerData() with no args → all fields are None."""
        cd = CustomerData()
        assert cd.customer_id is None
        assert cd.first_name is None
        assert cd.last_name is None
        assert cd.notes is None

    def test_customer_data_partial(self):
        """CustomerData(first_name="Ana") → only first_name set, rest None."""
        cd = CustomerData(first_name="Ana")
        assert cd.first_name == "Ana"
        assert cd.last_name is None
        assert cd.notes is None
        assert cd.customer_id is None

    def test_customer_data_all_fields(self):
        """CustomerData with all fields populated."""
        cd = CustomerData(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            first_name="Ana",
            last_name="Gómez",
            notes="VIP",
        )
        assert cd.customer_id == "550e8400-e29b-41d4-a716-446655440000"
        assert cd.first_name == "Ana"
        assert cd.last_name == "Gómez"
        assert cd.notes == "VIP"

    def test_manage_customer_schema_coerces_dict_to_customer_data(self):
        """ManageCustomerSchema coerces dict → CustomerData automatically."""
        schema = ManageCustomerSchema(
            action="create",
            phone="+34600000000",
            data={"first_name": "Ana"},
        )
        assert isinstance(schema.data, CustomerData)
        assert schema.data.first_name == "Ana"
        assert schema.data.last_name is None

    def test_manage_customer_schema_no_data(self):
        """ManageCustomerSchema(action='get', ...) works with data=None."""
        schema = ManageCustomerSchema(action="get", phone="+34600000000")
        assert schema.data is None


# ============================================================================
# T4.2 — QueryFilters model construction and defaults
# ============================================================================


class TestQueryFiltersModel:
    def test_query_filters_category_only(self):
        """QueryFilters(category=...) — keywords defaults to None."""
        qf = QueryFilters(category="Peluquería")
        assert qf.category == "Peluquería"
        assert qf.keywords is None

    def test_query_filters_keywords_only(self):
        """QueryFilters(keywords=...) — category defaults to None."""
        qf = QueryFilters(keywords=["hours", "parking"])
        assert qf.keywords == ["hours", "parking"]
        assert qf.category is None

    def test_query_filters_all_none(self):
        """QueryFilters() with no args → all fields are None."""
        qf = QueryFilters()
        assert qf.category is None
        assert qf.keywords is None


# ============================================================================
# T4.3 — parse_filters validator all branches
# ============================================================================


class TestParseFiltersValidator:
    def test_none_passthrough(self):
        """parse_filters with None → field is None."""
        schema = QueryInfoSchema(type="services", filters=None)
        assert schema.filters is None

    def test_from_json_string_category(self):
        """parse_filters with JSON string containing category."""
        schema = QueryInfoSchema(type="services", filters='{"category": "Peluquería"}')
        assert isinstance(schema.filters, QueryFilters)
        assert schema.filters.category == "Peluquería"

    def test_from_json_string_keywords(self):
        """parse_filters with JSON string containing keywords."""
        schema = QueryInfoSchema(type="faqs", filters='{"keywords": ["hours"]}')
        assert isinstance(schema.filters, QueryFilters)
        assert schema.filters.keywords == ["hours"]

    def test_from_dict(self):
        """parse_filters with dict → coerces to QueryFilters."""
        schema = QueryInfoSchema(type="services", filters={"category": "Estética"})
        assert isinstance(schema.filters, QueryFilters)
        assert schema.filters.category == "Estética"

    def test_from_dict_keywords(self):
        """parse_filters with dict containing keywords."""
        schema = QueryInfoSchema(type="faqs", filters={"keywords": ["corte"]})
        assert isinstance(schema.filters, QueryFilters)
        assert schema.filters.keywords == ["corte"]

    def test_already_instance(self):
        """parse_filters with QueryFilters instance → returned as-is."""
        qf = QueryFilters(category="Peluquería")
        schema = QueryInfoSchema(type="services", filters=qf)
        assert isinstance(schema.filters, QueryFilters)
        assert schema.filters.category == "Peluquería"

    def test_invalid_json_raises_validation_error(self):
        """parse_filters with broken JSON string → raises ValidationError."""
        with pytest.raises(ValidationError):
            QueryInfoSchema(type="services", filters='"broken')

    def test_wrong_type_raises_validation_error(self):
        """parse_filters with wrong type (int) → raises ValidationError."""
        with pytest.raises(ValidationError):
            QueryInfoSchema(type="services", filters=123)


# ============================================================================
# T4.4 — Regression: book() called without last_name/notes
# ============================================================================


def _get_book_fn():
    """Resolve the underlying function from the LangChain @tool wrapper."""
    # For sync tools: book.func; for async tools: book.coroutine; fallback: book itself
    if hasattr(book, "coroutine") and book.coroutine is not None:
        return book.coroutine
    if hasattr(book, "func") and book.func is not None:
        return book.func
    return book


class TestBookSignatureDefaults:
    def test_book_last_name_has_default_none(self):
        """book() function has last_name=None default."""
        sig = inspect.signature(_get_book_fn())
        assert sig.parameters["last_name"].default is None

    def test_book_notes_has_default_none(self):
        """book() function has notes=None default."""
        sig = inspect.signature(_get_book_fn())
        assert sig.parameters["notes"].default is None

    def test_book_schema_without_optional_params(self):
        """BookSchema works without last_name and notes → both None."""
        schema = BookSchema(
            customer_id="550e8400-e29b-41d4-a716-446655440000",
            first_name="Ana",
            services=["Corte de Caballero"],
            stylist_id="550e8400-e29b-41d4-a716-446655440001",
            start_time="2026-06-01T10:00:00+02:00",
        )
        assert schema.last_name is None
        assert schema.notes is None


# ============================================================================
# T4.5 — Strict schema compliance (no additionalProperties: true)
# ============================================================================


def _has_additional_properties_true(schema_dict: dict) -> bool:
    """Recursively check if any object in the schema allows additionalProperties."""
    if schema_dict.get("additionalProperties") is True:
        return True
    for value in schema_dict.values():
        if isinstance(value, dict) and _has_additional_properties_true(value):
            return True
    return False


class TestStrictSchemaCompliance:
    def test_manage_customer_schema_strict_compatible(self):
        """ManageCustomerSchema JSON schema has no open additionalProperties."""
        schema = ManageCustomerSchema.model_json_schema()
        assert not _has_additional_properties_true(schema), (
            "ManageCustomerSchema has additionalProperties: true — not strict mode compatible"
        )

    def test_query_info_schema_strict_compatible(self):
        """QueryInfoSchema JSON schema has no open additionalProperties."""
        schema = QueryInfoSchema.model_json_schema()
        assert not _has_additional_properties_true(schema), (
            "QueryInfoSchema has additionalProperties: true — not strict mode compatible"
        )


# ============================================================================
# T4.6 — QueryFilters 'required' field present (Azure strict schema fix)
# ============================================================================


class TestQueryFiltersRequiredField:
    def test_query_filters_schema_has_required(self):
        """QueryFilters JSON schema must include 'required' array.

        Azure (via OpenRouter) rejects tool schemas where 'properties' exists
        but 'required' is absent, even when all fields are nullable/optional.
        See: agent/tools/info_tools.py QueryFilters model_config.
        """
        schema = QueryFilters.model_json_schema()
        assert "required" in schema, (
            "QueryFilters schema is missing 'required' — Azure strict validation will reject it"
        )

    def test_query_filters_required_contains_all_properties(self):
        """QueryFilters 'required' must list every key in 'properties'."""
        schema = QueryFilters.model_json_schema()
        properties = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        assert properties == required, (
            f"QueryFilters 'required' {required} does not match 'properties' {properties}"
        )

    def test_query_filters_fields_still_nullable(self):
        """Fields in 'required' are still nullable (anyOf includes null) — defaults work."""
        schema = QueryFilters.model_json_schema()
        for field_name in schema.get("required", []):
            field_schema = schema["properties"][field_name]
            any_of_types = [opt.get("type") for opt in field_schema.get("anyOf", [])]
            assert "null" in any_of_types, (
                f"QueryFilters.{field_name} is in 'required' but not nullable — "
                "optional fields must allow null"
            )
