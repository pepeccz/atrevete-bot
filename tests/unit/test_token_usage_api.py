"""Unit tests for token usage API endpoints."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from api.models.token_usage import (
    CurrentMonthUsageResponse,
    TokenPricingResponse,
    TokenUsageResponse,
)


def _make_token_usage(
    year: int = 2026,
    month: int = 3,
    input_tokens: int = 10000,
    output_tokens: int = 5000,
    total_requests: int = 42,
):
    """Create a mock TokenUsage ORM object."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.year = year
    mock.month = month
    mock.input_tokens = input_tokens
    mock.output_tokens = output_tokens
    mock.total_requests = total_requests
    mock.created_at = datetime(2026, 3, 1, tzinfo=UTC)
    mock.updated_at = datetime(2026, 3, 15, tzinfo=UTC)
    return mock


class TestTokenUsageResponse:
    """Tests for the Pydantic schema computed fields."""

    def test_total_tokens_computed(self):
        """total_tokens should be input + output."""
        resp = TokenUsageResponse(
            id=uuid.uuid4(),
            year=2026,
            month=3,
            input_tokens=10000,
            output_tokens=5000,
            total_requests=42,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
            updated_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
        assert resp.total_tokens == 15000

    def test_cost_computation(self):
        """Costs should be computed from configured prices."""
        with patch(
            "api.models.token_usage._get_cached_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.TOKEN_PRICE_INPUT = Decimal("0.15")
            settings.TOKEN_PRICE_OUTPUT = Decimal("0.60")
            mock_settings.return_value = settings

            # Clear the lru_cache so our mock is used
            from api.models.token_usage import _get_cached_settings
            _get_cached_settings.cache_clear()

            resp = TokenUsageResponse(
                id=uuid.uuid4(),
                year=2026,
                month=3,
                input_tokens=1_000_000,  # 1M input tokens
                output_tokens=500_000,  # 500K output tokens
                total_requests=100,
                created_at=datetime(2026, 3, 1, tzinfo=UTC),
                updated_at=datetime(2026, 3, 15, tzinfo=UTC),
            )

            # 1M tokens * 0.15 EUR/M = 0.15 EUR
            assert resp.cost_input_eur == Decimal("0.15")
            # 500K tokens * 0.60 EUR/M = 0.30 EUR
            assert resp.cost_output_eur == Decimal("0.30")
            # Total = 0.45 EUR
            assert resp.cost_total_eur == Decimal("0.45")

            # Clean up
            _get_cached_settings.cache_clear()

    def test_from_attributes(self):
        """Should work with from_attributes for ORM objects."""
        mock_orm = _make_token_usage()
        resp = TokenUsageResponse.model_validate(mock_orm)
        assert resp.year == 2026
        assert resp.month == 3
        assert resp.input_tokens == 10000


class TestCurrentMonthUsageResponse:
    """Tests for the current month response schema."""

    def test_zero_values(self):
        """Should handle all-zero values."""
        resp = CurrentMonthUsageResponse(
            year=2026,
            month=3,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            total_requests=0,
            cost_input_eur=Decimal("0.00"),
            cost_output_eur=Decimal("0.00"),
            cost_total_eur=Decimal("0.00"),
        )
        assert resp.total_tokens == 0
        assert resp.cost_total_eur == Decimal("0.00")


class TestTokenPricingResponse:
    """Tests for the pricing response schema."""

    def test_pricing_fields(self):
        """Should serialize pricing correctly."""
        resp = TokenPricingResponse(
            input_price_per_million=Decimal("0.15"),
            output_price_per_million=Decimal("0.60"),
        )
        assert resp.input_price_per_million == Decimal("0.15")
        assert resp.output_price_per_million == Decimal("0.60")
