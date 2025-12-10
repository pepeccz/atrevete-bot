"""
Admin API Endpoints for NextJS Admin Panel

Provides REST endpoints for:
- Authentication (JWT)
- Dashboard KPIs
- CRUD operations for all entities
- Calendar and availability
"""

import logging
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import pytz
from dateutil.parser import parse as parse_datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    BlockingEvent,
    BlockingEventType,
    BusinessHours,
    Customer,
    Holiday,
    Policy,
    Service,
    Stylist,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# =============================================================================
# Security
# =============================================================================

security = HTTPBearer()
settings = get_settings()

# JWT Configuration
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24


def get_jwt_secret() -> str:
    """Get JWT secret from settings."""
    secret = getattr(settings, "ADMIN_JWT_SECRET", None)
    if not secret:
        # Fallback for development - use a default secret
        logger.warning("ADMIN_JWT_SECRET not set, using development fallback")
        return "dev-secret-change-in-production-min-32-chars"
    return secret


def get_admin_credentials() -> tuple[str, str]:
    """Get admin credentials from settings."""
    username = getattr(settings, "ADMIN_USERNAME", "admin")
    password = getattr(settings, "ADMIN_PASSWORD", None)
    if not password:
        # Fallback for development
        logger.warning("ADMIN_PASSWORD not set, using development fallback")
        password = "admin123"
    return username, password


def create_access_token(username: str) -> str:
    """Create JWT access token."""
    expires = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "sub": username,
        "exp": expires,
        "iat": datetime.utcnow(),
        "type": "admin",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    """Verify JWT token and return payload."""
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "admin":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict[str, Any]:
    """Dependency to get current authenticated user."""
    return verify_token(credentials.credentials)


# =============================================================================
# Request/Response Models
# =============================================================================


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = JWT_EXPIRATION_HOURS * 3600


class UserResponse(BaseModel):
    username: str
    role: str = "admin"


class DashboardKPIs(BaseModel):
    appointments_this_month: int
    total_customers: int
    avg_appointment_duration: float
    total_hours_booked: float


