"""
SQLAlchemy ORM models for core database tables.

This module defines the core tables:
- customers: Salon customers with contact info and preferences
- stylists: Salon professionals with Google Calendar integration
- services: Individual salon services with pricing and duration
- business_hours: Salon operating hours configuration by day of week

All models use:
- UUID primary keys (auto-generated)
- TIMESTAMP WITH TIME ZONE for datetime fields
- JSONB for flexible metadata storage
- Proper indexes and constraints
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ============================================================================
# Base Class
# ============================================================================


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# ============================================================================
# Enums
# ============================================================================


class ServiceCategory(str, PyEnum):
    """Service category enumeration."""

    HAIRDRESSING = "Peluquería"
    AESTHETICS = "Estética"


class PaymentStatus(str, PyEnum):
    """Payment status for appointments."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REFUNDED = "refunded"
    FORFEITED = "forfeited"


class AppointmentStatus(PyEnum):
    """Appointment lifecycle status."""

    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    def __str__(self):
        return self.value


class MessageRole(str, PyEnum):
    """Role of message sender in conversation history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ============================================================================
# Core Models
# ============================================================================


class Stylist(Base):
    """
    Stylist model - Salon professionals providing services.

    Each stylist has a Google Calendar for appointment management.
    Stylists can specialize in Hairdressing, Aesthetics, or Both.
    """

    __tablename__ = "stylists"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Core fields
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[ServiceCategory] = mapped_column(
        SQLEnum(ServiceCategory, name="service_category", create_type=True),
        nullable=False,
    )
    google_calendar_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadata
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    preferred_customers: Mapped[list["Customer"]] = relationship(
        "Customer", back_populates="preferred_stylist", foreign_keys="[Customer.preferred_stylist_id]"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment", back_populates="stylist", foreign_keys="[Appointment.stylist_id]"
    )

    # Indexes
    __table_args__ = (
        # Conditional index on category where active
        Index(
            "idx_stylists_category_active",
            "category",
            postgresql_where=text("is_active = true"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Stylist(id={self.id}, name='{self.name}', category='{self.category.value}')>"


class Customer(Base):
    """
    Customer model - Salon customers with contact info and booking history.

    Phone number is the primary identifier (E.164 format).
    Tracks customer preferences, spending history, and preferred stylist.
    """

    __tablename__ = "customers"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Contact information
    phone: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Customer metrics
    total_spent: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    last_service_date: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Preferences
    preferred_stylist_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stylists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Metadata (JSONB for flexible data like whatsapp_name, referred_by, etc.)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    preferred_stylist: Mapped[Optional["Stylist"]] = relationship(
        "Stylist", back_populates="preferred_customers", foreign_keys=[preferred_stylist_id]
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="customer",
        foreign_keys="[Appointment.customer_id]",
        cascade="all, delete-orphan",
    )

    # Indexes and constraints
    __table_args__ = (
        # Phone validation: must be at least 10 characters (E.164 format)
        CheckConstraint("length(phone) >= 10", name="check_phone_length"),
        # Index on last_service_date for sorting recent customers
        Index(
            "idx_customers_last_service_date",
            "last_service_date",
            postgresql_ops={"last_service_date": "DESC NULLS LAST"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Customer(id={self.id}, phone='{self.phone}', name='{self.first_name} {self.last_name}')>"


class Service(Base):
    """
    Service model - Individual salon services with pricing and duration.

    Services can require advance payment (anticipo) or allow walk-ins.
    Supports fuzzy search on service name using pg_trgm extension.
    """

    __tablename__ = "services"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Core fields
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[ServiceCategory] = mapped_column(
        SQLEnum(ServiceCategory, name="service_category", create_type=False),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_euros: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    requires_advance_payment: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Constraints and indexes
    __table_args__ = (
        # CHECK constraints
        CheckConstraint("duration_minutes > 0", name="check_duration_positive"),
        CheckConstraint("price_euros >= 0", name="check_price_non_negative"),
        # Conditional index on category where active
        Index(
            "idx_services_category_active",
            "category",
            postgresql_where=text("is_active = true"),
        ),
        # GIN index for fuzzy search on name using pg_trgm
        Index(
            "idx_services_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Service(id={self.id}, name='{self.name}', price={self.price_euros}€)>"


# ============================================================================
# Transactional Models
# ============================================================================


class Appointment(Base):
    """
    Appointment model - Booking transactions with state management.

    Tracks the full appointment lifecycle from provisional to confirmed/completed.
    Integrates with Stripe (payment tracking) and Google Calendar (scheduling).
    Supports group bookings and third-party bookings.
    """

    __tablename__ = "appointments"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Foreign keys
    customer_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stylist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stylists.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Service tracking
    service_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )

    # Scheduling
    start_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Financial
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    advance_payment_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

    # Status tracking
    payment_status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status", create_type=True),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(AppointmentStatus, name="appointment_status", create_type=False),
        default=AppointmentStatus.PROVISIONAL,
        nullable=False,
        index=True,
    )

    # External integration IDs
    google_calendar_event_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    stripe_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_link_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Stripe Payment Link ID for deactivation on expiration"
    )

    # Operational fields
    payment_retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Group booking support
    group_booking_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    booked_by_customer_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer", foreign_keys=[customer_id], back_populates="appointments"
    )
    stylist: Mapped["Stylist"] = relationship(
        "Stylist", foreign_keys=[stylist_id], back_populates="appointments"
    )
    booked_by: Mapped[Optional["Customer"]] = relationship(
        "Customer", foreign_keys=[booked_by_customer_id]
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="appointment", cascade="all, delete-orphan"
    )

    # Constraints and indexes
    __table_args__ = (
        # CHECK constraints
        CheckConstraint("duration_minutes > 0", name="check_appointment_duration_positive"),
        CheckConstraint("total_price >= 0", name="check_appointment_total_price_non_negative"),
        CheckConstraint("advance_payment_amount >= 0", name="check_appointment_advance_payment_non_negative"),
        CheckConstraint("payment_retry_count >= 0", name="check_appointment_payment_retry_count_non_negative"),
        # Conditional index on stripe_payment_id for webhook lookups (sparse - only when NOT NULL)
        Index(
            "idx_appointments_stripe_payment_id",
            "stripe_payment_id",
            postgresql_where=text("stripe_payment_id IS NOT NULL"),
        ),
        # Conditional index on group_booking_id for group booking queries (sparse - only when NOT NULL)
        Index(
            "idx_appointments_group_booking_id",
            "group_booking_id",
            postgresql_where=text("group_booking_id IS NOT NULL"),
        ),
        # Composite index for reminder worker queries (includes status for filtering)
        Index(
            "idx_appointments_reminder_status",
            "start_time",
            "reminder_sent",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return f"<Appointment(id={self.id}, customer_id={self.customer_id}, status='{self.status.value}')>"


class Payment(Base):
    """
    Payment model - Records Stripe payment transactions for appointment deposits.

    Tracks payment lifecycle from intent creation through completion/failure.
    Each payment is linked to exactly one appointment.
    """

    __tablename__ = "payments"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Unique payment identifier",
    )

    # Foreign key to appointment
    appointment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Associated appointment",
    )

    # Stripe identifiers
    stripe_payment_intent_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Stripe PaymentIntent ID (pi_xxx)",
    )

    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Stripe Checkout Session ID (cs_xxx)",
    )

    # Payment details
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Payment amount in euros (e.g., 15.00 for 15€ deposit)",
    )

    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status", create_type=False),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
        comment="Payment status (pending, succeeded, failed, canceled)",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When payment intent was created",
    )

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last status update",
    )

    # Additional metadata from Stripe
    stripe_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional Stripe webhook data (payment method, receipt URL, etc.)",
    )

    # Relationship back to appointment
    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        back_populates="payments",
    )

    __table_args__ = (
        # Index for querying payments by status
        Index("idx_payments_status", "status"),
        # Index for querying payments by appointment
        Index("idx_payments_appointment_id", "appointment_id"),
    )

    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, appointment_id={self.appointment_id}, status='{self.status.value}', amount={self.amount})>"


class Policy(Base):
    """
    Policy model - Business rules and FAQs stored as key-value pairs.

    Enables dynamic configuration without code changes.
    Values are stored as JSONB for flexible schema.
    """

    __tablename__ = "policies"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Core fields
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("idx_policies_key", "key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Policy(id={self.id}, key='{self.key}')>"


class ConversationHistory(Base):
    """
    ConversationHistory model - Archives conversation messages for long-term storage.

    Messages are grouped by conversation_id (LangGraph thread_id).
    Metadata stores additional context like node_name, tool_calls, escalation_reason.
    """

    __tablename__ = "conversation_history"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Foreign keys
    customer_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True,  # Allows unidentified customer conversations before phone collection
        index=True,
    )

    # Conversation grouping (logical, not FK)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Message details
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    message_role: Mapped[MessageRole] = mapped_column(
        SQLEnum(MessageRole, name="message_role", create_type=True),
        nullable=False,
    )
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    # Relationship
    customer: Mapped[Optional["Customer"]] = relationship("Customer")

    # Indexes
    __table_args__ = (
        # Composite index for thread retrieval with chronological ordering
        Index("idx_conversation_history_conversation_timestamp", "conversation_id", "timestamp"),
        # Descending index for recent message queries
        Index(
            "idx_conversation_history_timestamp_desc",
            "timestamp",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )

    def __repr__(self) -> str:
        return f"<ConversationHistory(id={self.id}, conversation_id='{self.conversation_id}', role='{self.message_role.value}')>"


class BusinessHours(Base):
    """
    Salon business hours configuration.

    Stores opening/closing times for each day of the week.
    Allows dynamic configuration of salon schedule without code changes.

    Day of week: 0=Monday, 1=Tuesday, ..., 6=Sunday
    """

    __tablename__ = "business_hours"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Day of week (0=Monday, 1=Tuesday, ..., 6=Sunday)
    day_of_week: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="valid_day_of_week"),
        nullable=False,
        unique=True,  # One row per day
    )

    # Closed status
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Opening time (null if closed)
    start_hour: Mapped[Optional[int]] = mapped_column(
        Integer,
        CheckConstraint("start_hour IS NULL OR (start_hour >= 0 AND start_hour <= 23)", name="valid_start_hour"),
        nullable=True,
    )
    start_minute: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("start_minute >= 0 AND start_minute <= 59", name="valid_start_minute"),
        default=0,
        nullable=False,
    )

    # Closing time (null if closed)
    end_hour: Mapped[Optional[int]] = mapped_column(
        Integer,
        CheckConstraint("end_hour IS NULL OR (end_hour >= 0 AND end_hour <= 23)", name="valid_end_hour"),
        nullable=True,
    )
    end_minute: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("end_minute >= 0 AND end_minute <= 59", name="valid_end_minute"),
        default=0,
        nullable=False,
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("idx_business_hours_day", "day_of_week"),
    )

    def __repr__(self) -> str:
        if self.is_closed:
            return f"<BusinessHours(day={self.day_of_week}, CLOSED)>"
        return f"<BusinessHours(day={self.day_of_week}, {self.start_hour}:{self.start_minute:02d}-{self.end_hour}:{self.end_minute:02d})>"
