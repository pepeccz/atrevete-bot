"""
Integration tests for Token Usage API endpoints.

Tests the 3 endpoints in api/routes/token_usage.py:
- GET /api/token-usage          — usage history list
- GET /api/token-usage/current  — current month with computed costs
- GET /api/token-usage/pricing  — configured pricing

Uses FastAPI TestClient with mocked auth and database sessions,
following the same pattern as test_stylist_calendar_conflict_integration.py.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.admin import get_current_user
from database.models import TokenUsage


# ============================================================================
# Test Fixtures and Setup
# ============================================================================


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Disable Redis-based rate limiting for all tests in this module."""
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)  # Always 1st request
    mock_redis.expire = AsyncMock()
    with patch("api.middleware.rate_limiting.get_redis_client", return_value=mock_redis):
        yield


@pytest.fixture
def client():
    """Provide a TestClient for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    """Provide authentication headers for admin endpoints."""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_auth():
    """Override get_current_user dependency to bypass authentication."""
    fake_user = {"sub": "admin", "jti": str(uuid4()), "exp": 9999999999, "type": "admin"}
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield fake_user
    app.dependency_overrides.pop(get_current_user, None)


def _make_token_usage(
    year: int = 2026,
    month: int = 3,
    input_tokens: int = 500_000,
    output_tokens: int = 200_000,
    total_requests: int = 150,
) -> MagicMock:
    """Create a mock TokenUsage ORM object."""
    usage = MagicMock(spec=TokenUsage)
    usage.id = uuid4()
    usage.year = year
    usage.month = month
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.total_requests = total_requests
    usage.created_at = datetime(year, month, 1, tzinfo=timezone.utc)
    usage.updated_at = datetime(year, month, 15, tzinfo=timezone.utc)
    return usage


_SENTINEL = object()


def _mock_session_with_result(scalars_result=None, scalar_one_or_none_result=_SENTINEL):
    """Build a mock async session context manager that returns the given query result."""
    mock_session = AsyncMock()
    mock_result = MagicMock()

    if scalars_result is not None:
        mock_result.scalars.return_value.all.return_value = scalars_result
    if scalar_one_or_none_result is not _SENTINEL:
        mock_result.scalar_one_or_none.return_value = scalar_one_or_none_result

    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


# ============================================================================
# GET /api/token-usage — Usage History
# ============================================================================


class TestGetTokenUsage:
    """Tests for GET /api/token-usage endpoint."""

    def test_returns_list_of_months(self, client, mock_auth):
        """GIVEN usage data exists, WHEN requesting history, THEN returns items list."""
        usage_jan = _make_token_usage(year=2026, month=1, input_tokens=100_000, output_tokens=50_000)
        usage_feb = _make_token_usage(year=2026, month=2, input_tokens=200_000, output_tokens=80_000)

        mock_session = _mock_session_with_result(scalars_result=[usage_feb, usage_jan])

        with patch("api.routes.token_usage.get_async_session") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/api/token-usage", headers={"Authorization": "Bearer t"})

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 2
        assert len(data["items"]) == 2
        # Most recent first
        assert data["items"][0]["month"] == 2
        assert data["items"][1]["month"] == 1

    def test_returns_empty_list_when_no_data(self, client, mock_auth):
        """GIVEN no usage data, WHEN requesting history, THEN returns empty list."""
        mock_session = _mock_session_with_result(scalars_result=[])

        with patch("api.routes.token_usage.get_async_session") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/api/token-usage", headers={"Authorization": "Bearer t"})

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_items_include_computed_fields(self, client, mock_auth):
        """GIVEN usage data, WHEN requesting history, THEN items include computed costs."""
        usage = _make_token_usage(input_tokens=1_000_000, output_tokens=1_000_000)
        mock_session = _mock_session_with_result(scalars_result=[usage])

        with patch("api.routes.token_usage.get_async_session") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/api/token-usage", headers={"Authorization": "Bearer t"})

        assert response.status_code == 200
        item = response.json()["items"][0]
        # Computed fields must be present
        assert "total_tokens" in item
        assert "cost_input_eur" in item
        assert "cost_output_eur" in item
        assert "cost_total_eur" in item
        assert item["total_tokens"] == 2_000_000


# ============================================================================
# GET /api/token-usage/current — Current Month
# ============================================================================


class TestGetCurrentMonthUsage:
    """Tests for GET /api/token-usage/current endpoint."""

    def test_returns_current_month_with_costs(self, client, mock_auth):
        """GIVEN current month data exists, WHEN requesting current, THEN returns with costs."""
        usage = _make_token_usage(
            year=2026,
            month=3,
            input_tokens=1_000_000,
            output_tokens=500_000,
            total_requests=200,
        )
        mock_session = _mock_session_with_result(scalar_one_or_none_result=usage)

        with (
            patch("api.routes.token_usage.get_async_session") as mock_factory,
            patch("api.routes.token_usage.get_settings") as mock_settings,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            settings = MagicMock()
            settings.TOKEN_PRICE_INPUT = Decimal("0.15")
            settings.TOKEN_PRICE_OUTPUT = Decimal("0.60")
            mock_settings.return_value = settings

            response = client.get(
                "/api/token-usage/current", headers={"Authorization": "Bearer t"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 3
        assert data["input_tokens"] == 1_000_000
        assert data["output_tokens"] == 500_000
        assert data["total_tokens"] == 1_500_000
        assert data["total_requests"] == 200
        # Cost calculations: 1M input * 0.15/M = 0.15, 0.5M output * 0.60/M = 0.30
        assert Decimal(data["cost_input_eur"]) == Decimal("0.15")
        assert Decimal(data["cost_output_eur"]) == Decimal("0.30")
        assert Decimal(data["cost_total_eur"]) == Decimal("0.45")

    def test_returns_zeros_when_no_data(self, client, mock_auth):
        """GIVEN no data for current month, WHEN requesting current, THEN returns zeros (NOT 404)."""
        mock_session = _mock_session_with_result(scalar_one_or_none_result=None)

        with (
            patch("api.routes.token_usage.get_async_session") as mock_factory,
            patch("api.routes.token_usage.get_settings") as mock_settings,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            settings = MagicMock()
            settings.TOKEN_PRICE_INPUT = Decimal("0.15")
            settings.TOKEN_PRICE_OUTPUT = Decimal("0.60")
            mock_settings.return_value = settings

            response = client.get(
                "/api/token-usage/current", headers={"Authorization": "Bearer t"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["input_tokens"] == 0
        assert data["output_tokens"] == 0
        assert data["total_tokens"] == 0
        assert data["total_requests"] == 0
        assert Decimal(data["cost_input_eur"]) == Decimal("0.00")
        assert Decimal(data["cost_output_eur"]) == Decimal("0.00")
        assert Decimal(data["cost_total_eur"]) == Decimal("0.00")


# ============================================================================
# GET /api/token-usage/pricing — Configured Pricing
# ============================================================================


class TestGetPricing:
    """Tests for GET /api/token-usage/pricing endpoint."""

    def test_returns_configured_pricing(self, client, mock_auth):
        """GIVEN pricing configured in settings, WHEN requesting pricing, THEN returns values."""
        with patch("api.routes.token_usage.get_settings") as mock_settings:
            settings = MagicMock()
            settings.TOKEN_PRICE_INPUT = Decimal("0.15")
            settings.TOKEN_PRICE_OUTPUT = Decimal("0.60")
            mock_settings.return_value = settings

            response = client.get(
                "/api/token-usage/pricing", headers={"Authorization": "Bearer t"}
            )

        assert response.status_code == 200
        data = response.json()
        assert Decimal(data["input_price_per_million"]) == Decimal("0.15")
        assert Decimal(data["output_price_per_million"]) == Decimal("0.60")

    def test_returns_custom_pricing(self, client, mock_auth):
        """GIVEN custom pricing values, WHEN requesting pricing, THEN returns those values."""
        with patch("api.routes.token_usage.get_settings") as mock_settings:
            settings = MagicMock()
            settings.TOKEN_PRICE_INPUT = Decimal("0.25")
            settings.TOKEN_PRICE_OUTPUT = Decimal("1.00")
            mock_settings.return_value = settings

            response = client.get(
                "/api/token-usage/pricing", headers={"Authorization": "Bearer t"}
            )

        assert response.status_code == 200
        data = response.json()
        assert Decimal(data["input_price_per_million"]) == Decimal("0.25")
        assert Decimal(data["output_price_per_million"]) == Decimal("1.00")


# ============================================================================
# Authentication — All 3 endpoints require admin auth
# ============================================================================


class TestTokenUsageAuth:
    """Tests that all token usage endpoints reject unauthenticated requests."""

    def test_get_usage_requires_auth(self, client):
        """GIVEN no auth, WHEN requesting usage history, THEN returns 401/403."""
        response = client.get("/api/token-usage")
        assert response.status_code in (401, 403)

    def test_get_current_requires_auth(self, client):
        """GIVEN no auth, WHEN requesting current month, THEN returns 401/403."""
        response = client.get("/api/token-usage/current")
        assert response.status_code in (401, 403)

    def test_get_pricing_requires_auth(self, client):
        """GIVEN no auth, WHEN requesting pricing, THEN returns 401/403."""
        response = client.get("/api/token-usage/pricing")
        assert response.status_code in (401, 403)