class StylistResponse(BaseModel):
    id: str
    name: str
    category: str
    google_calendar_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerResponse(BaseModel):
    id: str
    phone: str
    first_name: str
    last_name: str | None
    total_spent: str
    last_service_date: datetime | None
    preferred_stylist_id: str | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceResponse(BaseModel):
    id: str
    name: str
    category: str
    duration_minutes: int
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppointmentResponse(BaseModel):
    id: str
    customer_id: str
    stylist_id: str
    service_ids: list[str]
    start_time: datetime
    duration_minutes: int
    status: str
    google_calendar_event_id: str | None
    first_name: str
    last_name: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BusinessHoursResponse(BaseModel):
    id: str
    day_of_week: int
    is_closed: bool
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# =============================================================================
# Auth Endpoints
# =============================================================================


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate admin user and return JWT token."""
    admin_username, admin_password = get_admin_credentials()

    if request.username != admin_username or request.password != admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(request.username)
    return LoginResponse(access_token=token)


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: Annotated[dict, Depends(get_current_user)]):
    """Get current authenticated user info."""
    return UserResponse(username=current_user["sub"])


# =============================================================================
# Chart Data Response Models
# =============================================================================


class ChartDataPoint(BaseModel):
    label: str
    value: float


class AppointmentTrendPoint(BaseModel):
    date: str
    count: int


class TopServicePoint(BaseModel):
    name: str
    count: int


class HoursWorkedPoint(BaseModel):
    month: str
    hours: float


class CustomerGrowthPoint(BaseModel):
    month: str
    count: int


class StylistPerformancePoint(BaseModel):
    name: str
    appointments: int
    hours: float


# =============================================================================
# Dashboard Endpoints
# =============================================================================


@router.get("/dashboard/kpis", response_model=DashboardKPIs)
async def get_dashboard_kpis(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get dashboard KPI metrics."""
    async with get_async_session() as session:
        # Get current month start
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Appointments this month
        appointments_query = select(func.count(Appointment.id)).where(
            Appointment.start_time >= month_start,
            Appointment.status.in_(
                [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
            ),
        )
        appointments_result = await session.execute(appointments_query)
        appointments_this_month = appointments_result.scalar() or 0

        # Total customers
        customers_query = select(func.count(Customer.id))
        customers_result = await session.execute(customers_query)
        total_customers = customers_result.scalar() or 0

        # Average appointment duration
        avg_duration_query = select(func.avg(Appointment.duration_minutes)).where(
            Appointment.start_time >= month_start
        )
        avg_result = await session.execute(avg_duration_query)
        avg_duration = avg_result.scalar() or 0

        # Total hours booked this month
        hours_query = select(func.sum(Appointment.duration_minutes)).where(
            Appointment.start_time >= month_start,
            Appointment.status.in_(
                [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]
            ),
        )
        hours_result = await session.execute(hours_query)
        total_minutes = hours_result.scalar() or 0
        total_hours = total_minutes / 60

        return DashboardKPIs(
            appointments_this_month=appointments_this_month,
            total_customers=total_customers,
            avg_appointment_duration=round(float(avg_duration), 1),
            total_hours_booked=round(total_hours, 1),
        )


@router.get("/dashboard/charts/appointments-trend")
async def get_appointments_trend(
    current_user: Annotated[dict, Depends(get_current_user)],
    days: int = 30,
):
    """Get appointment trend for the last N days."""
    async with get_async_session() as session:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Query appointments grouped by date
        query = (
            select(
                func.date(Appointment.start_time).label("date"),
                func.count(Appointment.id).label("count"),
            )
            .where(
                Appointment.start_time >= start_date,
                Appointment.start_time <= end_date,
                Appointment.status.in_(
                    [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED]
                ),
            )
            .group_by(func.date(Appointment.start_time))
            .order_by(func.date(Appointment.start_time))
        )

        result = await session.execute(query)
        rows = result.all()

        # Create a dict of date -> count
        date_counts = {row.date: row.count for row in rows}

        # Fill in missing dates with 0
        data = []
        current = start_date
        while current <= end_date:
            date_key = current.date()
            data.append({
                "date": date_key.strftime("%d/%m"),
                "count": date_counts.get(date_key, 0),
            })
            current += timedelta(days=1)

        return data


@router.get("/dashboard/charts/top-services")
async def get_top_services(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = 10,
):
    """Get top N most booked services."""
    async with get_async_session() as session:
        # Get all services to map IDs to names
        services_result = await session.execute(select(Service))
        services = {str(s.id): s.name for s in services_result.scalars().all()}

        # Get appointments from last 90 days
        start_date = datetime.now() - timedelta(days=90)
        appointments_result = await session.execute(
            select(Appointment.service_ids).where(
                Appointment.start_time >= start_date,
                Appointment.status.in_(
                    [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED]
                ),
            )
        )

        # Count service occurrences
        service_counts: dict[str, int] = {}
        for (service_ids,) in appointments_result.all():
            if service_ids:
                for sid in service_ids:
                    sid_str = str(sid)
                    service_counts[sid_str] = service_counts.get(sid_str, 0) + 1

        # Sort and get top N
        sorted_services = sorted(
            service_counts.items(), key=lambda x: x[1], reverse=True
        )[:limit]

        return [
            {"name": services.get(sid, "Desconocido"), "count": count}
            for sid, count in sorted_services
        ]


@router.get("/dashboard/charts/hours-worked")
async def get_hours_worked(
    current_user: Annotated[dict, Depends(get_current_user)],
    months: int = 12,
):
    """Get hours worked per month for the last N months."""
    async with get_async_session() as session:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)

        # Query appointments grouped by month
        month_col = func.date_trunc("month", Appointment.start_time).label("month")
        query = (
            select(
                month_col,
                func.sum(Appointment.duration_minutes).label("total_minutes"),
            )
            .where(
                Appointment.start_time >= start_date,
                Appointment.start_time <= end_date,
                Appointment.status.in_(
                    [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED]
                ),
            )
            .group_by(month_col)
            .order_by(month_col)
        )

        result = await session.execute(query)
        rows = result.all()

        # Format month names in Spanish
        month_names = [
            "Ene", "Feb", "Mar", "Abr", "May", "Jun",
            "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
        ]

        return [
            {
                "month": month_names[row.month.month - 1] + " " + str(row.month.year)[-2:],
                "hours": round((row.total_minutes or 0) / 60, 1),
            }
            for row in rows
        ]


@router.get("/dashboard/charts/customer-growth")
async def get_customer_growth(
    current_user: Annotated[dict, Depends(get_current_user)],
    months: int = 12,
):
    """Get customer growth per month for the last N months."""
    async with get_async_session() as session:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)

        # Query customers grouped by creation month
        month_col = func.date_trunc("month", Customer.created_at).label("month")
        query = (
            select(
                month_col,
                func.count(Customer.id).label("count"),
            )
            .where(
                Customer.created_at >= start_date,
                Customer.created_at <= end_date,
            )
            .group_by(month_col)
            .order_by(month_col)
        )

        result = await session.execute(query)
        rows = result.all()

        month_names = [
            "Ene", "Feb", "Mar", "Abr", "May", "Jun",
            "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"
        ]

        return [
            {
                "month": month_names[row.month.month - 1] + " " + str(row.month.year)[-2:],
                "count": row.count,
            }
            for row in rows
        ]


