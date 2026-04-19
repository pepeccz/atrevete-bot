"""
Unit tests for _load_service_names expanded to ServiceCatalogEntry.

TDD pair:
- T1.7 RED: this file (ServiceCatalogEntry not yet defined)
- T1.8 GREEN: agent/booking/models.py (ServiceCatalogEntry Pydantic) +
              agent/modes/booking_mode.py (expanded _load_service_names)

Requirements: R34, R35, R36, R37, R38
Scenarios: S29, S30, S31
"""

from __future__ import annotations

import pytest

# This import will FAIL until T1.8 creates ServiceCatalogEntry — RED state
from agent.booking.models import ServiceCatalogEntry


# ============================================================================
# ServiceCatalogEntry shape (R34)
# ============================================================================


class TestServiceCatalogEntryShape:
    """R34 — ServiceCatalogEntry is a Pydantic model with required fields."""

    def test_has_name_field(self) -> None:
        entry = ServiceCatalogEntry(
            name="Óleo",
            audience=None,
            siblings=[],
        )
        assert entry.name == "Óleo"

    def test_has_audience_field(self) -> None:
        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
        )
        assert entry.audience == "adult_female"

    def test_has_siblings_field(self) -> None:
        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
        )
        assert isinstance(entry.siblings, list)
        assert len(entry.siblings) == 3

    def test_has_has_audience_siblings_field(self) -> None:
        """R34 — has_audience_siblings computed from siblings list."""
        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero"],
        )
        assert entry.has_audience_siblings is True

    def test_has_audience_siblings_false_when_empty_siblings(self) -> None:
        entry = ServiceCatalogEntry(
            name="Óleo",
            audience=None,
            siblings=[],
        )
        assert entry.has_audience_siblings is False


# ============================================================================
# S29 — Audience service entry shape (R35)
# ============================================================================


class TestAudienceServiceEntry:
    """S29 — entry for 'Corte Señora' has audience and siblings."""

    def test_audience_entry_siblings_include_self_and_others(self) -> None:
        """R35 — siblings list includes the service itself plus audience variants."""
        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero", "Corte Niño"],
        )
        assert "Corte Señora" in entry.siblings
        assert "Corte Caballero" in entry.siblings
        assert "Corte Niño" in entry.siblings

    def test_audience_entry_has_audience_siblings_true(self) -> None:
        entry = ServiceCatalogEntry(
            name="Corte Señora",
            audience="adult_female",
            siblings=["Corte Señora", "Corte Caballero"],
        )
        assert entry.has_audience_siblings is True


# ============================================================================
# S30 — Non-audience service has empty siblings (R36)
# ============================================================================


class TestNonAudienceServiceEntry:
    """S30 — service with audience=None has empty siblings."""

    def test_no_audience_entry_has_empty_siblings(self) -> None:
        entry = ServiceCatalogEntry(
            name="Óleo",
            audience=None,
            siblings=[],
        )
        assert entry.siblings == []

    def test_no_audience_entry_has_audience_siblings_false(self) -> None:
        entry = ServiceCatalogEntry(
            name="Óleo",
            audience=None,
            siblings=[],
        )
        assert entry.has_audience_siblings is False


# ============================================================================
# S31 — mypy-friendly: ServiceCatalogEntry.name attribute accessible (R37)
# ============================================================================


class TestNameAttributeAccess:
    """R37 — callers that used list[str] now use .name attribute."""

    def test_name_attribute_on_service_catalog_entry(self) -> None:
        entry = ServiceCatalogEntry(name="Mechas", audience=None, siblings=[])
        assert entry.name == "Mechas"

    def test_list_of_entries_name_access(self) -> None:
        entries = [
            ServiceCatalogEntry(name="Óleo", audience=None, siblings=[]),
            ServiceCatalogEntry(name="Mechas", audience=None, siblings=[]),
        ]
        names = [e.name for e in entries]
        assert names == ["Óleo", "Mechas"]


# ============================================================================
# ServiceCatalogEntry is a Pydantic model (R34)
# ============================================================================


class TestIsPydanticModel:
    def test_is_pydantic_base_model(self) -> None:
        from pydantic import BaseModel

        assert issubclass(ServiceCatalogEntry, BaseModel)

    def test_instantiation_with_keyword_args(self) -> None:
        entry = ServiceCatalogEntry(name="Test", audience="adult_female", siblings=["Test"])
        assert entry.name == "Test"

    def test_invalid_name_type_raises(self) -> None:
        """Pydantic validation should reject non-string name."""
        with pytest.raises(Exception):
            ServiceCatalogEntry(name=123, audience=None, siblings=[])  # type: ignore[arg-type]

    def test_serializable_to_dict(self) -> None:
        entry = ServiceCatalogEntry(name="Óleo", audience=None, siblings=[])
        d = entry.model_dump()
        assert d["name"] == "Óleo"
        assert d["audience"] is None
        assert d["siblings"] == []
