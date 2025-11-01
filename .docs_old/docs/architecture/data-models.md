# 4. Data Models

This section defines the core data models/entities shared between frontend and backend. These models form the conceptual foundation before implementing database schemas.

## 4.1 Customer

**Purpose:** Represents salon customers (new and returning) with their contact information, preferences, and booking history.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `phone`: string - E.164 format (e.g., "+34612345678"), unique, indexed
- `first_name`: string - Customer's given name
- `last_name`: string (optional) - Customer's surname (collected before first payment)
- `created_at`: datetime - Account creation timestamp (Europe/Madrid timezone)
- `last_service_date`: datetime (nullable) - Most recent completed appointment
- `preferred_stylist_id`: UUID (nullable) - FK to Stylist, for "lo de siempre" logic
- `total_spent`: decimal - Cumulative revenue from confirmed appointments
- `metadata`: JSONB - Flexible storage for conversation preferences, referral source

### TypeScript Interface

```typescript
interface Customer {
  id: string; // UUID
  phone: string; // E.164 format
  first_name: string;
  last_name: string | null;
  created_at: string; // ISO 8601
  last_service_date: string | null; // ISO 8601
  preferred_stylist_id: string | null; // UUID
  total_spent: number; // Decimal as float
  metadata: {
    whatsapp_name?: string;
    referred_by_customer_id?: string;
    communication_preferences?: string[];
  };
}
```

### Relationships

- **One-to-Many with Appointments:** Customer can have multiple appointments (history and future)
- **Many-to-One with Stylist:** Customer may prefer one stylist (optional relationship)
- **Self-Referential (Referrals):** metadata.referred_by_customer_id links to another Customer for third-party bookings

---

## 4.2 Stylist

**Purpose:** Represents salon professionals providing services, each with their own Google Calendar and service category specialization.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `name`: string - Stylist's full name (e.g., "Pilar", "Marta")
- `category`: enum - Service category: "Hairdressing" | "Aesthetics" | "Both"
- `google_calendar_id`: string - Unique Google Calendar ID for event management
- `is_active`: boolean - Whether stylist is currently accepting bookings
- `metadata`: JSONB - Working hours, skills, notification preferences

### TypeScript Interface

```typescript
type ServiceCategory = "Hairdressing" | "Aesthetics" | "Both";

interface Stylist {
  id: string; // UUID
  name: string;
  category: ServiceCategory;
  google_calendar_id: string; // e.g., "pilar@atrevete.com"
  is_active: boolean;
  metadata: {
    working_hours?: { [day: string]: { start: string; end: string } };
    notification_email?: string;
    notification_phone?: string;
  };
}
```

### Relationships

- **One-to-Many with Appointments:** Stylist provides multiple appointments
- **One-to-Many with Customers (Preferences):** Multiple customers may prefer this stylist

---

## 4.3 Service

**Purpose:** Represents individual salon services with pricing, duration, and advance payment requirements.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `name`: string - Service name (e.g., "MECHAS", "Corte de pelo")
- `category`: enum - "Hairdressing" | "Aesthetics"
- `duration_minutes`: integer - Service duration (e.g., 60)
- `price_euros`: decimal - Full service price (e.g., 45.00)
- `requires_advance_payment`: boolean - Whether 20% anticipo is needed
- `description`: text - Service details for customer inquiries

### TypeScript Interface

```typescript
interface Service {
  id: string; // UUID
  name: string;
  category: ServiceCategory;
  duration_minutes: number; // Integer
  price_euros: number; // Decimal as float
  requires_advance_payment: boolean;
  description: string;
}
```

### Relationships

- **Many-to-Many with Appointments:** Appointments can include multiple services (e.g., "Corte + Color")
- **Many-to-Many with Packs:** Services can belong to multiple package deals

---

## 4.4 Pack

**Purpose:** Represents discounted service packages (e.g., "Mechas + Corte" for €80 instead of €90).

**Key Attributes:**
- `id`: UUID - Primary identifier
- `name`: string - Pack name (e.g., "Mechas + Corte")
- `included_service_ids`: array<UUID> - List of services in the pack
- `duration_minutes`: integer - Total pack duration
- `price_euros`: decimal - Discounted total price
- `description`: text - Pack description and savings explanation

### TypeScript Interface

```typescript
interface Pack {
  id: string; // UUID
  name: string;
  included_service_ids: string[]; // Array of Service UUIDs
  duration_minutes: number;
  price_euros: number; // Discounted price
  description: string;
}
```

### Relationships

- **Many-to-Many with Services:** Pack references multiple services via `included_service_ids`
- **One-to-Many with Appointments:** Appointments can book a pack instead of individual services

---

## 4.5 Appointment

