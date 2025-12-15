"""
Admin API Endpoints for NextJS Admin Panel

Provides REST endpoints for:
- Authentication (JWT)
- Dashboard KPIs
- CRUD operations for all entities
- Calendar and availability
"""

import asyncio
import logging
import time
from datetime import date, datetime, time as dt_time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import pytz
from dateutil.parser import parse as parse_datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.connection import get_async_session
from database.models import (
    Appointment,
    AppointmentStatus,
    BlockingEvent,
    BlockingEventType,
    BusinessHours,
    ConversationHistory,
    Customer,
    Holiday,
    Notification,
    NotificationType,
    Policy,
    RecurringBlockingSeries,
    RecurrenceFrequency,
    Service,
    Stylist,
)
from shared.config import get_settings
from agent.services.recurrence_service import (
    expand_recurrence,
    check_conflicts_for_dates,
    get_business_hours_summary,
    get_remaining_week_days,
    format_byday,
    format_bymonthday,
    parse_byday,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# =============================================================================
# Timezone Handling
# =============================================================================

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Spanish date formatting constants
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]


def format_date_spanish(dt: datetime) -> str:
    """Format datetime to Spanish date string like 'lunes 15 de diciembre'."""
    return f"{WEEKDAYS_ES[dt.weekday()]} {dt.day} de {MONTHS_ES[dt.month - 1]}"


# =============================================================================
# GCal Fire-and-Forget Helpers
# =============================================================================


async def _safe_delete_gcal_event(stylist_id: UUID, event_id: str) -> None:
    """
    Fire-and-forget wrapper for GCal event deletion.

    This function is designed to be used with asyncio.create_task() to avoid
    blocking the HTTP response while waiting for Google Calendar API calls.
    Failures are logged but don't affect the caller.
    """
    from agent.services.gcal_push_service import delete_gcal_event

    try:
        await delete_gcal_event(stylist_id, event_id)
        logger.info(f"GCal event {event_id} deleted successfully")
    except Exception as e:
        logger.warning(f"Failed to delete GCal event {event_id}: {e}")


async def _safe_send_admin_appointment_template(
    customer_phone: str,
    template_name: str,
    body_params: dict[str, str],
    customer_name: str | None,
    conversation_id: int | None,
    appointment_id: UUID,
) -> None:
    """
    Fire-and-forget wrapper for sending WhatsApp template for admin-created appointments.

    This function is designed to be used with asyncio.create_task() to avoid
    blocking the HTTP response while waiting for Chatwoot API calls.
    Failures are logged but don't affect the caller.
    """
    from shared.chatwoot_client import ChatwootClient

    try:
        chatwoot = ChatwootClient()
        success = await chatwoot.send_template_message(
            customer_phone=customer_phone,
            template_name=template_name,
            body_params=body_params,
            customer_name=customer_name,
            conversation_id=conversation_id,
            fallback_content=f"Nueva cita reservada: {body_params.get('2', '')} a las {body_params.get('3', '')}",
        )
        if success:
            logger.info(f"Admin appointment template sent for appointment {appointment_id}")
        else:
            logger.warning(f"Failed to send admin appointment template for appointment {appointment_id}")
    except Exception as e:
        logger.warning(f"Error sending admin appointment template for appointment {appointment_id}: {e}")


def parse_datetime_as_madrid(v: Any) -> datetime | None:
    """
    Parse datetime string/object and ensure Madrid timezone.

    This handles the case where frontend sends naive datetime strings
    (e.g., "2024-12-12T10:30:00") without timezone info. We assume
    these are in Madrid time since the app is for a Spanish salon.
    """
    if v is None:
        return None
    if isinstance(v, str):
        # Parse ISO string, handle 'Z' suffix (UTC marker)
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Naive datetime → assume Madrid timezone
            return dt.replace(tzinfo=MADRID_TZ)
        return dt
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=MADRID_TZ)
        return v
    return v

# =============================================================================
# Security
# =============================================================================

security = HTTPBearer(auto_error=False)  # auto_error=False allows cookie fallback
settings = get_settings()

# JWT Configuration
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24  # 24h for convenience during development
JWT_COOKIE_NAME = "admin_token"  # HttpOnly cookie name
JWT_COOKIE_SECURE = False  # Set to True in production with HTTPS
JWT_COOKIE_SAMESITE = "lax"  # "strict" may break some OAuth flows


def get_jwt_secret() -> str:
    """
    Get JWT secret from settings.

    Raises:
        RuntimeError: If ADMIN_JWT_SECRET is not set in environment
    """
    secret = getattr(settings, "ADMIN_JWT_SECRET", None)
    if not secret:
        raise RuntimeError(
            "ADMIN_JWT_SECRET must be set in environment variables. "
            "Generate a secure secret with: openssl rand -hex 32"
        )
    return secret


def get_admin_credentials() -> tuple[str, str | None, str | None]:
    """
    Get admin credentials from settings.

    Returns:
        Tuple of (username, password_plain, password_hash)
        - password_hash is preferred if set (more secure)
        - password_plain is used as fallback (DEPRECATED, logs warning)

    Raises:
        RuntimeError: If ADMIN_USERNAME or neither password option is set
    """
    username = getattr(settings, "ADMIN_USERNAME", None)
    password_plain = getattr(settings, "ADMIN_PASSWORD", None) or None
    password_hash = getattr(settings, "ADMIN_PASSWORD_HASH", None) or None

    if not username:
        raise RuntimeError(
            "ADMIN_USERNAME must be set in environment variables."
        )

    if not password_hash and not password_plain:
        raise RuntimeError(
            "Either ADMIN_PASSWORD_HASH (recommended) or ADMIN_PASSWORD must be set. "
            "Generate hash with: python -c \"from passlib.hash import bcrypt; print(bcrypt.hash('your_password'))\""
        )

    if password_plain and not password_hash:
        logger.warning(
            "ADMIN_PASSWORD (plain text) is deprecated. "
            "Use ADMIN_PASSWORD_HASH for secure password storage."
        )

    return username, password_plain, password_hash


def verify_admin_password(password_input: str, password_plain: str | None, password_hash: str | None) -> bool:
    """
    Verify admin password using bcrypt hash or plain text fallback.

    Args:
        password_input: Password provided by user
        password_plain: Plain text password (DEPRECATED)
        password_hash: Bcrypt hash of password (preferred)

    Returns:
        True if password matches, False otherwise
    """
    # Prefer bcrypt hash verification (secure)
    if password_hash:
        try:
            return bcrypt.verify(password_input, password_hash)
        except Exception as e:
            logger.error(f"Error verifying password hash: {e}")
            return False

    # Fallback to plain text comparison (insecure, deprecated)
    if password_plain:
        # Use constant-time comparison to prevent timing attacks
        # Encode to bytes to support non-ASCII characters
        import hmac
        return hmac.compare_digest(
            password_input.encode("utf-8"),
            password_plain.encode("utf-8")
        )

    return False


def create_access_token(username: str) -> tuple[str, str]:
    """
    Create JWT access token with proper Unix timestamps.

    Returns:
        Tuple of (encoded_token, jti) for potential token tracking/revocation
    """
    now = int(time.time())
    expires = now + (JWT_EXPIRATION_HOURS * 3600)
    jti = str(uuid4())  # Unique token ID for revocation support

    payload = {
        "sub": username,
        "exp": expires,  # Unix timestamp (required by JWT spec)
        "iat": now,  # Unix timestamp (issued at)
        "jti": jti,  # JWT ID for token revocation tracking
        "type": "admin",
    }
    token = jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, jti


async def check_token_blacklist(jti: str) -> bool:
    """Check if token JTI is blacklisted (revoked)."""
    from shared.redis_client import get_redis_client

    try:
        redis_client = get_redis_client()
        result = await redis_client.get(f"token_blacklist:{jti}")
        return result is not None
    except Exception as e:
        logger.error(f"Error checking token blacklist: {e}")
        # Fail open on Redis errors to avoid blocking all requests
        return False


async def add_token_to_blacklist(jti: str, exp: int) -> bool:
    """
    Add token JTI to blacklist with TTL until token expiration.

    Args:
        jti: JWT ID to blacklist
        exp: Token expiration timestamp (Unix)

    Returns:
        True if added successfully, False otherwise
    """
    from shared.redis_client import get_redis_client
    import time

    try:
        redis_client = get_redis_client()
        ttl = max(0, exp - int(time.time()))  # Remaining time until expiration
        if ttl > 0:
            await redis_client.setex(f"token_blacklist:{jti}", ttl, "1")
            logger.info(f"Token {jti[:8]}... added to blacklist (TTL: {ttl}s)")
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding token to blacklist: {e}")
        return False


