--
-- PostgreSQL database dump
--

\restrict 5Esh6xBbMXDjFtwVLjgrqhmDeWnekGr4HuDW002FdgId61CXWGJfPWCEpMyg7hZ

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Required extensions. This snapshot references public.gin_trgm_ops (pg_trgm),
-- GIST EXCLUDE constraints over uuid columns (btree_gist), and uuid defaults
-- (uuid-ossp). pg_dump omitted these, so a fresh bootstrap (CI / new prod) must
-- create them BEFORE the indexes/constraints below or those statements fail
-- silently and leave the schema incomplete. IF NOT EXISTS keeps it idempotent.
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: appointment_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.appointment_status AS ENUM (
    'hold',
    'pending',
    'confirmed',
    'completed',
    'cancelled',
    'expired',
    'no_show'
);


--
-- Name: blocking_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.blocking_event_type AS ENUM (
    'vacation',
    'meeting',
    'break',
    'general',
    'personal'
);


--
-- Name: escalation_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.escalation_source AS ENUM (
    'manual',
    'auto_error',
    'fallback'
);


--
-- Name: escalation_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.escalation_status AS ENUM (
    'triggered',
    'resolved'
);


--
-- Name: invoice_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.invoice_status AS ENUM (
    'draft',
    'issued',
    'paid',
    'overdue',
    'void'
);


--
-- Name: message_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.message_role AS ENUM (
    'user',
    'assistant',
    'system'
);


--
-- Name: notification_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_type AS ENUM (
    'appointment_created',
    'appointment_cancelled',
    'appointment_confirmed',
    'appointment_completed',
    'confirmation_sent',
    'confirmation_received',
    'auto_cancelled',
    'confirmation_failed',
    'reminder_sent',
    'escalation_manual',
    'escalation_technical',
    'escalation_auto',
    'escalation_medical',
    'escalation_ambiguity',
    'confirmation_retry',
    'confirmation_permanently_failed',
    'reminder_failed',
    'reminder_permanently_failed',
    'conversation_paused_reminder'
);


--
-- Name: payment_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.payment_status AS ENUM (
    'pending',
    'processing',
    'succeeded',
    'failed',
    'refunded'
);


--
-- Name: recurrence_frequency; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.recurrence_frequency AS ENUM (
    'WEEKLY',
    'MONTHLY'
);


--
-- Name: service_category; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.service_category AS ENUM (
    'HAIRDRESSING',
    'AESTHETICS',
    'BOTH'
);


--
-- Name: appointment_range(timestamp with time zone, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.appointment_range(start_time timestamp with time zone, duration_minutes integer) RETURNS tstzrange
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
                SELECT tstzrange(start_time, start_time + (duration_minutes * interval '1 minute'))
            $$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_users (
    id uuid NOT NULL,
    username character varying(64) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role character varying(16) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    display_name character varying(120),
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT admin_users_role_check CHECK (((role)::text = ANY ((ARRAY['admin'::character varying, 'stylist'::character varying])::text[])))
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: appointments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.appointments (
    id uuid NOT NULL,
    customer_id uuid NOT NULL,
    stylist_id uuid NOT NULL,
    service_ids uuid[] NOT NULL,
    start_time timestamp with time zone NOT NULL,
    duration_minutes integer NOT NULL,
    status public.appointment_status NOT NULL,
    google_calendar_event_id character varying(255),
    reminder_sent boolean NOT NULL,
    group_booking_id uuid,
    booked_by_customer_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100),
    notes text,
    confirmation_sent_at timestamp with time zone,
    reminder_sent_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    notification_failed boolean DEFAULT false NOT NULL,
    cancellation_reason text,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    reminder_failed boolean DEFAULT false NOT NULL,
    reminder_retry_count integer DEFAULT 0 NOT NULL,
    reminder_next_retry_at timestamp with time zone,
    hold_expires_at timestamp with time zone,
    CONSTRAINT check_appointment_duration_positive CHECK ((duration_minutes > 0))
);


--
-- Name: blocking_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blocking_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    stylist_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    start_time timestamp with time zone NOT NULL,
    end_time timestamp with time zone NOT NULL,
    event_type public.blocking_event_type DEFAULT 'general'::public.blocking_event_type NOT NULL,
    google_calendar_event_id character varying(255),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    recurring_series_id uuid,
    occurrence_index integer,
    is_exception boolean DEFAULT false NOT NULL,
    CONSTRAINT check_blocking_end_after_start CHECK ((end_time > start_time))
);


--
-- Name: business_hours; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.business_hours (
    id uuid NOT NULL,
    day_of_week integer NOT NULL,
    is_closed boolean DEFAULT false NOT NULL,
    start_hour integer,
    start_minute integer DEFAULT 0 NOT NULL,
    end_hour integer,
    end_minute integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT valid_day_of_week CHECK (((day_of_week >= 0) AND (day_of_week <= 6))),
    CONSTRAINT valid_end_hour CHECK (((end_hour IS NULL) OR ((end_hour >= 0) AND (end_hour <= 23)))),
    CONSTRAINT valid_end_minute CHECK (((end_minute >= 0) AND (end_minute <= 59))),
    CONSTRAINT valid_start_hour CHECK (((start_hour IS NULL) OR ((start_hour >= 0) AND (start_hour <= 23)))),
    CONSTRAINT valid_start_minute CHECK (((start_minute >= 0) AND (start_minute <= 59)))
);


--
-- Name: conversation_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_history (
    id uuid NOT NULL,
    customer_id uuid,
    conversation_id character varying(255) NOT NULL,
    metadata jsonb NOT NULL,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    message_count integer DEFAULT 0 NOT NULL,
    summary text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    paused_at timestamp with time zone,
    resumed_at timestamp with time zone,
    context_injected_at timestamp with time zone,
    can_reply boolean,
    can_reply_captured_at timestamp with time zone
);


--
-- Name: conversation_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_messages (
    id uuid NOT NULL,
    conversation_history_id uuid NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    chatwoot_message_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    author_user_id uuid,
    author_type character varying(20),
    read_at timestamp with time zone,
    delivery_failed boolean DEFAULT false NOT NULL
);


--
-- Name: conversation_notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_notes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_history_id uuid NOT NULL,
    author_user_id uuid,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: conversation_turns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_turns (
    id uuid NOT NULL,
    conversation_history_id uuid NOT NULL,
    turn_number integer NOT NULL,
    latency_ms integer NOT NULL,
    tokens_in integer,
    tokens_out integer,
    tool_calls jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    id uuid NOT NULL,
    phone character varying(20) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100),
    total_spent numeric(10,2) NOT NULL,
    last_service_date timestamp with time zone,
    preferred_stylist_id uuid,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    notes text,
    chatwoot_conversation_id character varying(50),
    CONSTRAINT check_phone_length CHECK ((length((phone)::text) >= 10))
);


--
-- Name: escalations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.escalations (
    id uuid NOT NULL,
    conversation_id character varying(50) NOT NULL,
    customer_id uuid,
    customer_phone character varying(20) NOT NULL,
    reason character varying(100) NOT NULL,
    source public.escalation_source NOT NULL,
    status public.escalation_status NOT NULL,
    is_technical_error boolean NOT NULL,
    issue_summary text,
    contact_preference character varying(50),
    triggered_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    metadata_escalation jsonb,
    resolved_by_user_id uuid
);


--
-- Name: gcal_sync_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gcal_sync_state (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    stylist_id uuid NOT NULL,
    sync_token character varying(500),
    last_sync_at timestamp with time zone,
    events_synced integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: google_oauth_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.google_oauth_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    encrypted_access_token text NOT NULL,
    encrypted_refresh_token text NOT NULL,
    token_expiry timestamp with time zone,
    connected_email character varying(255) NOT NULL,
    calendar_scopes character varying[],
    is_active boolean DEFAULT true NOT NULL,
    connected_at timestamp with time zone DEFAULT now() NOT NULL,
    last_refresh_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: holidays; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.holidays (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    date date NOT NULL,
    name character varying(200) NOT NULL,
    is_all_day boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    id uuid NOT NULL,
    invoice_number character varying(20) NOT NULL,
    year integer NOT NULL,
    month integer NOT NULL,
    maintenance_amount_eur numeric(10,2) NOT NULL,
    token_amount_eur numeric(10,2) NOT NULL,
    total_amount_eur numeric(10,2) NOT NULL,
    status public.invoice_status DEFAULT 'draft'::public.invoice_status NOT NULL,
    issued_at timestamp with time zone,
    paid_at timestamp with time zone,
    due_date date NOT NULL,
    pdf_path character varying(500),
    stripe_payment_intent_id character varying(100),
    token_usage_id uuid,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    stripe_invoice_id character varying(100),
    invoice_pdf_url character varying(500),
    subtotal_eur numeric(10,2),
    tax_rate_pct numeric(5,2),
    tax_amount_eur numeric(10,2),
    gross_amount_eur numeric(10,2)
);


--
-- Name: message_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_attachments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    message_id uuid NOT NULL,
    file_type text NOT NULL,
    url text NOT NULL,
    thumb_url text,
    content_type text,
    filename text,
    size_bytes integer,
    width integer,
    height integer,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    type public.notification_type NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id uuid,
    is_read boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    read_at timestamp with time zone,
    is_starred boolean DEFAULT false NOT NULL,
    starred_at timestamp with time zone
);


