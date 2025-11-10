"""
Unit tests for customer tools with mocked database.

Tests cover:
- get_customer_by_phone: phone normalization, customer found/not found, database errors
- create_customer: successful creation, duplicate phone, invalid phone, database errors
- update_customer_name: successful update, invalid customer_id, database errors
- update_customer_preferences: successful update, invalid stylist_id FK, database errors
- get_customer_history: ordering, limit parameter, database errors
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from agent.tools.customer_tools import (
    create_customer,
    get_customer_by_phone,
    get_customer_history,
    normalize_phone,
    update_customer_name,
    update_customer_preferences,
)


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestNormalizePhone:
    """Test phone normalization function."""

    def test_spanish_mobile_with_country_code(self):
        """Test Spanish mobile with +34 prefix."""
        assert normalize_phone("+34612345678") == "+34612345678"

    def test_spanish_mobile_without_country_code(self):
        """Test Spanish mobile without prefix (should add +34)."""
        assert normalize_phone("612345678") == "+34612345678"

    def test_spanish_mobile_with_spaces(self):
        """Test Spanish mobile with spaces (should normalize)."""
        assert normalize_phone("+34 612 34 56 78") == "+34612345678"

    def test_international_format(self):
        """Test international phone number (US format)."""
        assert normalize_phone("+12025551234") == "+12025551234"

    def test_invalid_phone(self):
        """Test invalid phone number returns None."""
        assert normalize_phone("invalid") is None
        assert normalize_phone("123") is None
        assert normalize_phone("") is None


# ============================================================================
# Tool Tests with Mocked Database
# ============================================================================


class TestGetCustomerByPhone:
    """Test get_customer_by_phone tool."""

    @pytest.mark.asyncio
    async def test_customer_found(self):
        """Test successful customer retrieval."""
        mock_customer = MagicMock(spec=Customer)
        mock_customer.id = uuid4()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "Juan"
        mock_customer.last_name = "García"
        mock_customer.total_spent = Decimal("150.00")
        mock_customer.last_service_date = datetime(2025, 10, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_customer.preferred_stylist_id = uuid4()
        mock_customer.created_at = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):
            result = await get_customer_by_phone.ainvoke({"phone": "612345678"})

            assert result is not None
            assert result["phone"] == "+34612345678"
            assert result["first_name"] == "Juan"
            assert result["last_name"] == "García"
            assert result["total_spent"] == 150.00

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        """Test customer not found returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await get_customer_by_phone.ainvoke({"phone": "+34612345678"})

            assert result is None

    @pytest.mark.asyncio
    async def test_invalid_phone_format(self):
        """Test invalid phone number returns error."""
        result = await get_customer_by_phone.ainvoke({"phone": "invalid"})

        assert "error" in result
        assert result["error"] == "Invalid phone number format"

    @pytest.mark.asyncio
    async def test_database_error(self):
        """Test database error returns graceful error message."""
        mock_session = AsyncMock()
        mock_session.execute.side_effect = SQLAlchemyError("Database connection failed")

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await get_customer_by_phone.ainvoke({"phone": "+34612345678"})

            assert "error" in result
            assert "Failed to retrieve customer" in result["error"]