def verify_token(token: str) -> dict[str, Any]:
    """
    Verify JWT token and return payload.

    Note: This is synchronous for compatibility with HTTPBearer dependency.
    Blacklist check is done asynchronously in get_current_user.
    """
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
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    admin_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, Any]:
    """
    Dependency to get current authenticated user.

    Supports two authentication methods (in priority order):
    1. HttpOnly cookie (recommended, XSS-safe)
    2. Authorization header (for API clients/mobile apps)

    Verifies JWT signature and checks token blacklist for revoked tokens.
    """
    # Try to get token from cookie first (more secure)
    token = admin_token

    # Fall back to Authorization header
    if not token and credentials:
        token = credentials.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)

    # Check if token is blacklisted (revoked via logout)
    jti = payload.get("jti")
    if jti and await check_token_blacklist(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    return payload


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
    color: str | None = None
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
# Search & Notification Models
# =============================================================================


class SearchResultItem(BaseModel):
    id: str
    type: str  # 'customer', 'appointment', 'service', 'stylist'
    title: str
    subtitle: str | None = None
    url: str  # Frontend route to navigate to


class GlobalSearchResponse(BaseModel):
    customers: list[SearchResultItem]
    appointments: list[SearchResultItem]
    services: list[SearchResultItem]
    stylists: list[SearchResultItem]
    total: int


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    entity_type: str
    entity_id: str | None
    is_read: bool
    is_starred: bool
    created_at: datetime
    read_at: datetime | None
    starred_at: datetime | None

    class Config:
        from_attributes = True


class NotificationsListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int
    total: int


class NotificationsPaginatedResponse(BaseModel):
    """Paginated notifications response with full filter support."""
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
    unread_count: int
    starred_count: int


class NotificationStatsResponse(BaseModel):
    """Statistics for notification charts."""
    by_type: dict[str, int]
    by_category: dict[str, int]
    trend: list[dict[str, Any]]
    total: int
    unread: int
    starred: int


class NotificationBulkRequest(BaseModel):
    """Request for bulk operations on notifications."""
    ids: list[UUID]


# Notification categories mapping
NOTIFICATION_CATEGORIES = {
    "citas": [
        "appointment_created",
        "appointment_cancelled",
        "appointment_confirmed",
        "appointment_completed",
    ],
    "confirmaciones": [
        "confirmation_sent",
        "confirmation_received",
        "auto_cancelled",
        "confirmation_failed",
        "reminder_sent",
    ],
    "escalaciones": [
        "escalation_manual",
        "escalation_technical",
        "escalation_auto",
        "escalation_medical",
        "escalation_ambiguity",
    ],
}


# =============================================================================
# Auth Endpoints
# =============================================================================


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    Authenticate admin user and return JWT token.

    Sets HttpOnly cookie for browser-based clients (XSS-safe).
    Also returns token in response body for API clients.
    """
    admin_username, password_plain, password_hash = get_admin_credentials()

    # Verify username
    if request.username != admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Verify password using bcrypt hash (preferred) or plain text (deprecated)
    if not verify_admin_password(request.password, password_plain, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token, _jti = create_access_token(request.username)

    # Set HttpOnly cookie for browser clients (XSS-safe)
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=token,
        httponly=True,  # Not accessible via JavaScript
        secure=JWT_COOKIE_SECURE,  # Only sent over HTTPS
        samesite=JWT_COOKIE_SAMESITE,  # CSRF protection
        max_age=JWT_EXPIRATION_HOURS * 3600,
        path="/api/admin",  # Scope to admin routes only
    )

    # Also return token in body for API clients (mobile apps, etc.)
    return LoginResponse(access_token=token)


@router.post("/auth/logout")
async def logout(
    response: Response,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Logout user by adding token to blacklist and clearing cookie.

    The token's JTI (JWT ID) is added to Redis with TTL matching token expiration.
    Subsequent requests with this token will be rejected.
    """
    jti = current_user.get("jti")
    exp = current_user.get("exp")

    # Clear the HttpOnly cookie
    response.delete_cookie(
        key=JWT_COOKIE_NAME,
        path="/api/admin",
        httponly=True,
        secure=JWT_COOKIE_SECURE,
        samesite=JWT_COOKIE_SAMESITE,
    )

    if not jti or not exp:
        # Token doesn't have jti claim (old token format)
        logger.warning("Logout attempted with token missing jti/exp claims")
        return {"message": "Logged out (token will remain valid until expiration)"}

    success = await add_token_to_blacklist(jti, exp)

    if success:
        return {"message": "Successfully logged out"}
    else:
        # Return success anyway - don't expose internal errors
        return {"message": "Logged out"}


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


class CreateStylistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(default="HAIRDRESSING")
    google_calendar_id: str = Field(..., min_length=1)
    is_active: bool = True
    color: str | None = Field(None, min_length=7, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")


class UpdateStylistRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    category: str | None = None
    google_calendar_id: str | None = Field(None, min_length=1)
    is_active: bool | None = None
    color: str | None = Field(None, min_length=7, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")


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
                    "color": s.color,
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
            "color": stylist.color,
            "created_at": stylist.created_at.isoformat(),
            "updated_at": stylist.updated_at.isoformat(),
        }


@router.post("/stylists", status_code=status.HTTP_201_CREATED)
async def create_stylist(
    request: CreateStylistRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new stylist."""
    from database.models import ServiceCategory

    # Validate category
    try:
        category_enum = ServiceCategory(request.category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category: {request.category}. Must be HAIRDRESSING, AESTHETICS, or BOTH"
        )

    async with get_async_session() as session:
        stylist = Stylist(
            name=request.name,
            category=category_enum,
            google_calendar_id=request.google_calendar_id,
            is_active=request.is_active,
            color=request.color,
        )
        session.add(stylist)
        await session.commit()
        await session.refresh(stylist)

        return {
            "id": str(stylist.id),
            "name": stylist.name,
            "category": stylist.category.value,
            "google_calendar_id": stylist.google_calendar_id,
            "is_active": stylist.is_active,
            "color": stylist.color,
            "created_at": stylist.created_at.isoformat(),
            "updated_at": stylist.updated_at.isoformat(),
        }


@router.put("/stylists/{stylist_id}")
async def update_stylist(
    stylist_id: UUID,
    request: UpdateStylistRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update an existing stylist."""
    from database.models import ServiceCategory

    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.id == stylist_id)
        )
        stylist = result.scalar_one_or_none()

        if not stylist:
            raise HTTPException(status_code=404, detail="Stylist not found")

        # Update fields if provided
        if request.name is not None:
            stylist.name = request.name
        if request.category is not None:
            try:
                stylist.category = ServiceCategory(request.category)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {request.category}"
                )
        if request.google_calendar_id is not None:
            stylist.google_calendar_id = request.google_calendar_id
        if request.is_active is not None:
            stylist.is_active = request.is_active
        if request.color is not None:
            stylist.color = request.color

        await session.commit()
        await session.refresh(stylist)

        return {
            "id": str(stylist.id),
            "name": stylist.name,
            "category": stylist.category.value,
            "google_calendar_id": stylist.google_calendar_id,
            "is_active": stylist.is_active,
            "color": stylist.color,
            "created_at": stylist.created_at.isoformat(),
            "updated_at": stylist.updated_at.isoformat(),
        }


@router.delete("/stylists/{stylist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stylist(
    stylist_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a stylist."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.id == stylist_id)
        )
        stylist = result.scalar_one_or_none()

        if not stylist:
            raise HTTPException(status_code=404, detail="Stylist not found")

        await session.delete(stylist)
        await session.commit()


# =============================================================================
# Customers CRUD
# =============================================================================


class CreateCustomerRequest(BaseModel):
    phone: str = Field(..., min_length=1)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = None
    notes: str | None = None
    preferred_stylist_id: UUID | None = None


class UpdateCustomerRequest(BaseModel):
    phone: str | None = Field(None, min_length=1)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = None
    notes: str | None = None
    preferred_stylist_id: UUID | None = None


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


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    request: CreateCustomerRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new customer."""
    async with get_async_session() as session:
        # Check if phone already exists
        existing = await session.execute(
            select(Customer).where(Customer.phone == request.phone)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Customer with phone {request.phone} already exists"
            )

        customer = Customer(
            phone=request.phone,
            first_name=request.first_name,
            last_name=request.last_name,
            notes=request.notes,
            preferred_stylist_id=request.preferred_stylist_id,
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)

        return {
            "id": str(customer.id),
            "phone": customer.phone,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "total_spent": str(customer.total_spent),
            "last_service_date": None,
            "preferred_stylist_id": (
                str(customer.preferred_stylist_id)
                if customer.preferred_stylist_id
                else None
            ),
            "notes": customer.notes,
            "created_at": customer.created_at.isoformat(),
        }


@router.put("/customers/{customer_id}")
async def update_customer(
    customer_id: UUID,
    request: UpdateCustomerRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update an existing customer."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()

        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        # Update fields if provided
        if request.phone is not None:
            # Check if new phone already exists (for another customer)
            existing = await session.execute(
                select(Customer).where(
                    Customer.phone == request.phone,
                    Customer.id != customer_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"Phone {request.phone} already in use"
                )
            customer.phone = request.phone
        if request.first_name is not None:
            customer.first_name = request.first_name
        if request.last_name is not None:
            customer.last_name = request.last_name
        if request.notes is not None:
            customer.notes = request.notes
        if request.preferred_stylist_id is not None:
            customer.preferred_stylist_id = request.preferred_stylist_id

        await session.commit()
        await session.refresh(customer)

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


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a customer."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        customer = result.scalar_one_or_none()

        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        await session.delete(customer)
        await session.commit()


# =============================================================================
# Services CRUD
# =============================================================================


class CreateServiceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="HAIRDRESSING")
    duration_minutes: int = Field(default=30, ge=5, le=480)
    description: str | None = None
    is_active: bool = True


class UpdateServiceRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = None
    duration_minutes: int | None = Field(None, ge=5, le=480)
    description: str | None = None
    is_active: bool | None = None


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


@router.get("/services/{service_id}")
async def get_service(
    service_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get a single service by ID."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        return {
            "id": str(service.id),
            "name": service.name,
            "category": service.category.value,
            "duration_minutes": service.duration_minutes,
            "description": service.description,
            "is_active": service.is_active,
            "created_at": service.created_at.isoformat(),
            "updated_at": service.updated_at.isoformat(),
        }


@router.post("/services", status_code=status.HTTP_201_CREATED)
async def create_service(
    request: CreateServiceRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new service."""
    from database.models import ServiceCategory

    # Validate category
    try:
        category_enum = ServiceCategory(request.category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category: {request.category}. Must be HAIRDRESSING, AESTHETICS, or BOTH"
        )

    async with get_async_session() as session:
        service = Service(
            name=request.name,
            category=category_enum,
            duration_minutes=request.duration_minutes,
            description=request.description,
            is_active=request.is_active,
        )
        session.add(service)
        await session.commit()
        await session.refresh(service)

        return {
            "id": str(service.id),
            "name": service.name,
            "category": service.category.value,
            "duration_minutes": service.duration_minutes,
            "description": service.description,
            "is_active": service.is_active,
            "created_at": service.created_at.isoformat(),
            "updated_at": service.updated_at.isoformat(),
        }


