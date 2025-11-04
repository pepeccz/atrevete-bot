"""
Consolidated Customer Management Tool for v3.0 Architecture.

This module consolidates customer CRUD operations into a single manage_customer() tool:
- get_customer_by_phone() → manage_customer(action="get", ...)
- create_customer() → manage_customer(action="create", ...)
- update_customer_name() → manage_customer(action="update", ...)
- update_customer_preferences() → (kept separate for clarity)
- get_customer_history() → (kept separate, different use case)

The manage_customer() tool uses an action parameter to route to the appropriate operation.
"""

import logging
from typing import Any, Literal
from uuid import UUID

import phonenumbers
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.connection import get_async_session
from database.models import Appointment, Customer

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================


def normalize_phone(phone: str) -> str | None:
    """
    Normalize phone number to E.164 format.

    Args:
        phone: Phone number in any format

    Returns:
        E.164 formatted phone number (e.g., "+34612345678") or None if invalid

    Examples:
        "612345678" -> "+34612345678"
        "+34 612 34 56 78" -> "+34612345678"
        "invalid" -> None
    """
    try:
        # Default to Spain (ES) region for numbers without country code
        parsed = phonenumbers.parse(phone, "ES")

        if not phonenumbers.is_valid_number(parsed):
            logger.warning(f"Invalid phone number: {phone}")
            return None

        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as e:
        logger.error(f"Failed to parse phone number '{phone}': {e}")
        return None


# ============================================================================
# Pydantic Schemas
# ============================================================================


class ManageCustomerSchema(BaseModel):
    """Schema for manage_customer tool parameters."""

    action: Literal["get", "create", "update"] = Field(
        description=(
            "Customer management action:\n"
            "- 'get': Retrieve existing customer by phone\n"
            "- 'create': Create new customer with phone and name\n"
            "- 'update': Update existing customer's name"
        )
    )

    phone: str = Field(
        description="Customer phone number (required for get/create, optional for update)"
    )

    data: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Additional data for the action:\n"
            "For 'create': {'first_name': str, 'last_name': str (optional)}\n"
            "For 'update': {'customer_id': str, 'first_name': str, 'last_name': str}"
        )
    )


class GetCustomerHistorySchema(BaseModel):
    """Schema for getting customer appointment history."""

    customer_id: str = Field(description="Customer UUID as string")
    limit: int = Field(default=5, description="Maximum number of appointments to return")


# ============================================================================
# Customer Tools
# ============================================================================


