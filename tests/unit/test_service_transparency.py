"""Tests for the service-transparency feature.

Covers:
- T-9:  _upsert_service_detail — dedup, null-description skip, cap at 5
- T-10: _build_service_details_section — rendering with 1, 2, empty, null filtered
- T-11: extract_service_fields Shape 1 + Shape 3 populate selected_services_details
- T-12: Serialization round-trip via to_mode_context / from_mode_context
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.tool_extractors import _upsert_service_detail, extract_service_fields
from agent.modes.booking_mode import _build_service_details_section


# ============================================================================
# T-9: _upsert_service_detail
# ============================================================================


class TestUpsertServiceDetail:
    """T-9: _upsert_service_detail — dedup, null skip, cap at 5."""

    def test_single_service_detail(self):
        ctx = BookingContext()
        svc = {"name": "Cortar", "duration_minutes": 40, "description": "Corte completo con lavado"}
        _upsert_service_detail(ctx, svc)
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0] == {
            "name": "Cortar",
            "duration": 40,
            "description": "Corte completo con lavado",
        }

    def test_upsert_deduplicates_by_name(self):
        ctx = BookingContext()
        svc1 = {"name": "Cortar", "duration_minutes": 40, "description": "Desc v1"}
        svc2 = {"name": "Cortar", "duration_minutes": 45, "description": "Desc v2"}
        _upsert_service_detail(ctx, svc1)
        _upsert_service_detail(ctx, svc2)
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["description"] == "Desc v2"
        assert ctx.selected_services_details[0]["duration"] == 45

    def test_null_description_skipped(self):
        ctx = BookingContext()
        _upsert_service_detail(ctx, {"name": "Cortar", "duration_minutes": 40, "description": None})
        assert ctx.selected_services_details == []

    def test_empty_description_skipped(self):
        ctx = BookingContext()
        _upsert_service_detail(ctx, {"name": "Cortar", "duration_minutes": 40, "description": ""})
        assert ctx.selected_services_details == []

    def test_missing_description_key_skipped(self):
        ctx = BookingContext()
        _upsert_service_detail(ctx, {"name": "Cortar", "duration_minutes": 40})
        assert ctx.selected_services_details == []

    def test_cap_at_5(self):
        ctx = BookingContext()
        for i in range(7):
            _upsert_service_detail(
                ctx,
                {"name": f"Service{i}", "duration_minutes": 30, "description": f"Desc {i}"},
            )
        assert len(ctx.selected_services_details) == 5
        names = [d["name"] for d in ctx.selected_services_details]
        assert names == ["Service0", "Service1", "Service2", "Service3", "Service4"]

    def test_upsert_within_cap_allows_replacement(self):
        """Replacing an existing entry should not increase count beyond cap."""
        ctx = BookingContext()
        for i in range(5):
            _upsert_service_detail(
                ctx,
                {"name": f"Service{i}", "duration_minutes": 30, "description": f"Desc {i}"},
            )
        # Upsert existing entry — should replace, not exceed cap
        _upsert_service_detail(
            ctx,
            {"name": "Service2", "duration_minutes": 60, "description": "Updated"},
        )
        assert len(ctx.selected_services_details) == 5
        updated = next(d for d in ctx.selected_services_details if d["name"] == "Service2")
        assert updated["description"] == "Updated"


# ============================================================================
# T-10: _build_service_details_section
# ============================================================================


class TestBuildServiceDetailsSection:
    """T-10: _build_service_details_section — rendering."""

    def test_empty_list_returns_empty_string(self):
        ctx = BookingContext()
        assert _build_service_details_section(ctx) == ""

    def test_single_entry_with_duration(self):
        ctx = BookingContext(
            selected_services_details=[
                {"name": "Cortar", "duration": 40, "description": "Corte con lavado"}
            ]
        )
        result = _build_service_details_section(ctx)
        assert result == "- **Cortar** (40min): Corte con lavado"

    def test_single_entry_without_duration(self):
        ctx = BookingContext(
            selected_services_details=[
                {"name": "Cortar", "duration": None, "description": "Corte con lavado"}
            ]
        )
        result = _build_service_details_section(ctx)
        assert result == "- **Cortar**: Corte con lavado"

    def test_multi_entry(self):
        ctx = BookingContext(
            selected_services_details=[
                {"name": "Cortar", "duration": 40, "description": "Corte con lavado"},
                {"name": "Tinte", "duration": 90, "description": "Coloración completa"},
            ]
        )
        result = _build_service_details_section(ctx)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "**Cortar**" in lines[0]
        assert "**Tinte**" in lines[1]

    def test_null_description_filtered(self):
        ctx = BookingContext(
            selected_services_details=[
                {"name": "Cortar", "duration": 40, "description": "Corte con lavado"},
                {"name": "Tinte", "duration": 90, "description": None},
            ]
        )
        result = _build_service_details_section(ctx)
        assert "Cortar" in result
        assert "Tinte" not in result


# ============================================================================
# T-11: extract_service_fields populates selected_services_details
# ============================================================================


class TestExtractServiceFieldsDetails:
    """T-11: Shape 1 + Shape 3 populate selected_services_details."""

    def test_shape1_resolved_service_with_description(self):
        ctx = BookingContext()
        result = {
            "resolved_service": {
                "id": "uuid-1",
                "name": "Cortar",
                "category": "Peluquería",
                "duration_minutes": 40,
                "description": "Corte capilar completo con lavado incluido",
            }
        }
        extract_service_fields(result, ctx)
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["name"] == "Cortar"
        assert ctx.selected_services_details[0]["description"] == (
            "Corte capilar completo con lavado incluido"
        )

    def test_shape1_resolved_service_without_description(self):
        ctx = BookingContext()
        result = {
            "resolved_service": {
                "id": "uuid-1",
                "name": "Cortar",
                "category": "Peluquería",
                "duration_minutes": 40,
            }
        }
        extract_service_fields(result, ctx)
        assert ctx.selected_services_details == []

    def test_shape3_single_result_with_description(self):
        ctx = BookingContext()
        result = {
            "services": [
                {
                    "id": "uuid-2",
                    "name": "Tinte",
                    "category": "Peluquería",
                    "duration_minutes": 90,
                    "description": "Coloración completa con producto premium",
                }
            ]
        }
        extract_service_fields(result, ctx)
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["name"] == "Tinte"

    def test_services_locked_appends_detail(self):
        ctx = BookingContext(
            services_locked=True,
            selected_services=["Cortar"],
            service_id="uuid-1",
        )
        result = {
            "resolved_service": {
                "id": "uuid-2",
                "name": "Tinte",
                "duration_minutes": 90,
                "description": "Coloración premium",
            }
        }
        extract_service_fields(result, ctx)
        assert "Tinte" in ctx.selected_services
        assert len(ctx.selected_services_details) == 1
        assert ctx.selected_services_details[0]["name"] == "Tinte"

    def test_multi_service_accumulates_details(self):
        ctx = BookingContext()
        result1 = {
            "resolved_service": {
                "id": "uuid-1",
                "name": "Cortar",
                "category": "Peluquería",
                "duration_minutes": 40,
                "description": "Corte con lavado",
            }
        }
        result2 = {
            "resolved_service": {
                "id": "uuid-2",
                "name": "Tinte",
                "category": "Peluquería",
                "duration_minutes": 90,
                "description": "Coloración completa",
            }
        }
        extract_service_fields(result1, ctx)
        extract_service_fields(result2, ctx)
        assert len(ctx.selected_services_details) == 2
        names = [d["name"] for d in ctx.selected_services_details]
        assert "Cortar" in names
        assert "Tinte" in names


# ============================================================================
# T-12: Serialization round-trip
# ============================================================================


class TestSerializationRoundTrip:
    """T-12: to_mode_context / from_mode_context preserves selected_services_details."""

    def test_round_trip_preserves_details(self):
        original = BookingContext(
            service_name="Cortar",
            selected_services=["Cortar"],
            selected_services_details=[
                {"name": "Cortar", "duration": 40, "description": "Corte con lavado"}
            ],
        )
        serialized = original.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)
        assert restored.selected_services_details == original.selected_services_details

    def test_round_trip_empty_details_not_serialized(self):
        original = BookingContext(service_name="Cortar")
        serialized = original.to_mode_context()
        # Empty lists are filtered out by to_mode_context
        assert "selected_services_details" not in serialized
        restored = BookingContext.from_mode_context(serialized)
        assert restored.selected_services_details == []

    def test_round_trip_multiple_details(self):
        details = [
            {"name": "Cortar", "duration": 40, "description": "Corte con lavado"},
            {"name": "Tinte", "duration": 90, "description": "Coloración completa"},
        ]
        original = BookingContext(
            selected_services=["Cortar", "Tinte"],
            selected_services_details=details,
        )
        serialized = original.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)
        assert len(restored.selected_services_details) == 2
        assert restored.selected_services_details == details