@router.get("/dashboard/charts/stylist-performance")
async def get_stylist_performance(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get stylist performance for current month."""
    async with get_async_session() as session:
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Get all active stylists
        stylists_result = await session.execute(
            select(Stylist).where(Stylist.is_active == True)
        )
        stylists = {str(s.id): s.name for s in stylists_result.scalars().all()}

        # Query appointments per stylist for current month
        query = (
            select(
                Appointment.stylist_id,
                func.count(Appointment.id).label("appointments"),
                func.sum(Appointment.duration_minutes).label("total_minutes"),
            )
            .where(
                Appointment.start_time >= month_start,
                Appointment.status.in_(
                    [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED]
                ),
            )
            .group_by(Appointment.stylist_id)
        )

        result = await session.execute(query)
        rows = result.all()

        return [
            {
                "name": stylists.get(str(row.stylist_id), "Desconocido"),
                "appointments": row.appointments,
                "hours": round((row.total_minutes or 0) / 60, 1),
            }
            for row in rows
        ]


# =============================================================================
# Stylists CRUD
# =============================================================================


@router.get("/stylists")
async def list_stylists(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 50,
    is_active: bool | None = None,
):
    """List all stylists with optional filtering."""
    async with get_async_session() as session:
        query = select(Stylist)
        if is_active is not None:
            query = query.where(Stylist.is_active == is_active)
        query = query.offset((page - 1) * page_size).limit(page_size + 1)

        result = await session.execute(query)
        stylists = result.scalars().all()

        has_more = len(stylists) > page_size
        items = stylists[:page_size]

        return {
            "items": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "category": s.category.value,
                    "google_calendar_id": s.google_calendar_id,
                    "is_active": s.is_active,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in items
            ],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }


@router.get("/stylists/{stylist_id}")
async def get_stylist(
    stylist_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get a single stylist by ID."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.id == stylist_id)
        )
        stylist = result.scalar_one_or_none()

        if not stylist:
            raise HTTPException(status_code=404, detail="Stylist not found")

        return {
            "id": str(stylist.id),
            "name": stylist.name,
            "category": stylist.category.value,
            "google_calendar_id": stylist.google_calendar_id,
            "is_active": stylist.is_active,
            "created_at": stylist.created_at.isoformat(),
            "updated_at": stylist.updated_at.isoformat(),
        }


# =============================================================================
# Customers CRUD
# =============================================================================


@router.get("/customers")
async def list_customers(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
):
    """List all customers with optional search."""
    async with get_async_session() as session:
        query = select(Customer)
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (Customer.phone.ilike(search_pattern))
                | (Customer.first_name.ilike(search_pattern))
                | (Customer.last_name.ilike(search_pattern))
            )
        query = query.order_by(Customer.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size + 1)

        result = await session.execute(query)
        customers = result.scalars().all()

        has_more = len(customers) > page_size
        items = customers[:page_size]

        return {
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "total_spent": str(c.total_spent),
                    "last_service_date": (
                        c.last_service_date.isoformat() if c.last_service_date else None
                    ),
                    "preferred_stylist_id": (
                        str(c.preferred_stylist_id) if c.preferred_stylist_id else None
                    ),
                    "notes": c.notes,
                    "created_at": c.created_at.isoformat(),
                }
                for c in items
            ],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get a single customer by ID."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()

        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        return {
            "id": str(customer.id),
            "phone": customer.phone,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "total_spent": str(customer.total_spent),
            "last_service_date": (
                customer.last_service_date.isoformat()
                if customer.last_service_date
                else None
            ),
            "preferred_stylist_id": (
                str(customer.preferred_stylist_id)
                if customer.preferred_stylist_id
                else None
            ),
            "notes": customer.notes,
            "created_at": customer.created_at.isoformat(),
        }


# =============================================================================
# Services CRUD
# =============================================================================


@router.get("/services")
async def list_services(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 100,
    is_active: bool | None = None,
    category: str | None = None,
):
    """List all services with optional filtering."""
    async with get_async_session() as session:
        query = select(Service)
        if is_active is not None:
            query = query.where(Service.is_active == is_active)
        if category:
            query = query.where(Service.category == category)
        query = query.order_by(Service.name)
        query = query.offset((page - 1) * page_size).limit(page_size + 1)

        result = await session.execute(query)
        services = result.scalars().all()

        has_more = len(services) > page_size
        items = services[:page_size]

        return {
            "items": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "category": s.category.value,
                    "duration_minutes": s.duration_minutes,
                    "description": s.description,
                    "is_active": s.is_active,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in items
            ],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }


# =============================================================================
# Appointments CRUD
# =============================================================================


@router.get("/appointments")
async def list_appointments(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 50,
    stylist_id: UUID | None = None,
    status: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """List appointments with optional filtering."""
    async with get_async_session() as session:
        query = select(Appointment)

        if stylist_id:
            query = query.where(Appointment.stylist_id == stylist_id)
        if status:
            query = query.where(Appointment.status == status)
        if start_date:
            query = query.where(Appointment.start_time >= start_date)
        if end_date:
            query = query.where(Appointment.start_time <= end_date)

        query = query.order_by(Appointment.start_time.desc())
        query = query.offset((page - 1) * page_size).limit(page_size + 1)

        result = await session.execute(query)
        appointments = result.scalars().all()

        has_more = len(appointments) > page_size
        items = appointments[:page_size]

        return {
            "items": [
                {
                    "id": str(a.id),
                    "customer_id": str(a.customer_id),
                    "stylist_id": str(a.stylist_id),
                    "service_ids": [str(sid) for sid in a.service_ids],
                    "start_time": a.start_time.isoformat(),
                    "duration_minutes": a.duration_minutes,
                    "status": a.status.value,
                    "google_calendar_event_id": a.google_calendar_event_id,
                    "first_name": a.first_name,
                    "last_name": a.last_name,
                    "notes": a.notes,
                    "created_at": a.created_at.isoformat(),
                    "updated_at": a.updated_at.isoformat(),
                }
                for a in items
            ],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        }


class CreateAppointmentRequest(BaseModel):
    customer_id: UUID
    stylist_id: UUID
    service_ids: list[UUID]
    start_time: datetime
    first_name: str
    last_name: str | None = None
    notes: str | None = None


@router.post("/appointments")
async def create_appointment(
    request: CreateAppointmentRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new appointment with Google Calendar integration."""
    async with get_async_session() as session:
        # Verify customer exists
        customer_result = await session.execute(
            select(Customer).where(Customer.id == request.customer_id)
        )
        customer = customer_result.scalar_one_or_none()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Verify stylist exists and is active
        stylist_result = await session.execute(
            select(Stylist).where(Stylist.id == request.stylist_id)
        )
        stylist = stylist_result.scalar_one_or_none()
        if not stylist:
            raise HTTPException(status_code=404, detail="Stylist not found")
        if not stylist.is_active:
            raise HTTPException(status_code=400, detail="Stylist is not active")

        # Verify all services exist and calculate total duration
        services_result = await session.execute(
            select(Service).where(Service.id.in_(request.service_ids))
        )
        services = services_result.scalars().all()
        if len(services) != len(request.service_ids):
            raise HTTPException(status_code=404, detail="One or more services not found")

        total_duration = sum(s.duration_minutes for s in services)

        # Create appointment in database
        new_appointment = Appointment(
            customer_id=request.customer_id,
            stylist_id=request.stylist_id,
            service_ids=request.service_ids,
            start_time=request.start_time,
            duration_minutes=total_duration,
            status=AppointmentStatus.CONFIRMED,
            first_name=request.first_name,
            last_name=request.last_name,
            notes=request.notes,
            google_calendar_event_id=None,  # Will be set after Google Calendar creation
        )

        session.add(new_appointment)

        # DB-first architecture: Commit to database FIRST (source of truth)
        await session.commit()
        await session.refresh(new_appointment)

        logger.info(
            f"Appointment {new_appointment.id} committed to database (DB-first)",
            extra={
                "appointment_id": str(new_appointment.id),
                "stylist_id": str(request.stylist_id),
            }
        )

        # Push to Google Calendar (fire-and-forget, non-blocking)
        # Push failures are logged but don't affect the appointment creation
        try:
            from agent.services.gcal_push_service import push_appointment_to_gcal

            service_names = ", ".join(s.name for s in services)
            customer_name = f"{request.first_name} {request.last_name or ''}".strip()

            google_event_id = await push_appointment_to_gcal(
                appointment_id=new_appointment.id,
                stylist_id=request.stylist_id,
                customer_name=customer_name,
                service_names=service_names,
                start_time=request.start_time,
                duration_minutes=total_duration,
                status="confirmed",  # Admin crea citas auto-confirmadas
            )

            if google_event_id:
                # Update appointment with Google Calendar event ID
                new_appointment.google_calendar_event_id = google_event_id
                await session.commit()
                logger.info(
                    f"Google Calendar event {google_event_id} created for appointment {new_appointment.id}"
                )
            else:
                # Log warning but don't fail - appointment is already committed
                logger.warning(
                    f"Google Calendar push failed for appointment {new_appointment.id} (booking still valid)"
                )

        except Exception as e:
            # Log error but don't fail - appointment is already committed (DB-first)
            logger.warning(
                f"Google Calendar push error for appointment {new_appointment.id}: {e} (booking still valid)"
            )

        return {
            "id": str(new_appointment.id),
            "customer_id": str(new_appointment.customer_id),
            "stylist_id": str(new_appointment.stylist_id),
            "service_ids": [str(sid) for sid in new_appointment.service_ids],
            "start_time": new_appointment.start_time.isoformat(),
            "duration_minutes": new_appointment.duration_minutes,
            "status": new_appointment.status.value,
            "google_calendar_event_id": new_appointment.google_calendar_event_id,
            "first_name": new_appointment.first_name,
            "last_name": new_appointment.last_name,
            "notes": new_appointment.notes,
            "created_at": new_appointment.created_at.isoformat(),
            "updated_at": new_appointment.updated_at.isoformat(),
        }


# =============================================================================
# Calendar Endpoints
# =============================================================================


@router.get("/calendar/appointments")
async def get_calendar_appointments(
    current_user: Annotated[dict, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    stylist_id: UUID | None = None,
    sync_google: bool = True,  # Query param opcional para desactivar sync
):
    """
    Get appointments from DB and optionally sync with Google Calendar.

    Returns combined view of:
    - DB appointments (with status colors)
    - External Google Calendar events (gray color)

    Args:
        start: Start date range (ISO format)
        end: End date range (ISO format)
        stylist_id: Optional filter by stylist
        sync_google: If False, only return DB appointments (default True)
    """
    from agent.tools.calendar_tools import fetch_calendar_events_async, get_calendar_client

    async with get_async_session() as session:
        # 1. Leer citas de DB (rápido ~50ms)
        query = select(Appointment).where(
            Appointment.start_time >= start,
            Appointment.start_time <= end,
        )
        if stylist_id:
            query = query.where(Appointment.stylist_id == stylist_id)

        result = await session.execute(query)
        appointments = result.scalars().all()

        logger.info(f"Found {len(appointments)} appointments in DB for range {start} to {end}")
        if appointments:
            logger.info(f"First appointment: id={appointments[0].id}, start={appointments[0].start_time}, name={appointments[0].first_name}")

        # Crear diccionario para identificar eventos ya en DB
        db_events_by_gcal_id = {
            a.google_calendar_event_id: a
            for a in appointments
            if a.google_calendar_event_id
        }

        # Color mapping for appointment status
        status_colors = {
            AppointmentStatus.PENDING: "#eab308",  # Yellow
            AppointmentStatus.CONFIRMED: "#22c55e",  # Green
            AppointmentStatus.COMPLETED: "#6b7280",  # Gray
            AppointmentStatus.CANCELLED: "#ef4444",  # Red
            AppointmentStatus.NO_SHOW: "#f97316",  # Orange
        }

        # 2. Formatear eventos de DB (mantener formato actual)
        # Convertir fechas a Europe/Madrid timezone
        madrid_tz = pytz.timezone('Europe/Madrid')

        events = []
        for a in appointments:
            end_time = a.start_time + timedelta(minutes=a.duration_minutes)

            # Convertir a Madrid timezone antes de serializar
            start_madrid = a.start_time.astimezone(madrid_tz)
            end_madrid = end_time.astimezone(madrid_tz)

            events.append({
                "id": str(a.id),
                "title": f"{a.first_name} {a.last_name or ''}".strip(),
                "start": start_madrid.isoformat(),
                "end": end_madrid.isoformat(),
                "backgroundColor": status_colors.get(a.status, "#6b7280"),
                "borderColor": status_colors.get(a.status, "#6b7280"),
                "extendedProps": {
                    "appointment_id": str(a.id),
                    "customer_id": str(a.customer_id),
                    "stylist_id": str(a.stylist_id),
                    "status": a.status.value,
                    "duration_minutes": a.duration_minutes,
                    "notes": a.notes,
                },
            })

        # 3. Si sync_google=True, consultar Google Calendar
        if sync_google:
            # Obtener estilistas activos (o solo el seleccionado)
            if stylist_id:
                stylists_query = select(Stylist).where(Stylist.id == stylist_id)
            else:
                stylists_query = select(Stylist).where(Stylist.is_active == True)

            stylists_result = await session.execute(stylists_query)
            stylists = stylists_result.scalars().all()

            # Obtener Google Calendar service
            try:
                calendar_client = get_calendar_client()
                service = calendar_client.get_service()
            except Exception as e:
                logger.warning(f"Failed to initialize Google Calendar client: {e}")
                # Fallback: retornar solo eventos de DB
                return events

            # Consultar Google Calendar por cada estilista (~2-3s por estilista)
            for stylist in stylists:
                try:
                    # Timeout de 5s por estilista
                    gcal_events = await fetch_calendar_events_async(
                        service=service,
                        calendar_id=stylist.google_calendar_id,
                        time_min=start.isoformat(),
                        time_max=end.isoformat(),
                        timeout=5.0
                    )

                    # Filtrar solo eventos NO en DB (creados externamente)
                    for event in gcal_events:
                        event_id = event.get("id")

                        # Skip si ya existe en DB
                        if event_id in db_events_by_gcal_id:
                            continue

                        # Extraer datetimes de Google Calendar
                        event_start = event.get("start", {}).get("dateTime")
                        event_end = event.get("end", {}).get("dateTime")

                        if not event_start or not event_end:
                            continue  # Skip all-day events

                        # Convertir fechas de Google Calendar a Madrid timezone
                        try:
                            start_dt = parse_datetime(event_start).astimezone(madrid_tz)
                            end_dt = parse_datetime(event_end).astimezone(madrid_tz)
                        except Exception as e:
                            logger.warning(f"Failed to parse Google Calendar event dates: {e}")
                            continue

                        # Formatear evento externo
                        events.append({
                            "id": f"google-{event_id}",  # Prefijo para distinguir
                            "title": event.get("summary", "Sin título"),
                            "start": start_dt.isoformat(),
                            "end": end_dt.isoformat(),
                            "backgroundColor": "#9CA3AF",  # Gris para externos
                            "borderColor": "#6B7280",      # Gris oscuro borde
                            "extendedProps": {
                                "appointment_id": None,
                                "customer_id": None,
                                "stylist_id": str(stylist.id),
                                "status": "external",
                                "duration_minutes": 0,
                                "notes": "Evento creado externamente en Google Calendar",
                                "google_event_id": event_id,
                            },
                        })

                except Exception as e:
                    logger.warning(
                        f"Failed to fetch Google Calendar for stylist {stylist.name} ({stylist.id}): {e}"
                    )
                    # Continuar con otros estilistas si uno falla

        # 4. Retornar eventos combinados
        logger.info(
            f"GET /calendar/appointments: Returning {len(events)} events "
            f"(params: start={start}, end={end}, stylist_id={stylist_id}, sync_google={sync_google})"
        )
        if events:
            logger.info(f"First event sample: {events[0]}")
        else:
            logger.warning("No events found in DB or Google Calendar!")

        return events


@router.get("/calendar/availability")
async def get_calendar_availability(
    current_user: Annotated[dict, Depends(get_current_user)],
    stylist_id: UUID,
    date: str,  # YYYY-MM-DD format
    time_range: str | None = None,  # "morning" | "afternoon" | None
):
    """
    Get available time slots for a stylist on a specific date.

    Args:
        stylist_id: UUID of the stylist
        date: Date in YYYY-MM-DD format
        time_range: Optional filter ("morning" or "afternoon")

    Returns:
        List of available time slots with stylist information
    """
    from agent.tools.availability_tools import check_availability

    async with get_async_session() as session:
        # Get stylist info
        stylist_result = await session.execute(
            select(Stylist).where(Stylist.id == stylist_id)
        )
        stylist = stylist_result.scalar_one_or_none()

        if not stylist:
            raise HTTPException(
                status_code=404,
                detail=f"Stylist not found: {stylist_id}"
            )

        # Call availability tool
        try:
            result = await check_availability.ainvoke({
                "service_category": stylist.category.value,
                "date": date,
                "time_range": time_range,
                "stylist_id": str(stylist_id),
            })

            if not result.get("success"):
                return {
                    "slots": [],
                    "error": result.get("error", "Unknown error checking availability"),
                    "holiday_detected": result.get("holiday_detected", False)
                }

            # Format slots for frontend
            slots = []
            for slot_data in result.get("available_slots", []):
                for slot in slot_data.get("slots", []):
                    slots.append({
                        "time": slot["time"],
                        "end_time": slot["end_time"],
                        "available": True,
                        "stylist_id": slot_data["stylist_id"],
                        "stylist_name": slot_data["stylist_name"],
                    })

            return {
                "slots": slots,
                "holiday_detected": result.get("holiday_detected", False)
            }

        except Exception as e:
            logger.exception(f"Error checking availability for stylist {stylist_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check availability: {str(e)}"
            )


# =============================================================================
# Business Hours
# =============================================================================


@router.get("/business-hours")
async def list_business_hours(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get business hours for all days of the week."""
    async with get_async_session() as session:
        result = await session.execute(
            select(BusinessHours).order_by(BusinessHours.day_of_week)
        )
        hours = result.scalars().all()

        return {
            "items": [
                {
                    "id": str(h.id),
                    "day_of_week": h.day_of_week,
                    "is_closed": h.is_closed,
                    "start_hour": h.start_hour,
                    "start_minute": h.start_minute,
                    "end_hour": h.end_hour,
                    "end_minute": h.end_minute,
                }
                for h in hours
            ]
        }


# =============================================================================
# Blocking Events CRUD
# =============================================================================


class CreateBlockingEventRequest(BaseModel):
    """Request schema for creating a blocking event."""
    stylist_id: UUID
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    start_time: datetime
    end_time: datetime
    event_type: str = Field(default="general")  # vacation, meeting, break, general


class UpdateBlockingEventRequest(BaseModel):
    """Request schema for updating a blocking event."""
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    event_type: str | None = None


@router.get("/blocking-events")
async def list_blocking_events(
    current_user: Annotated[dict, Depends(get_current_user)],
    stylist_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
):
    """
    List blocking events with optional filters.

    Args:
        stylist_id: Optional filter by stylist
        start: Optional start date range
        end: Optional end date range
    """
    async with get_async_session() as session:
        query = select(BlockingEvent)

        if stylist_id:
            query = query.where(BlockingEvent.stylist_id == stylist_id)

        if start:
            query = query.where(BlockingEvent.end_time >= start)

        if end:
            query = query.where(BlockingEvent.start_time <= end)

        query = query.order_by(BlockingEvent.start_time)

        result = await session.execute(query)
        events = result.scalars().all()

        return {
            "items": [
                {
                    "id": str(e.id),
                    "stylist_id": str(e.stylist_id),
                    "title": e.title,
                    "description": e.description,
                    "start_time": e.start_time.isoformat(),
                    "end_time": e.end_time.isoformat(),
                    "event_type": e.event_type.value,
                    "google_calendar_event_id": e.google_calendar_event_id,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ],
            "total": len(events),
        }


@router.post("/blocking-events", status_code=status.HTTP_201_CREATED)
async def create_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    request: CreateBlockingEventRequest,
):
    """
    Create a new blocking event.

    This creates the event in the database and optionally pushes to Google Calendar.
    """
    from agent.services.gcal_push_service import fire_and_forget_push_blocking_event

    # Validate event_type
    try:
        event_type_enum = BlockingEventType(request.event_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type: {request.event_type}. Must be one of: vacation, meeting, break, general"
        )

    # Validate end_time > start_time
    if request.end_time <= request.start_time:
        raise HTTPException(
            status_code=400,
            detail="end_time must be after start_time"
        )

    async with get_async_session() as session:
        # Verify stylist exists
        stylist_result = await session.execute(
            select(Stylist).where(Stylist.id == request.stylist_id)
        )
        stylist = stylist_result.scalar_one_or_none()

        if not stylist:
            raise HTTPException(status_code=404, detail="Stylist not found")

        # Create blocking event
        blocking_event = BlockingEvent(
            stylist_id=request.stylist_id,
            title=request.title,
            description=request.description,
            start_time=request.start_time,
            end_time=request.end_time,
            event_type=event_type_enum,
        )

        session.add(blocking_event)
        await session.commit()
        await session.refresh(blocking_event)

        # Fire-and-forget push to Google Calendar
        await fire_and_forget_push_blocking_event(
            blocking_event_id=blocking_event.id,
            stylist_id=blocking_event.stylist_id,
            title=blocking_event.title,
            description=blocking_event.description,
            start_time=blocking_event.start_time,
            end_time=blocking_event.end_time,
            event_type=blocking_event.event_type.value,
        )

        return {
            "id": str(blocking_event.id),
            "stylist_id": str(blocking_event.stylist_id),
            "title": blocking_event.title,
            "description": blocking_event.description,
            "start_time": blocking_event.start_time.isoformat(),
            "end_time": blocking_event.end_time.isoformat(),
            "event_type": blocking_event.event_type.value,
            "created_at": blocking_event.created_at.isoformat(),
        }


@router.put("/blocking-events/{event_id}")
async def update_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
    request: UpdateBlockingEventRequest,
):
    """Update a blocking event."""
    async with get_async_session() as session:
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        # Update fields if provided
        if request.title is not None:
            event.title = request.title
        if request.description is not None:
            event.description = request.description
        if request.start_time is not None:
            event.start_time = request.start_time
        if request.end_time is not None:
            event.end_time = request.end_time
        if request.event_type is not None:
            try:
                event.event_type = BlockingEventType(request.event_type)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid event_type: {request.event_type}"
                )

        # Validate end_time > start_time
        if event.end_time <= event.start_time:
            raise HTTPException(
                status_code=400,
                detail="end_time must be after start_time"
            )

        await session.commit()
        await session.refresh(event)

        return {
            "id": str(event.id),
            "stylist_id": str(event.stylist_id),
            "title": event.title,
            "description": event.description,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat(),
            "event_type": event.event_type.value,
        }


@router.delete("/blocking-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
):
    """Delete a blocking event."""
    from agent.services.gcal_push_service import delete_gcal_event

    async with get_async_session() as session:
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        # Delete from Google Calendar if it was synced
        if event.google_calendar_event_id:
            await delete_gcal_event(event.stylist_id, event.google_calendar_event_id)

        await session.delete(event)
        await session.commit()


# =============================================================================
# Multi-Stylist Calendar Events (DB-First)
# =============================================================================


@router.get("/calendar/events")
async def get_calendar_events(
    current_user: Annotated[dict, Depends(get_current_user)],
    start: datetime,
    end: datetime,
    stylist_ids: str | None = None,  # Comma-separated UUIDs
):
    """
    Get calendar events for multiple stylists from database (DB-first).

    This endpoint returns both appointments and blocking events from the database.
    No Google Calendar sync is performed - DB is the source of truth.

    Args:
        start: Start date range (ISO format)
        end: End date range (ISO format)
        stylist_ids: Comma-separated list of stylist UUIDs (optional, all if not provided)

    Returns:
        List of events formatted for FullCalendar with stylist color coding
    """
    from agent.services.availability_service import get_calendar_events_for_range

    # Parse stylist_ids if provided
    if stylist_ids:
        try:
            stylist_uuid_list = [UUID(sid.strip()) for sid in stylist_ids.split(",")]
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stylist_ids format: {e}"
            )
    else:
        # Get all active stylists
        async with get_async_session() as session:
            result = await session.execute(
                select(Stylist.id).where(Stylist.is_active == True)
            )
            stylist_uuid_list = [row[0] for row in result.all()]

    # Define color palette for stylists
    STYLIST_COLORS = [
        "#7C3AED",  # Violet
        "#2563EB",  # Blue
        "#059669",  # Emerald
        "#DC2626",  # Red
        "#D97706",  # Amber
        "#7C2D12",  # Brown
        "#DB2777",  # Pink
        "#0891B2",  # Cyan
    ]

    # Get events from DB
    events = await get_calendar_events_for_range(
        stylist_ids=stylist_uuid_list,
        start_time=start,
        end_time=end,
    )

    # Assign colors based on stylist order
    stylist_color_map = {}
    for i, sid in enumerate(stylist_uuid_list):
        stylist_color_map[str(sid)] = STYLIST_COLORS[i % len(STYLIST_COLORS)]

    # Apply stylist colors to appointment events
    for event in events:
        stylist_id = event.get("extendedProps", {}).get("stylist_id")
        if stylist_id and event.get("extendedProps", {}).get("type") == "appointment":
            color = stylist_color_map.get(stylist_id, "#7C3AED")
            event["backgroundColor"] = color
            event["borderColor"] = color

    return {
        "events": events,
        "stylist_colors": stylist_color_map,
        "total": len(events),
    }


# =============================================================================
# Holidays CRUD
# =============================================================================


@router.get("/holidays")
async def list_holidays(
    current_user: Annotated[dict, Depends(get_current_user)],
    year: int | None = None,
):
    """List all holidays, optionally filtered by year."""
    async with get_async_session() as session:
        query = select(Holiday).order_by(Holiday.date)

        if year:
            from sqlalchemy import extract
            query = query.where(extract("year", Holiday.date) == year)

        result = await session.execute(query)
        holidays = result.scalars().all()

        return {
            "items": [
                {
                    "id": str(h.id),
                    "date": h.date.isoformat(),
                    "name": h.name,
                    "is_all_day": h.is_all_day,
                }
                for h in holidays
            ],
            "total": len(holidays),
        }


class CreateHolidayRequest(BaseModel):
    """Request schema for creating a holiday."""
    date: str  # YYYY-MM-DD format
    name: str = Field(..., min_length=1, max_length=200)
    is_all_day: bool = True


@router.post("/holidays", status_code=status.HTTP_201_CREATED)
async def create_holiday(
    current_user: Annotated[dict, Depends(get_current_user)],
    request: CreateHolidayRequest,
):
    """Create a new holiday."""
    from datetime import date as date_type

    try:
        holiday_date = date_type.fromisoformat(request.date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Use YYYY-MM-DD"
        )

    async with get_async_session() as session:
        # Check if holiday already exists for this date
        existing = await session.execute(
            select(Holiday).where(Holiday.date == holiday_date)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Holiday already exists for date {request.date}"
            )

        holiday = Holiday(
            date=holiday_date,
            name=request.name,
            is_all_day=request.is_all_day,
        )

        session.add(holiday)
        await session.commit()
        await session.refresh(holiday)

        return {
            "id": str(holiday.id),
            "date": holiday.date.isoformat(),
            "name": holiday.name,
            "is_all_day": holiday.is_all_day,
        }


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    current_user: Annotated[dict, Depends(get_current_user)],
    holiday_id: UUID,
):
    """Delete a holiday."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Holiday).where(Holiday.id == holiday_id)
        )
        holiday = result.scalar_one_or_none()

        if not holiday:
            raise HTTPException(status_code=404, detail="Holiday not found")

        await session.delete(holiday)
        await session.commit()
