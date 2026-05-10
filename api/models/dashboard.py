"""
Pydantic response models for dashboard endpoints — Slice 2a.

Models:
  - DashboardKPIs: expanded KPI response (4 new fields + deprecated legacy fields)
  - AgendaCustomer, AgendaStylist, AgendaService: nested sub-models for today-agenda
  - TodayAgendaItem: single appointment in today's agenda
  - TodayAgendaResponse: wrapper for today-agenda endpoint
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

# =============================================================================
# KPI Models
# =============================================================================


class DashboardKPIs(BaseModel):
    """
    Dashboard KPI metrics — today-scoped data.

    New fields (Slice 2a):
      - confirmation_rate_today: fraction of today's non-cancelled appts that are confirmed (0..1)
      - confirmed_today: count of confirmed appointments today
      - total_today: total non-cancelled/no_show appointments today
      - appointments_today: alias of total_today (kept for frontend clarity)
      - occupation_today: booked_minutes / available_minutes (0..1)
      - booked_minutes_today: sum of confirmed+pending appointment durations
      - business_minutes_today: total capacity (active stylists × open minutes)
      - new_customers_this_week: customers created in the rolling last-7-days window

    Legacy fields (deprecated, kept for transition — removable in next change):
      - appointments_this_month: monthly aggregate (deprecated)
      - total_customers: total customer count (deprecated)
      - avg_appointment_duration: average duration this month (deprecated)
      - total_hours_booked: total hours booked this month (deprecated)
    """

    # New today-scoped KPIs
    confirmation_rate_today: float
    confirmed_today: int
    total_today: int
    appointments_today: int
    occupation_today: float
    booked_minutes_today: int
    business_minutes_today: int
    new_customers_this_week: int

    # Legacy monthly-aggregate fields (deprecated — will be removed in next slice)
    appointments_this_month: int | None = None
    total_customers: int | None = None
    avg_appointment_duration: float | None = None
    total_hours_booked: float | None = None


# =============================================================================
# Today-Agenda Models
# =============================================================================


class AgendaCustomer(BaseModel):
    """Minimal customer info embedded in a TodayAgendaItem."""

    id: str
    name: str


class AgendaStylist(BaseModel):
    """Minimal stylist info embedded in a TodayAgendaItem."""

    id: str
    name: str
    color: str | None = None


class AgendaService(BaseModel):
    """Minimal service info embedded in a TodayAgendaItem."""

    id: str
    name: str


class TodayAgendaItem(BaseModel):
    """Single appointment entry in today's agenda list."""

    id: str
    start_time: datetime
    duration_minutes: int
    status: str

    # Convenience flat fields (frontend friendly)
    customer_name: str
    stylist_name: str
    stylist_color: str | None = None

    # Nested sub-objects for richer access
    customer: AgendaCustomer
    stylist: AgendaStylist
    services: list[AgendaService]


class TodayAgendaResponse(BaseModel):
    """Response envelope for GET /api/admin/dashboard/today-agenda."""

    date: date
    appointments: list[TodayAgendaItem]