@tool(args_schema=ManageCustomerSchema)
async def manage_customer(
    action: Literal["get", "create", "update"],
    phone: str,
    data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Manage customer operations (get, create, update).

    This consolidated tool handles all customer CRUD operations through a single interface.
    Use the 'action' parameter to specify what operation you need.

    Args:
        action: Customer management action:
            - "get": Retrieve existing customer by phone number
            - "create": Create new customer with phone and name
            - "update": Update existing customer's name
        phone: Customer phone number (any format, will be normalized to E.164)
        data: Additional data dict for create/update:
            - For create: {"first_name": str, "last_name": str (optional)}
            - For update: {"customer_id": str, "first_name": str, "last_name": str}

    Returns:
        Dict with customer data or error. Structure varies by action:

        get (success):
            {
                "id": str,
                "phone": str,
                "first_name": str,
                "last_name": str,
                "total_spent": float,
                "last_service_date": str | None,
                "preferred_stylist_id": str | None,
                "created_at": str
            }

        get (not found):
            None

        create (success):
            {
                "id": str,
                "phone": str,
                "first_name": str,
                "last_name": str,
                "total_spent": float,
                "created_at": str
            }

        create (duplicate):
            {"error": "Customer with this phone number already exists", "phone": str}

        update (success):
            {
                "success": True,
                "customer_id": str,
                "first_name": str,
                "last_name": str
            }

        update (not found):
            {"error": "Customer not found", "customer_id": str}

    Examples:
        Get existing customer:
        >>> await manage_customer("get", "+34612345678")
        {"id": "uuid", "phone": "+34612345678", "first_name": "Pedro", ...}

        Get non-existent customer:
        >>> await manage_customer("get", "+34999999999")
        None

        Create new customer:
        >>> await manage_customer("create", "612345678", {"first_name": "Pedro", "last_name": "Gómez"})
        {"id": "uuid", "phone": "+34612345678", "first_name": "Pedro", ...}

        Update customer name:
        >>> await manage_customer("update", "+34612345678", {"customer_id": "uuid", "first_name": "Pedro", "last_name": "García"})
        {"success": True, "customer_id": "uuid", "first_name": "Pedro", "last_name": "García"}
    """
    try:
        if action == "get":
            return await _get_customer(phone)
        elif action == "create":
            return await _create_customer(phone, data or {})
        elif action == "update":
            return await _update_customer(phone, data or {})
        else:
            logger.error(f"Invalid action: {action}")
            return {"error": f"Invalid action: {action}"}

    except Exception as e:
        logger.error(f"Error in manage_customer(action={action}): {e}", exc_info=True)
        return {"error": f"Error in {action} operation", "details": str(e)}


async def _get_customer(phone: str) -> dict[str, Any] | None:
    """
    Get customer by phone number.

    Internal function called by manage_customer(action="get").
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        logger.error(f"Invalid phone number format: {phone}")
        return {"error": "Invalid phone number format", "phone": phone}

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Customer).where(Customer.phone == normalized_phone)
            )
            customer = result.scalar_one_or_none()

            if customer is None:
                logger.info(f"Customer not found for phone: {normalized_phone}")
                return None

            logger.info(f"Customer found: {customer.id} for phone {normalized_phone}")

            return {
                "id": str(customer.id),
                "phone": customer.phone,
                "first_name": customer.first_name,
                "last_name": customer.last_name or "",
                "total_spent": float(customer.total_spent),
                "last_service_date": customer.last_service_date.isoformat() if customer.last_service_date else None,
                "preferred_stylist_id": str(customer.preferred_stylist_id) if customer.preferred_stylist_id else None,
                "created_at": customer.created_at.isoformat(),
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error in _get_customer: {e}", extra={"phone": normalized_phone})
        return {"error": "Failed to retrieve customer from database", "details": str(e)}


async def _create_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:
    """
    Create a new customer record.

    Internal function called by manage_customer(action="create").
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        logger.error(f"Invalid phone number format: {phone}")
        return {"error": "Invalid phone number format", "phone": phone}

    first_name = data.get("first_name")
    if not first_name:
        logger.error("first_name is required for customer creation")
        return {"error": "first_name is required", "data": data}

    last_name = data.get("last_name", "")

    try:
        async for session in get_async_session():
            new_customer = Customer(
                phone=normalized_phone,
                first_name=first_name,
                last_name=last_name if last_name else None,
                metadata_={},
            )
            session.add(new_customer)
            await session.commit()
            await session.refresh(new_customer)

            logger.info(
                f"Customer created: {new_customer.id}",
                extra={"customer_id": str(new_customer.id), "phone": normalized_phone}
            )

            return {
                "id": str(new_customer.id),
                "phone": new_customer.phone,
                "first_name": new_customer.first_name,
                "last_name": new_customer.last_name or "",
                "total_spent": float(new_customer.total_spent),
                "created_at": new_customer.created_at.isoformat(),
            }

    except IntegrityError as e:
        logger.warning(
            f"Duplicate phone number: {normalized_phone}",
            extra={"phone": normalized_phone, "error": str(e)}
        )
        return {"error": "Customer with this phone number already exists", "phone": normalized_phone}

    except SQLAlchemyError as e:
        logger.error(f"Database error in _create_customer: {e}", extra={"phone": normalized_phone})
        return {"error": "Failed to create customer in database", "details": str(e)}


async def _update_customer(phone: str, data: dict[str, Any]) -> dict[str, Any]:
    """
    Update customer's name.

    Internal function called by manage_customer(action="update").
    """
    customer_id_str = data.get("customer_id")
    first_name = data.get("first_name")
    last_name = data.get("last_name")

    if not customer_id_str:
        logger.error("customer_id is required for update")
        return {"error": "customer_id is required", "data": data}

    if not first_name:
        logger.error("first_name is required for update")
        return {"error": "first_name is required", "data": data}

    try:
        customer_uuid = UUID(customer_id_str)
    except ValueError:
        logger.error(f"Invalid customer_id format: {customer_id_str}")
        return {"error": "Invalid customer_id format", "customer_id": customer_id_str}

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Customer).where(Customer.id == customer_uuid)
            )
            customer = result.scalar_one_or_none()

            if customer is None:
                logger.warning(f"Customer not found: {customer_id_str}")
                return {"error": "Customer not found", "customer_id": customer_id_str}

            customer.first_name = first_name
            customer.last_name = last_name if last_name else None

            await session.commit()
            await session.refresh(customer)

            logger.info(
                f"Customer name updated: {customer_id_str}",
                extra={"customer_id": customer_id_str, "first_name": first_name, "last_name": last_name}
            )

            return {
                "success": True,
                "customer_id": str(customer.id),
                "first_name": customer.first_name,
                "last_name": customer.last_name or "",
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error in _update_customer: {e}", extra={"customer_id": customer_id_str})
        return {"error": "Failed to update customer name", "details": str(e)}


@tool(args_schema=GetCustomerHistorySchema)
async def get_customer_history(customer_id: str, limit: int = 5) -> dict[str, Any]:
    """
    Get customer's appointment history.

    Retrieves the most recent appointments for a customer, ordered by start time (most recent first).
    Includes related appointment information.

    This tool is kept separate from manage_customer() because it serves a different use case
    (querying appointments rather than managing customer data).

    Args:
        customer_id: Customer UUID as string
        limit: Maximum number of appointments to return (default: 5)

    Returns:
        Dict with:
            {
                "customer_id": str,
                "appointments": [
                    {
                        "id": str,
                        "start_time": str,
                        "duration_minutes": int,
                        "total_price": float,
                        "status": str,
                        "payment_status": str,
                        "stylist_id": str,
                        "service_ids": list[str]
                    }
                ]
            }

        Or error dict if customer not found

    Example:
        >>> await get_customer_history("customer-uuid", limit=3)
        {
            "customer_id": "customer-uuid",
            "appointments": [
                {"id": "apt-1", "start_time": "2025-11-03T10:00:00+01:00", ...},
                {"id": "apt-2", "start_time": "2025-10-15T14:00:00+02:00", ...}
            ]
        }
    """
    try:
        customer_uuid = UUID(customer_id)
    except ValueError:
        logger.error(f"Invalid customer_id format: {customer_id}")
        return {"error": "Invalid customer_id format", "customer_id": customer_id}

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Appointment)
                .where(Appointment.customer_id == customer_uuid)
                .order_by(desc(Appointment.start_time))
                .limit(limit)
            )
            appointments = result.scalars().all()

            logger.info(
                f"Retrieved {len(appointments)} appointments for customer {customer_id}",
                extra={"customer_id": customer_id, "limit": limit}
            )

            return {
                "customer_id": customer_id,
                "appointments": [
                    {
                        "id": str(apt.id),
                        "start_time": apt.start_time.isoformat(),
                        "duration_minutes": apt.duration_minutes,
                        "total_price": float(apt.total_price),
                        "status": apt.status.value,
                        "payment_status": apt.payment_status.value,
                        "stylist_id": str(apt.stylist_id),
                        "service_ids": [str(sid) for sid in apt.service_ids],
                    }
                    for apt in appointments
                ],
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error in get_customer_history: {e}", extra={"customer_id": customer_id})
        return {"error": "Failed to retrieve customer history", "details": str(e)}
