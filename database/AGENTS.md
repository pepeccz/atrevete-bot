# Database Component Guidelines

This directory contains SQLAlchemy 2.0 models, Alembic migrations, and data seeds for the Atrévete Bot application.

> **Architecture**: PostgreSQL 15+ with asyncpg driver, SQLAlchemy 2.0 ORM, Alembic migrations.

---

## Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating/modifying database models | `atrevete-database` |
| Writing Alembic migrations | `atrevete-database` |
| Working with seeds | `atrevete-database` |
| Generic SQLAlchemy patterns | `atrevete-database` |
| Writing Python tests | `pytest` |

---

## Directory Structure

```
database/
├── models.py                    # 9 core models + calendar models (1,441 lines)
├── connection.py                # Async engine, session factory, pooling
├── __init__.py                  # Package exports
│
├── alembic/
│   ├── env.py                   # Alembic environment configuration
│   ├── script.py.mako           # Migration template
│   └── versions/                # Migration files
│       ├── 1a030dcddf99_create_core_tables.py
│       ├── a1b2c3d4e5f6_add_blocking_events.py
│       └── ... (30+ migrations)
│
└── seeds/
    ├── services.py              # Service catalog seeding
    ├── stylists.py              # Stylist data seeding
    ├── business_hours.py        # Operating hours seeding
    ├── holidays.py              # Holiday seeding
    ├── faqs.py                  # FAQ/policies seeding
    └── system_settings_seed.py  # System settings seeding
```

---

## Architecture

### Core Models (9 tables)

| Model | Table | Purpose | Key Fields |
|-------|-------|---------|------------|
| `Stylist` | `stylists` | Salon professionals | `name`, `google_calendar_id`, `category`, `color` |
| `Customer` | `customers` | Salon customers | `phone` (E.164), `first_name`, `preferred_stylist_id` |
| `Service` | `services` | Salon services | `name`, `duration_minutes`, `category` |
| `Appointment` | `appointments` | Booking transactions | `customer_id`, `stylist_id`, `start_time`, `status` |
| `Policy` | `policies` | Business rules/FAQs | `key`, `value` (JSONB) |
| `BusinessHours` | `business_hours` | Operating schedule | `day_of_week`, `start_hour`, `end_hour` |
| `ConversationHistory` | `conversation_history` | Conversation metadata | `conversation_id`, `message_count`, `summary` |
| `ConversationMessage` | `conversation_messages` | Individual messages | `role`, `content`, `chatwoot_message_id` |
| `Notification` | `notifications` | Admin notifications | `type`, `title`, `message`, `is_read` |

### Calendar Models (5 tables)

| Model | Table | Purpose |
|-------|-------|---------|
| `BlockingEvent` | `blocking_events` | Calendar blocking (vacations, meetings) |
| `RecurringBlockingSeries` | `recurring_blocking_series` | Recurring block patterns |
| `Holiday` | `holidays` | Salon-wide closure dates |
| `GCalSyncState` | `gcal_sync_state` | Google Calendar sync tokens |
| `GoogleOAuthCredential` | `google_oauth_credentials` | Encrypted OAuth tokens |

### System Models (2 tables)

| Model | Table | Purpose |
|-------|-------|---------|
| `SystemSetting` | `system_settings` | Runtime configuration |
| `SystemSettingsHistory` | `system_settings_history` | Configuration audit trail |

---

## Model Patterns

### UUID Primary Keys

```python
from uuid import UUID, uuid4
from sqlalchemy.dialects.postgresql import UUID as PGUUID

class MyModel(Base):
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
```

### Timezone-Aware Timestamps

```python
from datetime import datetime
from sqlalchemy import TIMESTAMP

class MyModel(Base):
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
```

### Enums with Values

```python
from enum import Enum as PyEnum
from sqlalchemy import Enum as SQLEnum

class AppointmentStatus(PyEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

class Appointment(Base):
    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(
            AppointmentStatus,
            name="appointment_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AppointmentStatus.PENDING,
    )
```

### JSONB Fields

```python
from sqlalchemy.dialects.postgresql import JSONB

class Customer(Base):
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
```

### Relationships with Lazy Loading

```python
class Customer(Base):
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="customer",
        lazy="selectin",  # Async-friendly eager loading
    )

class Appointment(Base):
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="appointments"
    )
```

---

## Connection & Session Management

### Async Engine Configuration

```python
# database/connection.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before use
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects usable after commit
    autocommit=False,
    autoflush=False,
)
```

### Database Driver Gotcha

**CRITICAL**: Use different drivers for Alembic vs runtime:

```bash
# Alembic migrations (synchronous)
DATABASE_URL="postgresql+psycopg://user:pass@localhost/db"
alembic upgrade head

# Application runtime (asynchronous)
DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db"
python -m api.main
```

- `psycopg` (sync): Required for Alembic migrations
- `asyncpg` (async): Required for FastAPI/agent async operations

### Session Context Manager

```python
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

---

## Migration Workflow

### Create Migration

```bash
# Auto-generate from model changes
DATABASE_URL="postgresql+psycopg://..." alembic revision --autogenerate -m "add notifications table"
```

### Apply Migrations

```bash
# Upgrade to latest
DATABASE_URL="postgresql+psycopg://..." alembic upgrade head

# Downgrade one
DATABASE_URL="postgresql+psycopg://..." alembic downgrade -1

# Current version
DATABASE_URL="postgresql+psycopg://..." alembic current
```

### Migration Structure

```python
# alembic/versions/xxx_add_table.py
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table(
        'my_table',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_my_table_name', 'my_table', ['name'])

def downgrade() -> None:
    op.drop_index('ix_my_table_name', table_name='my_table')
    op.drop_table('my_table')
```

---

## Critical Rules

1. **ALWAYS use UUID** for primary keys (not auto-increment)
2. **ALWAYS use `DateTime(timezone=True)`** for timestamps
3. **ALWAYS specify `ondelete`** for foreign keys (`CASCADE` or `SET NULL`)
4. **ALWAYS create indexes** on foreign key columns
5. **ALWAYS include `downgrade()`** in migrations (never `pass`)
6. **NEVER modify existing migrations** — create new ones
7. **NEVER use synchronous DB operations** in async code
8. **NEVER use `lazy="joined"`** — use `lazy="selectin"` for async

---

## Indexes and Constraints

### Partial Indexes

```python
from sqlalchemy import Index, text

class Stylist(Base):
    __table_args__ = (
        Index(
            "idx_stylists_category_active",
            "category",
            postgresql_where=text("is_active = true"),
        ),
    )
```

### Check Constraints

```python
from sqlalchemy import CheckConstraint

class Service(Base):
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="check_duration_positive"),
    )
```

### GIN Index for Fuzzy Search

```python
class Service(Base):
    __table_args__ = (
        Index(
            "idx_services_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
```

---

## Resources

- [Root AGENTS.md](../AGENTS.md) — Repository governance
- [atrevete-database skill](../skills/atrevete-database/SKILL.md) — Detailed patterns
- `database/models.py` — All model definitions
- `database/connection.py` — Engine and session factory

**Last Updated**: March 2026

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| Creating migrations | `atrevete-database` |
| Creating/modifying models | `atrevete-database` |
| Working on database models | `atrevete-database` |
| Working with SQLAlchemy | `atrevete-database` |