--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    id uuid NOT NULL,
    invoice_id uuid NOT NULL,
    stripe_payment_intent_id character varying(100) NOT NULL,
    stripe_charge_id character varying(100),
    amount_eur numeric(10,2) NOT NULL,
    stripe_fee_eur numeric(10,2),
    status public.payment_status DEFAULT 'pending'::public.payment_status NOT NULL,
    payment_method character varying(50) DEFAULT 'sepa_debit'::character varying NOT NULL,
    failure_reason character varying(500),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.policies (
    id uuid NOT NULL,
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recurring_blocking_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recurring_blocking_series (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    stylist_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    event_type public.blocking_event_type DEFAULT 'general'::public.blocking_event_type NOT NULL,
    start_time_of_day time without time zone NOT NULL,
    end_time_of_day time without time zone NOT NULL,
    rrule_frequency public.recurrence_frequency DEFAULT 'WEEKLY'::public.recurrence_frequency NOT NULL,
    rrule_interval integer DEFAULT 1 NOT NULL,
    rrule_byday character varying(50),
    rrule_bymonthday character varying(50),
    rrule_count integer NOT NULL,
    original_start_date date NOT NULL,
    instances_created integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT check_series_count_range CHECK (((rrule_count > 0) AND (rrule_count <= 52))),
    CONSTRAINT check_series_end_after_start CHECK ((end_time_of_day > start_time_of_day)),
    CONSTRAINT check_series_interval_range CHECK (((rrule_interval > 0) AND (rrule_interval <= 12)))
);


--
-- Name: services; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.services (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    category public.service_category NOT NULL,
    duration_minutes integer NOT NULL,
    description text,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    audience character varying(30),
    price_cents integer,
    CONSTRAINT check_duration_positive CHECK ((duration_minutes > 0))
);


--
-- Name: stylists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stylists (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    category public.service_category NOT NULL,
    google_calendar_id character varying(255),
    is_active boolean NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    color character varying(7),
    slug character varying(100) NOT NULL
);


--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    category character varying(50) NOT NULL,
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    value_type character varying(20) NOT NULL,
    default_value jsonb NOT NULL,
    min_value jsonb,
    max_value jsonb,
    allowed_values jsonb,
    label character varying(200) NOT NULL,
    description text,
    requires_restart boolean DEFAULT false NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by character varying(100)
);