class TestCreateCustomer:
    """Test create_customer tool."""

    @pytest.mark.asyncio
    async def test_create_customer_success(self):
        """Test successful customer creation."""
        new_customer_id = uuid4()
        mock_customer = MagicMock(spec=Customer)
        mock_customer.id = new_customer_id
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "María"
        mock_customer.last_name = "López"
        mock_customer.total_spent = Decimal("0.00")
        mock_customer.created_at = datetime.now(timezone.utc)

        mock_session = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", new_customer_id))

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):
            mock_session.refresh.side_effect = lambda obj: None

            # Simulate refresh behavior
            async def mock_refresh(obj):
                obj.id = mock_customer.id
                obj.phone = mock_customer.phone
                obj.first_name = mock_customer.first_name
                obj.last_name = mock_customer.last_name
                obj.total_spent = mock_customer.total_spent
                obj.created_at = mock_customer.created_at

            mock_session.refresh.side_effect = mock_refresh

            result = await create_customer.ainvoke({
                "phone": "612345678",
                "first_name": "María",
                "last_name": "López"
            })

            assert "error" not in result
            assert result["phone"] == "+34612345678"
            assert result["first_name"] == "María"
            assert result["last_name"] == "López"

    @pytest.mark.asyncio
    async def test_create_customer_duplicate_phone(self):
        """Test duplicate phone number returns error."""
        mock_session = AsyncMock()
        mock_session.commit.side_effect = IntegrityError(
            "duplicate key value", None, None
        )

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await create_customer.ainvoke({
                "phone": "+34612345678",
                "first_name": "Test",
                "last_name": "User"
            })

            assert "error" in result
            assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_create_customer_invalid_phone(self):
        """Test invalid phone format returns error."""
        result = await create_customer.ainvoke({
            "phone": "invalid",
            "first_name": "Test",
            "last_name": "User"
        })

        assert "error" in result
        assert "Invalid phone number format" in result["error"]

    @pytest.mark.asyncio
    async def test_create_customer_with_empty_last_name(self):
        """Test creating customer with empty last name."""
        new_customer_id = uuid4()

        mock_session = AsyncMock()

        async def mock_refresh(obj):
            obj.id = new_customer_id
            obj.phone = "+34612345678"
            obj.first_name = "Pedro"
            obj.last_name = None
            obj.total_spent = Decimal("0.00")
            obj.created_at = datetime.now(timezone.utc)

        mock_session.refresh.side_effect = mock_refresh

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await create_customer.ainvoke({
                "phone": "+34612345678",
                "first_name": "Pedro",
                "last_name": ""
            })

            assert "error" not in result
            assert result["first_name"] == "Pedro"
            assert result["last_name"] == ""