@router.put("/services/{service_id}")
async def update_service(
    service_id: UUID,
    request: UpdateServiceRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update an existing service."""
    from database.models import ServiceCategory

    async with get_async_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        # Update fields if provided
        if request.name is not None:
            service.name = request.name
        if request.category is not None:
            try:
                service.category = ServiceCategory(request.category)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category: {request.category}"
                )
        if request.duration_minutes is not None:
            service.duration_minutes = request.duration_minutes
        if request.description is not None:
            service.description = request.description
        if request.is_active is not None:
            service.is_active = request.is_active

        await session.commit()
        await session.refresh(service)

        return {
            "id": str(service.id),
            "name": service.name,
            "category": service.category.value,
            "duration_minutes": service.duration_minutes,
            "description": service.description,
            "is_active": service.is_active,
            "created_at": service.created_at.isoformat(),
            "updated_at": service.updated_at.isoformat(),
        }


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    service_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a service."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        await session.delete(service)
        await session.commit()


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
                    "start_time": a.start_time.astimezone(MADRID_TZ).isoformat(),
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


@router.get("/appointments/pending-actions")
async def get_pending_actions(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Get appointments that have passed but are still pending/confirmed
    (not marked as completed or no_show).

    These are appointments that require action from the admin/stylist.
    """
    now = datetime.now(MADRID_TZ)

    async with get_async_session() as session:
        result = await session.execute(
            select(Appointment)
            .options(
                selectinload(Appointment.customer),
                selectinload(Appointment.stylist),
            )
            .where(
                and_(
                    Appointment.start_time < now,  # Already passed
                    Appointment.status.in_([
                        AppointmentStatus.PENDING,
                        AppointmentStatus.CONFIRMED
                    ]),
                )
            )
            .order_by(Appointment.start_time.desc())
            .limit(50)
        )
        appointments = list(result.scalars().all())

        # Get service names for each appointment
        items = []
        for appt in appointments:
            # Fetch services
            services_result = await session.execute(
                select(Service).where(Service.id.in_(appt.service_ids))
            )
            services = list(services_result.scalars().all())

            items.append({
                "id": str(appt.id),
                "customer_id": str(appt.customer_id),
                "stylist_id": str(appt.stylist_id),
                "start_time": appt.start_time.astimezone(MADRID_TZ).isoformat(),
                "duration_minutes": appt.duration_minutes,
                "status": appt.status.value,
                "first_name": appt.first_name or (appt.customer.first_name if appt.customer else "Cliente"),
                "last_name": appt.last_name,
                "stylist": {
                    "id": str(appt.stylist.id),
                    "name": appt.stylist.name,
                } if appt.stylist else None,
                "services": [
                    {"id": str(s.id), "name": s.name}
                    for s in services
                ],
            })

        return {
            "items": items,
            "total": len(items),
        }


class CreateAppointmentRequest(BaseModel):
    customer_id: UUID
    stylist_id: UUID
    service_ids: list[UUID]
    start_time: datetime
    first_name: str
    last_name: str | None = None
    notes: str | None = None
    send_notification: bool = True

    @field_validator("start_time", mode="before")
    @classmethod
    def ensure_madrid_tz(cls, v):
        return parse_datetime_as_madrid(v)


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
            status=AppointmentStatus.PENDING,
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
                status="pending",  # Admin crea citas pendientes (como WhatsApp)
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

        # Create notification for new appointment
        try:
            await create_notification(session, NotificationType.APPOINTMENT_CREATED, new_appointment)
            await session.commit()
        except Exception as e:
            logger.warning(f"Failed to create notification for appointment {new_appointment.id}: {e}")

        # Send WhatsApp notification to customer (fire-and-forget)
        if request.send_notification and customer.phone:
            conv_id = None
            if customer.chatwoot_conversation_id:
                try:
                    conv_id = int(customer.chatwoot_conversation_id)
                except (ValueError, TypeError):
                    pass

            appt_time = request.start_time.astimezone(MADRID_TZ)
            fecha = format_date_spanish(appt_time)
            hora = appt_time.strftime("%H:%M")
            display_name = request.first_name or customer.first_name or "Cliente"

            body_params = {
                "1": display_name,
                "2": fecha,
                "3": hora,
                "4": stylist.name,
                "5": service_names,  # Already computed above for GCal
            }

            settings = get_settings()
            asyncio.create_task(
                _safe_send_admin_appointment_template(
                    customer_phone=customer.phone,
                    template_name=settings.ADMIN_APPOINTMENT_TEMPLATE_NAME,
                    body_params=body_params,
                    customer_name=display_name,
                    conversation_id=conv_id,
                    appointment_id=new_appointment.id,
                )
            )

        return {
            "id": str(new_appointment.id),
            "customer_id": str(new_appointment.customer_id),
            "stylist_id": str(new_appointment.stylist_id),
            "service_ids": [str(sid) for sid in new_appointment.service_ids],
            "start_time": new_appointment.start_time.astimezone(MADRID_TZ).isoformat(),
            "duration_minutes": new_appointment.duration_minutes,
            "status": new_appointment.status.value,
            "google_calendar_event_id": new_appointment.google_calendar_event_id,
            "first_name": new_appointment.first_name,
            "last_name": new_appointment.last_name,
            "notes": new_appointment.notes,
            "created_at": new_appointment.created_at.isoformat(),
            "updated_at": new_appointment.updated_at.isoformat(),
        }


@router.get("/appointments/{appointment_id}")
async def get_appointment(
    appointment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get a single appointment by ID with all related data."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Appointment)
            .options(
                selectinload(Appointment.customer),
                selectinload(Appointment.stylist),
            )
            .where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        # Load services separately by IDs (no relationship in model)
        services = []
        if appointment.service_ids:
            services_result = await session.execute(
                select(Service).where(Service.id.in_(appointment.service_ids))
            )
            services = services_result.scalars().all()

        return {
            "id": str(appointment.id),
            "customer_id": str(appointment.customer_id),
            "stylist_id": str(appointment.stylist_id),
            "start_time": appointment.start_time.astimezone(MADRID_TZ).isoformat(),
            "duration_minutes": appointment.duration_minutes,
            "status": appointment.status.value,
            "first_name": appointment.first_name,
            "last_name": appointment.last_name,
            "notes": appointment.notes,
            "services": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "category": s.category.value,
                    "duration_minutes": s.duration_minutes,
                }
                for s in services
            ],
            "customer": {
                "id": str(appointment.customer.id),
                "phone": appointment.customer.phone,
                "first_name": appointment.customer.first_name,
                "last_name": appointment.customer.last_name,
            },
            "stylist": {
                "id": str(appointment.stylist.id),
                "name": appointment.stylist.name,
                "category": appointment.stylist.category.value,
            },
            "created_at": appointment.created_at.isoformat(),
            "updated_at": appointment.updated_at.isoformat(),
        }


class UpdateAppointmentRequest(BaseModel):
    stylist_id: UUID | None = None
    service_ids: list[UUID] | None = None
    start_time: datetime | None = None
    status: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    notes: str | None = None

    @field_validator("start_time", mode="before")
    @classmethod
    def ensure_madrid_tz(cls, v):
        return parse_datetime_as_madrid(v)


@router.put("/appointments/{appointment_id}")
async def update_appointment(
    appointment_id: UUID,
    request: UpdateAppointmentRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update an existing appointment."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        # Track old status for notification
        old_status = appointment.status

        # Update fields if provided
        if request.stylist_id is not None:
            # Verify stylist exists
            stylist_result = await session.execute(
                select(Stylist).where(Stylist.id == request.stylist_id)
            )
            if not stylist_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Stylist not found")
            appointment.stylist_id = request.stylist_id

        if request.service_ids is not None:
            # Verify all services exist and recalculate duration
            services_result = await session.execute(
                select(Service).where(Service.id.in_(request.service_ids))
            )
            services = services_result.scalars().all()
            if len(services) != len(request.service_ids):
                raise HTTPException(status_code=404, detail="One or more services not found")
            appointment.service_ids = request.service_ids
            appointment.duration_minutes = sum(s.duration_minutes for s in services)

        if request.start_time is not None:
            appointment.start_time = request.start_time

        if request.status is not None:
            try:
                appointment.status = AppointmentStatus(request.status)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {request.status}. Must be pending, confirmed, completed, cancelled, or no_show"
                )

        if request.first_name is not None:
            appointment.first_name = request.first_name
        if request.last_name is not None:
            appointment.last_name = request.last_name
        if request.notes is not None:
            appointment.notes = request.notes

        await session.commit()
        await session.refresh(appointment)

        # Create notification for status change
        if request.status is not None and appointment.status != old_status:
            notification_type = None
            if appointment.status == AppointmentStatus.CONFIRMED and old_status != AppointmentStatus.CONFIRMED:
                notification_type = NotificationType.APPOINTMENT_CONFIRMED
            elif appointment.status == AppointmentStatus.CANCELLED:
                notification_type = NotificationType.APPOINTMENT_CANCELLED
            elif appointment.status == AppointmentStatus.COMPLETED:
                notification_type = NotificationType.APPOINTMENT_COMPLETED

            if notification_type:
                try:
                    await create_notification(session, notification_type, appointment)
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Failed to create notification for appointment {appointment.id}: {e}")

        # Sync with Google Calendar
        # Get customer name and service names for Google Calendar
        customer_name = f"{appointment.first_name} {appointment.last_name or ''}".strip()

        services_result = await session.execute(
            select(Service).where(Service.id.in_(appointment.service_ids))
        )
        services = services_result.scalars().all()
        service_names = ", ".join(s.name for s in services)

        if appointment.google_calendar_event_id:
            # Update existing event (fire-and-forget)
            from agent.services.gcal_push_service import update_appointment_in_gcal

            asyncio.create_task(
                update_appointment_in_gcal(
                    appointment_id=appointment.id,
                    stylist_id=appointment.stylist_id,
                    event_id=appointment.google_calendar_event_id,
                    customer_name=customer_name,
                    service_names=service_names,
                    start_time=appointment.start_time,
                    duration_minutes=appointment.duration_minutes,
                    status=appointment.status.value,
                )
            )
            logger.info(
                f"Triggered Google Calendar update for appointment {appointment.id}"
            )
        else:
            # Create new event if missing (immediate push)
            from agent.services.gcal_push_service import push_appointment_to_gcal

            try:
                event_id = await push_appointment_to_gcal(
                    appointment_id=appointment.id,
                    stylist_id=appointment.stylist_id,
                    customer_name=customer_name,
                    service_names=service_names,
                    start_time=appointment.start_time,
                    duration_minutes=appointment.duration_minutes,
                    status=appointment.status.value,
                )
                if event_id:
                    appointment.google_calendar_event_id = event_id
                    await session.commit()
                    logger.info(
                        f"Created GCal event {event_id} for appointment {appointment.id}"
                    )
                else:
                    logger.warning(
                        f"GCal push returned None for appointment {appointment.id}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to create GCal event for appointment {appointment.id}: {e}"
                )

        return {
            "id": str(appointment.id),
            "customer_id": str(appointment.customer_id),
            "stylist_id": str(appointment.stylist_id),
            "service_ids": [str(sid) for sid in appointment.service_ids],
            "start_time": appointment.start_time.astimezone(MADRID_TZ).isoformat(),
            "duration_minutes": appointment.duration_minutes,
            "status": appointment.status.value,
            "google_calendar_event_id": appointment.google_calendar_event_id,
            "first_name": appointment.first_name,
            "last_name": appointment.last_name,
            "notes": appointment.notes,
            "created_at": appointment.created_at.isoformat(),
            "updated_at": appointment.updated_at.isoformat(),
        }


