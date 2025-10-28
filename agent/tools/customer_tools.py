"""
Customer tools for database operations on customer lifecycle management.

This module provides LangChain tools for:
- Querying customers by phone number
- Creating new customer records
- Updating customer names
- Managing customer preferences
- Retrieving customer appointment history

All tools use async SQLAlchemy sessions and follow E.164 phone normalization.
"""

import logging
from typing import Any
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
# Pydantic Schemas for Tool Parameters
# ============================================================================


class CustomerPhoneSchema(BaseModel):
    """Schema for phone number parameter."""

    phone: str = Field(description="Customer phone number in any format (will be normalized to E.164)")


class CreateCustomerSchema(BaseModel):
    """Schema for creating a new customer."""

    phone: str = Field(description="Customer phone number in any format")
    first_name: str = Field(description="Customer's first name")
    last_name: str = Field(default="", description="Customer's last name (optional)")


class UpdateCustomerNameSchema(BaseModel):
    """Schema for updating customer name."""

    customer_id: str = Field(description="Customer UUID as string")
    first_name: str = Field(description="New first name")
    last_name: str = Field(description="New last name")


class UpdateCustomerPreferencesSchema(BaseModel):
    """Schema for updating customer preferences."""

    customer_id: str = Field(description="Customer UUID as string")
    preferred_stylist_id: str = Field(description="Preferred stylist UUID as string")


class GetCustomerHistorySchema(BaseModel):
    """Schema for getting customer appointment history."""

    customer_id: str = Field(description="Customer UUID as string")
    limit: int = Field(default=5, description="Maximum number of appointments to return")


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
# Customer Tools
# ============================================================================


@tool(args_schema=CustomerPhoneSchema)
async def get_customer_by_phone(phone: str) -> dict[str, Any] | None:
    """
    Get customer by phone number.

    Queries the database for a customer with the given phone number.
    Phone number is automatically normalized to E.164 format.

    Args:
        phone: Customer phone number in any format

    Returns:
        Customer data dict with id, phone, first_name, last_name, etc., or None if not found
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
        logger.error(f"Database error in get_customer_by_phone: {e}", extra={"phone": normalized_phone})
        return {"error": "Failed to retrieve customer from database", "details": str(e)}


@tool(args_schema=CreateCustomerSchema)
async def create_customer(phone: str, first_name: str, last_name: str = "") -> dict[str, Any]:
    """
    Create a new customer record.

    Creates a new customer with the provided phone number and name.
    Phone number is automatically normalized to E.164 format.

    Args:
        phone: Customer phone number in any format
        first_name: Customer's first name
        last_name: Customer's last name (optional, defaults to empty string)

    Returns:
        Created customer data dict with id, phone, first_name, last_name, etc.
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        logger.error(f"Invalid phone number format: {phone}")
        return {"error": "Invalid phone number format", "phone": phone}

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
        logger.error(f"Database error in create_customer: {e}", extra={"phone": normalized_phone})
        return {"error": "Failed to create customer in database", "details": str(e)}


@tool(args_schema=UpdateCustomerNameSchema)
async def update_customer_name(customer_id: str, first_name: str, last_name: str) -> dict[str, Any]:
    """
    Update customer's name.

    Updates the first name and last name for an existing customer.

    Args:
        customer_id: Customer UUID as string
        first_name: New first name
        last_name: New last name

    Returns:
        Success dict with updated customer data, or error dict if customer not found
    """
    try:
        customer_uuid = UUID(customer_id)
    except ValueError:
        logger.error(f"Invalid customer_id format: {customer_id}")
        return {"error": "Invalid customer_id format", "customer_id": customer_id}

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Customer).where(Customer.id == customer_uuid)
            )
            customer = result.scalar_one_or_none()

            if customer is None:
                logger.warning(f"Customer not found: {customer_id}")
                return {"error": "Customer not found", "customer_id": customer_id}

            customer.first_name = first_name
            customer.last_name = last_name if last_name else None

            await session.commit()
            await session.refresh(customer)

            logger.info(
                f"Customer name updated: {customer_id}",
                extra={"customer_id": customer_id, "first_name": first_name, "last_name": last_name}
            )

            return {
                "success": True,
                "customer_id": str(customer.id),
                "first_name": customer.first_name,
                "last_name": customer.last_name or "",
            }

    except SQLAlchemyError as e:
        logger.error(f"Database error in update_customer_name: {e}", extra={"customer_id": customer_id})
        return {"error": "Failed to update customer name", "details": str(e)}


@tool(args_schema=UpdateCustomerPreferencesSchema)
async def update_customer_preferences(customer_id: str, preferred_stylist_id: str) -> dict[str, Any]:
    """
    Update customer's preferred stylist.

    Sets or updates the customer's preferred stylist preference.

    Args:
        customer_id: Customer UUID as string
        preferred_stylist_id: Preferred stylist UUID as string

    Returns:
        Success dict with updated preference, or error dict if customer/stylist not found
    """
    try:
        customer_uuid = UUID(customer_id)
        stylist_uuid = UUID(preferred_stylist_id)
    except ValueError as e:
        logger.error(f"Invalid UUID format: {e}")
        return {"error": "Invalid UUID format", "details": str(e)}

    try:
        async for session in get_async_session():
            result = await session.execute(
                select(Customer).where(Customer.id == customer_uuid)
            )
            customer = result.scalar_one_or_none()

            if customer is None:
                logger.warning(f"Customer not found: {customer_id}")
                return {"error": "Customer not found", "customer_id": customer_id}

            customer.preferred_stylist_id = stylist_uuid

            await session.commit()
            await session.refresh(customer)

            logger.info(
                f"Customer preferences updated: {customer_id}",
                extra={"customer_id": customer_id, "preferred_stylist_id": preferred_stylist_id}
            )

            return {
                "success": True,
                "customer_id": str(customer.id),
                "preferred_stylist_id": str(customer.preferred_stylist_id) if customer.preferred_stylist_id else None,
            }

    except IntegrityError as e:
        logger.warning(
            f"Invalid stylist_id (FK constraint): {preferred_stylist_id}",
            extra={"customer_id": customer_id, "preferred_stylist_id": preferred_stylist_id}
        )
        return {"error": "Invalid stylist_id - stylist does not exist", "preferred_stylist_id": preferred_stylist_id}

    except SQLAlchemyError as e:
        logger.error(f"Database error in update_customer_preferences: {e}", extra={"customer_id": customer_id})
        return {"error": "Failed to update customer preferences", "details": str(e)}


@tool(args_schema=GetCustomerHistorySchema)
async def get_customer_history(customer_id: str, limit: int = 5) -> dict[str, Any]:
    """
    Get customer's appointment history.

    Retrieves the most recent appointments for a customer, ordered by start time (most recent first).
    Includes related stylist and service information.

    Args:
        customer_id: Customer UUID as string
        limit: Maximum number of appointments to return (default: 5)

    Returns:
        Dict with list of appointments or error dict if customer not found
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
