"""
Unit tests for location information retrieval.

Tests that the system correctly returns salon address information
through the query_info tool with type="location".
"""

import pytest

from agent.tools.info_tools import query_info


@pytest.mark.asyncio
class TestLocationInfo:
    """Test location information retrieval through query_info tool."""

    async def test_query_location_returns_address(self):
        """Test query_info with type='location' returns address."""
        # Act
        result = await query_info(type="location")

        # Assert
        assert "address" in result
        assert "formatted" in result
        assert isinstance(result["address"], str)
        assert len(result["address"]) > 0

    async def test_query_location_address_format(self):
        """Test location address contains expected Spanish address components."""
        # Act
        result = await query_info(type="location")

        # Assert: Spanish address should contain typical components
        address = result["address"].lower()
        # Should contain either street type (calle, avenida, plaza, etc.) or postal code
        has_street_type = any(
            word in address
            for word in ["calle", "c/", "avenida", "av.", "plaza", "pl."]
        )
        has_postal_code = any(char.isdigit() for char in address)

        assert has_street_type or has_postal_code, \
            f"Address should contain street type or postal code: {result['address']}"

    async def test_query_location_formatted_equals_address(self):
        """Test that formatted field equals address field."""
        # Act
        result = await query_info(type="location")

        # Assert
        assert result["formatted"] == result["address"]

    async def test_query_location_returns_consistent_result(self):
        """Test that calling query_info location multiple times returns same result."""
        # Act
        result1 = await query_info(type="location")
        result2 = await query_info(type="location")

        # Assert
        assert result1["address"] == result2["address"]
        assert result1["formatted"] == result2["formatted"]

    async def test_query_location_no_error(self):
        """Test that query_info location doesn't return error."""
        # Act
        result = await query_info(type="location")

        # Assert
        assert "error" not in result
        assert result["address"] is not None

    async def test_query_location_ignores_filters(self):
        """Test that filters parameter is ignored for location queries."""
        # Act: Call with filters (should be ignored)
        result_with_filters = await query_info(
            type="location",
            filters={"some_key": "some_value"}
        )
        result_without_filters = await query_info(type="location")

        # Assert: Results should be identical
        assert result_with_filters["address"] == result_without_filters["address"]

    async def test_query_location_ignores_max_results(self):
        """Test that max_results parameter is ignored for location queries."""
        # Act: Call with different max_results
        result_max_5 = await query_info(type="location", max_results=5)
        result_max_50 = await query_info(type="location", max_results=50)

        # Assert: Results should be identical
        assert result_max_5["address"] == result_max_50["address"]

    async def test_query_location_from_config(self):
        """Test that location is retrieved from config.SALON_ADDRESS."""
        from shared.config import get_settings

        # Arrange
        settings = get_settings()
        expected_address = settings.SALON_ADDRESS

        # Act
        result = await query_info(type="location")

        # Assert
        assert result["address"] == expected_address

    async def test_query_location_not_empty(self):
        """Test that location address is not empty string."""
        # Act
        result = await query_info(type="location")

        # Assert
        assert result["address"] != ""
        assert result["formatted"] != ""
        assert len(result["address"]) > 10  # Minimum reasonable address length


@pytest.mark.asyncio
class TestLocationIntegration:
    """Integration tests for location in booking confirmation flow."""

    async def test_location_can_be_used_in_confirmation_message(self):
        """Test that location info can be formatted for user confirmation."""
        # Act
        location_info = await query_info(type="location")

        # Assert: Can construct a confirmation message
        confirmation_msg = (
            f"📍 Te esperamos en Atrévete Peluquería:\n"
            f"{location_info['formatted']}"
        )

        assert "📍" in confirmation_msg
        assert "Atrévete" in confirmation_msg
        assert location_info["address"] in confirmation_msg

    async def test_all_query_info_types_work(self):
        """Test that all query_info types (services, faqs, hours, location) work."""
        # Act: Call each type
        services_result = await query_info(type="services", max_results=5)
        faqs_result = await query_info(type="faqs", max_results=5)
        hours_result = await query_info(type="hours")
        location_result = await query_info(type="location")

        # Assert: All return valid results without errors
        assert "services" in services_result or "error" not in services_result
        assert "faqs" in faqs_result or "error" not in faqs_result
        assert "schedule" in hours_result or "formatted" in hours_result
        assert "address" in location_result
