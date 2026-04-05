"""Unit tests for agent/modes/tool_extractors.py — resolved_axes tracking.

When extract_service_fields processes a resolved_service that came from
a clarification (the result includes axis information), it must store
the axis+value in ctx.resolved_axes so future search_services calls
auto-inject them and the LLM doesn't re-ask.
"""

from __future__ import annotations

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.tool_extractors import extract_service_fields


# ═══════════════════════════════════════════════════════════════════════
# resolved_axes tracking in extract_service_fields
# ═══════════════════════════════════════════════════════════════════════


class TestResolvedAxesTracking:
    """extract_service_fields must update ctx.resolved_axes when a service
    is resolved via a disambiguation axis (clarification_needed → user answers → resolved)."""

    def test_resolved_service_with_ask_if_missing_stores_axes(self):
        """When resolved_service has ask_if_missing axes that are now satisfied,
        the axis values should be stored in resolved_axes."""
        result = {
            "resolved_service": {
                "id": "svc-001",
                "name": "Peinado",
                "duration_minutes": 40,
                "category": "HAIRDRESSING",
                "family": "hairstyle",
                "ask_if_missing": ["hair_length"],
                "combo_recommendations": [],
                "description": "Peinado corto/medio",
            },
            "query": "peinado",
            "count": 1,
            "resolved_axes": {"hair_length": "short_medium"},
        }
        ctx = BookingContext()
        extract_service_fields(result, ctx)

        assert ctx.resolved_axes.get("hair_length") == "short_medium"

    def test_resolved_service_with_audience_axis(self):
        """Audience axis should also be tracked."""
        result = {
            "resolved_service": {
                "id": "svc-002",
                "name": "Corte Señora",
                "duration_minutes": 45,
                "category": "HAIRDRESSING",
                "family": "haircut",
                "ask_if_missing": ["audience"],
                "combo_recommendations": [],
            },
            "query": "corte",
            "count": 1,
            "resolved_axes": {"audience": "adult_female"},
        }
        ctx = BookingContext()
        extract_service_fields(result, ctx)

        assert ctx.resolved_axes.get("audience") == "adult_female"

    def test_multiple_axes_accumulated(self):
        """Axes from different resolutions accumulate (don't overwrite)."""
        ctx = BookingContext(resolved_axes={"audience": "adult_female"})

        result = {
            "resolved_service": {
                "id": "svc-003",
                "name": "Peinado",
                "duration_minutes": 40,
                "category": "HAIRDRESSING",
                "family": "hairstyle",
                "ask_if_missing": ["hair_length"],
                "combo_recommendations": [],
            },
            "query": "peinado",
            "count": 1,
            "resolved_axes": {"hair_length": "short_medium"},
        }
        extract_service_fields(result, ctx)

        assert ctx.resolved_axes == {"audience": "adult_female", "hair_length": "short_medium"}

    def test_no_resolved_axes_key_no_crash(self):
        """When result has no resolved_axes key, no crash, no mutation."""
        result = {
            "resolved_service": {
                "id": "svc-004",
                "name": "Bioterapia",
                "duration_minutes": 90,
                "category": "AESTHETICS",
                "family": None,
                "ask_if_missing": [],
                "combo_recommendations": [],
            },
            "query": "bioterapia",
            "count": 1,
        }
        ctx = BookingContext()
        extract_service_fields(result, ctx)

        assert ctx.resolved_axes == {}

    def test_resolved_axes_survive_round_trip(self):
        """resolved_axes set by extractor survive context serialization."""
        result = {
            "resolved_service": {
                "id": "svc-005",
                "name": "Mechas",
                "duration_minutes": 60,
                "category": "HAIRDRESSING",
                "family": "highlights",
                "ask_if_missing": ["hair_density"],
                "combo_recommendations": [],
            },
            "query": "mechas",
            "count": 1,
            "resolved_axes": {"hair_density": "normal"},
        }
        ctx = BookingContext()
        extract_service_fields(result, ctx)

        # Round-trip
        restored = BookingContext.from_mode_context(ctx.to_mode_context())
        assert restored.resolved_axes == {"hair_density": "normal"}