class TestUpdateCustomerName:
    """Test update_customer_name tool."""

    @pytest.mark.asyncio
    async def test_update_name_success(self):
        """Test successful name update."""
        customer_id = uuid4()
        mock_customer = MagicMock(spec=Customer)
        mock_customer.id = customer_id
        mock_customer.first_name = "Updated"
        mock_customer.last_name = "Name"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await update_customer_name.ainvoke({
                "customer_id": str(customer_id),
                "first_name": "Updated",
                "last_name": "Name"
            })

            assert result["success"] is True
            assert result["first_name"] == "Updated"
            assert result["last_name"] == "Name"

    @pytest.mark.asyncio
    async def test_update_name_customer_not_found(self):
        """Test updating non-existent customer returns error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await update_customer_name.ainvoke({
                "customer_id": str(uuid4()),
                "first_name": "Test",
                "last_name": "User"
            })

            assert "error" in result
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_name_invalid_uuid(self):
        """Test invalid customer_id format returns error."""
        result = await update_customer_name.ainvoke({
            "customer_id": "invalid-uuid",
            "first_name": "Test",
            "last_name": "User"
        })

        assert "error" in result
        assert "Invalid customer_id format" in result["error"]


class TestUpdateCustomerPreferences:
    """Test update_customer_preferences tool."""

    @pytest.mark.asyncio
    async def test_update_preferences_success(self):
        """Test successful preference update."""
        customer_id = uuid4()
        stylist_id = uuid4()

        mock_customer = MagicMock(spec=Customer)
        mock_customer.id = customer_id
        mock_customer.preferred_stylist_id = stylist_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await update_customer_preferences.ainvoke({
                "customer_id": str(customer_id),
                "preferred_stylist_id": str(stylist_id)
            })

            assert result["success"] is True
            assert result["preferred_stylist_id"] == str(stylist_id)

    @pytest.mark.asyncio
    async def test_update_preferences_invalid_stylist_id(self):
        """Test invalid stylist_id (FK constraint) returns error."""
        customer_id = uuid4()
        stylist_id = uuid4()

        mock_customer = MagicMock(spec=Customer)
        mock_customer.id = customer_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit.side_effect = IntegrityError(
            "foreign key constraint", None, None
        )

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await update_customer_preferences.ainvoke({
                "customer_id": str(customer_id),
                "preferred_stylist_id": str(stylist_id)
            })

            assert "error" in result
            assert "stylist does not exist" in result["error"]

    @pytest.mark.asyncio
    async def test_update_preferences_invalid_uuid(self):
        """Test invalid UUID format returns error."""
        result = await update_customer_preferences.ainvoke({
            "customer_id": "invalid",
            "preferred_stylist_id": str(uuid4())
        })

        assert "error" in result
        assert "Invalid UUID format" in result["error"]


class TestGetCustomerHistory:
    """Test get_customer_history tool."""

    @pytest.mark.asyncio
    async def test_get_history_success(self):
        """Test successful history retrieval with ordering."""
        customer_id = uuid4()
        stylist_id = uuid4()

        # Create mock appointments (most recent first)
        apt1 = MagicMock(spec=Appointment)
        apt1.id = uuid4()
        apt1.start_time = datetime(2025, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        apt1.duration_minutes = 60
        apt1.total_price = Decimal("50.00")
        apt1.status = AppointmentStatus.COMPLETED
        apt1.stylist_id = stylist_id
        apt1.service_ids = [uuid4()]

        apt2 = MagicMock(spec=Appointment)
        apt2.id = uuid4()
        apt2.start_time = datetime(2025, 10, 15, 14, 0, 0, tzinfo=timezone.utc)
        apt2.duration_minutes = 90
        apt2.total_price = Decimal("75.00")
        apt2.status = AppointmentStatus.COMPLETED
        apt2.stylist_id = stylist_id
        apt2.service_ids = [uuid4(), uuid4()]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [apt1, apt2]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await get_customer_history.ainvoke({
                "customer_id": str(customer_id),
                "limit": 5
            })

            assert "error" not in result
            assert len(result["appointments"]) == 2
            # Verify most recent is first
            assert result["appointments"][0]["total_price"] == 50.00
            assert result["appointments"][1]["total_price"] == 75.00

    @pytest.mark.asyncio
    async def test_get_history_with_limit(self):
        """Test limit parameter works correctly."""
        customer_id = uuid4()

        # Create 3 mock appointments
        appointments = []
        for i in range(3):
            apt = MagicMock(spec=Appointment)
            apt.id = uuid4()
            apt.start_time = datetime(2025, 10, i + 1, 10, 0, 0, tzinfo=timezone.utc)
            apt.duration_minutes = 60
            apt.total_price = Decimal("50.00")
            apt.status = AppointmentStatus.COMPLETED
            apt.stylist_id = uuid4()
            apt.service_ids = [uuid4()]
            appointments.append(apt)

        mock_result = MagicMock()
        # Only return first 2 (simulating LIMIT 2)
        mock_result.scalars.return_value.all.return_value = appointments[:2]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await get_customer_history.ainvoke({
                "customer_id": str(customer_id),
                "limit": 2
            })

            assert len(result["appointments"]) == 2

    @pytest.mark.asyncio
    async def test_get_history_invalid_customer_id(self):
        """Test invalid customer_id format returns error."""
        result = await get_customer_history.ainvoke({
            "customer_id": "invalid-uuid",
            "limit": 5
        })

        assert "error" in result
        assert "Invalid customer_id format" in result["error"]

    @pytest.mark.asyncio
    async def test_get_history_empty_results(self):
        """Test customer with no appointments returns empty list."""
        customer_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        async def mock_session_generator():
            yield mock_session

        with patch("agent.tools.customer_tools.get_async_session", return_value=mock_session_generator()):

            result = await get_customer_history.ainvoke({
                "customer_id": str(customer_id),
                "limit": 5
            })

            assert "error" not in result
            assert len(result["appointments"]) == 0
