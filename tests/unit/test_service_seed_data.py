"""
Unit tests for database/seeds/services.py seed data integrity.

Validates that service catalog metadata is correctly populated,
preventing regressions where combo_recommendations or other
critical fields are accidentally cleared.
"""

from __future__ import annotations

import pytest

from database.seeds.services import ALL_SERVICES, HAIRDRESSING_SERVICES


def _find_service(name: str) -> dict | None:
    """Find a service dict by exact name from ALL_SERVICES."""
    return next((s for s in ALL_SERVICES if s["name"] == name), None)


def _all_service_names() -> set[str]:
    """Return the set of all service names in the catalog."""
    return {s["name"] for s in ALL_SERVICES}


class TestCortarComboRecommendations:
    """BUG #4 regression guard: Cortar must have non-empty combo_recommendations."""

    def test_cortar_exists_in_seed(self) -> None:
        service = _find_service("Cortar")
        assert service is not None, "Cortar service must exist in seed data"

    def test_cortar_has_nonempty_combo_recommendations(self) -> None:
        service = _find_service("Cortar")
        assert service is not None
        metadata = service.get("metadata_", {})
        recommendations = metadata.get("combo_recommendations", [])
        assert len(recommendations) > 0, (
            "Cortar must have non-empty combo_recommendations to trigger add-ons substep"
        )

    def test_cortar_combo_recommendations_are_valid_services(self) -> None:
        """Each recommendation must reference an existing service name in the catalog."""
        service = _find_service("Cortar")
        assert service is not None
        metadata = service.get("metadata_", {})
        recommendations = metadata.get("combo_recommendations", [])
        catalog_names = _all_service_names()

        for rec in recommendations:
            assert rec in catalog_names, (
                f"Combo recommendation '{rec}' does not match any service in the catalog"
            )

    def test_cortar_combo_recommendations_expected_values(self) -> None:
        """Verify the specific add-ons match the spec."""
        service = _find_service("Cortar")
        assert service is not None
        metadata = service.get("metadata_", {})
        recommendations = metadata.get("combo_recommendations", [])
        assert recommendations == ["Peinado", "Barro", "Óleo Pigmento"]


class TestComboRecommendationsIntegrity:
    """Ensure all combo_recommendations across the catalog reference valid services."""

    def test_all_combo_recommendations_reference_existing_services(self) -> None:
        catalog_names = _all_service_names()

        for service in ALL_SERVICES:
            metadata = service.get("metadata_", {})
            recommendations = metadata.get("combo_recommendations", [])
            for rec in recommendations:
                assert rec in catalog_names, (
                    f"Service '{service['name']}' has combo_recommendation '{rec}' "
                    f"that does not exist in the catalog"
                )

    def test_corte_bebe_has_combo_recommendations(self) -> None:
        """Corte Bebé is the reference model — it must keep its add-ons."""
        service = _find_service("Corte Bebé")
        assert service is not None
        metadata = service.get("metadata_", {})
        recommendations = metadata.get("combo_recommendations", [])
        assert len(recommendations) > 0, (
            "Corte Bebé combo_recommendations must not be empty"
        )