**Purpose:** Represents booking transactions with state management (provisional → confirmed) and payment tracking.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `customer_id`: UUID - FK to Customer
- `stylist_id`: UUID - FK to Stylist
- `service_ids`: array<UUID> - List of services booked (or pack reference)
- `pack_id`: UUID (nullable) - FK to Pack if booking a package
- `start_time`: datetime - Appointment start (Europe/Madrid timezone)
- `duration_minutes`: integer - Total duration
- `total_price`: decimal - Full service price
- `advance_payment_amount`: decimal - 20% anticipo (or 0 for free consultations)
- `payment_status`: enum - "pending" | "confirmed" | "refunded" | "forfeited"
- `status`: enum - "provisional" | "confirmed" | "completed" | "cancelled" | "expired"
- `google_calendar_event_id`: string (nullable) - Google Calendar event ID for updates/deletion
- `stripe_payment_id`: string (nullable) - Stripe Payment Link ID for webhook matching
- `payment_retry_count`: integer - Number of payment retry attempts (max 2)
- `reminder_sent`: boolean - Whether 48h reminder was sent
- `group_booking_id`: UUID (nullable) - Links appointments in group bookings
- `booked_by_customer_id`: UUID (nullable) - For third-party bookings (who made the booking)
- `created_at`: datetime - Record creation timestamp
- `updated_at`: datetime - Last modification timestamp

### TypeScript Interface

```typescript
type PaymentStatus = "pending" | "confirmed" | "refunded" | "forfeited";
type AppointmentStatus = "provisional" | "confirmed" | "completed" | "cancelled" | "expired";

interface Appointment {
  id: string; // UUID
  customer_id: string;
  stylist_id: string;
  service_ids: string[]; // Array of Service UUIDs
  pack_id: string | null;
  start_time: string; // ISO 8601
  duration_minutes: number;
  total_price: number;
  advance_payment_amount: number;
  payment_status: PaymentStatus;
  status: AppointmentStatus;
  google_calendar_event_id: string | null;
  stripe_payment_id: string | null;
  payment_retry_count: number;
  reminder_sent: boolean;
  group_booking_id: string | null;
  booked_by_customer_id: string | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### Relationships

- **Many-to-One with Customer:** Appointment belongs to one customer
- **Many-to-One with Stylist:** Appointment assigned to one stylist
- **Many-to-Many with Services:** Appointment includes multiple services
- **Many-to-One with Pack (optional):** Appointment may use a pack
- **Self-Referential (Group Bookings):** Multiple appointments share `group_booking_id`
- **Self-Referential (Third-Party Bookings):** `booked_by_customer_id` references another customer

---

## 4.6 Policy

**Purpose:** Stores business rules and FAQ content as key-value pairs for dynamic configuration without code changes.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `key`: string - Unique policy identifier (e.g., "cancellation_threshold_hours", "faq_parking")
- `value`: JSONB - Policy data (flexible schema per key)

### TypeScript Interface

```typescript
interface Policy {
  id: string; // UUID
  key: string; // Unique key
  value: {
    // For business rules:
    threshold_hours?: number;
    payment_percentage?: number;
    timeout_minutes_standard?: number;
    timeout_minutes_same_day?: number;

    // For FAQs:
    question?: string;
    answer?: string;
    keywords?: string[];  // REFERENCE ONLY - Not used for matching.
                          // Claude performs semantic classification.
                          // Field exists for documentation/human reference.
    category?: string;
    requires_location_link?: boolean;
  };
}
```

### Relationships

- **None (Standalone):** Policy table is queried by key for configuration lookup

---

## 4.7 ConversationHistory

**Purpose:** Archives conversation messages from Redis to PostgreSQL for long-term analysis and GDPR compliance.

**Key Attributes:**
- `id`: UUID - Primary identifier
- `customer_id`: UUID - FK to Customer
- `conversation_id`: string - LangGraph thread_id (groups related messages)
- `timestamp`: datetime - Message timestamp (Europe/Madrid timezone)
- `message_role`: enum - "user" | "assistant" | "system"
- `message_content`: text - Message text or summary
- `metadata`: JSONB - Additional context (tool calls, escalation flags, node names)

### TypeScript Interface

```typescript
type MessageRole = "user" | "assistant" | "system";

interface ConversationHistory {
  id: string; // UUID
  customer_id: string;
  conversation_id: string; // LangGraph thread_id
  timestamp: string; // ISO 8601
  message_role: MessageRole;
  message_content: string;
  metadata: {
    node_name?: string; // LangGraph node that generated message
    tool_calls?: string[]; // Tools invoked
    escalation_reason?: string;
  };
}
```

### Relationships

- **Many-to-One with Customer:** Conversation history belongs to one customer
- **Logical Grouping:** `conversation_id` groups messages (not enforced FK)

---
