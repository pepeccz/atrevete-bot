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

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DATE,
    TIME,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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

    HAIRDRESSING = "HAIRDRESSING"
    AESTHETICS = "AESTHETICS"
    BOTH = "BOTH"


class AppointmentStatus(PyEnum):
    """Appointment lifecycle status."""

    HOLD = "hold"  # Slot temporarily reserved while customer confirms (expires in 5 min)
    PENDING = "pending"  # Cita agendada, esperando confirmación del cliente
    CONFIRMED = "confirmed"  # Cliente confirmó asistencia
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

    def __str__(self):
        return self.value


class MessageRole(str, PyEnum):
    """Role of message sender in conversation history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationMode(str, PyEnum):
    """
    Conversation mode for the mode-based architecture (v6.0).

    Used for logging and archival purposes in conversation_history metadata.
    The canonical definition lives in agent/state/schemas.py as a Literal type;
    this enum mirrors it for database storage/querying.

    Values:
        GREETING: Initial contact / first interaction with the customer
        BOOKING: Appointment booking flow (availability, confirmation, etc.)
        GENERAL: Informational queries (FAQs, hours, services, prices)
        ESCALATION: Human handoff triggered (complex or sensitive request)
    """

    GREETING = "GREETING"
    BOOKING = "BOOKING"
    GENERAL = "GENERAL"
    ESCALATION = "ESCALATION"


class BlockingEventType(str, PyEnum):
    """Type of calendar blocking event."""

    VACATION = "vacation"  # Vacaciones del estilista
    MEETING = "meeting"  # Reuniones, formaciones
    BREAK = "break"  # Descanso programado
    GENERAL = "general"  # Bloqueo general
    PERSONAL = "personal"  # Asunto propio


class RecurrenceFrequency(str, PyEnum):
    """Frequency type for recurring events (RFC 5545 compatible)."""

    WEEKLY = "WEEKLY"  # Repetir cada N semanas
    MONTHLY = "MONTHLY"  # Repetir cada N meses


class NotificationType(str, PyEnum):
    """Type of admin panel notification."""

    # Appointment lifecycle
    APPOINTMENT_CREATED = "appointment_created"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_COMPLETED = "appointment_completed"

    # Confirmation system
    CONFIRMATION_SENT = "confirmation_sent"  # 48h confirmation request sent
    CONFIRMATION_RECEIVED = "confirmation_received"  # Customer confirmed appointment
    AUTO_CANCELLED = "auto_cancelled"  # Auto-cancelled due to no response
    CONFIRMATION_FAILED = "confirmation_failed"  # Failed to send confirmation template
    CONFIRMATION_RETRY = "confirmation_retry"  # Retry attempt for failed confirmation
    CONFIRMATION_PERMANENTLY_FAILED = "confirmation_permanently_failed"  # All retries exhausted
    REMINDER_SENT = "reminder_sent"  # 2h reminder sent
    REMINDER_FAILED = "reminder_failed"  # Failed to send reminder
    REMINDER_PERMANENTLY_FAILED = "reminder_permanently_failed"  # All reminder retries exhausted

    # Escalation system (human handoff)
    ESCALATION_MANUAL = "escalation_manual"  # User explicitly requested human
    ESCALATION_TECHNICAL = "escalation_technical"  # Technical error triggered escalation
    ESCALATION_AUTO = "escalation_auto"  # Auto-escalation (error_count >= 3)
    ESCALATION_MEDICAL = "escalation_medical"  # Medical consultation requires human
    ESCALATION_AMBIGUITY = "escalation_ambiguity"  # Ambiguous request after multiple attempts


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
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Core fields
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    category: Mapped[ServiceCategory] = mapped_column(
        SQLEnum(ServiceCategory, name="service_category", create_type=True),
        nullable=False,
    )
    google_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Calendar color (hex code like "#7C3AED")
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    # Metadata
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

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
        "Customer",
        back_populates="preferred_stylist",
        foreign_keys="[Customer.preferred_stylist_id]",
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
        # Partial unique index: allows multiple NULLs, enforces uniqueness on non-null values
        Index(
            "uq_stylists_google_calendar_id_notnull",
            "google_calendar_id",
            unique=True,
            postgresql_where=text("google_calendar_id IS NOT NULL"),
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
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Contact information
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
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

    # Customer notes (allergies, preferences, special requests)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # External integration IDs
    chatwoot_conversation_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Metadata (JSONB for flexible data like whatsapp_name, referred_by, etc.)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

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
    Service model - Individual salon services with duration.

    Supports fuzzy search on service name using pg_trgm extension.
    """

    __tablename__ = "services"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Core fields
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[ServiceCategory] = mapped_column(
        SQLEnum(ServiceCategory, name="service_category", create_type=False),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    audience: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Storage in cents (EUR). Nullable; reserved for future reporting feature.
    # Not consumed by agent or admin UI yet.
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Disambiguation metadata (JSONB) — used by the service resolver to disambiguate
    # ambiguous service names without hardcoding families in prompts.
    # Default: {} (empty — all existing services are metadata-free until seeded).
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

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
        # Conditional index on category where active
        Index(
            "idx_services_category_active",
            "category",
            postgresql_where=text("is_active = true"),
        ),
        # Partial index on audience for active services
        Index(
            "idx_services_audience",
            "audience",
            postgresql_where=text("is_active = true"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Service(id={self.id}, name='{self.name}')>"


# ============================================================================
# Transactional Models
# ============================================================================


class Appointment(Base):
    """
    Appointment model - Booking transactions with state management.

    Tracks the full appointment lifecycle (confirmed/completed/cancelled).
    Integrates with Google Calendar (scheduling).
    Supports group bookings and third-party bookings.
    Stores customer-specific data (name, notes) for each appointment.
    """

    __tablename__ = "appointments"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

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
    service_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)

    # Scheduling
    start_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Status tracking
    # Note: values_callable ensures SQLAlchemy uses enum .value ("pending")
    # instead of .name ("PENDING") when create_type=False
    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(
            AppointmentStatus,
            name="appointment_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AppointmentStatus.PENDING,
        nullable=False,
        index=True,
    )

    # HOLD expiry — only set for status=HOLD. Expired HOLDs are treated as free slots
    # by all queries via lazy-expiry pattern (WHERE status != 'hold' OR hold_expires_at > NOW()).
    # Note: The excl_no_overlap GIST exclusion constraint is created via raw DDL migration
    # (database/alembic/versions/20260401_double_booking_prevention.py) because Alembic
    # autogenerate cannot express functional EXCLUDE USING GIST constraints.
    hold_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, default=None
    )

    # External integration IDs
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Customer-specific appointment data
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operational fields
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Confirmation/reminder tracking (Epic 2 support)
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Reminder retry tracking
    reminder_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    reminder_retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reminder_next_retry_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Group booking support
    group_booking_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
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

    # Constraints and indexes
    __table_args__ = (
        # CHECK constraints
        CheckConstraint("duration_minutes > 0", name="check_appointment_duration_positive"),
        # GIST exclusion constraint — prevents double-bookings at the DB level (L1 defense).
        # NOT added via ORM (Alembic can't autogenerate EXCLUDE USING GIST). Instead,
        # the raw DDL is in migration 20260401_double_booking_prevention.py:
        #   EXCLUDE USING GIST (
        #       stylist_id WITH =,
        #       tstzrange(start_time, start_time + make_interval(mins => duration_minutes)) WITH &&
        #   )
        #   WHERE (status NOT IN ('cancelled', 'no_show', 'completed'))
        # Requires btree_gist extension (also in the migration).
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
        # Partial index for retry worker queries (only notification_failed rows)
        Index(
            "idx_appointments_retry_eligible",
            "notification_failed",
            "retry_count",
            "next_retry_at",
            postgresql_where=text("notification_failed = true"),
        ),
        # Partial index for reminder retry worker queries (only reminder_failed rows)
        Index(
            "idx_appointments_reminder_retry_eligible",
            "reminder_failed",
            "reminder_retry_count",
            "reminder_next_retry_at",
            postgresql_where=text("reminder_failed = true"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Appointment(id={self.id}, customer_id={self.customer_id}, status='{self.status.value}')>"


class Policy(Base):
    """
    Policy model - Business rules and FAQs stored as key-value pairs.

    Enables dynamic configuration without code changes.
    Values are stored as JSONB for flexible schema.
    """

    __tablename__ = "policies"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

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
    __table_args__ = (Index("idx_policies_key", "key", unique=True),)

    def __repr__(self) -> str:
        return f"<Policy(id={self.id}, key='{self.key}')>"


class ConversationHistory(Base):
    """
    ConversationHistory model - Parent record for a conversation session.

    One row per conversation (identified by conversation_id / LangGraph thread_id).
    Individual messages are stored in ConversationMessage (child table).
    CASCADE delete: deleting a ConversationHistory removes all its messages automatically.
    """

    __tablename__ = "conversation_history"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to customer (nullable — allows conversations before customer is identified)
    customer_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Conversation identifier (LangGraph thread_id / Chatwoot conversation ID)
    # UNIQUE — exactly one parent row per conversation
    conversation_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    # Conversation-level timing
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Denormalized counters (updated by archiver on each sync)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AI-generated summary (populated by archiver / summarize_node)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Flexible metadata (node_name, escalation_reason, mode_history, etc.)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Row creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    customer: Mapped[Optional["Customer"]] = relationship("Customer")
    message_records: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )
    turns: Mapped[list["ConversationTurn"]] = relationship(
        "ConversationTurn",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationTurn.turn_number",
    )

    # Indexes
    __table_args__ = (
        # Fast lookup by conversation_id + time window (archiver, admin panel)
        Index(
            "idx_conversation_history_conversation_started",
            "conversation_id",
            "started_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationHistory(id={self.id}, "
            f"conversation_id='{self.conversation_id}', "
            f"messages={self.message_count})>"
        )


class ConversationMessage(Base):
    """
    ConversationMessage model - Individual messages within a conversation.

    Each row is one message (user, assistant, or system).
    Automatically deleted via CASCADE when the parent ConversationHistory is deleted.
    """

    __tablename__ = "conversation_messages"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to parent conversation (CASCADE DELETE)
    conversation_history_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message content
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,  # values: 'user', 'assistant', 'system'
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional Chatwoot correlation ID
    chatwoot_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Timestamp (timezone-aware, server-set for consistency)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship back to parent
    conversation: Mapped["ConversationHistory"] = relationship(
        "ConversationHistory",
        back_populates="message_records",
    )

    # Indexes
    __table_args__ = (
        # Primary query pattern: all messages for a conversation in chronological order
        Index(
            "idx_conversation_messages_conv_created",
            "conversation_history_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage(id={self.id}, "
            f"conversation_history_id={self.conversation_history_id}, "
            f"role='{self.role}')>"
        )


class BusinessHours(Base):
    """
    Salon business hours configuration.

    Stores opening/closing times for each day of the week.
    Allows dynamic configuration of salon schedule without code changes.

    Day of week: 0=Monday, 1=Tuesday, ..., 6=Sunday
    """

    __tablename__ = "business_hours"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

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
        CheckConstraint(
            "start_hour IS NULL OR (start_hour >= 0 AND start_hour <= 23)", name="valid_start_hour"
        ),
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
        CheckConstraint(
            "end_hour IS NULL OR (end_hour >= 0 AND end_hour <= 23)", name="valid_end_hour"
        ),
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
    __table_args__ = (Index("idx_business_hours_day", "day_of_week"),)

    def __repr__(self) -> str:
        if self.is_closed:
            return f"<BusinessHours(day={self.day_of_week}, CLOSED)>"
        return f"<BusinessHours(day={self.day_of_week}, {self.start_hour}:{self.start_minute:02d}-{self.end_hour}:{self.end_minute:02d})>"


# ============================================================================
# Calendar Management Models
# ============================================================================


class RecurringBlockingSeries(Base):
    """
    RecurringBlockingSeries model - Defines recurrence patterns for blocking events.

    Stores the recurrence rule definition (RFC 5545 compatible) for generating
    multiple BlockingEvent instances. Individual instances are created in the
    blocking_events table and linked back to this series via recurring_series_id.

    Supported patterns:
    - Weekly: Every N weeks on specific days (e.g., every Monday and Wednesday)
    - Monthly: Every N months on specific days of the month (e.g., 15th and 30th)
    """

    __tablename__ = "recurring_blocking_series"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to stylist
    stylist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stylists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Template for generated instances
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Event type for instances
    event_type: Mapped[BlockingEventType] = mapped_column(
        SQLEnum(
            BlockingEventType,
            name="blocking_event_type",
            create_type=False,  # Already created by BlockingEvent
            values_callable=lambda x: [e.value for e in x],
        ),
        default=BlockingEventType.GENERAL,
        nullable=False,
    )

    # Time template (hour:minute of day, applied to each occurrence date)
    start_time_of_day: Mapped[time] = mapped_column(TIME, nullable=False)
    end_time_of_day: Mapped[time] = mapped_column(TIME, nullable=False)

    # RFC 5545 RRULE components (simplified)
    rrule_frequency: Mapped[RecurrenceFrequency] = mapped_column(
        SQLEnum(
            RecurrenceFrequency,
            name="recurrence_frequency",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=RecurrenceFrequency.WEEKLY,
        nullable=False,
    )
    rrule_interval: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )  # Every N weeks/months
    rrule_byday: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g., 'MO,WE,FR' for days of week
    rrule_bymonthday: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g., '15,30' for days of month
    rrule_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Number of occurrences (1-52)

    # Series metadata
    original_start_date: Mapped[date] = mapped_column(DATE, nullable=False)  # First occurrence date
    instances_created: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Track how many were created

    # Timestamps
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

    # Relationships
    stylist: Mapped["Stylist"] = relationship("Stylist")
    instances: Mapped[list["BlockingEvent"]] = relationship(
        "BlockingEvent", back_populates="recurring_series"
    )

    # Constraints and indexes
    __table_args__ = (
        # End time must be after start time
        CheckConstraint("end_time_of_day > start_time_of_day", name="check_series_end_after_start"),
        # Count must be between 1 and 52
        CheckConstraint("rrule_count > 0 AND rrule_count <= 52", name="check_series_count_range"),
        # Interval must be positive
        CheckConstraint(
            "rrule_interval > 0 AND rrule_interval <= 12", name="check_series_interval_range"
        ),
        # Index for querying by stylist
        Index("idx_recurring_series_stylist", "stylist_id"),
    )

    def __repr__(self) -> str:
        return f"<RecurringBlockingSeries(id={self.id}, title='{self.title}', frequency={self.rrule_frequency.value}, count={self.rrule_count})>"


class BlockingEvent(Base):
    """
    BlockingEvent model - Calendar blocking events for stylists.

    Used to block time slots for vacations, meetings, breaks, or general purposes.
    These events prevent booking availability during the specified time range.
    Optionally syncs to Google Calendar for stylist visibility on mobile.
    """

    __tablename__ = "blocking_events"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to stylist
    stylist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stylists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Event details
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Time range
    start_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    # Event type
    event_type: Mapped[BlockingEventType] = mapped_column(
        SQLEnum(
            BlockingEventType,
            name="blocking_event_type",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=BlockingEventType.GENERAL,
        nullable=False,
    )

    # Google Calendar sync (optional - for push to stylist's mobile)
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Recurrence fields (optional - for events belonging to a recurring series)
    recurring_series_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("recurring_blocking_series.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    occurrence_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1, 2, 3... position in series
    is_exception: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # True if modified from original pattern

    # Timestamps
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

    # Relationships
    stylist: Mapped["Stylist"] = relationship("Stylist")
    recurring_series: Mapped["RecurringBlockingSeries | None"] = relationship(
        "RecurringBlockingSeries", back_populates="instances"
    )

    # Constraints and indexes
    __table_args__ = (
        # End time must be after start time
        CheckConstraint("end_time > start_time", name="check_blocking_end_after_start"),
        # Composite index for efficient overlap queries
        Index(
            "idx_blocking_events_stylist_time",
            "stylist_id",
            "start_time",
            "end_time",
        ),
        # Index for querying instances by series
        Index("idx_blocking_events_series", "recurring_series_id"),
    )

    def __repr__(self) -> str:
        series_info = f", series={self.recurring_series_id}" if self.recurring_series_id else ""
        return f"<BlockingEvent(id={self.id}, stylist_id={self.stylist_id}, title='{self.title}', type='{self.event_type.value}'{series_info})>"


class Holiday(Base):
    """
    Holiday model - Salon-wide closure dates.

    Stores dates when the entire salon is closed (national holidays, etc.).
    All stylists are considered unavailable on these dates.
    These are salon-specific holidays, not fetched from Google Calendar.
    """

    __tablename__ = "holidays"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Holiday details
    date: Mapped[date] = mapped_column(DATE, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # All-day flag (always true for now, future support for partial closures)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Indexes
    __table_args__ = (Index("idx_holidays_date", "date"),)

    def __repr__(self) -> str:
        return f"<Holiday(id={self.id}, date={self.date}, name='{self.name}')>"


# ============================================================================
# Admin Panel Models
# ============================================================================


class Notification(Base):
    """
    Notification model - Admin panel notifications.

    Tracks appointment-related events for the admin notification center.
    Notifications are created automatically when appointments change status.
    """

    __tablename__ = "notifications"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Notification type
    type: Mapped[NotificationType] = mapped_column(
        SQLEnum(
            NotificationType,
            name="notification_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )

    # Content
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Entity reference (for navigation)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Read status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Starred/important status
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    starred_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("idx_notifications_is_read", "is_read"),
        Index(
            "idx_notifications_created_at_desc", "created_at", postgresql_ops={"created_at": "DESC"}
        ),
        Index("idx_notifications_entity", "entity_type", "entity_id"),
        Index("idx_notifications_is_starred", "is_starred"),
        Index("idx_notifications_type", "type"),
    )

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type='{self.type.value}', is_read={self.is_read})>"


# ============================================================================
# System Settings Models
# ============================================================================


class SettingValueType(str, PyEnum):
    """Type of setting value for validation."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"


class SettingCategory(str, PyEnum):
    """Category grouping for system settings."""

    CONFIRMATION = "confirmation"
    BOOKING = "booking"
    LLM = "llm"
    RATE_LIMITING = "rate_limiting"
    CACHE = "cache"
    ARCHIVAL = "archival"
    GCAL_SYNC = "gcal_sync"
    AI_CONTROL = "ai_control"


class SystemSetting(Base):
    """
    System-wide configuration settings stored in database.

    Enables runtime configuration changes without code deployment.
    Settings are grouped by category and support typed validation.

    Features:
    - JSONB value storage for type flexibility
    - Min/max validation for numeric types
    - Allowed values for enum types
    - Audit trail via SystemSettingsHistory
    - requires_restart flag for settings needing service restart
    """

    __tablename__ = "system_settings"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Categorization
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    # Value storage (JSONB for type flexibility)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    default_value: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Validation constraints
    min_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    max_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Documentation
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    requires_restart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
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
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Indexes
    __table_args__ = (Index("idx_system_settings_category", "category"),)

    def __repr__(self) -> str:
        return f"<SystemSetting(key='{self.key}', value={self.value})>"


class SystemSettingsHistory(Base):
    """
    Audit trail for system settings changes.

    Records every change made to system settings including:
    - Previous and new values
    - Who made the change
    - Optional reason for the change
    - Timestamp
    """

    __tablename__ = "system_settings_history"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Reference to setting
    setting_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("system_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    setting_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # Denormalized for historical queries

    # Change tracking
    previous_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp
    changed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("idx_settings_history_setting_id", "setting_id"),
        Index(
            "idx_settings_history_changed_at",
            "changed_at",
            postgresql_ops={"changed_at": "DESC"},
        ),
        Index("idx_settings_history_key", "setting_key"),
    )

    def __repr__(self) -> str:
        return f"<SystemSettingsHistory(setting_key='{self.setting_key}', changed_by='{self.changed_by}')>"


class GCalSyncState(Base):
    """
    Google Calendar sync state per stylist.

    Stores the sync token for incremental sync with Google Calendar API.
    Each stylist has their own sync token to track changes since last sync.

    The sync token is returned by Google Calendar API after each list/sync
    and should be used in the next request to only get changes.
    """

    __tablename__ = "gcal_sync_state"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to stylist (one sync state per stylist)
    stylist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("stylists.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Google Calendar sync token for incremental sync
    sync_token: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Last successful sync timestamp
    last_sync_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Sync statistics
    events_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
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

    # Relationship
    stylist: Mapped["Stylist"] = relationship("Stylist")

    def __repr__(self) -> str:
        return f"<GCalSyncState(stylist_id={self.stylist_id}, last_sync={self.last_sync_at})>"


# ============================================================================
# OAuth2 Credential Models
# ============================================================================


class GoogleOAuthCredential(Base):
    """
    GoogleOAuthCredential model - Encrypted OAuth2 tokens for Google Calendar access.

    Stores the encrypted access/refresh tokens obtained after the admin connects their
    Google account via OAuth2 flow. The credential factory uses this table as the
    primary source when authenticating to Google Calendar API.

    Only one active credential is allowed at a time (partial unique index on is_active).
    Tokens are encrypted using Fernet symmetric encryption (shared/encryption.py).
    """

    __tablename__ = "google_oauth_credentials"

    # Primary key — server-generated UUID
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # Encrypted token fields (Fernet-encrypted, base64-encoded ciphertext)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)

    # Token expiry (UTC, nullable — some providers omit it)
    token_expiry: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Google account info
    connected_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # OAuth2 scopes granted (e.g., ["https://www.googleapis.com/auth/calendar"])
    calendar_scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Status — only one active credential allowed (enforced via partial unique index)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # Connection tracking
    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_refresh_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Constraints and indexes
    __table_args__ = (
        # Partial unique index: only ONE active credential allowed at a time
        # INSERT a new active credential → deactivate the old one first
        Index(
            "uq_google_oauth_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        # Index for history queries (all credentials, ordered by connection date)
        Index("idx_google_oauth_connected_at", "connected_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<GoogleOAuthCredential(id={self.id}, "
            f"email='{self.connected_email}', "
            f"is_active={self.is_active})>"
        )


# ============================================================================
# Token Usage Model — LLM token consumption tracking
# ============================================================================


class TokenUsage(Base):
    """
    Monthly aggregated LLM token usage.

    One row per (year, month) — uses PostgreSQL UPSERT to atomically
    increment counters on each LLM call. Used for cost tracking in
    the admin panel.
    """

    __tablename__ = "token_usage"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Period
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    # Token counters
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_token_usage_year_month"),
        Index("idx_token_usage_year_month", "year", "month"),
    )

    def __repr__(self) -> str:
        return (
            f"<TokenUsage(id={self.id}, "
            f"year={self.year}, month={self.month}, "
            f"input={self.input_tokens}, output={self.output_tokens})>"
        )


# ============================================================================
# Billing Models — Invoice and payment tracking
# ============================================================================


class InvoiceStatus(str, PyEnum):
    """Invoice lifecycle status."""

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentStatus(str, PyEnum):
    """Stripe payment status."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Invoice(Base):
    """
    Monthly billing invoice combining maintenance + token costs.

    One active invoice per (year, month) — void invoices don't count.
    Invoice number format: ATR-YYYY-MM-SEQ (e.g., ATR-2026-04-001).
    """

    __tablename__ = "invoices"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Invoice identification
    invoice_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    # Amounts (Decimal — NEVER float for money)
    maintenance_amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    token_amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Status
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(
            InvoiceStatus,
            name="invoice_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=InvoiceStatus.DRAFT,
        nullable=False,
    )

    # Dates
    issued_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    due_date: Mapped[date] = mapped_column(DATE, nullable=False)

    # PDF
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Stripe
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Stripe Invoicing (nullable — old invoices won't have these)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subtotal_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tax_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    tax_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    gross_amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # FK to TokenUsage (nullable — month may have no token usage)
    token_usage_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("token_usage.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
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

    # Relationships
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="invoice", lazy="selectin"
    )
    token_usage: Mapped[Optional["TokenUsage"]] = relationship("TokenUsage", lazy="selectin")

    # Indexes — partial unique index created in migration via raw SQL
    __table_args__ = (
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_year_month", "year", "month"),
        Index("idx_invoices_stripe_invoice_id", "stripe_invoice_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice(number='{self.invoice_number}', "
            f"period={self.year}-{self.month:02d}, "
            f"total={self.total_amount_eur}€, status={self.status.value})>"
        )


class Payment(Base):
    """
    Stripe payment record tied to an invoice.

    One invoice may have multiple payment attempts (failed → retry).
    """

    __tablename__ = "payments"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # FK to Invoice
    invoice_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Stripe identifiers
    stripe_payment_intent_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    stripe_charge_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Amount
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stripe_fee_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Status
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(
            PaymentStatus,
            name="payment_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False, default="sepa_debit")
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
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

    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="payments")

    # Indexes
    __table_args__ = (
        Index("idx_payments_invoice_id", "invoice_id"),
        Index("idx_payments_stripe_pi", "stripe_payment_intent_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Payment(invoice_id={self.invoice_id}, "
            f"amount={self.amount_eur}€, status={self.status.value})>"
        )


# ============================================================================
# Escalation Models
# ============================================================================


class EscalationSource(str, PyEnum):
    """Source / trigger of the escalation event."""

    MANUAL = "manual"
    AUTO_ERROR = "auto_error"
    FALLBACK = "fallback"


class EscalationStatus(str, PyEnum):
    """Lifecycle status of an escalation record."""

    TRIGGERED = "triggered"
    RESOLVED = "resolved"


class ConversationTurn(Base):
    """
    ConversationTurn model — per-turn telemetry for each agent invocation.

    One row per `graph.ainvoke()` call. Captures latency, LLM token counts,
    and a compact JSONB summary of tool calls made during the turn.
    CASCADE delete: removed automatically with the parent ConversationHistory.
    """

    __tablename__ = "conversation_turns"

    # Primary key
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to parent conversation (CASCADE DELETE)
    conversation_history_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Turn ordering (1-based, monotonically increasing per conversation)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Latency of graph.ainvoke() in milliseconds
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # LLM token counts (NULL when usage_metadata is absent)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Tool call summaries: [{name, args, result_summary}], NULL for no-tool turns
    tool_calls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Row creation timestamp (server-set)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship back to parent conversation
    conversation: Mapped["ConversationHistory"] = relationship(
        "ConversationHistory",
        back_populates="turns",
    )

    # Constraints and indexes
    __table_args__ = (
        # Composite index for ordered timeline reads per conversation
        Index(
            "idx_conversation_turns_conv_turn",
            "conversation_history_id",
            "turn_number",
        ),
        # Uniqueness: at most one row per (conversation, turn_number)
        UniqueConstraint(
            "conversation_history_id",
            "turn_number",
            name="uq_conversation_turns_conv_turn",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationTurn(id={self.id}, "
            f"conversation_history_id={self.conversation_history_id}, "
            f"turn_number={self.turn_number}, latency_ms={self.latency_ms})>"
        )


class Escalation(Base):
    """
    Escalation model — records every human-handoff event.

    Tracks who was escalated, why, how (source), and the steps performed.
    Deduplication is handled at service level (5-minute window per conversation).
    """

    __tablename__ = "escalations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[EscalationSource] = mapped_column(
        SQLEnum(
            EscalationSource,
            name="escalation_source",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    status: Mapped[EscalationStatus] = mapped_column(
        SQLEnum(
            EscalationStatus,
            name="escalation_status",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=EscalationStatus.TRIGGERED,
    )
    is_technical_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    issue_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_preference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata_escalation", JSONB, nullable=True)

    __table_args__ = (Index("idx_escalations_conv_triggered", "conversation_id", "triggered_at"),)

    def __repr__(self) -> str:
        return (
            f"<Escalation(id={self.id}, "
            f"conversation_id='{self.conversation_id}', "
            f"source='{self.source.value}', "
            f"status='{self.status.value}')>"
        )
