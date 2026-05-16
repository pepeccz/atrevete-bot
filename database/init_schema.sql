--
-- PostgreSQL database dump
--

\restrict 6LKyvPRFqAKZhCxdT0cwkBYFLlCdG0K9tvQJNkl28IRRW2I6YIxaO9DbT5gPiwM

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

\unrestrict 6LKyvPRFqAKZhCxdT0cwkBYFLlCdG0K9tvQJNkl28IRRW2I6YIxaO9DbT5gPiwM

--
-- PostgreSQL database dump
--

\restrict dGPK3MyPZo5DLDYpvYB2gt07ODZLaJeHt6kmWprf8gZlHbaR7uqgFr2lJqxLskP

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
-- PostgreSQL database dump complete
--

\unrestrict dGPK3MyPZo5DLDYpvYB2gt07ODZLaJeHt6kmWprf8gZlHbaR7uqgFr2lJqxLskP

