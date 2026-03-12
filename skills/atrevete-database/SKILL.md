---
name: atrevete-database
description: >
  Atrévete Bot database patterns using SQLAlchemy 2.0+ and Alembic.
  Trigger: When working on database models, migrations, or SQLAlchemy queries.
license: MIT
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, database]
  auto_invoke:
    - "Working on database models"
    - "Creating migrations"
    - "Working with SQLAlchemy"
    - "Creating/modifying models"
---

## Database Structure

```
database/
├── models.py              # SQLAlchemy models (customers, stylists, services, appointments)
├── connection.py          # Async engine and session factory
├── __init__.py            # Package exports
├── alembic/
│   ├── env.py             # Alembic environment config
│   └── versions/          # Migration files
└── seeds/
    ├── seed_data.py       # Initial data seeding
    └── run_seeds.py       # Seed orchestrator
```

## Model Pattern

```python
import uuid
from datetime import datetime, UTC
from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase

class Base(DeclarativeBase):
    pass

class Customer(Base):
    """Customer model — salon clients."""
    __tablename__ = "customers"
    
    # Primary key (UUID)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Fields
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # JSONB metadata
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    
    # Relationships (ALWAYS use lazy="selectin" for async)
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="customer",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    
    # Table constraints
    __table_args__ = (
        Index("ix_customers_active", "is_active"),
    )
```

## Connection Setup

```python
# database/connection.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from shared.config import get_settings

settings = get_settings()

# CRITICAL: Different drivers for sync vs async
# Sync (Alembic): postgresql+psycopg://
# Async (App):    postgresql+asyncpg://

engine = create_async_engine(
    settings.DATABASE_URL,  # Must use asyncpg driver
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connection before use
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects usable after commit
    autocommit=False,
    autoflush=False,
)

# Context manager for sessions
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_async_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

## Query Patterns

```python
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

# Basic query
async for session in get_async_session():
    result = await session.execute(
        select(Customer).where(Customer.phone == "+34612345678")
    )
    customer = result.scalar_one_or_none()
    break

# Eager loading (prevents N+1)
async for session in get_async_session():
    result = await session.execute(
        select(Customer)
        .options(selectinload(Customer.appointments))
        .where(Customer.id == customer_id)
    )
    customer = result.scalar_one()
    # Access appointments (no additional queries)
    for appt in customer.appointments:
        print(appt.start_time)
    break

# Filtering with conditions
async for session in get_async_session():
    result = await session.execute(
        select(Appointment)
        .where(
            and_(
                Appointment.stylist_id == stylist_id,
                Appointment.start_time >= start_date,
                Appointment.status == "CONFIRMED",
            )
        )
        .order_by(Appointment.start_time)
    )
    appointments = result.scalars().all()
    break
```

## Alembic Migrations

```python
"""Add blocking_events table

Revision ID: 001_add_blocking_events
Create Date: 2024-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "001_add_blocking_events"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "blocking_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stylist_id", UUID(as_uuid=True), 
                  sa.ForeignKey("stylists.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Create indexes AFTER table
    op.create_index(
        op.f("ix_blocking_events_stylist_id"),
        "blocking_events",
        ["stylist_id"]
    )
    op.create_index(
        op.f("ix_blocking_events_start_time"),
        "blocking_events",
        ["start_time"]
    )

def downgrade() -> None:
    # Drop in reverse order
    op.drop_index(op.f("ix_blocking_events_start_time"))
    op.drop_index(op.f("ix_blocking_events_stylist_id"))
    op.drop_table("blocking_events")
```

## Migration Commands

```bash
# Create new migration
DATABASE_URL="postgresql+psycopg://atrevete:password@localhost:5432/atrevete_db" alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:password@localhost:5432/atrevete_db" alembic upgrade head

# Check current version
DATABASE_URL="postgresql+psycopg://atrevete:password@localhost:5432/atrevete_db" alembic current

# Rollback one
DATABASE_URL="postgresql+psycopg://atrevete:password@localhost:5432/atrevete_db" alembic downgrade -1

# View history
DATABASE_URL="postgresql+psycopg://atrevete:password@localhost:5432/atrevete_db" alembic history
```

## CRITICAL: Driver Differences

**Sync (Alembic):** `postgresql+psycopg://`
**Async (App):** `postgresql+asyncpg://`

```python
# WRONG — using psycopg with async engine
engine = create_async_engine("postgresql+psycopg://...")  # Error!

# CORRECT
engine = create_async_engine("postgresql+asyncpg://...")  # OK
```

## Transaction Pattern

```python
async def create_appointment(data: AppointmentCreate) -> Appointment:
    async for session in get_async_session():
        appointment = Appointment(
            customer_id=data.customer_id,
            stylist_id=data.stylist_id,
            start_time=data.start_time,
            status="CONFIRMED",
        )
        session.add(appointment)
        await session.commit()  # Commits here
        await session.refresh(appointment)  # Refresh to get DB defaults
        return appointment
```

## Upsert (ON CONFLICT)

```python
from sqlalchemy.dialects.postgresql import insert

stmt = insert(Customer).values(
    id=customer_id,
    phone="+34612345678",
    first_name="Juan",
)
stmt = stmt.on_conflict_do_update(
    index_elements=[Customer.phone],
    set_={
        "first_name": stmt.excluded.first_name,
        "updated_at": datetime.now(UTC),
    }
)

async for session in get_async_session():
    await session.execute(stmt)
    await session.commit()
    break
```

## Enum Types

```python
import enum
from sqlalchemy import Enum

class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class Appointment(Base):
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus),
        default=AppointmentStatus.CONFIRMED,
    )
```

## Critical Rules

- **ALWAYS** use `UUID(as_uuid=True)` for primary keys
- **ALWAYS** use `DateTime(timezone=True)` for timestamps
- **ALWAYS** use `lazy="selectin"` for relationships (async-safe)
- **ALWAYS** create indexes on foreign keys
- **ALWAYS** specify `ondelete` for foreign keys
- **ALWAYS** include `downgrade()` in migrations
- **NEVER** use synchronous operations in async code
- **NEVER** use `lazy="joined"` (causes issues with async)
- **NEVER** modify existing migrations (create new ones)

---

**Version**: 1.0
**Last Updated**: March 2026
