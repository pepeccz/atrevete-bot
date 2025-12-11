# Data Models - Atrévete Bot

## Overview

SQLAlchemy 2.0+ ORM models with PostgreSQL 15+ backend. All models use:
- UUID primary keys (auto-generated)
- TIMESTAMP WITH TIME ZONE for datetime fields
- JSONB for flexible metadata storage

## Enums

### ServiceCategory
```python
class ServiceCategory(str, PyEnum):
    HAIRDRESSING = "HAIRDRESSING"
    AESTHETICS = "AESTHETICS"
    BOTH = "BOTH"
```

### AppointmentStatus
```python
class AppointmentStatus(PyEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
```

### MessageRole
```python
class MessageRole(str, PyEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
```

---

## Core Models

### Stylist

Salon professionals providing services.

**Table**: `stylists`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `name` | VARCHAR(100) | NOT NULL | Stylist name |
| `category` | ServiceCategory | NOT NULL | Specialization |
| `google_calendar_id` | VARCHAR(255) | UNIQUE, NOT NULL | Calendar ID |
| `is_active` | BOOLEAN | DEFAULT TRUE | Active status |
| `metadata` | JSONB | DEFAULT {} | Flexible metadata |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP(TZ) | NOT NULL | Last update |

**Indexes**:
- `idx_stylists_category_active`: Conditional on `is_active = true`

**Relationships**:
- `preferred_customers`: One-to-Many → Customer
- `appointments`: One-to-Many → Appointment

---

### Customer

Salon customers with contact info and booking history.

**Table**: `customers`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `phone` | VARCHAR(20) | UNIQUE, NOT NULL | E.164 format |
| `first_name` | VARCHAR(100) | NOT NULL | First name |
| `last_name` | VARCHAR(100) | NULLABLE | Last name |
| `total_spent` | NUMERIC(10,2) | DEFAULT 0.00 | Lifetime spending |
| `last_service_date` | TIMESTAMP(TZ) | NULLABLE | Last appointment |
| `preferred_stylist_id` | UUID | FK → stylists | Preferred stylist |
| `notes` | TEXT | NULLABLE | Customer notes |
| `metadata` | JSONB | DEFAULT {} | Flexible metadata |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |

**Constraints**:
- `check_phone_length`: `length(phone) >= 10`

**Indexes**:
- `phone`: Unique index
- `preferred_stylist_id`: FK index
- `idx_customers_last_service_date`: DESC NULLS LAST

**Relationships**:
- `preferred_stylist`: Many-to-One → Stylist
- `appointments`: One-to-Many → Appointment (cascade delete)

---

### Service

Individual salon services with duration.

**Table**: `services`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `name` | VARCHAR(200) | NOT NULL | Service name |
| `category` | ServiceCategory | NOT NULL | Category |
| `duration_minutes` | INTEGER | NOT NULL | Duration |
| `description` | TEXT | NULLABLE | Description |
| `is_active` | BOOLEAN | DEFAULT TRUE | Active status |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP(TZ) | NOT NULL | Last update |

**Constraints**:
- `check_duration_positive`: `duration_minutes > 0`

**Indexes**:
- `idx_services_category_active`: Conditional on `is_active = true`
- `idx_services_name_trgm`: GIN index for fuzzy search (pg_trgm)

---

## Transactional Models

### Appointment

Booking transactions with state management.

**Table**: `appointments`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `customer_id` | UUID | FK → customers, NOT NULL | Customer reference |
| `stylist_id` | UUID | FK → stylists, NOT NULL | Stylist reference |
| `service_ids` | UUID[] | NOT NULL | Array of service IDs |
| `start_time` | TIMESTAMP(TZ) | NOT NULL | Appointment start |
| `duration_minutes` | INTEGER | NOT NULL | Total duration |
| `status` | AppointmentStatus | DEFAULT PROVISIONAL | Booking status |
| `google_calendar_event_id` | VARCHAR(255) | NULLABLE | GCal event ID |
| `first_name` | VARCHAR(100) | NOT NULL | Customer first name |
| `last_name` | VARCHAR(100) | NULLABLE | Customer last name |
| `notes` | TEXT | NULLABLE | Appointment notes |
| `reminder_sent` | BOOLEAN | DEFAULT FALSE | Reminder status |
| `group_booking_id` | UUID | NULLABLE | Group booking ref |
| `booked_by_customer_id` | UUID | FK → customers | Third-party booker |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP(TZ) | NOT NULL | Last update |

