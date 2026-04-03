"""Unit tests for booking-confirmation-message-fix.

Covers:
- format_service_list() — Spanish grammar for service name lists

No DB, no LLM — all external dependencies are mocked.
"""

from __future__ import annotations

from agent.modes.booking_context import format_service_list


# =============================================================================
# format_service_list
# =============================================================================


class TestFormatServiceList:
    def test_format_empty_list(self):
        """Empty list returns empty string."""
        assert format_service_list([]) == ""

    def test_format_single_service(self):
        """Single service returns the service name as-is."""
        assert format_service_list(["Corte Caballero"]) == "Corte Caballero"

    def test_format_two_services(self):
        """Two services joined with 'y' (no comma)."""
        result = format_service_list(["Corte Caballero", "Corte Niño"])
        assert result == "Corte Caballero y Corte Niño"

    def test_format_three_services(self):
        """Three services: comma-separated with 'y' before last."""
        result = format_service_list(["A", "B", "C"])
        assert result == "A, B y C"

    def test_format_four_services(self):
        """Four services: comma-separated with 'y' before last."""
        result = format_service_list(["A", "B", "C", "D"])
        assert result == "A, B, C y D"