--
-- Name: system_settings_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    setting_id uuid NOT NULL,
    setting_key character varying(100) NOT NULL,
    previous_value jsonb,
    new_value jsonb NOT NULL,
    changed_by character varying(100) NOT NULL,
    change_reason text,
    changed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: token_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_usage (
    id uuid NOT NULL,
    year integer NOT NULL,
    month integer NOT NULL,
    input_tokens bigint DEFAULT '0'::bigint NOT NULL,
    output_tokens bigint DEFAULT '0'::bigint NOT NULL,
    total_requests integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_users admin_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: appointments appointments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_pkey PRIMARY KEY (id);


--
-- Name: blocking_events blocking_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocking_events
    ADD CONSTRAINT blocking_events_pkey PRIMARY KEY (id);


--
-- Name: business_hours business_hours_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_hours
    ADD CONSTRAINT business_hours_pkey PRIMARY KEY (id);


--
-- Name: conversation_history conversation_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_history
    ADD CONSTRAINT conversation_history_pkey PRIMARY KEY (id);


--
-- Name: conversation_messages conversation_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_pkey PRIMARY KEY (id);


--
-- Name: conversation_notes conversation_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_notes
    ADD CONSTRAINT conversation_notes_pkey PRIMARY KEY (id);


--
-- Name: conversation_turns conversation_turns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_pkey PRIMARY KEY (id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);


--
-- Name: escalations escalations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalations
    ADD CONSTRAINT escalations_pkey PRIMARY KEY (id);


--
-- Name: appointments excl_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT excl_no_overlap EXCLUDE USING gist (stylist_id WITH =, public.appointment_range(start_time, duration_minutes) WITH &&) WHERE ((status <> ALL (ARRAY['cancelled'::public.appointment_status, 'no_show'::public.appointment_status, 'completed'::public.appointment_status])));


--
-- Name: gcal_sync_state gcal_sync_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gcal_sync_state
    ADD CONSTRAINT gcal_sync_state_pkey PRIMARY KEY (id);


--
-- Name: google_oauth_credentials google_oauth_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.google_oauth_credentials
    ADD CONSTRAINT google_oauth_credentials_pkey PRIMARY KEY (id);


--
-- Name: holidays holidays_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.holidays
    ADD CONSTRAINT holidays_pkey PRIMARY KEY (id);


--
-- Name: invoices invoices_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: message_attachments message_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_attachments
    ADD CONSTRAINT message_attachments_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: payments payments_stripe_payment_intent_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_stripe_payment_intent_id_key UNIQUE (stripe_payment_intent_id);


--
-- Name: policies policies_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_key_key UNIQUE (key);


--
-- Name: policies policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.policies
    ADD CONSTRAINT policies_pkey PRIMARY KEY (id);


--
-- Name: recurring_blocking_series recurring_blocking_series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recurring_blocking_series
    ADD CONSTRAINT recurring_blocking_series_pkey PRIMARY KEY (id);


--
-- Name: services services_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.services
    ADD CONSTRAINT services_pkey PRIMARY KEY (id);


--
-- Name: stylists stylists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stylists
    ADD CONSTRAINT stylists_pkey PRIMARY KEY (id);


--
-- Name: system_settings_history system_settings_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings_history
    ADD CONSTRAINT system_settings_history_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (id);


--
-- Name: token_usage token_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT token_usage_pkey PRIMARY KEY (id);


--
-- Name: business_hours unique_day_of_week; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_hours
    ADD CONSTRAINT unique_day_of_week UNIQUE (day_of_week);


--
-- Name: conversation_turns uq_conversation_turns_conv_turn; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT uq_conversation_turns_conv_turn UNIQUE (conversation_history_id, turn_number);


--
-- Name: system_settings uq_system_settings_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT uq_system_settings_key UNIQUE (key);


--
-- Name: token_usage uq_token_usage_year_month; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_usage
    ADD CONSTRAINT uq_token_usage_year_month UNIQUE (year, month);


--
-- Name: idx_appointments_group_booking_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_appointments_group_booking_id ON public.appointments USING btree (group_booking_id) WHERE (group_booking_id IS NOT NULL);


--
-- Name: idx_appointments_reminder_retry_eligible; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_appointments_reminder_retry_eligible ON public.appointments USING btree (reminder_failed, reminder_retry_count, reminder_next_retry_at) WHERE (reminder_failed = true);


--
-- Name: idx_appointments_reminder_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_appointments_reminder_status ON public.appointments USING btree (start_time, reminder_sent, status);


--
-- Name: idx_appointments_retry_eligible; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_appointments_retry_eligible ON public.appointments USING btree (notification_failed, retry_count, next_retry_at) WHERE (notification_failed = true);


--
-- Name: idx_blocking_events_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blocking_events_series ON public.blocking_events USING btree (recurring_series_id);


--
-- Name: idx_blocking_events_stylist_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_blocking_events_stylist_time ON public.blocking_events USING btree (stylist_id, start_time, end_time);


--
-- Name: idx_business_hours_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_business_hours_day ON public.business_hours USING btree (day_of_week);


--
-- Name: idx_conv_messages_content_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conv_messages_content_trgm ON public.conversation_messages USING gin (content public.gin_trgm_ops);


--
-- Name: idx_conversation_history_conversation_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_history_conversation_started ON public.conversation_history USING btree (conversation_id, started_at);


--
-- Name: idx_conversation_messages_conv_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_messages_conv_created ON public.conversation_messages USING btree (conversation_history_id, created_at);


--
-- Name: idx_conversation_messages_unread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_messages_unread ON public.conversation_messages USING btree (conversation_history_id) WHERE (read_at IS NULL);


--
-- Name: idx_conversation_notes_author; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_notes_author ON public.conversation_notes USING btree (author_user_id);


--
-- Name: idx_conversation_notes_conv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_notes_conv ON public.conversation_notes USING btree (conversation_history_id, created_at DESC);


--
-- Name: idx_conversation_turns_conv_hist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_turns_conv_hist_id ON public.conversation_turns USING btree (conversation_history_id);


--
-- Name: idx_conversation_turns_conv_turn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_turns_conv_turn ON public.conversation_turns USING btree (conversation_history_id, turn_number);


--
-- Name: idx_customers_last_service_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_customers_last_service_date ON public.customers USING btree (last_service_date DESC NULLS LAST);


--
-- Name: idx_customers_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_customers_name_trgm ON public.customers USING gin (first_name public.gin_trgm_ops);


--
-- Name: idx_customers_phone_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_customers_phone_trgm ON public.customers USING gin (phone public.gin_trgm_ops);


--
-- Name: idx_escalations_conv_triggered; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_escalations_conv_triggered ON public.escalations USING btree (conversation_id, triggered_at);


--
-- Name: idx_google_oauth_connected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_google_oauth_connected_at ON public.google_oauth_credentials USING btree (connected_at);


--
-- Name: idx_holidays_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_holidays_date ON public.holidays USING btree (date);


--
-- Name: idx_invoices_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invoices_status ON public.invoices USING btree (status);


--
-- Name: idx_invoices_stripe_invoice_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invoices_stripe_invoice_id ON public.invoices USING btree (stripe_invoice_id);


--
-- Name: idx_invoices_year_month; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invoices_year_month ON public.invoices USING btree (year, month);


--
-- Name: idx_message_attachments_message; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_attachments_message ON public.message_attachments USING btree (message_id, "position");


--
-- Name: idx_notifications_created_at_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_created_at_desc ON public.notifications USING btree (created_at DESC);


--
-- Name: idx_notifications_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_entity ON public.notifications USING btree (entity_type, entity_id);


--
-- Name: idx_notifications_is_read; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_is_read ON public.notifications USING btree (is_read);


--
-- Name: idx_notifications_is_starred; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_is_starred ON public.notifications USING btree (is_starred);


--
-- Name: idx_notifications_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notifications_type ON public.notifications USING btree (type);


--
-- Name: idx_payments_invoice_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_invoice_id ON public.payments USING btree (invoice_id);


--
-- Name: idx_payments_stripe_pi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_payments_stripe_pi ON public.payments USING btree (stripe_payment_intent_id);


--
-- Name: idx_policies_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_policies_key ON public.policies USING btree (key);


--
-- Name: idx_recurring_series_stylist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recurring_series_stylist ON public.recurring_blocking_series USING btree (stylist_id);


--
-- Name: idx_services_audience; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_services_audience ON public.services USING btree (audience) WHERE (is_active = true);


--
-- Name: idx_services_category_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_services_category_active ON public.services USING btree (category) WHERE (is_active = true);


--
-- Name: idx_settings_history_changed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_settings_history_changed_at ON public.system_settings_history USING btree (changed_at DESC);


--
-- Name: idx_settings_history_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_settings_history_key ON public.system_settings_history USING btree (setting_key);


--
-- Name: idx_settings_history_setting_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_settings_history_setting_id ON public.system_settings_history USING btree (setting_id);


--
-- Name: idx_stylists_category_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stylists_category_active ON public.stylists USING btree (category) WHERE (is_active = true);


--
-- Name: idx_system_settings_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_settings_category ON public.system_settings USING btree (category);


--
-- Name: idx_token_usage_year_month; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_token_usage_year_month ON public.token_usage USING btree (year, month);


--
-- Name: ix_admin_users_role_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_admin_users_role_active ON public.admin_users USING btree (role, is_active);


--
-- Name: ix_admin_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_admin_users_username ON public.admin_users USING btree (username);


--
-- Name: ix_appointments_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_appointments_customer_id ON public.appointments USING btree (customer_id);


--
-- Name: ix_appointments_start_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_appointments_start_time ON public.appointments USING btree (start_time);


--
-- Name: ix_appointments_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_appointments_status ON public.appointments USING btree (status);


--
-- Name: ix_appointments_stylist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_appointments_stylist_id ON public.appointments USING btree (stylist_id);


--
-- Name: ix_blocking_events_recurring_series_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_blocking_events_recurring_series_id ON public.blocking_events USING btree (recurring_series_id);


--
-- Name: ix_blocking_events_stylist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_blocking_events_stylist_id ON public.blocking_events USING btree (stylist_id);


--
-- Name: ix_conversation_history_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_conversation_history_conversation_id ON public.conversation_history USING btree (conversation_id);


--
-- Name: ix_conversation_history_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_history_customer_id ON public.conversation_history USING btree (customer_id);


--
-- Name: ix_conversation_messages_author_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_messages_author_user ON public.conversation_messages USING btree (author_user_id);


--
-- Name: ix_conversation_messages_chatwoot_message_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_messages_chatwoot_message_id ON public.conversation_messages USING btree (chatwoot_message_id);


--
-- Name: ix_conversation_messages_conversation_history_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_conversation_messages_conversation_history_id ON public.conversation_messages USING btree (conversation_history_id);


--
-- Name: ix_customers_phone; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_customers_phone ON public.customers USING btree (phone);


--
-- Name: ix_customers_preferred_stylist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_customers_preferred_stylist_id ON public.customers USING btree (preferred_stylist_id);


--
-- Name: ix_escalations_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_escalations_conversation_id ON public.escalations USING btree (conversation_id);


--
-- Name: ix_escalations_resolved_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_escalations_resolved_by ON public.escalations USING btree (resolved_by_user_id);


--
-- Name: ix_escalations_triggered_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_escalations_triggered_at ON public.escalations USING btree (triggered_at);


--
-- Name: ix_gcal_sync_state_stylist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_gcal_sync_state_stylist_id ON public.gcal_sync_state USING btree (stylist_id);


--
-- Name: ix_holidays_date; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_holidays_date ON public.holidays USING btree (date);


--
-- Name: ix_recurring_blocking_series_stylist_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recurring_blocking_series_stylist_id ON public.recurring_blocking_series USING btree (stylist_id);


--
-- Name: ix_stylists_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_stylists_slug ON public.stylists USING btree (slug);


--
-- Name: ix_system_settings_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_system_settings_category ON public.system_settings USING btree (category);


--
-- Name: uq_active_invoice_year_month; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_active_invoice_year_month ON public.invoices USING btree (year, month) WHERE (status <> 'void'::public.invoice_status);


--
-- Name: uq_google_oauth_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_google_oauth_active ON public.google_oauth_credentials USING btree (is_active) WHERE (is_active = true);


--
-- Name: uq_stylists_google_calendar_id_notnull; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_stylists_google_calendar_id_notnull ON public.stylists USING btree (google_calendar_id) WHERE (google_calendar_id IS NOT NULL);


--
-- Name: appointments update_appointments_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_appointments_updated_at BEFORE UPDATE ON public.appointments FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: blocking_events update_blocking_events_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_blocking_events_updated_at BEFORE UPDATE ON public.blocking_events FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: business_hours update_business_hours_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_business_hours_updated_at BEFORE UPDATE ON public.business_hours FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: policies update_policies_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_policies_updated_at BEFORE UPDATE ON public.policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: recurring_blocking_series update_recurring_blocking_series_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_recurring_blocking_series_updated_at BEFORE UPDATE ON public.recurring_blocking_series FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: services update_services_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_services_updated_at BEFORE UPDATE ON public.services FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: stylists update_stylists_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_stylists_updated_at BEFORE UPDATE ON public.stylists FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: appointments appointments_booked_by_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_booked_by_customer_id_fkey FOREIGN KEY (booked_by_customer_id) REFERENCES public.customers(id) ON DELETE SET NULL;


--
-- Name: appointments appointments_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE;


--
-- Name: appointments appointments_stylist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.appointments
    ADD CONSTRAINT appointments_stylist_id_fkey FOREIGN KEY (stylist_id) REFERENCES public.stylists(id) ON DELETE RESTRICT;


--
-- Name: blocking_events blocking_events_recurring_series_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocking_events
    ADD CONSTRAINT blocking_events_recurring_series_id_fkey FOREIGN KEY (recurring_series_id) REFERENCES public.recurring_blocking_series(id) ON DELETE SET NULL;


--
-- Name: blocking_events blocking_events_stylist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blocking_events
    ADD CONSTRAINT blocking_events_stylist_id_fkey FOREIGN KEY (stylist_id) REFERENCES public.stylists(id) ON DELETE CASCADE;


--
-- Name: conversation_history conversation_history_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_history
    ADD CONSTRAINT conversation_history_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE;


--
-- Name: conversation_messages conversation_messages_conversation_history_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_conversation_history_id_fkey FOREIGN KEY (conversation_history_id) REFERENCES public.conversation_history(id) ON DELETE CASCADE;


--
-- Name: conversation_notes conversation_notes_author_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_notes
    ADD CONSTRAINT conversation_notes_author_user_id_fkey FOREIGN KEY (author_user_id) REFERENCES public.admin_users(id) ON DELETE SET NULL;


--
-- Name: conversation_notes conversation_notes_conversation_history_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_notes
    ADD CONSTRAINT conversation_notes_conversation_history_id_fkey FOREIGN KEY (conversation_history_id) REFERENCES public.conversation_history(id) ON DELETE CASCADE;


--
-- Name: conversation_turns conversation_turns_conversation_history_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_conversation_history_id_fkey FOREIGN KEY (conversation_history_id) REFERENCES public.conversation_history(id) ON DELETE CASCADE;


--
-- Name: customers customers_preferred_stylist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_preferred_stylist_id_fkey FOREIGN KEY (preferred_stylist_id) REFERENCES public.stylists(id) ON DELETE SET NULL;


--
-- Name: escalations escalations_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalations
    ADD CONSTRAINT escalations_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE SET NULL;


--
-- Name: conversation_messages fk_conversation_messages_author_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT fk_conversation_messages_author_user FOREIGN KEY (author_user_id) REFERENCES public.admin_users(id) ON DELETE SET NULL;


--
-- Name: escalations fk_escalations_resolved_by_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escalations
    ADD CONSTRAINT fk_escalations_resolved_by_user FOREIGN KEY (resolved_by_user_id) REFERENCES public.admin_users(id) ON DELETE SET NULL;


--
-- Name: gcal_sync_state gcal_sync_state_stylist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gcal_sync_state
    ADD CONSTRAINT gcal_sync_state_stylist_id_fkey FOREIGN KEY (stylist_id) REFERENCES public.stylists(id) ON DELETE CASCADE;


--
-- Name: invoices invoices_token_usage_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_token_usage_id_fkey FOREIGN KEY (token_usage_id) REFERENCES public.token_usage(id) ON DELETE SET NULL;


--
-- Name: message_attachments message_attachments_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_attachments
    ADD CONSTRAINT message_attachments_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.conversation_messages(id) ON DELETE CASCADE;


--
-- Name: payments payments_invoice_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE CASCADE;


--
-- Name: recurring_blocking_series recurring_blocking_series_stylist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recurring_blocking_series
    ADD CONSTRAINT recurring_blocking_series_stylist_id_fkey FOREIGN KEY (stylist_id) REFERENCES public.stylists(id) ON DELETE CASCADE;


--
-- Name: system_settings_history system_settings_history_setting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings_history
    ADD CONSTRAINT system_settings_history_setting_id_fkey FOREIGN KEY (setting_id) REFERENCES public.system_settings(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 5Esh6xBbMXDjFtwVLjgrqhmDeWnekGr4HuDW002FdgId61CXWGJfPWCEpMyg7hZ

--
-- PostgreSQL database dump
--

\restrict 9IJUZlFAdS6xCPw2IvhFGGbPtZ5ooBiIFAlcU7DQ5uacj2ciEqaygt0HMoNJyA3

-- Dumped from database version 15.17
-- Dumped by pg_dump version 15.17

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.alembic_version VALUES ('c7d8e9f0a1b2');


--
-- Data for Name: stylists; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.stylists VALUES ('5f1745ba-d2b1-4d87-8d47-79821a99ae93', 'Marta', 'HAIRDRESSING', NULL, true, '{}', '2026-04-19 16:35:41.67619+00', '2026-05-10 15:04:23.37398+00', '#3066d8', 'marta');
INSERT INTO public.stylists VALUES ('dd309c98-0253-485d-a255-f6729ce72c6b', 'Victor', 'HAIRDRESSING', NULL, true, '{}', '2026-04-19 16:35:41.676202+00', '2026-05-10 15:04:23.37398+00', '#3a9a4d', 'victor');
INSERT INTO public.stylists VALUES ('1ece0cc9-d4f1-4385-b15b-089c196e33dd', 'Harolyn', 'HAIRDRESSING', NULL, true, '{}', '2026-04-19 16:35:41.67621+00', '2026-05-10 15:04:23.37398+00', '#cc3a3a', 'harolyn');
INSERT INTO public.stylists VALUES ('a0e747dd-04a6-4d3b-8db1-1eef9a0b0487', 'Rosa', 'AESTHETICS', NULL, true, '{}', '2026-04-19 16:35:41.676214+00', '2026-05-10 15:04:23.37398+00', '#d97a1f', 'rosa');
INSERT INTO public.stylists VALUES ('ddf7e495-c682-480b-8231-cf665f39d0e4', 'Pilar', 'HAIRDRESSING', '4df9392d761b0e0a80c5f62f921c073179c2d889b29b71baff0278a8c1868c6e@group.calendar.google.com', true, '{}', '2026-04-19 16:35:41.676198+00', '2026-05-10 15:36:08.179523+00', '#1ba8c4', 'pilar');


--
-- Data for Name: blocking_events; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.blocking_events VALUES ('7e399411-1863-42cc-b055-b31f56dd0f65', 'dd309c98-0253-485d-a255-f6729ce72c6b', 'Comidass', NULL, '2026-05-04 12:00:00+00', '2026-05-04 13:00:00+00', 'break', NULL, '2026-05-10 16:11:16.490254+00', '2026-05-10 16:11:16.490254+00', NULL, NULL, false);
INSERT INTO public.blocking_events VALUES ('310b7a8b-85bc-4926-9318-77e9267359db', 'a0e747dd-04a6-4d3b-8db1-1eef9a0b0487', 'Prueba', NULL, '2026-05-04 12:00:00+00', '2026-05-04 13:00:00+00', 'break', NULL, '2026-05-10 16:17:46.72051+00', '2026-05-10 16:18:18.582999+00', NULL, NULL, false);
INSERT INTO public.blocking_events VALUES ('3356984a-64d8-4e34-b928-d6da1ec22738', 'ddf7e495-c682-480b-8231-cf665f39d0e4', '☕ Prueba', NULL, '2026-05-04 12:00:00+00', '2026-05-04 13:00:00+00', 'break', 'koptrujt0gq080cpbaambbjtv8', '2026-05-10 16:17:46.72051+00', '2026-05-10 16:19:28.228188+00', NULL, NULL, false);


--
-- Data for Name: business_hours; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.business_hours VALUES ('402fdc12-b6bd-4b20-991c-a8d5d3d99e82', 0, true, NULL, 0, NULL, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('b8b2183d-a2d9-4e95-9cce-c744d481aaf4', 1, false, 10, 0, 20, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('bf032404-f545-4eb6-8bc2-5642b4f722e2', 2, false, 10, 0, 20, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('e318d799-9199-45a9-9419-f6e6ac250dbe', 3, false, 10, 0, 20, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('c60733f7-53fa-4bb1-9fb9-4ff4ce677e03', 4, false, 10, 0, 20, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('8e0f431f-603d-45d8-93e4-f581122d1411', 5, false, 9, 0, 14, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');
INSERT INTO public.business_hours VALUES ('cefc791b-02f4-40d8-929e-8a6362437030', 6, true, NULL, 0, NULL, 0, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00');


--
-- Data for Name: holidays; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.holidays VALUES ('fcc7c957-5730-484f-8ab7-5b2c503c3fb0', '2026-04-29', 'Festivo de prueba', true, '2026-04-27 18:28:56.803071+00');
INSERT INTO public.holidays VALUES ('8d7f54a7-149b-4d53-8874-16e1076ec95a', '2026-01-01', 'Año Nuevo', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('7fce0d27-ae0a-404d-bdd2-f794f1427848', '2026-01-06', 'Reyes Magos', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('608c652f-3230-4121-b904-ab9997307731', '2026-04-03', 'Viernes Santo', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('3195dcc5-273e-4977-97f7-63964a184bf3', '2026-05-01', 'Día del Trabajo', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('d1bb967a-ec92-486a-807b-4263b48f9d8e', '2026-05-10', 'Día de la Madre', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('c8896e87-a347-492c-9790-5cea124fa963', '2026-08-15', 'Asunción de la Virgen', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('922bf34a-7b4b-4453-8b3d-f1be2caff23e', '2026-10-12', 'Fiesta Nacional', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('ab5d500f-7ef5-4108-b7da-ef7a990bcc6a', '2026-11-01', 'Todos los Santos', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('2bf558d0-7b32-4d12-a404-37815b52b75b', '2026-12-06', 'Día de la Constitución', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('d7c4b76d-dd37-4c3e-8cdf-0422b78bcea9', '2026-12-08', 'Inmaculada Concepción', true, '2026-05-10 15:04:32.143977+00');
INSERT INTO public.holidays VALUES ('62f3b30a-0b05-4675-8723-84a6e58de376', '2026-12-25', 'Navidad', true, '2026-05-10 15:04:32.143977+00');


--
-- Data for Name: policies; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.policies VALUES ('284ee1b6-7274-4430-8685-d202f62fb237', 'cancellation_threshold_hours', '{"description": "Minimum hours before appointment to allow cancellation without penalty", "threshold_hours": 24}', 'Cancellation threshold for appointments', '2026-04-19 16:35:42.153235+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('f82c4aa0-2818-4fe3-8cce-8c29cbcd361e', 'advance_payment_percentage', '{"description": "Percentage of total price required as anticipo for services requiring advance payment", "payment_percentage": 20}', 'Advance payment percentage for bookings', '2026-04-19 16:35:42.155287+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('d79ac806-9478-494d-9b13-c3d2d59c6107', 'provisional_timeout_standard', '{"description": "Minutes to hold provisional booking before expiration (standard bookings)", "timeout_minutes": 30}', 'Provisional booking timeout for standard bookings', '2026-04-19 16:35:42.156112+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('71b3b165-0055-4661-8436-c882b80688f9', 'provisional_timeout_same_day', '{"description": "Minutes to hold provisional booking before expiration (same-day bookings)", "timeout_minutes": 10}', 'Provisional booking timeout for same-day bookings', '2026-04-19 16:35:42.156921+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('15a1327c-fd64-4fb0-a5ff-bda870c8a76b', 'reminder_advance_hours', '{"description": "Hours before appointment to send reminder notification", "advance_hours": 48}', 'Reminder notification advance time', '2026-04-19 16:35:42.157698+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('813fff20-d2be-4b9e-8adb-87dd5005f218', 'faq_parking', '{"answer": "Tenemos parking gratuito en la calle trasera del salón", "keywords": ["parking", "aparcar", "coche"], "question": "¿Dónde puedo aparcar?"}', 'FAQ: Parking information', '2026-04-19 16:35:42.15848+00', '2026-04-19 16:35:58.972669+00');
INSERT INTO public.policies VALUES ('11023a8c-3c62-4dc1-a448-9fee91233b15', 'faq_location', '{"answer": "Estamos en C/ Olivar 2.  28100, Alcobendas (Madrid). Enlace a google maps: https://maps.app.goo.gl/iXWaUFVVzJbavboEA", "keywords": ["ubicación", "dirección", "dónde"], "question": "¿Dónde están ubicados?"}', 'FAQ: Salon location', '2026-04-19 16:35:42.159246+00', '2026-04-19 16:35:58.972669+00');


--
-- Data for Name: services; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.services VALUES ('370dd66d-74dd-bcbf-c7bc-607d0d47fb8f', 'Mechas Localizadas', 'HAIRDRESSING', 20, 'Mechas solo en zonas elegidas: sin full-head. Ideal para un toque de luz puntual (20 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "highlights", "service_type": "variant", "parent_service_name": "Mechas"}', NULL, NULL);
INSERT INTO public.services VALUES ('8d9a4e6c-f02a-42be-313f-fb6b77b9b546', 'Moldeado', 'HAIRDRESSING', 50, 'Moldeado capilar con productos profesionales para dar forma y textura al cabello', true, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', '{}', NULL, NULL);
INSERT INTO public.services VALUES ('47c71bb9-5ac0-6469-208d-7b8189c0e813', 'Infoactivo Fuerza', 'HAIRDRESSING', 30, 'Tratamiento que refuerza la fibra capilar desde la raíz. Para cabello debilitado (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('5f753100-934a-09b5-1500-58a8738639c9', 'Óleo Extra', 'HAIRDRESSING', 40, 'Tratamiento intensivo con óleos para cabello muy seco o químicamente dañado (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('6f42c88a-3784-79a9-d4b1-d7357fcab0cc', 'Tinte + Permanente de Pestañas', 'AESTHETICS', 90, 'Combina color + curvatura duradera en un solo turno. Más completo (90 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "eyelash", "service_type": "variant", "parent_service_name": "Tinte de Pestañas"}', NULL, NULL);
INSERT INTO public.services VALUES ('76f7caea-f53a-f260-0a30-efe8481b2f42', 'Recogido', 'HAIRDRESSING', 60, 'Peinado recogido para eventos especiales. Incluye diseño y fijación profesional (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "updo", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('7c71f92c-1dd1-20cf-320d-9318b50bf16f', 'Secado', 'HAIRDRESSING', 20, 'Secado profesional sin lavado. Para quienes ya vienen con el pelo mojado (20 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "blowdry", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('866747a0-495b-f770-5d10-6d9767ee9209', 'Masaje Corporal (30 min)', 'AESTHETICS', 30, 'Masaje relajante de 30 min para aliviar tensiones y descansar zonas específicas', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "massage", "service_type": "variant", "parent_service_name": "Masaje Corporal (60 min)"}', NULL, NULL);
INSERT INTO public.services VALUES ('734ded93-f640-bb34-eff6-813c4c8b6d20', 'Corte de Bebé', 'HAIRDRESSING', 20, 'Primer corte para bebés con técnica suave y paciencia extra. Rápido y sin tensiones (20 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('5539b349-78d8-e6a5-99a7-87db1b41a6e6', 'Barba', 'HAIRDRESSING', 15, 'Arreglo, perfilado y modelado de barba para un acabado limpio y definido (15 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 11:23:13.861505+00', '{"dimension": "cut", "service_type": "addon", "parent_service_name": null}', 'adult_male', NULL);
INSERT INTO public.services VALUES ('388c9655-12ed-a7b2-4df9-b3cc096a78f1', 'Perilla', 'HAIRDRESSING', 10, 'Perfilado de patillas con navaja. Acabado preciso para un look prolijo (10 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 11:23:13.861505+00', '{"dimension": "cut", "service_type": "addon", "parent_service_name": null}', 'adult_male', NULL);
INSERT INTO public.services VALUES ('24d6074b-fc24-f426-13e7-c365856ce8f0', 'Mechas Extras', 'HAIRDRESSING', 70, 'Mechas completas para cabello con más volumen o largo extra. 10 min más que Mechas estándar (70 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "highlights", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('469d07e5-a207-dbd1-6716-5ad619c6a34c', 'Piernas Perfectas + Presoterapia (30 min)', 'AESTHETICS', 90, 'Drenaje + descongestión + reafirmación de piernas. Combinado con presoterapia (90 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "body_contour", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('8ad44531-6a60-366c-009d-9fa006b7c98f', 'Infoactivo Sensitivo', 'HAIRDRESSING', 30, 'Calma el cuero cabelludo sensible o irritado y lo protege (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('99797892-7a22-e447-8f57-f1afc35ff7b9', 'Barro Gold', 'HAIRDRESSING', 40, 'Tratamiento con barro que aporta tonos dorados cálidos mientras nutre (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "variant", "parent_service_name": "Barro"}', NULL, NULL);
INSERT INTO public.services VALUES ('a2ae9e5c-3e8e-12d7-a856-e3ac29aa3e7b', 'Tratamiento Precolor', 'HAIRDRESSING', 5, 'Preparación del cabello antes de la coloración para potenciar el resultado (5 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "color", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('a68c927c-da18-797a-18c1-f0497122f697', 'Semirecogido', 'HAIRDRESSING', 40, 'Recogido parcial para looks elegantes sin estructuras rígidas (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "updo", "service_type": "variant", "parent_service_name": "Recogido"}', NULL, NULL);
INSERT INTO public.services VALUES ('e0a77bcb-4028-7ed0-2115-66a43fe75dc2', 'Moldeado Extra', 'HAIRDRESSING', 70, 'Moldeado para cabello largo o muy denso. Más tiempo de proceso que el estándar (70 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "hairstyle", "service_type": "variant", "parent_service_name": "Peinado"}', NULL, NULL);
INSERT INTO public.services VALUES ('e311902e-73b6-2d2a-b19e-c46f6846ca9c', 'Peinado', 'HAIRDRESSING', 40, 'Lavado + secado con forma para cabello corto/medio. El estilo del día a día (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "hairstyle", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('e47b8a73-a8f7-1ff1-7a20-135acc452125', 'Agua Lluvia', 'HAIRDRESSING', 25, 'Hidratación intensa que aporta suavidad y brillo sin pesar el cabello (25 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('e482f13f-0052-8182-c625-f3f19fd86ed4', 'Maquillaje', 'AESTHETICS', 60, 'Maquillaje profesional para eventos y fiestas. Adaptado a tu estilo y ocasión (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "makeup", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('a59f4ae2-596a-af5e-7d73-4ea3ce023b3c', 'Recogido de Novia', 'HAIRDRESSING', 120, 'Recogido completo de novia: prueba previa y ejecución el día del evento (120 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "updo", "service_type": "variant", "parent_service_name": "Recogido"}', NULL, NULL);
INSERT INTO public.services VALUES ('29576d22-b572-a406-18ce-6398f29f0513', 'Mechas', 'HAIRDRESSING', 60, 'Mechas completas con lavado y procesado. Para cabello normal (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-22 13:25:44.877318+00', '{"dimension": "highlights", "service_type": "principal", "parent_service_name": null}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('c6598943-f686-a232-31fa-095f1147d4f9', 'Peinado de Comunión', 'HAIRDRESSING', 70, 'Peinado de gala para niñas en su Primera Comunión. Diseño elegante y duradero (70 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "hairstyle", "service_type": "variant", "parent_service_name": "Peinado"}', 'child_female', NULL);
INSERT INTO public.services VALUES ('cb7ae91c-97ff-e1d1-3b0b-696b11467add', 'Corte de Mujer', 'HAIRDRESSING', 40, 'Corte de dama con lavado, corte y secado incluidos. Longitud estándar (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:48:36.0679+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('c6d8e772-1e99-3b4d-a7f5-0e7af142875b', 'Depilación de Brazos Enteros o Pecho', 'AESTHETICS', 30, 'Depilación con cera de brazos completos o zona del pecho a elegir (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('94577ac8-9814-a06f-712b-f97f124fce72', 'Corte de Flequillo', 'HAIRDRESSING', 15, 'Recorte y modelado del flequillo. Sin lavado ni secado, ideal para un retoque rápido (15 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 11:23:13.861505+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('a0851913-d268-e750-68fa-b11f337762ff', 'Barro Extra', 'HAIRDRESSING', 40, 'Barro intensivo para cabello con alta densidad o daño avanzado (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('d5e9f10a-9c36-d7e1-28a1-0d205016e772', 'Tratamiento Facial + Radiofrecuencia (15 min)', 'AESTHETICS', 75, 'Facial + 15 min de radiofrecuencia para reafirmar y rejuvenecer la piel (75 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "facial", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('db6ab654-132a-8ff6-371b-d8d0b1d733e6', 'Barro Gold Extra', 'AESTHETICS', 40, 'Tratamiento facial con barro dorado extra para nutrición profunda y luminosidad (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "facial", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('4c9907c5-80eb-019b-8a5f-1b8ea2738f71', 'Agua Tierra', 'HAIRDRESSING', 25, 'Detox capilar: purifica el cuero cabelludo y reduce el exceso de grasa (25 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('7e57cd7a-9af5-1162-4d7e-4b9c7fe9982b', 'Mechas Localizadas Exprés', 'HAIRDRESSING', 15, 'Versión express de Mechas Localizadas. Resultado rápido en zonas puntuales (15 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "highlights", "service_type": "variant", "parent_service_name": "Mechas"}', NULL, NULL);
INSERT INTO public.services VALUES ('590d0e0c-9a02-57ad-0124-13674ac32ef5', 'Corte de Niño', 'HAIRDRESSING', 30, 'Corte con lavado y secado para niños. Estilo y comodidad pensados para los más activos (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', 'child_male', NULL);
INSERT INTO public.services VALUES ('39251edd-8ac0-efb3-9836-fa744baa08cc', 'Corte de Hombre', 'HAIRDRESSING', 40, 'Corte de caballero con lavado y secado. Incluye modelado y acabado profesional (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', 'adult_male', NULL);
INSERT INTO public.services VALUES ('558e5d12-9a63-155d-c2d1-0aac92a3cdfe', 'Exfoliación Corporal', 'AESTHETICS', 60, 'Peeling corporal: exfoliación profunda que elimina células muertas y renueva la textura de la piel (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "body_treatment", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('52719909-edb9-fffb-3e99-1f9957566e06', 'Maquillaje Exprés', 'AESTHETICS', 30, 'Maquillaje rápido y prolijo para el día a día. Resultado fresco en 30 min', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "makeup", "service_type": "variant", "parent_service_name": "Maquillaje"}', NULL, NULL);
INSERT INTO public.services VALUES ('763b7823-8c85-3ad6-6f66-87c6601a5fb3', 'Retirada de Esmalte Permanente', 'AESTHETICS', 25, 'Quitar esmalte semipermanente de uñas de forma segura, sin dañar la uña natural (25 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "manicure", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('7905e111-6193-e949-088c-6c77522c3d02', 'Tratamiento Anticelulítico Completo', 'AESTHETICS', 60, 'Tratamiento Sculptor anticelulítico completo: reduce nódulos, drena y combate la retención de líquidos (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "body_contour", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('cc30a1c4-b1c7-56f4-2f19-14a88a6f09b1', 'Manicura', 'AESTHETICS', 30, 'Limar uñas + esmaltado tradicional de manos. Dura aproximadamente 1 semana (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "manicure", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('d9f8705f-7785-b210-20a3-649561f0d89f', 'Depilación', 'AESTHETICS', 40, 'Depilación con cera. Elige la zona corporal (40 min para piernas enteras)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:53:39.38019+00', '{"dimension": "wax", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('7abe2fe3-5b47-eb8c-64da-dd4a82b759e0', 'Depilación de Cejas', 'AESTHETICS', 15, 'Diseño y depilación con cera. Da forma y limpia el contorno para enmarcar la mirada (15 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('6643ea81-7f5b-9a89-24e2-63ab01541b50', 'Depilación de Ingles o Axilas', 'AESTHETICS', 30, 'Depilación con cera de ingles o axilas a elección. Piel lisa y sin irritación (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('b5aa7faf-ab07-2e0e-08ad-5e8d99fdcf4f', 'Depilación de Abdomen, Glúteos, Espalda o Pecho', 'AESTHETICS', 30, 'Depilación con cera de una zona a elegir. Resultado limpio y prolijo (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('44ccc4ea-a3e7-7493-a5f4-e41726e3dd38', 'Tinte Extra', 'HAIRDRESSING', 50, 'Cultura de Color extendida para cabello muy denso o cambios de tono importantes (50 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "color", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('10e3e5dd-57aa-8d69-ec84-d2d47525465f', 'Tinte', 'HAIRDRESSING', 40, 'Cultura de Color: coloración completa con lavado, aplicación y resultado uniforme. Cabello normal (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:53:39.38019+00', '{"dimension": "color", "service_type": "principal", "parent_service_name": null}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('a7ea4022-d969-47c9-a8cb-edfd12bf4359', 'Piernas Enteras', 'AESTHETICS', 40, 'Depilación con cera de piernas enteras: desde tobillo hasta ingle (40 min)', true, '2026-05-11 07:53:39.38019+00', '2026-05-11 07:53:39.38019+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('09f76e50-7cef-7773-c89e-501011977543', 'Depilación de Antebrazo', 'AESTHETICS', 30, 'Depilación con cera de medio brazo: antebrazo o parte superior a elegir (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('08bddf70-8259-8725-a0a3-570e80c42b8d', 'Depilación de Media Pierna', 'AESTHETICS', 30, 'Depilación con cera de media pierna: pantorrilla o muslo a elegir (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('07da818a-a0fb-30e8-2d28-b9bfbdbe5e23', 'Peinado Extra', 'HAIRDRESSING', 70, 'Lavado + secado para cabello muy largo o con mucho volumen. Versión más extensa (70 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "hairstyle", "service_type": "variant", "parent_service_name": "Peinado"}', NULL, NULL);
INSERT INTO public.services VALUES ('056b1e73-846c-8421-4e95-2786c0235c88', 'Depilación de Muslos', 'AESTHETICS', 30, 'Depilación con cera de la zona de los muslos. Completa la media pierna (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('08d22b4e-3076-7785-7a6a-8a08e4c22b79', 'Peinado Largo', 'HAIRDRESSING', 45, 'Lavado + secado con forma para cabello largo. Más tiempo de trabajo (45 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "hairstyle", "service_type": "variant", "parent_service_name": "Peinado"}', NULL, NULL);
INSERT INTO public.services VALUES ('108d88c8-1cc7-d1f4-ec36-77486bf63cb1', 'Pedicura Permanente', 'AESTHETICS', 40, 'Limar uñas + esmaltado semipermanente de pies. Durabilidad de hasta 3 semanas (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "pedicure", "service_type": "variant", "parent_service_name": "Pedicura"}', NULL, NULL);
INSERT INTO public.services VALUES ('0e952bd3-bc20-e3fd-a354-88393473e588', 'Permanente de Pestañas', 'AESTHETICS', 40, 'Curvatura duradera para las pestañas sin rizador. Resultado natural (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "eyelash", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('01e9680d-5e1b-c271-0994-ef1a16409d50', 'Color para Hombre', 'HAIRDRESSING', 30, 'Cultura de Color específica para caballeros. Cubre canas con resultado natural (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "color", "service_type": "principal", "parent_service_name": null}', 'adult_male', NULL);
INSERT INTO public.services VALUES ('13258273-41df-f9c3-9362-a7bfb1226bff', 'Corte de Niña', 'HAIRDRESSING', 30, 'Corte con lavado y secado para niñas. Técnicas adaptadas a su edad y tipo de cabello (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "cut", "service_type": "principal", "parent_service_name": null}', 'child_female', NULL);
INSERT INTO public.services VALUES ('0248a4df-e050-ac26-b16a-5a1d1c30decb', 'Maquillaje de Novia', 'AESTHETICS', 70, 'Maquillaje de novia con prueba previa. Duración garantizada durante todo el evento (70 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "makeup", "service_type": "variant", "parent_service_name": "Maquillaje"}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('068c2468-0e76-bb33-6e3c-36ecfcb742ed', 'Pedicura', 'AESTHETICS', 30, 'Limar uñas + esmaltado tradicional de pies. Dura aproximadamente 1 semana (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "pedicure", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('0c1a5afb-df01-baa9-b284-c0a84906f825', 'Tratamiento de Manos', 'AESTHETICS', 45, 'Tratamiento bioterapéutico de manos: hidratación y revitalización intensiva. No incluye esmaltado (45 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "hand_treatment", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('68e46df4-ccd2-393a-7cf5-90ea2b95454e', 'Depilación de Pubis Completo', 'AESTHETICS', 30, 'Depilación con cera de la zona del pubis al completo (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('d5d3d368-4c04-bf9c-a306-dcb7dcbb23b5', 'Depilación Brasileña', 'AESTHETICS', 30, 'Depilación con cera de ingles brasileñas: elimina todo el vello de la zona íntima (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('96548a2a-fc10-30c3-8d53-c7d323487db4', 'Depilación de Labio', 'AESTHETICS', 10, 'Depilación con cera del labio superior. Resultado suave y duradero (10 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('9921b5f7-b48e-f3fe-b94a-ef24c18da613', 'Manicura Permanente con Tratamiento', 'AESTHETICS', 90, 'Limar uñas + esmaltado semipermanente + tratamiento hidratante de manos en un solo turno (90 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "manicure", "service_type": "variant", "parent_service_name": "Manicura"}', NULL, NULL);
INSERT INTO public.services VALUES ('dfefc36d-070f-ff40-4835-60b5b28cb825', 'Manicura Permanente', 'AESTHETICS', 40, 'Limar uñas + esmaltado semipermanente de manos. Durabilidad de hasta 3 semanas (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "manicure", "service_type": "variant", "parent_service_name": "Manicura"}', NULL, NULL);
INSERT INTO public.services VALUES ('31f591a2-53f4-88a3-c60c-950f3857d2e0', 'Pedicura Permanente con Tratamiento', 'AESTHETICS', 75, 'Pedicura completa + esmaltado semipermanente + tratamiento hidratante de pies en un turno (75 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "pedicure", "service_type": "variant", "parent_service_name": "Pedicura"}', NULL, NULL);
INSERT INTO public.services VALUES ('613f5c9d-58b8-240c-0cd0-55da96564379', 'Bono Tratamiento de Senos', 'AESTHETICS', 60, 'Pack de sesiones del tratamiento bioterapéutico de senos para un resultado más progresivo y duradero (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "body_treatment", "service_type": "variant", "parent_service_name": "Tratamiento de Senos"}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('d31cdeaf-5ba8-1ec6-5a05-652d274e233d', 'Manicura de Hombre', 'AESTHETICS', 30, 'Manicura específica para caballeros: limado, arreglo de cutículas e hidratación. Sin esmalte (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 11:23:13.861505+00', '{"dimension": "manicure", "service_type": "principal", "parent_service_name": null}', 'adult_male', NULL);
INSERT INTO public.services VALUES ('2395f8c8-2d44-125e-058c-1b7d6a1d9ebc', 'Tratamiento Anticelulítico + Radiofrecuencia (30 min)', 'AESTHETICS', 90, 'Sculptor + 30 min de radiofrecuencia para resultados anticelulíticos potenciados (90 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "body_contour", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('e764e68d-ddba-ae39-35c6-f23345266b0c', 'Óleo Pigmento', 'HAIRDRESSING', 30, 'Regula la porosidad y equilibra el pH. Deja el cabello brillante y manejable (30 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('ebb7e494-f189-b020-e749-5c7a57e9fe3e', 'Prepigmentar', 'HAIRDRESSING', 10, 'Prepigmentación: permite aplicar colores oscuros sobre cabello muy aclarado (10 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "color", "service_type": "addon", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('ebf81fc5-91f9-6bcc-9ae7-100d790e2e4b', 'Tinte de Pestañas', 'AESTHETICS', 40, 'Da color oscuro y duradero a las pestañas naturales. Sin extensiones (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "eyelash", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('f380a789-c6a8-d18b-20e9-653c38902937', 'Barro', 'HAIRDRESSING', 40, 'Tratamiento nutritivo con barro natural: cierra la cutícula y da brillo duradero (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "treatment", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('fdbda36d-2501-86fe-3bcd-d87d293dfb9e', 'Masaje Corporal (60 min)', 'AESTHETICS', 60, 'Masaje de cuerpo completo de 60 min. Profunda relajación y alivio muscular (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-20 00:11:31.721826+00', '{"dimension": "massage", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('e4a00383-c692-d3a2-2fb2-ccd0f5143f54', 'Tratamiento Facial', 'AESTHETICS', 60, 'Bioterapia facial personalizada según el tipo de piel: limpieza, nutrición y equilibrio (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "facial", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('fe4f4bed-5afa-92ee-5bc0-7c752194c4ca', 'Limpieza de Espalda', 'AESTHETICS', 60, 'Higiene profunda de la espalda: extracción de impurezas, granos y limpieza de poros (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "body_treatment", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('e5ab3a0f-72c6-a6b7-8864-6a06970e3436', 'Tratamiento de Senos', 'AESTHETICS', 60, 'Bioterapia de senos: tratamiento natural que mejora tonicidad e hidratación de la zona del busto (60 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "body_treatment", "service_type": "principal", "parent_service_name": null}', 'adult_female', NULL);
INSERT INTO public.services VALUES ('f33c4305-6c5a-0c4a-1a51-c328e5febb8d', 'Tratamiento de Pies', 'AESTHETICS', 40, 'Tratamiento bioterapéutico podal: hidrata, revitaliza y alivia la fatiga. No incluye esmaltado (40 min)', true, '2026-04-19 16:34:54.095623+00', '2026-04-28 09:47:42.285125+00', '{"dimension": "foot_treatment", "service_type": "principal", "parent_service_name": null}', NULL, NULL);
INSERT INTO public.services VALUES ('fe7423fe-3292-c404-e122-78cde0449680', 'Depilación de Medio Brazo', 'AESTHETICS', 20, 'Depilación con cera de media brazo. Variante más rápida sin incluir codo (20 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 07:56:47.673477+00', '{"dimension": "wax", "service_type": "variant", "parent_service_name": "Depilación"}', NULL, NULL);
INSERT INTO public.services VALUES ('fdf7b7de-a330-345d-564a-fe8daace8371', 'Tratamiento Facial + Radiofrecuencia (30 min)', 'AESTHETICS', 90, 'Facial + 30 min de radiofrecuencia. Máxima potencia anti-edad (90 min)', true, '2026-04-19 16:34:54.095623+00', '2026-05-11 12:53:22.458849+00', '{"dimension": "facial", "service_type": "addon", "parent_service_name": null}', NULL, NULL);


--
-- Data for Name: system_settings; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.system_settings VALUES ('0c53b3ef-e4ae-4946-9924-b1648b7d3d08', 'booking', 'max_pending_appointments_per_customer', '3', 'int', '3', '1', '10', NULL, 'Citas pendientes máx. por cliente', 'Número máximo de citas futuras (pendientes o confirmadas) que un cliente puede tener activas. Solo aplica a reservas desde WhatsApp.', false, 15, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('dccd0524-49b3-4adf-8072-5c9267f23f96', 'confirmation', 'confirmation_job_time', '"10:00"', 'string', '"10:00"', NULL, NULL, NULL, 'Hora de envío de confirmaciones', 'Hora del día (HH:MM) en que se envían las solicitudes de confirmación de citas. Formato 24h.', true, 1, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('d80b04c4-9370-43ab-b9c6-cb22f6a75565', 'confirmation', 'auto_cancel_job_time', '"10:00"', 'string', '"10:00"', NULL, NULL, NULL, 'Hora de cancelaciones automáticas', 'Hora del día (HH:MM) en que se procesan las cancelaciones automáticas de citas no confirmadas.', true, 2, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('9fa36f64-bfcc-457f-ad52-93e7d22e2b1e', 'confirmation', 'reminder_job_interval', '"hourly"', 'enum', '"hourly"', NULL, NULL, '["hourly", "30min"]', 'Intervalo de recordatorios', 'Con qué frecuencia se ejecuta el job de envío de recordatorios.', true, 3, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('646b929a-009c-4c8a-b35a-442508ed8c41', 'confirmation', 'confirmation_hours_before', '48', 'int', '48', '24', '72', NULL, 'Horas antes para confirmar', 'Cuántas horas antes de la cita se envía la solicitud de confirmación.', false, 4, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('b2d19bee-f03b-4e8c-be32-f07b6805c2f5', 'confirmation', 'auto_cancel_hours_before', '24', 'int', '24', '12', '48', NULL, 'Horas antes para cancelar', 'Cuántas horas antes de la cita se cancela automáticamente si no fue confirmada.', false, 5, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('7c7445fb-aeee-4f77-b704-f80a54e7aa00', 'confirmation', 'reminder_hours_before', '2', 'int', '2', '1', '24', NULL, 'Horas antes para recordatorio', 'Cuántas horas antes de la cita se envía el recordatorio final.', false, 6, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('9ee833b4-3fe5-4d61-9342-a8eb4623bc15', 'confirmation', 'confirmation_template_name', '"appointment_confirmation_48h"', 'string', '"appointment_confirmation_48h"', NULL, NULL, NULL, 'Template de confirmación', 'Nombre del template de Chatwoot para solicitudes de confirmación.', false, 7, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('836e518a-a9b9-41d0-a02b-07ba545d0042', 'confirmation', 'auto_cancel_template_name', '"appointment_auto_cancelled"', 'string', '"appointment_auto_cancelled"', NULL, NULL, NULL, 'Template de cancelación', 'Nombre del template de Chatwoot para notificaciones de cancelación automática.', false, 8, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('1e346ba3-ad10-4397-9adc-e4c689bf29f6', 'confirmation', 'reminder_template_name', '"appointment_reminder_2h"', 'string', '"appointment_reminder_2h"', NULL, NULL, NULL, 'Template de recordatorio', 'Nombre del template de Chatwoot para recordatorios de cita.', false, 9, '2026-04-19 16:34:54.095623+00', '2026-04-19 16:34:54.095623+00', NULL);
INSERT INTO public.system_settings VALUES ('5ee3fb89-fef7-4221-9348-0440a6e45a77', 'ai_control', 'ai_agent_enabled', 'true', 'boolean', 'true', NULL, NULL, NULL, 'Agente IA Activo', 'Activa o desactiva a Maite en todas las conversaciones de WhatsApp. Al desactivar, los mensajes entrantes serán ignorados por la IA y deberán ser atendidos manualmente desde Chatwoot.', false, 0, '2026-04-19 16:35:17.428694+00', '2026-04-19 16:35:17.428694+00', NULL);
INSERT INTO public.system_settings VALUES ('1fde4c18-95ac-409b-8b94-1a97fcf8ee80', 'confirmation', 'whatsapp_template_confirm_48h', '"atrevete_confirm_48h"', 'string', '"atrevete_confirm_48h"', NULL, NULL, NULL, 'Plantilla WhatsApp — Confirmación 48h', 'Nombre de la plantilla HSM aprobada en Chatwoot para el envío de confirmación 48h antes.', false, 50, '2026-04-26 16:10:04.689414+00', '2026-04-26 16:10:04.689414+00', NULL);
INSERT INTO public.system_settings VALUES ('ed1640c0-d312-41c2-b080-99b93684f7db', 'confirmation', 'whatsapp_template_reminder_24h', '"atrevete_reminder_24h"', 'string', '"atrevete_reminder_24h"', NULL, NULL, NULL, 'Plantilla WhatsApp — Recordatorio 24h', 'Nombre de la plantilla HSM aprobada en Chatwoot para el recordatorio 24h antes de la cita.', false, 51, '2026-04-26 16:10:04.689414+00', '2026-04-26 16:10:04.689414+00', NULL);
INSERT INTO public.system_settings VALUES ('1867a98a-13e0-4f8d-bf50-0395bd733812', 'confirmation', 'whatsapp_template_admin_booking', '"appointment_booked_by_admin"', 'string', '"appointment_booked_by_admin"', NULL, NULL, NULL, 'Plantilla WhatsApp — Reserva por Admin', 'Nombre de la plantilla HSM aprobada en Chatwoot para notificar al cliente cuando el admin crea una cita.', false, 52, '2026-04-26 16:10:04.689414+00', '2026-04-26 16:10:04.689414+00', NULL);
INSERT INTO public.system_settings VALUES ('5e23326d-ddeb-4eca-9e10-08b803f7fe5d', 'booking', 'minimum_booking_days_advance', '3', 'int', '3', '0', '14', 'null', 'Días mínimos de antelación', 'Número mínimo de días de antelación requeridos para hacer una reserva.', false, 10, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('77e7304e-fcf1-4c40-b54e-989914744467', 'booking', 'same_day_buffer_hours', '1', 'int', '1', '0', '6', 'null', 'Buffer para mismo día (horas)', 'Horas mínimas de antelación para reservas del mismo día.', false, 11, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('cd170daf-2dfc-4e81-b4ee-14d3d5af3265', 'booking', 'max_slots_to_present', '3', 'int', '3', '1', '10', 'null', 'Máximo de slots a mostrar', 'Número máximo de slots de disponibilidad a presentar al cliente.', false, 12, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('19289489-9e0b-441f-81c6-7ff28984ea73', 'booking', 'buffer_minutes_between_appointments', '0', 'int', '0', '0', '30', 'null', 'Buffer entre citas (minutos)', 'Minutos de buffer entre citas consecutivas.', false, 13, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('4c989fac-8bae-4540-b293-bdf28c987e0a', 'booking', 'default_service_duration_minutes', '90', 'int', '90', '30', '180', 'null', 'Duración por defecto (minutos)', 'Duración por defecto de un servicio si no está especificada.', false, 14, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('fd04b12f-855a-47fd-9b43-22e1596f9c92', 'booking', 'cancellation_window_hours', '48', 'int', '48', '1', '168', 'null', 'Ventana de cancelación (horas)', 'Horas mínimas de antelación requeridas para cancelar una cita por WhatsApp. Si la cita está más próxima, el cliente debe contactar al equipo.', false, 16, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('2d01343f-10b8-4c16-aa26-a07dbaa5d6cc', 'llm', 'llm_model', '"openai/gpt-5.4-mini"', 'string', '"openai/gpt-5.4-mini"', 'null', 'null', 'null', 'Modelo LLM', 'Modelo de lenguaje a utilizar (formato OpenRouter: provider/model).', false, 15, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('74645f74-3136-43fb-8251-b895db2f5bea', 'llm', 'intent_extraction_temperature', '0.1', 'float', '0.1', '0.0', '1.0', 'null', 'Temperatura extracción de intención', 'Temperatura del LLM para extracción de intención (menor = más determinista).', false, 16, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('72ae9e29-3811-4a50-8860-a3c4f376eb79', 'llm', 'conversational_temperature', '0.3', 'float', '0.3', '0.0', '1.0', 'null', 'Temperatura conversacional', 'Temperatura del LLM para respuestas conversacionales.', false, 17, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('c54c81f8-4b82-4ff5-aead-948ff917d6bb', 'llm', 'summarization_temperature', '0.3', 'float', '0.3', '0.0', '1.0', 'null', 'Temperatura resumen', 'Temperatura del LLM para generación de resúmenes.', false, 18, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('4f3f2a0e-db6a-4660-af83-2ca57cb4a7a8', 'llm', 'llm_request_timeout_seconds', '30', 'int', '30', '5', '120', 'null', 'Timeout de requests (segundos)', 'Tiempo máximo de espera para respuestas del LLM.', false, 19, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('ad1f64dc-552c-4ed0-9e1b-87a4de9e8935', 'llm', 'llm_max_retries', '2', 'int', '2', '0', '5', 'null', 'Reintentos máximos', 'Número máximo de reintentos ante fallos del LLM.', false, 20, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('9888e77a-aca5-44c9-a3ae-66dcf1b7b69b', 'rate_limiting', 'rate_limit_requests_per_minute', '10', 'int', '10', '5', '100', 'null', 'Requests por minuto', 'Límite de requests por minuto por usuario/IP.', false, 21, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('d622706b-a025-442b-9de2-1d7e63e5c1a1', 'rate_limiting', 'login_max_attempts', '5', 'int', '5', '3', '20', 'null', 'Intentos máximos de login', 'Número máximo de intentos de login antes de bloquear.', false, 22, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('792348cd-ff63-40bd-bfbd-5b4ad4762106', 'rate_limiting', 'login_lockout_minutes', '5', 'int', '5', '1', '60', 'null', 'Tiempo de bloqueo (minutos)', 'Duración del bloqueo tras exceder intentos de login.', false, 23, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('63f8904b-2a38-480d-b4b8-3ff5bf4b51df', 'cache', 'stylist_cache_ttl_seconds', '600', 'int', '600', '60', '3600', 'null', 'Cache de estilistas (segundos)', 'TTL del cache de información de estilistas.', false, 24, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('75d2346a-40f5-4c1d-ae7b-7667e1910482', 'cache', 'message_batch_window_seconds', '30', 'int', '30', '0', '120', 'null', 'Ventana de batch mensajes (segundos)', 'Tiempo para agrupar mensajes consecutivos del mismo usuario.', false, 25, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('80d34d9b-1bd0-4dff-94a9-0fee4f47dd19', 'cache', 'max_messages_in_state', '10', 'int', '10', '5', '20', 'null', 'Máximo mensajes en estado', 'Número máximo de mensajes a mantener en el estado antes de resumir.', false, 26, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('dc8e7d6d-ad8b-49a6-b948-41b76a156314', 'archival', 'archival_cutoff_hours', '23', 'int', '23', '12', '24', 'null', 'Horas para archivar', 'Horas de inactividad tras las cuales se archiva una conversación.', false, 27, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('6a16897e-d1a1-4795-8f05-4231fedfb6e8', 'archival', 'archival_max_retry_attempts', '2', 'int', '2', '1', '5', 'null', 'Reintentos de archivado', 'Número máximo de reintentos para archivar una conversación.', false, 28, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('3bb11297-2a80-4da1-8d20-171ad5b99ed5', 'gcal_sync', 'gcal_sync_interval_minutes', '5', 'int', '5', '1', '60', 'null', 'Intervalo de sincronización (minutos)', 'Cada cuántos minutos se sincroniza con Google Calendar. Menor = más actualizado pero más uso de API.', true, 29, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);
INSERT INTO public.system_settings VALUES ('6c651b7f-4b00-499b-af1f-a76232556d75', 'gcal_sync', 'gcal_sync_enabled', 'true', 'boolean', 'true', 'null', 'null', 'null', 'Sincronización habilitada', 'Habilitar/deshabilitar la sincronización bidireccional con Google Calendar.', false, 30, '2026-04-27 17:22:49.739918+00', '2026-04-27 17:22:49.739918+00', NULL);


--
-- PostgreSQL database dump complete
--

\unrestrict 9IJUZlFAdS6xCPw2IvhFGGbPtZ5ooBiIFAlcU7DQ5uacj2ciEqaygt0HMoNJyA3