**Constraints**:
- `check_appointment_duration_positive`: `duration_minutes > 0`

**Indexes**:
- `customer_id`, `stylist_id`, `start_time`, `status`: Standard indexes
- `idx_appointments_group_booking_id`: Conditional (sparse)
- `idx_appointments_reminder_status`: Composite (start_time, reminder_sent, status)

**Relationships**:
- `customer`: Many-to-One → Customer
- `stylist`: Many-to-One → Stylist
- `booked_by`: Many-to-One → Customer (nullable)

---

### Policy

Business rules and FAQs as key-value pairs.

**Table**: `policies`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `key` | VARCHAR(100) | UNIQUE, NOT NULL | Policy key |
| `value` | JSONB | NOT NULL | Policy value |
| `description` | TEXT | NULLABLE | Description |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP(TZ) | NOT NULL | Last update |

**Indexes**:
- `idx_policies_key`: Unique on key

---

### ConversationHistory

Archives conversation messages for long-term storage.

**Table**: `conversation_history`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `customer_id` | UUID | FK → customers, NULLABLE | Customer reference |
| `conversation_id` | VARCHAR(255) | NOT NULL | Thread ID |
| `timestamp` | TIMESTAMP(TZ) | NOT NULL | Message time |
| `message_role` | MessageRole | NOT NULL | Sender role |
| `message_content` | TEXT | NOT NULL | Message text |
| `metadata` | JSONB | DEFAULT {} | Extra context |

**Indexes**:
- `idx_conversation_history_conversation_timestamp`: Composite for thread retrieval
- `idx_conversation_history_timestamp_desc`: DESC for recent queries

**Relationships**:
- `customer`: Many-to-One → Customer (nullable)

---

### BusinessHours

Salon operating hours configuration.

**Table**: `business_hours`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Auto-generated UUID |
| `day_of_week` | INTEGER | UNIQUE, 0-6 | 0=Monday, 6=Sunday |
| `is_closed` | BOOLEAN | DEFAULT FALSE | Closed status |
| `start_hour` | INTEGER | 0-23, NULLABLE | Opening hour |
| `start_minute` | INTEGER | 0-59, DEFAULT 0 | Opening minute |
| `end_hour` | INTEGER | 0-23, NULLABLE | Closing hour |
| `end_minute` | INTEGER | 0-59, DEFAULT 0 | Closing minute |
| `created_at` | TIMESTAMP(TZ) | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP(TZ) | NOT NULL | Last update |

**Constraints**:
- `valid_day_of_week`: `day_of_week >= 0 AND day_of_week <= 6`
- `valid_start_hour/minute`, `valid_end_hour/minute`: Range validations

**Indexes**:
- `idx_business_hours_day`: On day_of_week

---

## Migration History

| Migration | Description |
|-----------|-------------|
| `1a030dcddf99` | Create core tables (customers, stylists, services) |
| `de6f4bde8b7` | Create transactional tables (appointments) |
| `1f737760963f` | Make conversation_history customer_id nullable |
| `bd3989659200` | Add business_hours table |
| `0088717d25dd` | Remove packs table, update service model |
| `dc561f2b086e` | Add stripe_payment_link_id (later removed) |
| `3fd622c382cb` | Add payments table (later removed) |
| `e8f9a1b2c3d4` | Remove payment system completely |
| `bd0ab03a99b0` | Add customer notes column |
| `c4f7e6d9a2b1` | Add appointment customer fields (first_name, last_name, notes) |

---

## Entity Relationship Summary

```
Stylist (1) ←──────── (N) Customer.preferred_stylist
    │
    └────── (1) ←──── (N) Appointment

Customer (1) ←─────── (N) Appointment
    │
    └────── (1) ←──── (N) ConversationHistory

Service (independent - referenced by service_ids array in Appointment)

Policy (independent - key-value store)

BusinessHours (independent - one row per day of week)
```
