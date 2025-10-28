# 8. Database Schema

This section transforms the conceptual data models into concrete PostgreSQL database schemas with indexes, constraints, and relationships.

## 8.1 SQL DDL Schema

```sql
-- Enable UUID extension for primary keys
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- Fuzzy text search for services

-- Set default timezone for all timestamp operations
SET timezone = 'Europe/Madrid';

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

CREATE TYPE service_category AS ENUM ('Hairdressing', 'Aesthetics', 'Both');
CREATE TYPE payment_status AS ENUM ('pending', 'confirmed', 'refunded', 'forfeited');
CREATE TYPE appointment_status AS ENUM ('provisional', 'confirmed', 'completed', 'cancelled', 'expired');
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');

-- ============================================================================
-- CORE BUSINESS ENTITIES
-- ============================================================================

CREATE TABLE stylists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    category service_category NOT NULL,
    google_calendar_id VARCHAR(255) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_stylists_category ON stylists(category) WHERE is_active = true;
CREATE INDEX idx_stylists_google_calendar ON stylists(google_calendar_id);

-- ----------------------------------------------------------------------------

CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone VARCHAR(20) NOT NULL UNIQUE, -- E.164 format: +34612345678
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100), -- Optional until first payment
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_service_date TIMESTAMP WITH TIME ZONE,
    preferred_stylist_id UUID REFERENCES stylists(id) ON DELETE SET NULL,
    total_spent NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    metadata JSONB DEFAULT '{}'
);

CREATE UNIQUE INDEX idx_customers_phone ON customers(phone);
CREATE INDEX idx_customers_preferred_stylist ON customers(preferred_stylist_id);
CREATE INDEX idx_customers_last_service ON customers(last_service_date DESC NULLS LAST);

-- ----------------------------------------------------------------------------

CREATE TABLE services (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    category service_category NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price_euros NUMERIC(10, 2) NOT NULL CHECK (price_euros >= 0),
    requires_advance_payment BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_services_category ON services(category) WHERE is_active = true;
CREATE INDEX idx_services_name_trgm ON services USING gin (name gin_trgm_ops); -- Fuzzy search

-- ----------------------------------------------------------------------------

CREATE TABLE packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    included_service_ids UUID[] NOT NULL, -- Array of service UUIDs
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price_euros NUMERIC(10, 2) NOT NULL CHECK (price_euros > 0),
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_packs_service_ids ON packs USING gin (included_service_ids);

-- ============================================================================
-- TRANSACTIONAL TABLES
-- ============================================================================

CREATE TABLE appointments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    stylist_id UUID NOT NULL REFERENCES stylists(id) ON DELETE RESTRICT,
    service_ids UUID[] NOT NULL, -- Array of service UUIDs
    pack_id UUID REFERENCES packs(id) ON DELETE SET NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    total_price NUMERIC(10, 2) NOT NULL CHECK (total_price >= 0),
    advance_payment_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (advance_payment_amount >= 0),
    payment_status payment_status NOT NULL DEFAULT 'pending',
    status appointment_status NOT NULL DEFAULT 'provisional',
    google_calendar_event_id VARCHAR(255), -- Nullable until event created
    stripe_payment_id VARCHAR(255), -- Nullable for free consultations
    payment_retry_count INTEGER NOT NULL DEFAULT 0 CHECK (payment_retry_count >= 0),
    reminder_sent BOOLEAN NOT NULL DEFAULT false,
    group_booking_id UUID, -- Links related appointments
    booked_by_customer_id UUID REFERENCES customers(id) ON DELETE SET NULL, -- For third-party bookings
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_appointments_customer ON appointments(customer_id);
CREATE INDEX idx_appointments_stylist ON appointments(stylist_id);
CREATE INDEX idx_appointments_start_time ON appointments(start_time);
CREATE INDEX idx_appointments_status ON appointments(status);
CREATE INDEX idx_appointments_stripe_payment ON appointments(stripe_payment_id) WHERE stripe_payment_id IS NOT NULL;
CREATE INDEX idx_appointments_group_booking ON appointments(group_booking_id) WHERE group_booking_id IS NOT NULL;
CREATE INDEX idx_appointments_reminder_pending ON appointments(start_time, reminder_sent)
    WHERE status = 'confirmed' AND reminder_sent = false;

-- ----------------------------------------------------------------------------

CREATE TABLE policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(100) NOT NULL UNIQUE,
    value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_policies_key ON policies(key);

-- ----------------------------------------------------------------------------

CREATE TABLE conversation_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    conversation_id VARCHAR(255) NOT NULL, -- LangGraph thread_id
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    message_role message_role NOT NULL,
    message_content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_conversation_customer ON conversation_history(customer_id);
CREATE INDEX idx_conversation_thread ON conversation_history(conversation_id, timestamp);
CREATE INDEX idx_conversation_timestamp ON conversation_history(timestamp DESC);

-- ============================================================================
-- TRIGGERS FOR AUTOMATIC TIMESTAMP UPDATES
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_stylists_updated_at BEFORE UPDATE ON stylists
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON services
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_packs_updated_at BEFORE UPDATE ON packs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_appointments_updated_at BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_policies_updated_at BEFORE UPDATE ON policies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---