@router.delete("/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    appointment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete an appointment."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()

        if not appointment:
            raise HTTPException(status_code=404, detail="Appointment not found")

        # Fire-and-forget: Delete from Google Calendar without blocking
        if appointment.google_calendar_event_id:
            asyncio.create_task(
                _safe_delete_gcal_event(
                    appointment.stylist_id,
                    appointment.google_calendar_event_id
                )
            )

        await session.delete(appointment)
        await session.commit()


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


class AdminAvailabilityRequest(BaseModel):
    """Request schema for admin availability check with date range."""
    service_ids: list[UUID]
    start_date: str  # YYYY-MM-DD format
    end_date: str  # YYYY-MM-DD format
    stylist_id: UUID | None = None  # Optional filter by stylist


# Spanish day names
DAY_NAMES_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


@router.post("/availability/search")
async def search_availability(
    request: AdminAvailabilityRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Search availability for stylists across a date range.

    This endpoint is for admin use only - no 3-day limit restriction.
    Maximum date range: 14 days.

    Process:
    1. Calculate total duration from selected services
    2. Determine service category
    3. Find compatible stylists (by category), optionally filtered by stylist_id
    4. For each day in range, return available slots grouped by stylist

    Args:
        service_ids: List of service UUIDs to book
        start_date: Start date of range (YYYY-MM-DD)
        end_date: End date of range (YYYY-MM-DD)
        stylist_id: Optional UUID to filter by specific stylist

    Returns:
        {
            "start_date": "2025-12-15",
            "end_date": "2025-12-20",
            "total_duration_minutes": 90,
            "service_category": "HAIRDRESSING",
            "days": [
                {
                    "date": "2025-12-16",
                    "day_name": "Martes",
                    "is_closed": false,
                    "holiday": null,
                    "stylists": [
                        {
                            "id": "uuid",
                            "name": "María",
                            "category": "HAIRDRESSING",
                            "slots": [{"time": "10:00", "end_time": "11:30", ...}]
                        }
                    ]
                }
            ]
        }
    """
    from agent.services.availability_service import get_available_slots, is_holiday
    from database.models import ServiceCategory
    from datetime import date as date_type, timedelta
    from shared.business_hours_validator import is_date_closed

    # Parse dates
    try:
        start = date_type.fromisoformat(request.start_date)
        end = date_type.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Use YYYY-MM-DD"
        )

    # Validate date range
    if end < start:
        raise HTTPException(
            status_code=400,
            detail="end_date must be >= start_date"
        )

    days_diff = (end - start).days
    if days_diff > 14:
        raise HTTPException(
            status_code=400,
            detail="Maximum date range is 14 days"
        )

    async with get_async_session() as session:
        # Get services and calculate total duration + category
        services_result = await session.execute(
            select(Service).where(Service.id.in_(request.service_ids))
        )
        services = services_result.scalars().all()

        if len(services) != len(request.service_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more services not found"
            )

        total_duration = sum(s.duration_minutes for s in services)

        # Determine category - if mixed, need "BOTH" stylist
        categories = set(s.category for s in services)
        if ServiceCategory.HAIRDRESSING in categories and ServiceCategory.AESTHETICS in categories:
            required_category = ServiceCategory.BOTH
        elif ServiceCategory.AESTHETICS in categories:
            required_category = ServiceCategory.AESTHETICS
        else:
            required_category = ServiceCategory.HAIRDRESSING

        # Find compatible stylists
        stylists_query = select(Stylist).where(
            Stylist.is_active == True,
        )

        # Filter by specific stylist if provided
        if request.stylist_id:
            stylists_query = stylists_query.where(Stylist.id == request.stylist_id)
        else:
            # Filter by category compatibility
            if required_category == ServiceCategory.BOTH:
                stylists_query = stylists_query.where(
                    Stylist.category == ServiceCategory.BOTH
                )
            elif required_category == ServiceCategory.AESTHETICS:
                stylists_query = stylists_query.where(
                    Stylist.category.in_([ServiceCategory.AESTHETICS, ServiceCategory.BOTH])
                )
            else:  # HAIRDRESSING
                stylists_query = stylists_query.where(
                    Stylist.category.in_([ServiceCategory.HAIRDRESSING, ServiceCategory.BOTH])
                )

        stylists_result = await session.execute(stylists_query)
        compatible_stylists = stylists_result.scalars().all()

        if not compatible_stylists:
            return {
                "start_date": request.start_date,
                "end_date": request.end_date,
                "total_duration_minutes": total_duration,
                "service_category": required_category.value,
                "days": [],
                "message": "No hay estilistas disponibles para estos servicios",
            }

        # Iterate over each day in range
        days_result = []
        current_date = start
        while current_date <= end:
            # Check if holiday
            holiday_name = await is_holiday(current_date)

            # Check if salon is closed
            is_closed = await is_date_closed(current_date)

            day_stylists = []
            if not holiday_name and not is_closed:
                # Get availability for each stylist
                for stylist in compatible_stylists:
                    slots = await get_available_slots(
                        stylist_id=stylist.id,
                        target_date=current_date,
                        service_duration_minutes=total_duration,
                        slot_interval_minutes=15,
                    )

                    day_stylists.append({
                        "id": str(stylist.id),
                        "name": stylist.name,
                        "category": stylist.category.value,
                        "slots": slots,
                    })

            days_result.append({
                "date": current_date.isoformat(),
                "day_name": DAY_NAMES_ES[current_date.weekday()],
                "is_closed": is_closed,
                "holiday": holiday_name,
                "stylists": day_stylists,
            })

            current_date += timedelta(days=1)

        return {
            "start_date": request.start_date,
            "end_date": request.end_date,
            "total_duration_minutes": total_duration,
            "service_category": required_category.value,
            "days": days_result,
        }


# =============================================================================
# Business Hours
# =============================================================================


class UpdateBusinessHoursRequest(BaseModel):
    is_closed: bool | None = None
    start_hour: int | None = Field(None, ge=0, le=23)
    start_minute: int | None = Field(None, ge=0, le=59)
    end_hour: int | None = Field(None, ge=0, le=23)
    end_minute: int | None = Field(None, ge=0, le=59)


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


@router.put("/business-hours/{hours_id}")
async def update_business_hours(
    hours_id: UUID,
    request: UpdateBusinessHoursRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update business hours for a specific day."""
    async with get_async_session() as session:
        result = await session.execute(
            select(BusinessHours).where(BusinessHours.id == hours_id)
        )
        hours = result.scalar_one_or_none()

        if not hours:
            raise HTTPException(status_code=404, detail="Business hours not found")

        # Update fields if provided
        if request.is_closed is not None:
            hours.is_closed = request.is_closed
        if request.start_hour is not None:
            hours.start_hour = request.start_hour
        if request.start_minute is not None:
            hours.start_minute = request.start_minute
        if request.end_hour is not None:
            hours.end_hour = request.end_hour
        if request.end_minute is not None:
            hours.end_minute = request.end_minute

        await session.commit()
        await session.refresh(hours)

        return {
            "id": str(hours.id),
            "day_of_week": hours.day_of_week,
            "is_closed": hours.is_closed,
            "start_hour": hours.start_hour,
            "start_minute": hours.start_minute,
            "end_hour": hours.end_hour,
            "end_minute": hours.end_minute,
        }


# =============================================================================
# Blocking Events CRUD
# =============================================================================


class CreateBlockingEventRequest(BaseModel):
    """Request schema for creating blocking events for one or more stylists."""
    stylist_ids: list[UUID] = Field(..., min_length=1)  # One or more stylists
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    start_time: datetime
    end_time: datetime
    event_type: str = Field(default="general")  # vacation, meeting, break, general

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def ensure_madrid_tz(cls, v):
        return parse_datetime_as_madrid(v)


class UpdateBlockingEventRequest(BaseModel):
    """Request schema for updating a blocking event."""
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    event_type: str | None = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def ensure_madrid_tz(cls, v):
        return parse_datetime_as_madrid(v)


# =============================================================================
# Recurring Blocking Events Schemas
# =============================================================================


class RecurrencePattern(BaseModel):
    """Recurrence pattern definition (RFC 5545 compatible)."""
    frequency: Literal["WEEKLY", "MONTHLY"] = Field(
        default="WEEKLY",
        description="Recurrence frequency"
    )
    interval: int = Field(
        default=1,
        ge=1,
        le=12,
        description="Every N weeks/months"
    )
    days_of_week: list[int] | None = Field(
        default=None,
        description="List of weekdays (0=Monday, 6=Sunday) for WEEKLY frequency"
    )
    days_of_month: list[int] | None = Field(
        default=None,
        description="List of month days (1-31) for MONTHLY frequency"
    )
    count: int = Field(
        ...,
        ge=1,
        le=52,
        description="Number of occurrences to create"
    )


class CreateRecurringBlockingEventRequest(BaseModel):
    """Request schema for creating recurring blocking events."""
    stylist_ids: list[UUID] = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    event_type: str = Field(default="general")
    start_date: date = Field(..., description="First occurrence date (YYYY-MM-DD)")
    start_time: str = Field(..., description="Start time (HH:MM)")
    end_time: str = Field(..., description="End time (HH:MM)")
    recurrence: RecurrencePattern


class ConflictInfo(BaseModel):
    """Information about a scheduling conflict."""
    date: str
    stylist_id: str
    stylist_name: str
    conflict_type: str  # "appointment" or "blocking_event"
    conflict_title: str
    start_time: str
    end_time: str


class RecurringEventPreview(BaseModel):
    """Preview of instances that will be created."""
    total_instances: int
    dates: list[str]
    conflicts: list[ConflictInfo]
    instances_with_conflicts: int


class SeriesEditScope(str, Enum):
    """Scope of edit/delete operation on a recurring series."""
    THIS_ONLY = "this_only"
    THIS_AND_FUTURE = "this_and_future"
    ALL = "all"


class SeriesInfo(BaseModel):
    """Information about a recurring series."""
    series_id: str
    total_instances: int
    instance_index: int
    remaining_instances: int
    frequency: str
    interval: int
    days: str | None  # "MO,WE,FR" or "15,30"


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
    # Ensure timezone for query params (FastAPI doesn't support Pydantic validators on query params)
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=MADRID_TZ)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=MADRID_TZ)

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
                    "start_time": e.start_time.astimezone(MADRID_TZ).isoformat(),
                    "end_time": e.end_time.astimezone(MADRID_TZ).isoformat(),
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
    Create blocking events for one or more stylists.

    This creates events in the database and pushes each to Google Calendar.
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

    created_events = []

    async with get_async_session() as session:
        # Verify all stylists exist
        stylist_result = await session.execute(
            select(Stylist).where(Stylist.id.in_(request.stylist_ids))
        )
        found_stylists = {str(s.id) for s in stylist_result.scalars().all()}
        requested_ids = {str(sid) for sid in request.stylist_ids}

        missing_ids = requested_ids - found_stylists
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Stylists not found: {', '.join(missing_ids)}"
            )

        # Create blocking event for each stylist
        for stylist_id in request.stylist_ids:
            blocking_event = BlockingEvent(
                stylist_id=stylist_id,
                title=request.title,
                description=request.description,
                start_time=request.start_time,
                end_time=request.end_time,
                event_type=event_type_enum,
            )
            session.add(blocking_event)
            created_events.append(blocking_event)

        await session.commit()

        # Refresh all events and push to Google Calendar
        for event in created_events:
            await session.refresh(event)
            await fire_and_forget_push_blocking_event(
                blocking_event_id=event.id,
                stylist_id=event.stylist_id,
                title=event.title,
                description=event.description,
                start_time=event.start_time,
                end_time=event.end_time,
                event_type=event.event_type.value,
            )

        return {
            "created": len(created_events),
            "events": [
                {
                    "id": str(event.id),
                    "stylist_id": str(event.stylist_id),
                    "title": event.title,
                    "description": event.description,
                    "start_time": event.start_time.astimezone(MADRID_TZ).isoformat(),
                    "end_time": event.end_time.astimezone(MADRID_TZ).isoformat(),
                    "event_type": event.event_type.value,
                    "created_at": event.created_at.isoformat(),
                }
                for event in created_events
            ],
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

        # Mark as exception if this event is part of a recurring series
        # (it's now different from the series template)
        if event.recurring_series_id:
            event.is_exception = True

        await session.commit()
        await session.refresh(event)

        # Sync with Google Calendar if event exists
        if event.google_calendar_event_id:
            from agent.services.gcal_push_service import update_blocking_event_in_gcal

            # Fire-and-forget update to Google Calendar
            asyncio.create_task(
                update_blocking_event_in_gcal(
                    blocking_event_id=event.id,
                    stylist_id=event.stylist_id,
                    event_id=event.google_calendar_event_id,
                    title=event.title,
                    description=event.description,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    event_type=event.event_type.value,
                )
            )
            logger.info(
                f"Triggered Google Calendar update for blocking event {event.id}"
            )

        return {
            "id": str(event.id),
            "stylist_id": str(event.stylist_id),
            "title": event.title,
            "description": event.description,
            "start_time": event.start_time.astimezone(MADRID_TZ).isoformat(),
            "end_time": event.end_time.astimezone(MADRID_TZ).isoformat(),
            "event_type": event.event_type.value,
        }


@router.delete("/blocking-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
):
    """Delete a blocking event."""
    async with get_async_session() as session:
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        # Fire-and-forget: Delete from Google Calendar without blocking
        if event.google_calendar_event_id:
            asyncio.create_task(
                _safe_delete_gcal_event(event.stylist_id, event.google_calendar_event_id)
            )

        await session.delete(event)
        await session.commit()


# =============================================================================
# Recurring Blocking Events Endpoints
# =============================================================================


@router.get("/business-hours/summary")
async def get_business_hours_summary_endpoint(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Get business hours summary for all days of the week.

    Returns:
        Dict mapping day_of_week (0=Monday, 6=Sunday) to:
        - {"open": "HH:MM", "close": "HH:MM"} if open
        - null if closed
    """
    return await get_business_hours_summary()


@router.get("/blocking-events/remaining-week")
async def get_remaining_week_days_endpoint(
    current_user: Annotated[dict, Depends(get_current_user)],
    from_date: date,
):
    """
    Get the remaining days of the week from a given date.
    Only includes days when the salon is open.

    Args:
        from_date: Start date (YYYY-MM-DD)

    Returns:
        List of available days with date, day_of_week (0=Mon), and name
    """
    business_hours = await get_business_hours_summary()
    remaining = await get_remaining_week_days(from_date, business_hours)

    return {
        "from_date": from_date.isoformat(),
        "days": [
            {
                "date": d["date"].isoformat(),
                "day_of_week": d["day_of_week"],
                "name": d["name"],
            }
            for d in remaining
        ],
    }


@router.post("/blocking-events/recurring/preview")
async def preview_recurring_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    request: CreateRecurringBlockingEventRequest,
):
    """
    Preview what instances will be created and detect conflicts.

    Returns dates for all occurrences and any conflicts with
    existing appointments or blocking events.
    """
    # Parse times
    try:
        start_time = dt_time.fromisoformat(request.start_time)
        end_time = dt_time.fromisoformat(request.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {e}")

    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    # Validate event type
    valid_types = ["vacation", "meeting", "break", "general", "personal"]
    if request.event_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_types}"
        )

    # Expand recurrence to get all dates
    dates = expand_recurrence(
        start_date=request.start_date,
        frequency=request.recurrence.frequency,
        interval=request.recurrence.interval,
        days_of_week=request.recurrence.days_of_week,
        days_of_month=request.recurrence.days_of_month,
        count=request.recurrence.count,
    )

    # Check conflicts for each stylist
    all_conflicts: list[dict] = []
    async with get_async_session() as session:
        for stylist_id in request.stylist_ids:
            conflicts = await check_conflicts_for_dates(
                stylist_id=stylist_id,
                dates=dates,
                start_time=start_time,
                end_time=end_time,
                session=session,
            )
            all_conflicts.extend(conflicts)

    # Count unique dates with conflicts
    dates_with_conflicts = set(c["date"] for c in all_conflicts)

    return RecurringEventPreview(
        total_instances=len(dates) * len(request.stylist_ids),
        dates=[d.isoformat() for d in dates],
        conflicts=[ConflictInfo(**c) for c in all_conflicts],
        instances_with_conflicts=len(dates_with_conflicts),
    )


@router.post("/blocking-events/recurring", status_code=status.HTTP_201_CREATED)
async def create_recurring_blocking_event(
    current_user: Annotated[dict, Depends(get_current_user)],
    request: CreateRecurringBlockingEventRequest,
    ignore_conflicts: bool = False,
):
    """
    Create recurring blocking events.

    Creates a RecurringBlockingSeries and individual BlockingEvent instances.
    Optionally ignores conflicts if ignore_conflicts=true.
    """
    from agent.services.gcal_push_service import fire_and_forget_push_blocking_event

    # Parse times
    try:
        start_time = dt_time.fromisoformat(request.start_time)
        end_time = dt_time.fromisoformat(request.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {e}")

    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    # Validate event type
    valid_types = ["vacation", "meeting", "break", "general", "personal"]
    if request.event_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of: {valid_types}"
        )

    # Expand recurrence to get all dates
    dates = expand_recurrence(
        start_date=request.start_date,
        frequency=request.recurrence.frequency,
        interval=request.recurrence.interval,
        days_of_week=request.recurrence.days_of_week,
        days_of_month=request.recurrence.days_of_month,
        count=request.recurrence.count,
    )

    if not dates:
        raise HTTPException(status_code=400, detail="No dates generated from recurrence pattern")

    created_series: list[dict] = []
    created_events: list[dict] = []

    async with get_async_session() as session:
        # Verify all stylists exist
        for stylist_id in request.stylist_ids:
            result = await session.execute(
                select(Stylist).where(Stylist.id == stylist_id)
            )
            if not result.scalar_one_or_none():
                raise HTTPException(
                    status_code=404,
                    detail=f"Stylist {stylist_id} not found"
                )

        # Create one series per stylist
        for stylist_id in request.stylist_ids:
            # Format days for storage
            byday = None
            bymonthday = None
            if request.recurrence.frequency == "WEEKLY" and request.recurrence.days_of_week:
                byday = format_byday(request.recurrence.days_of_week)
            elif request.recurrence.frequency == "MONTHLY" and request.recurrence.days_of_month:
                bymonthday = format_bymonthday(request.recurrence.days_of_month)

            # Create the series
            series = RecurringBlockingSeries(
                stylist_id=stylist_id,
                title=request.title,
                description=request.description,
                event_type=BlockingEventType(request.event_type),
                start_time_of_day=start_time,
                end_time_of_day=end_time,
                rrule_frequency=RecurrenceFrequency(request.recurrence.frequency),
                rrule_interval=request.recurrence.interval,
                rrule_byday=byday,
                rrule_bymonthday=bymonthday,
                rrule_count=request.recurrence.count,
                original_start_date=request.start_date,
                instances_created=len(dates),
            )
            session.add(series)
            await session.flush()  # Get series.id

            created_series.append({
                "series_id": str(series.id),
                "stylist_id": str(stylist_id),
            })

            # Create individual blocking events
            for idx, event_date in enumerate(dates, start=1):
                start_dt = datetime.combine(event_date, start_time, tzinfo=MADRID_TZ)
                end_dt = datetime.combine(event_date, end_time, tzinfo=MADRID_TZ)

                event = BlockingEvent(
                    stylist_id=stylist_id,
                    title=request.title,
                    description=request.description,
                    start_time=start_dt,
                    end_time=end_dt,
                    event_type=BlockingEventType(request.event_type),
                    recurring_series_id=series.id,
                    occurrence_index=idx,
                    is_exception=False,
                )
                session.add(event)
                await session.flush()

                created_events.append({
                    "id": str(event.id),
                    "stylist_id": str(stylist_id),
                    "title": event.title,
                    "start_time": start_dt.isoformat(),
                    "end_time": end_dt.isoformat(),
                    "event_type": event.event_type.value,
                    "series_id": str(series.id),
                    "occurrence_index": idx,
                })

        await session.commit()

        # Fire-and-forget: Push all events to Google Calendar
        for event_data in created_events:
            asyncio.create_task(
                fire_and_forget_push_blocking_event(
                    blocking_event_id=UUID(event_data["id"]),
                    stylist_id=UUID(event_data["stylist_id"]),
                    title=event_data["title"],
                    description=request.description,
                    start_time=datetime.fromisoformat(event_data["start_time"]),
                    end_time=datetime.fromisoformat(event_data["end_time"]),
                    event_type=event_data["event_type"],
                )
            )

    return {
        "created_series": len(created_series),
        "created_events": len(created_events),
        "series": created_series,
        "events": created_events,
    }


@router.get("/blocking-events/{event_id}/series")
async def get_blocking_event_series(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
):
    """
    Get series information if the event belongs to a recurring series.

    Returns None if the event is not part of a series.
    """
    async with get_async_session() as session:
        # Get the event with its series
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        if not event.recurring_series_id:
            return None  # Not part of a series

        # Get series info
        series_result = await session.execute(
            select(RecurringBlockingSeries).where(
                RecurringBlockingSeries.id == event.recurring_series_id
            )
        )
        series = series_result.scalar_one_or_none()

        if not series:
            return None

        # Count remaining instances (including this one)
        count_result = await session.execute(
            select(func.count(BlockingEvent.id)).where(
                and_(
                    BlockingEvent.recurring_series_id == series.id,
                    BlockingEvent.occurrence_index >= event.occurrence_index,
                )
            )
        )
        remaining = count_result.scalar() or 0

        return SeriesInfo(
            series_id=str(series.id),
            total_instances=series.instances_created,
            instance_index=event.occurrence_index or 0,
            remaining_instances=remaining,
            frequency=series.rrule_frequency.value,
            interval=series.rrule_interval,
            days=series.rrule_byday or series.rrule_bymonthday,
        )


@router.get("/blocking-events/{event_id}/series/exceptions")
async def check_series_exceptions(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
    scope: SeriesEditScope = SeriesEditScope.ALL,
):
    """
    Check for exceptions (previously modified instances) in a series scope.

    Returns information about which instances have been modified individually
    so the frontend can warn the user before bulk updates.
    """
    async with get_async_session() as session:
        # Get the event
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        if not event.recurring_series_id:
            return {
                "has_exceptions": False,
                "exception_count": 0,
                "exceptions": [],
            }

        # Build query based on scope
        if scope == SeriesEditScope.THIS_AND_FUTURE:
            query = select(BlockingEvent).where(
                and_(
                    BlockingEvent.recurring_series_id == event.recurring_series_id,
                    BlockingEvent.occurrence_index >= event.occurrence_index,
                    BlockingEvent.is_exception == True,
                )
            )
        else:  # ALL
            query = select(BlockingEvent).where(
                and_(
                    BlockingEvent.recurring_series_id == event.recurring_series_id,
                    BlockingEvent.is_exception == True,
                )
            )

        result = await session.execute(query)
        exceptions = list(result.scalars().all())

        return {
            "has_exceptions": len(exceptions) > 0,
            "exception_count": len(exceptions),
            "exceptions": [
                {
                    "id": str(exc.id),
                    "title": exc.title,
                    "start_time": exc.start_time.astimezone(MADRID_TZ).isoformat(),
                    "occurrence_index": exc.occurrence_index,
                }
                for exc in exceptions
            ],
        }


@router.put("/blocking-events/{event_id}/series")
async def update_blocking_event_with_scope(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
    request: UpdateBlockingEventRequest,
    scope: SeriesEditScope = SeriesEditScope.THIS_ONLY,
    overwrite_exceptions: bool = False,
):
    """
    Update blocking event(s) with series awareness.

    Scope options:
    - this_only: Update only this instance (marks as exception)
    - this_and_future: Update this and all future instances
    - all: Update entire series

    When overwrite_exceptions is True, previously modified instances will be
    updated and their is_exception flag reset. When False, they are skipped.
    """
    async with get_async_session() as session:
        # Get the clicked event
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        # For non-series events or this_only scope, just update single event
        if not event.recurring_series_id or scope == SeriesEditScope.THIS_ONLY:
            # Apply updates
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

            # Validate times
            if event.end_time <= event.start_time:
                raise HTTPException(
                    status_code=400,
                    detail="end_time must be after start_time"
                )

            # Mark as exception since it differs from series
            if event.recurring_series_id:
                event.is_exception = True

            await session.commit()
            await session.refresh(event)

            # Fire-and-forget GCal update
            if event.google_calendar_event_id:
                from agent.services.gcal_push_service import update_blocking_event_in_gcal
                asyncio.create_task(
                    update_blocking_event_in_gcal(
                        blocking_event_id=event.id,
                        stylist_id=event.stylist_id,
                        event_id=event.google_calendar_event_id,
                        title=event.title,
                        description=event.description,
                        start_time=event.start_time,
                        end_time=event.end_time,
                        event_type=event.event_type.value,
                    )
                )

            return {
                "updated_count": 1,
                "skipped_exceptions": 0,
                "events": [{
                    "id": str(event.id),
                    "title": event.title,
                    "start_time": event.start_time.astimezone(MADRID_TZ).isoformat(),
                    "end_time": event.end_time.astimezone(MADRID_TZ).isoformat(),
                }],
            }

        # For series-aware updates, get affected events
        if scope == SeriesEditScope.THIS_AND_FUTURE:
            query = select(BlockingEvent).where(
                and_(
                    BlockingEvent.recurring_series_id == event.recurring_series_id,
                    BlockingEvent.occurrence_index >= event.occurrence_index,
                )
            ).order_by(BlockingEvent.occurrence_index)
        else:  # ALL
            query = select(BlockingEvent).where(
                BlockingEvent.recurring_series_id == event.recurring_series_id
            ).order_by(BlockingEvent.occurrence_index)

        result = await session.execute(query)
        affected_events = list(result.scalars().all())

        # Calculate time deltas based on the clicked event
        start_delta = None
        end_delta = None
        if request.start_time is not None:
            original_start = event.start_time.astimezone(MADRID_TZ)
            new_start = request.start_time.astimezone(MADRID_TZ)
            start_delta = new_start - original_start

        if request.end_time is not None:
            original_end = event.end_time.astimezone(MADRID_TZ)
            new_end = request.end_time.astimezone(MADRID_TZ)
            end_delta = new_end - original_end

        # Apply updates
        updated_events = []
        skipped_count = 0

        for evt in affected_events:
            # Skip exceptions if not overwriting
            if evt.is_exception and not overwrite_exceptions:
                skipped_count += 1
                continue

            # Apply field updates
            if request.title is not None:
                evt.title = request.title
            if request.description is not None:
                evt.description = request.description
            if request.event_type is not None:
                try:
                    evt.event_type = BlockingEventType(request.event_type)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid event_type: {request.event_type}"
                    )

            # Apply time deltas (preserves each event's date but changes time)
            if start_delta is not None:
                evt.start_time = evt.start_time + start_delta
            if end_delta is not None:
                evt.end_time = evt.end_time + end_delta

            # Validate times
            if evt.end_time <= evt.start_time:
                raise HTTPException(
                    status_code=400,
                    detail=f"end_time must be after start_time for event on {evt.start_time.date()}"
                )

            # Reset exception flag since it now matches the update
            evt.is_exception = False

            updated_events.append(evt)

        await session.commit()

        # Fire-and-forget GCal updates for all updated events
        from agent.services.gcal_push_service import update_blocking_event_in_gcal
        for evt in updated_events:
            if evt.google_calendar_event_id:
                asyncio.create_task(
                    update_blocking_event_in_gcal(
                        blocking_event_id=evt.id,
                        stylist_id=evt.stylist_id,
                        event_id=evt.google_calendar_event_id,
                        title=evt.title,
                        description=evt.description,
                        start_time=evt.start_time,
                        end_time=evt.end_time,
                        event_type=evt.event_type.value,
                    )
                )

        # Update series template if scope is ALL
        if scope == SeriesEditScope.ALL:
            series_result = await session.execute(
                select(RecurringBlockingSeries).where(
                    RecurringBlockingSeries.id == event.recurring_series_id
                )
            )
            series = series_result.scalar_one_or_none()
            if series:
                if request.title is not None:
                    series.title = request.title
                if request.event_type is not None:
                    try:
                        series.event_type = BlockingEventType(request.event_type)
                    except ValueError:
                        pass  # Already validated above
                # Note: We don't update series time templates as each instance
                # may be on different dates. The time delta approach handles this.
                await session.commit()

        return {
            "updated_count": len(updated_events),
            "skipped_exceptions": skipped_count,
            "events": [
                {
                    "id": str(evt.id),
                    "title": evt.title,
                    "start_time": evt.start_time.astimezone(MADRID_TZ).isoformat(),
                    "end_time": evt.end_time.astimezone(MADRID_TZ).isoformat(),
                }
                for evt in updated_events
            ],
        }


@router.delete("/blocking-events/{event_id}/series", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocking_event_with_scope(
    current_user: Annotated[dict, Depends(get_current_user)],
    event_id: UUID,
    scope: SeriesEditScope = SeriesEditScope.THIS_ONLY,
):
    """
    Delete blocking event(s) with series awareness.

    Scope options:
    - this_only: Delete only this instance
    - this_and_future: Delete this and all future instances
    - all: Delete entire series
    """
    logger.info(f"Delete blocking event with scope: {scope}, event_id: {event_id}")

    async with get_async_session() as session:
        # Get the event
        result = await session.execute(
            select(BlockingEvent).where(BlockingEvent.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            raise HTTPException(status_code=404, detail="Blocking event not found")

        logger.info(
            f"Event found: recurring_series_id={event.recurring_series_id}, "
            f"occurrence_index={event.occurrence_index}, start_time={event.start_time}"
        )

        events_to_delete: list[BlockingEvent] = []

        if not event.recurring_series_id or scope == SeriesEditScope.THIS_ONLY:
            # Single event or not part of series
            events_to_delete = [event]
        elif scope == SeriesEditScope.THIS_AND_FUTURE:
            # Delete this and all future instances
            # Handle NULL occurrence_index by using start_time comparison as fallback
            if event.occurrence_index is not None:
                result = await session.execute(
                    select(BlockingEvent).where(
                        and_(
                            BlockingEvent.recurring_series_id == event.recurring_series_id,
                            BlockingEvent.occurrence_index >= event.occurrence_index,
                        )
                    )
                )
            else:
                # Fallback: use start_time comparison if occurrence_index is NULL
                result = await session.execute(
                    select(BlockingEvent).where(
                        and_(
                            BlockingEvent.recurring_series_id == event.recurring_series_id,
                            BlockingEvent.start_time >= event.start_time,
                        )
                    )
                )
            events_to_delete = list(result.scalars().all())
        elif scope == SeriesEditScope.ALL:
            # Delete entire series
            result = await session.execute(
                select(BlockingEvent).where(
                    BlockingEvent.recurring_series_id == event.recurring_series_id
                )
            )
            events_to_delete = list(result.scalars().all())

            # Also delete the series itself
            series_result = await session.execute(
                select(RecurringBlockingSeries).where(
                    RecurringBlockingSeries.id == event.recurring_series_id
                )
            )
            series = series_result.scalar_one_or_none()
            if series:
                await session.delete(series)

        logger.info(f"Events to delete count: {len(events_to_delete)}")

        # Fire-and-forget: Delete from Google Calendar
        for evt in events_to_delete:
            if evt.google_calendar_event_id:
                asyncio.create_task(
                    _safe_delete_gcal_event(evt.stylist_id, evt.google_calendar_event_id)
                )
            await session.delete(evt)

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

    # Default color palette (fallback for stylists without custom color)
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

    # Parse stylist_ids if provided
    if stylist_ids:
        try:
            stylist_uuid_list = [UUID(sid.strip()) for sid in stylist_ids.split(",")]
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stylist_ids format: {e}"
            )
        # Load stylists with their colors
        async with get_async_session() as session:
            result = await session.execute(
                select(Stylist.id, Stylist.color).where(Stylist.id.in_(stylist_uuid_list))
            )
            stylist_colors_db = {str(row[0]): row[1] for row in result.all()}
    else:
        # Get all active stylists with their colors
        async with get_async_session() as session:
            result = await session.execute(
                select(Stylist.id, Stylist.color).where(Stylist.is_active == True)
            )
            rows = result.all()
            stylist_uuid_list = [row[0] for row in rows]
            stylist_colors_db = {str(row[0]): row[1] for row in rows}

    # Get events from DB
    events = await get_calendar_events_for_range(
        stylist_ids=stylist_uuid_list,
        start_time=start,
        end_time=end,
    )

    # Assign colors: use stored color if available, fallback to palette
    stylist_color_map = {}
    for i, sid in enumerate(stylist_uuid_list):
        sid_str = str(sid)
        db_color = stylist_colors_db.get(sid_str)
        stylist_color_map[sid_str] = db_color if db_color else STYLIST_COLORS[i % len(STYLIST_COLORS)]

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


# =============================================================================
# Conversation History (Read-only)
# =============================================================================


@router.get("/conversations")
async def list_conversations(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 50,
    customer_id: UUID | None = None,
):
    """
    List conversation history (read-only).

    Aggregates individual messages from conversation_history table
    into grouped conversations by conversation_id.
    """
    try:
        async with get_async_session() as session:
            # Subquery to aggregate messages by conversation_id
            subquery = (
                select(
                    ConversationHistory.conversation_id.label("id"),
                    func.array_agg(ConversationHistory.customer_id)[1].label("customer_id"),
                    func.min(ConversationHistory.timestamp).label("started_at"),
                    func.max(ConversationHistory.timestamp).label("ended_at"),
                    func.count().label("message_count"),
                    func.json_agg(
                        func.json_build_object(
                            "role", ConversationHistory.message_role,
                            "content", ConversationHistory.message_content,
                            "timestamp", ConversationHistory.timestamp,
                        ).cast(JSONB)
                    ).label("messages"),
                )
                .group_by(ConversationHistory.conversation_id)
            )

            # Apply customer_id filter if provided
            if customer_id:
                subquery = subquery.where(ConversationHistory.customer_id == customer_id)

            # Create CTE for pagination
            cte = subquery.cte("conversations_grouped")

            # Main query with pagination
            query = (
                select(cte)
                .order_by(cte.c.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size + 1)
            )

            result = await session.execute(query)
            rows = result.all()

            has_more = len(rows) > page_size
            items = rows[:page_size]

            # Helper to extract summary from SYSTEM message
            def extract_summary(messages: list | None) -> str | None:
                if not messages:
                    return None
                for msg in messages:
                    if msg.get("role") == "system":
                        return msg.get("content")
                return None

            return {
                "items": [
                    {
                        "id": str(row.id),
                        "customer_id": str(row.customer_id) if row.customer_id else None,
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                        "message_count": row.message_count or 0,
                        "messages": row.messages if row.messages else [],
                        "summary": extract_summary(row.messages),
                        "created_at": row.started_at.isoformat() if row.started_at else None,
                    }
                    for row in items
                ],
                "total": len(items),
                "page": page,
                "page_size": page_size,
                "has_more": has_more,
            }
    except Exception as e:
        logger.error(f"Error listing conversations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve conversations: {str(e)}"
        )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Get a single conversation by ID."""
    from database.models import ConversationHistory

    async with get_async_session() as session:
        result = await session.execute(
            select(ConversationHistory).where(ConversationHistory.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return {
            "id": str(conversation.id),
            "customer_id": str(conversation.customer_id),
            "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
            "ended_at": conversation.ended_at.isoformat() if conversation.ended_at else None,
            "message_count": conversation.message_count,
            "messages": conversation.messages,
            "summary": conversation.summary,
            "created_at": conversation.created_at.isoformat(),
        }


# =============================================================================
# Global Search Endpoint
# =============================================================================


@router.get("/search", response_model=GlobalSearchResponse)
async def global_search(
    current_user: Annotated[dict, Depends(get_current_user)],
    q: str = "",
    limit: int = 5,
):
    """
    Global search across all entities.

    Searches:
    - Customers: phone, first_name, last_name
    - Appointments: first_name, last_name, notes (last 90 days)
    - Services: name
    - Stylists: name

    Returns top N results per category, grouped by type.
    """
    if not q or len(q) < 2:
        return GlobalSearchResponse(
            customers=[], appointments=[], services=[], stylists=[], total=0
        )

    search_pattern = f"%{q}%"
    results = GlobalSearchResponse(
        customers=[], appointments=[], services=[], stylists=[], total=0
    )

    async with get_async_session() as session:
        # Search Customers
        customers_query = select(Customer).where(
            (Customer.phone.ilike(search_pattern))
            | (Customer.first_name.ilike(search_pattern))
            | (Customer.last_name.ilike(search_pattern))
        ).limit(limit)

        customers_result = await session.execute(customers_query)
        for c in customers_result.scalars().all():
            results.customers.append(SearchResultItem(
                id=str(c.id),
                type="customer",
                title=f"{c.first_name} {c.last_name or ''}".strip(),
                subtitle=c.phone,
                url=f"/customers?highlight={c.id}",
            ))

        # Search Appointments (recent 90 days)
        ninety_days_ago = datetime.utcnow() - timedelta(days=90)
        appointments_query = (
            select(Appointment)
            .where(
                Appointment.start_time >= ninety_days_ago,
                (Appointment.first_name.ilike(search_pattern))
                | (Appointment.last_name.ilike(search_pattern))
                | (Appointment.notes.ilike(search_pattern))
            )
            .order_by(Appointment.start_time.desc())
            .limit(limit)
        )

        appointments_result = await session.execute(appointments_query)
        for a in appointments_result.scalars().all():
            results.appointments.append(SearchResultItem(
                id=str(a.id),
                type="appointment",
                title=f"{a.first_name} {a.last_name or ''}".strip(),
                subtitle=a.start_time.strftime("%d/%m/%Y %H:%M"),
                url=f"/appointments?highlight={a.id}",
            ))

        # Search Services
        services_query = (
            select(Service)
            .where(
                Service.is_active == True,
                Service.name.ilike(search_pattern)
            )
            .limit(limit)
        )

        services_result = await session.execute(services_query)
        for s in services_result.scalars().all():
            results.services.append(SearchResultItem(
                id=str(s.id),
                type="service",
                title=s.name,
                subtitle=f"{s.duration_minutes} min - {s.category.value}",
                url=f"/services?highlight={s.id}",
            ))

        # Search Stylists
        stylists_query = (
            select(Stylist)
            .where(
                Stylist.is_active == True,
                Stylist.name.ilike(search_pattern)
            )
            .limit(limit)
        )

        stylists_result = await session.execute(stylists_query)
        for st in stylists_result.scalars().all():
            results.stylists.append(SearchResultItem(
                id=str(st.id),
                type="stylist",
                title=st.name,
                subtitle=st.category.value,
                url=f"/stylists?highlight={st.id}",
            ))

        results.total = (
            len(results.customers) + len(results.appointments) +
            len(results.services) + len(results.stylists)
        )

        return results


# =============================================================================
# Notifications Endpoints
# =============================================================================


async def create_notification(
    session: AsyncSession,
    notification_type: NotificationType,
    appointment: Appointment,
) -> None:
    """Create a notification for appointment events."""
    titles = {
        NotificationType.APPOINTMENT_CREATED: "Nueva cita",
        NotificationType.APPOINTMENT_CANCELLED: "Cita cancelada",
        NotificationType.APPOINTMENT_CONFIRMED: "Cita confirmada",
        NotificationType.APPOINTMENT_COMPLETED: "Cita completada",
    }

    customer_name = f"{appointment.first_name} {appointment.last_name or ''}".strip()
    date_str = appointment.start_time.strftime("%d/%m/%Y %H:%M")

    messages = {
        NotificationType.APPOINTMENT_CREATED: f"{customer_name} ha reservado una cita para el {date_str}",
        NotificationType.APPOINTMENT_CANCELLED: f"La cita de {customer_name} del {date_str} ha sido cancelada",
        NotificationType.APPOINTMENT_CONFIRMED: f"{customer_name} ha confirmado su cita del {date_str}",
        NotificationType.APPOINTMENT_COMPLETED: f"La cita de {customer_name} del {date_str} ha sido completada",
    }

    notification = Notification(
        type=notification_type,
        title=titles[notification_type],
        message=messages[notification_type],
        entity_type="appointment",
        entity_id=appointment.id,
    )
    session.add(notification)


@router.get("/notifications", response_model=NotificationsListResponse)
async def list_notifications(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
    include_read: bool = False,
):
    """
    List notifications for the admin panel.

    Returns notifications sorted by created_at DESC (newest first).
    Unread notifications are returned first by default.
    """
    async with get_async_session() as session:
        # Base query
        query = select(Notification).order_by(
            Notification.is_read.asc(),  # Unread first
            Notification.created_at.desc()
        )

        if not include_read:
            query = query.where(Notification.is_read == False)

        query = query.limit(limit)

        result = await session.execute(query)
        notifications = result.scalars().all()

        # Get unread count
        unread_query = select(func.count(Notification.id)).where(
            Notification.is_read == False
        )
        unread_result = await session.execute(unread_query)
        unread_count = unread_result.scalar() or 0

        return NotificationsListResponse(
            items=[
                NotificationResponse(
                    id=str(n.id),
                    type=n.type.value,
                    title=n.title,
                    message=n.message,
                    entity_type=n.entity_type,
                    entity_id=str(n.entity_id) if n.entity_id else None,
                    is_read=n.is_read,
                    is_starred=n.is_starred,
                    created_at=n.created_at,
                    read_at=n.read_at,
                    starred_at=n.starred_at,
                )
                for n in notifications
            ],
            unread_count=unread_count,
            total=len(notifications),
        )


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Mark a single notification as read."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        notification.is_read = True
        notification.read_at = datetime.utcnow()
        await session.commit()

        return {"success": True}


@router.put("/notifications/mark-all-read")
async def mark_all_notifications_read(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Mark all unread notifications as read."""
    from sqlalchemy import update

    async with get_async_session() as session:
        await session.execute(
            update(Notification)
            .where(Notification.is_read == False)
            .values(is_read=True, read_at=datetime.utcnow())
        )
        await session.commit()

        return {"success": True}


@router.get("/notifications/paginated", response_model=NotificationsPaginatedResponse)
async def list_notifications_paginated(
    current_user: Annotated[dict, Depends(get_current_user)],
    page: int = 1,
    page_size: int = 20,
    types: str | None = None,
    category: str | None = None,
    is_read: bool | None = None,
    is_starred: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """
    List notifications with full pagination and filter support.

    Args:
        page: Page number (1-indexed)
        page_size: Items per page (max 100)
        types: Comma-separated list of notification types
        category: Category filter (citas, confirmaciones, escalaciones)
        is_read: Filter by read status
        is_starred: Filter by starred status
        date_from: Filter from date
        date_to: Filter to date
        search: Search in title and message
        sort_by: Sort field (created_at, type)
        sort_order: Sort order (asc, desc)
    """
    from sqlalchemy import or_, and_, cast, Date

    async with get_async_session() as session:
        # Validate page_size
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size

        # Build base query
        query = select(Notification)

        # Apply filters
        conditions = []

        # Type filter (comma-separated list)
        if types:
            type_list = [t.strip() for t in types.split(",")]
            conditions.append(Notification.type.in_(type_list))

        # Category filter
        if category and category in NOTIFICATION_CATEGORIES:
            category_types = NOTIFICATION_CATEGORIES[category]
            conditions.append(Notification.type.in_(category_types))

        # Read status filter
        if is_read is not None:
            conditions.append(Notification.is_read == is_read)

        # Starred filter
        if is_starred is not None:
            conditions.append(Notification.is_starred == is_starred)

        # Date range filter
        if date_from:
            conditions.append(cast(Notification.created_at, Date) >= date_from)
        if date_to:
            conditions.append(cast(Notification.created_at, Date) <= date_to)

        # Search filter
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Notification.title.ilike(search_term),
                    Notification.message.ilike(search_term),
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        # Get total count before pagination
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        if sort_by == "type":
            sort_column = Notification.type
        else:
            sort_column = Notification.created_at

        if sort_order == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        query = query.offset(offset).limit(page_size)

        result = await session.execute(query)
        notifications = result.scalars().all()

        # Get unread count (global)
        unread_query = select(func.count(Notification.id)).where(
            Notification.is_read == False
        )
        unread_result = await session.execute(unread_query)
        unread_count = unread_result.scalar() or 0

        # Get starred count (global)
        starred_query = select(func.count(Notification.id)).where(
            Notification.is_starred == True
        )
        starred_result = await session.execute(starred_query)
        starred_count = starred_result.scalar() or 0

        return NotificationsPaginatedResponse(
            items=[
                NotificationResponse(
                    id=str(n.id),
                    type=n.type.value,
                    title=n.title,
                    message=n.message,
                    entity_type=n.entity_type,
                    entity_id=str(n.entity_id) if n.entity_id else None,
                    is_read=n.is_read,
                    is_starred=n.is_starred,
                    created_at=n.created_at,
                    read_at=n.read_at,
                    starred_at=n.starred_at,
                )
                for n in notifications
            ],
            total=total,
            page=page,
            page_size=page_size,
            has_more=(offset + len(notifications)) < total,
            unread_count=unread_count,
            starred_count=starred_count,
        )


@router.get("/notifications/stats", response_model=NotificationStatsResponse)
async def get_notification_stats(
    current_user: Annotated[dict, Depends(get_current_user)],
    days: int = 30,
):
    """
    Get notification statistics for charts.

    Args:
        days: Number of days for trend data (default 30)
    """
    from sqlalchemy import cast, Date
    from datetime import timedelta

    async with get_async_session() as session:
        # Count by type
        type_query = select(
            Notification.type,
            func.count(Notification.id)
        ).group_by(Notification.type)
        type_result = await session.execute(type_query)
        by_type = {row[0].value: row[1] for row in type_result.fetchall()}

        # Count by category
        by_category = {}
        for category_name, types in NOTIFICATION_CATEGORIES.items():
            count = sum(by_type.get(t, 0) for t in types)
            by_category[category_name] = count

        # Trend data (last N days)
        start_date = datetime.utcnow() - timedelta(days=days)
        trend_query = select(
            cast(Notification.created_at, Date).label("date"),
            func.count(Notification.id).label("count")
        ).where(
            Notification.created_at >= start_date
        ).group_by(
            cast(Notification.created_at, Date)
        ).order_by(
            cast(Notification.created_at, Date)
        )
        trend_result = await session.execute(trend_query)
        trend = [
            {"date": str(row.date), "count": row.count}
            for row in trend_result.fetchall()
        ]

        # Total count
        total_query = select(func.count(Notification.id))
        total_result = await session.execute(total_query)
        total = total_result.scalar() or 0

        # Unread count
        unread_query = select(func.count(Notification.id)).where(
            Notification.is_read == False
        )
        unread_result = await session.execute(unread_query)
        unread = unread_result.scalar() or 0

        # Starred count
        starred_query = select(func.count(Notification.id)).where(
            Notification.is_starred == True
        )
        starred_result = await session.execute(starred_query)
        starred = starred_result.scalar() or 0

        return NotificationStatsResponse(
            by_type=by_type,
            by_category=by_category,
            trend=trend,
            total=total,
            unread=unread,
            starred=starred,
        )


@router.put("/notifications/{notification_id}/star")
async def toggle_notification_star(
    notification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Toggle starred status of a notification."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        notification.is_starred = not notification.is_starred
        notification.starred_at = datetime.utcnow() if notification.is_starred else None
        await session.commit()

        return {
            "success": True,
            "is_starred": notification.is_starred,
            "starred_at": notification.starred_at.isoformat() if notification.starred_at else None,
        }


@router.put("/notifications/{notification_id}/unread")
async def mark_notification_unread(
    notification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Mark a notification as unread."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        notification.is_read = False
        notification.read_at = None
        await session.commit()

        return {"success": True}


@router.delete("/notifications/bulk")
async def bulk_delete_notifications(
    request: NotificationBulkRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete multiple notifications."""
    from sqlalchemy import delete as sql_delete

    async with get_async_session() as session:
        result = await session.execute(
            sql_delete(Notification).where(Notification.id.in_(request.ids))
        )
        await session.commit()

        return {"success": True, "deleted": result.rowcount}


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a single notification."""
    from sqlalchemy import delete as sql_delete

    async with get_async_session() as session:
        result = await session.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        await session.execute(
            sql_delete(Notification).where(Notification.id == notification_id)
        )
        await session.commit()

        return {"success": True}


@router.get("/notifications/export")
async def export_notifications(
    current_user: Annotated[dict, Depends(get_current_user)],
    types: str | None = None,
    category: str | None = None,
    is_read: bool | None = None,
    is_starred: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
):
    """
    Export notifications as CSV.

    Applies same filters as the paginated list endpoint.
    """
    from fastapi.responses import StreamingResponse
    from sqlalchemy import or_, and_, cast, Date
    import csv
    import io

    async with get_async_session() as session:
        # Build query with same filters as paginated endpoint
        query = select(Notification)

        conditions = []

        if types:
            type_list = [t.strip() for t in types.split(",")]
            conditions.append(Notification.type.in_(type_list))

        if category and category in NOTIFICATION_CATEGORIES:
            category_types = NOTIFICATION_CATEGORIES[category]
            conditions.append(Notification.type.in_(category_types))

        if is_read is not None:
            conditions.append(Notification.is_read == is_read)

        if is_starred is not None:
            conditions.append(Notification.is_starred == is_starred)

        if date_from:
            conditions.append(cast(Notification.created_at, Date) >= date_from)
        if date_to:
            conditions.append(cast(Notification.created_at, Date) <= date_to)

        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Notification.title.ilike(search_term),
                    Notification.message.ilike(search_term),
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(Notification.created_at.desc())

        result = await session.execute(query)
        notifications = result.scalars().all()

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "ID",
            "Tipo",
            "Categoria",
            "Titulo",
            "Mensaje",
            "Entidad",
            "ID Entidad",
            "Leida",
            "Favorita",
            "Fecha Creacion",
            "Fecha Lectura",
            "Fecha Favorita",
        ])

        # Get category for each type
        def get_category(notification_type: str) -> str:
            for cat_name, cat_types in NOTIFICATION_CATEGORIES.items():
                if notification_type in cat_types:
                    return cat_name
            return "otro"

        # Data rows
        for n in notifications:
            writer.writerow([
                str(n.id),
                n.type.value,
                get_category(n.type.value),
                n.title,
                n.message,
                n.entity_type,
                str(n.entity_id) if n.entity_id else "",
                "Si" if n.is_read else "No",
                "Si" if n.is_starred else "No",
                n.created_at.isoformat() if n.created_at else "",
                n.read_at.isoformat() if n.read_at else "",
                n.starred_at.isoformat() if n.starred_at else "",
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=notificaciones_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            },
        )
