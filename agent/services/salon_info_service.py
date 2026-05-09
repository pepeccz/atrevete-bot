"""
SalonInfoService — read-only salon information queries.

Owns DB sessions internally. Returns plain dicts (no success envelope) because
these are infallible read operations per design D1:
  - get_services() → list[dict]   active service catalog
  - get_hours()    → dict         business hours keyed by day_of_week string
  - get_policies() → dict         FAQ policies keyed by policy key

Callers (agent/tools/query_info.py) receive formatted data directly without
holding any DB session references.
"""

import logging

from sqlalchemy import select

from database.connection import get_async_session
from database.models import BusinessHours, Policy, Service

logger = logging.getLogger(__name__)


class SalonInfoService:
    """Read-only service for salon catalog, hours, and FAQ policies."""

    @staticmethod
    async def get_services() -> list[dict]:
        """Load all active services sorted by category then name.

        Returns:
            List of dicts with keys: name, audience, category, duration_minutes, description.
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Service)
                .where(Service.is_active.is_(True))
                .order_by(Service.category, Service.name)
            )
            services = result.scalars().all()

        return [
            {
                "name": svc.name,
                "audience": svc.audience,
                "category": svc.category.value if svc.category else None,
                "duration_minutes": svc.duration_minutes,
                "description": svc.description,
            }
            for svc in services
        ]

    @staticmethod
    async def get_hours() -> dict:
        """Load business hours keyed by day_of_week (str).

        Returns:
            Dict mapping day_of_week string → {"is_closed": bool} or
            {"is_closed": False, "open": "HH:MM", "close": "HH:MM"}.
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(BusinessHours).order_by(BusinessHours.day_of_week)
            )
            rows = result.scalars().all()

        hours: dict = {}
        for row in rows:
            if row.is_closed:
                hours[str(row.day_of_week)] = {"is_closed": True}
            else:
                hours[str(row.day_of_week)] = {
                    "is_closed": False,
                    "open": f"{row.start_hour:02d}:{row.start_minute:02d}",
                    "close": f"{row.end_hour:02d}:{row.end_minute:02d}",
                }
        return hours

    @staticmethod
    async def get_policies() -> dict:
        """Load all policies whose key starts with 'faq:'.

        Returns:
            Dict mapping policy key → policy value string.
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Policy).where(Policy.key.like("faq:%"))
            )
            rows = result.scalars().all()

        return {row.key: row.value for row in rows}
