# AGENTS.md — Atrévete Bot

## Repository Overview

**Atrévete Bot** is an AI-powered WhatsApp booking assistant for a beauty salon. It handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using a DB-first calendar architecture with Google Calendar as a push-only mirror.

### Tech Stack

| Component | Technology |
|-----------|------------|
| **Agent** | Python 3.11+, LangGraph 0.6.7+, LangChain 0.3.0+ |
| **LLM** | GPT-5.4-mini via OpenRouter (openai/gpt-5.4-mini) |
| **API** | FastAPI 0.116.1, Pydantic 2.x, Uvicorn 0.30.0+ |
| **Database** | PostgreSQL 15+, SQLAlchemy 2.0+ (asyncpg), Alembic 1.13+ |
| **Cache** | Redis Stack (RedisSearch, RedisJSON) |
| **Admin Panel** | Next.js 15.0.3 (App Router), React 18.3.1, Tailwind CSS |
| **External APIs** | Google Calendar API, Chatwoot API |
| **Testing** | pytest 8.3.0+, pytest-asyncio 0.24.0+ |
| **Code Quality** | black (line length 100), ruff, mypy |

### Key External Dependencies

- Google Calendar API (5 stylist calendars)
- Chatwoot API (WhatsApp integration)
- OpenRouter API (LLM gateway)
- PostgreSQL 15+ (data persistence)
- Redis Stack (checkpointing + RedisSearch/RedisJSON for LangGraph)

---

## Documentation Precedence

When guidance conflicts, follow this hierarchy (highest priority first):

```
1. CLAUDE.md (operational details) >
2. AGENTS.md (repository governance) >
3. Component AGENTS.md (component-specific) >
4. skills/* (pattern libraries)
```

### Boundary Rules

| Question | Where to Look |
|----------|---------------|
| How do I run tests? | **CLAUDE.md** (commands) |
| What's the database schema? | **CLAUDE.md** (models) |
| How do I add a new agent mode? | **agent/AGENTS.md** → **atrevete-agent** skill |
| How do I create a migration? | **database/AGENTS.md** → **atrevete-database** skill |
| What's the project architecture? | **AGENTS.md** (this file) |
| How do I write a FastAPI route? | **api/AGENTS.md** → **atrevete-api** skill |
| How do I style React components? | **atrevete-admin** skill → **tailwind-4** skill |

### Decision Tree

```
Need operational command (docker, test, migrate)?
  → CLAUDE.md

Need repository structure or navigation?
  → AGENTS.md (this file)

Working on a specific component?
  → Component AGENTS.md (agent/, api/, database/)

Need detailed patterns or examples?
  → skills/* (auto-invoked based on context)
```

---

## Project Navigation

```
atrevete-bot/
├── AGENTS.md              # This file — repository governance
├── CLAUDE.md              # Operational guide — READ THIS FIRST
├── README.md              # Project overview and quick start
│
├── api/                   # FastAPI webhook receiver
│   ├── AGENTS.md          # API-specific guidance
│   ├── main.py            # FastAPI app factory
│   ├── models/            # Pydantic models
│   ├── routes/            # API endpoints
│   │   ├── chatwoot.py    # Chatwoot webhook handler
│   │   └── admin.py       # Admin API endpoints
│   ├── services/          # Business logic
│   └── middleware/        # CORS, logging, rate limiting
│
├── agent/                 # create_agent + 7 middleware orchestrator (SSOT: agent/agent_factory.py:47-55)
│   ├── AGENTS.md          # Agent-specific guidance
│   ├── main.py            # Redis Streams consumer
│   ├── graph.py           # Thin wrapper → build_conversation_agent()
│   ├── agent_factory.py   # build_conversation_agent: create_agent + tools + middleware
│   ├── middleware/        # 7 base middlewares in execution order (agent/agent_factory.py:47-55)
│   │   ├── disclosure.py           # DisclosureMiddleware
│   │   ├── customer_resolve.py     # CustomerResolveMiddleware
│   │   ├── appointment_context.py  # AppointmentContextMiddleware
│   │   ├── dynamic_prompt.py       # DynamicPromptMiddleware
│   │   ├── availability_context.py # AvailabilityContextMiddleware
│   │   ├── prompt_assembly.py      # PromptAssemblyMiddleware
│   │   └── summarize.py            # SummarizeMiddleware
│   ├── tools/             # 6 LangChain tools
│   │   ├── check_availability.py
│   │   ├── next_available.py          # get_next_available_options
│   │   ├── book.py                    # atomic create + GCal push
│   │   ├── update_booking.py          # mutate active draft
│   │   ├── manage_appointments_tool.py # view/cancel/reschedule
│   │   └── escalation_tools.py
│   ├── prompts/           # Base prompt + dynamic loaders
│   │   └── shared/        # Core prompts (identity, rules, glossary, booking_flow)
│   ├── services/          # Business logic (availability, GCal push)
│   └── workers/           # Background workers (archiver)
│
├── database/              # SQLAlchemy models & Alembic migrations
│   ├── AGENTS.md          # Database-specific guidance
│   ├── models.py          # 9 core models + calendar models
│   ├── connection.py      # Async engine and session factory
│   ├── alembic/           # Migration files
│   └── seeds/             # Data seeding
│
├── admin-panel/           # Next.js 15 admin interface
│   ├── src/
│   │   ├── app/           # Next.js App Router
│   │   ├── components/    # React components
│   │   ├── contexts/      # Auth context
│   │   ├── hooks/         # Custom hooks
│   │   └── lib/           # API client, types
│   └── package.json
│
├── shared/                # Shared utilities
│   ├── config.py          # Pydantic Settings (env vars)
│   ├── chatwoot_client.py # Chatwoot API client
│   ├── redis_client.py    # Redis connection
│   └── logging_config.py  # Structured logging
│   # circuit_breaker.py intentionally removed — deletion guard: tests/unit/test_dead_code_cleanup_assertions.py:52
│   # Degradation strategy: docs/system/07-resilience.md
│
├── tests/                 # Test suite
│   ├── unit/              # Unit tests
│   ├── integration/       # Integration tests
│   └── mocks/             # API mocks
│
├── skills/                # AI agent skills
│   ├── atrevete/          # Main project skill
│   ├── atrevete-agent/    # Agent patterns
│   ├── atrevete-api/      # FastAPI patterns
│   ├── atrevete-database/ # SQLAlchemy patterns
│   ├── atrevete-admin/    # Next.js patterns
│   ├── atrevete-shared/   # Shared utilities
│   └── skill-sync/        # Skill sync tool
│
├── docker/                # Docker configurations
├── docs/                  # Documentation
│   ├── prd/               # Product Requirements
│   ├── architecture/      # Architecture docs
│   └── migrations/        # Migration guides
│
├── docker-compose.yml     # Service orchestration
├── requirements.txt       # Python dependencies
└── .env_example           # Environment variables template
```

---

## Architecture Status (2026-06-07)

Current architecture: `create_agent + 7 middleware + 6 tools` (SSOT: `agent/agent_factory.py:47-55`).

Middleware stack (execution order):
1. DisclosureMiddleware
2. CustomerResolveMiddleware
3. AppointmentContextMiddleware
4. DynamicPromptMiddleware
5. AvailabilityContextMiddleware
6. PromptAssemblyMiddleware
7. SummarizeMiddleware

No custom StateGraph, no mode nodes, no intent router. Single LLM tool-calling loop; middlewares hydrate context into XML-fenced slots assembled per turn by PromptAssemblyMiddleware.

Full architecture docs: `docs/system/`.

---

## Component Map

Each component has its own AGENTS.md with specific guidance:

| Component | Location | AGENTS.md | Purpose |
|-----------|----------|-----------|---------|
| **Agent** | `agent/` | [agent/AGENTS.md](agent/AGENTS.md) | `create_agent` + middleware stack, tools, prompts |
| **API** | `api/` | [api/AGENTS.md](api/AGENTS.md) | FastAPI routes, webhooks, services |
| **Database** | `database/` | [database/AGENTS.md](database/AGENTS.md) | SQLAlchemy models, migrations |
| **Shared** | `shared/` | N/A (use `atrevete-shared` skill) | Config, clients, utilities |
| **Admin Panel** | `admin-panel/` | N/A (use `atrevete-admin` skill) | Next.js 15 React components |

---

### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|
| After creating/modifying a skill | `skill-sync` |
| Choosing a QA persona | `atrevete-qa-context` |
| Creating React components | `atrevete-admin` |
| Creating UI components | `atrevete-admin` |
| Creating agent tools | `atrevete-agent` |
| Creating migrations | `atrevete-database` |
| Creating new prompt module | `atrevete-prompts` |
| Creating utilities | `atrevete-shared` |
| Creating webhooks | `atrevete-api` |
| Creating/modifying middleware | `atrevete-agent` |
| Creating/modifying models | `atrevete-database` |
| Creating/modifying services | `atrevete-api` |
| Editing agent system prompts | `atrevete-prompts` |
| Editing identity.md or critical_rules.md | `atrevete-prompts` |
| Evaluating a QA conversation | `atrevete-qa-evaluator` |
| Executing a conversational QA run | `atrevete-qa-tester` |
| General Atrévete Bot development questions | `atrevete` |
| Generating a QA report | `atrevete-qa-evaluator` |
| Loading QA context | `atrevete-qa-context` |
| Modifying core prompt rules | `atrevete-prompts` |
| Modifying files in agent/prompts/ | `atrevete-prompts` |
| Modifying mode prompt instructions | `atrevete-prompts` |
| Preparing a conversational QA scenario | `atrevete-qa-context` |
| Project overview and architecture | `atrevete` |
| Regenerate AGENTS.md Auto-invoke tables | `skill-sync` |
| Reviewing prompt quality | `atrevete-prompts` |
| Scoring a conversational flow | `atrevete-qa-evaluator` |
| Simulating a WhatsApp user | `atrevete-qa-tester` |
| Troubleshoot missing skill in auto-invoke | `skill-sync` |
| Validating a QA flow end to end | `atrevete-qa-tester` |
| Working on API routes | `atrevete-api` |
| Working on Chatwoot | `atrevete-api` |
| Working on Chatwoot client | `atrevete-shared` |
| Working on FastAPI | `atrevete-api` |
| Working on LangGraph | `atrevete-agent` |
| Working on Next.js | `atrevete-admin` |
| Working on Redis | `atrevete-shared` |
| Working on admin-panel/ | `atrevete-admin` |
| Working on agent/ | `atrevete-agent` |
| Working on atrevete-bot | `atrevete` |
| Working on config | `atrevete-shared` |
| Working on database models | `atrevete-database` |
| Working on prompt .md files | `atrevete-prompts` |
| Working on prompts | `atrevete-agent` |
| Working on routing | `atrevete-agent` |
| Working on shared/ | `atrevete-shared` |
| Working on state management | `atrevete-agent` |
| Working on system prompts | `atrevete-prompts` |
| Working with SQLAlchemy | `atrevete-database` |

---

## Quick Reference

### Environment Setup

```bash
# Create virtual environment (Python 3.11+ required)
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with real API keys - see docs/external-services-setup.md
```

### Deploy Runbook (create_agent v2)

After deploying the create_agent rewrite, flush old Redis checkpoints so stale
`BookingContext` state doesn't pollute new conversations:

```bash
# Flush all old checkpoint keys (v1 thread_ids — they don't have the "v2:" prefix)
redis-cli --scan --pattern 'checkpoint:*' | xargs redis-cli del

# Apply the data migration (rename Cortar → Corte Dama, tag audiences)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head
```

New conversations use thread_id `v2:{conversation_id}` — they start clean.

### Deploy Runbook (booking-flow-scripted)

Additive prompt + tool enrichment change. No DB migration, no thread_id bump, no checkpoint flush required. In-flight conversations pick up the new `booking_flow.md` system-prompt section and `calendar_link` payload on their next turn without state conflict.

```bash
# Restart only the agent container (api and archiver unaffected)
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart agent
```

### Deploy Runbook (billing-wip-completion)

**Pre-merge guard — MUST run on production before merging dead-code removal (T8/PR-2).**

This query returns the count of v1 PaymentIntent invoices still in flight.
If the count is > 0, do NOT remove `create_sepa_charge`, `cancel_payment_intent`, or the legacy
webhook handlers — those in-flight invoices still depend on them.

```bash
# Run on the SSH server (pepe@server):
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c \
  "SELECT COUNT(*) AS legacy_in_flight FROM invoices \
   WHERE stripe_payment_intent_id IS NOT NULL \
     AND stripe_invoice_id IS NULL \
     AND status NOT IN ('paid', 'void');"
```

Result must be **0** before PR-2 (dead-code removal) can be merged.

**setup-fiscal is curl-only — do NOT add a UI button.**

The `POST /api/billing/setup-fiscal` endpoint is a one-time deployment step.
Invoke it once via curl after first deploy with Stripe credentials configured:

```bash
# Run on the SSH server after first deploy:
curl -X POST https://your-api-host/api/billing/setup-fiscal \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json"
```

Do NOT add a button in the admin panel for this endpoint. See JSDoc in `admin-panel/src/lib/billing-api.ts`.

---

### Deploy Runbook (policy-acceptance)

Adds `policy_accepted_at` / `policy_version` columns to `customers` and a new `customer_consents` audit table. Wires the policy acceptance gate into the booking flow (agent) and exposes policy fields in the admin API. **DB migration must run BEFORE deploying the new api/agent images.**

```bash
# Step 1: Apply the migration (revision b9d4e8f1c2a3, parent c7d8e9f0a1b2)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade b9d4e8f1c2a3

# Step 2: Confirm env vars are set in the deploy environment
#   POLICY_VERSION (default "1.0") — opaque string, compared with ==, not semver-parsed
#   POLICY_URL (default "https://atrevetepeluqueria.com/politica-privacidad/")
# Both have sensible defaults in shared/config.py; set them explicitly in production .env.

# Step 3: Restart api and agent containers to pick up new endpoints, prompts, and gate logic
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api agent
```

**⚠ VERSION-BUMP UX WARNING**: bumping `POLICY_VERSION` (e.g. `"1.0"` → `"1.1"`) re-triggers the policy gate for EVERY returning customer on their next booking interaction. Existing rows with `policy_version = "1.0"` will mismatch the new setting and must re-accept. **Coordinate with Pilar before any POLICY_VERSION bump in production.**

No checkpoint flush required. Policy acceptance fields are additive (`NotRequired` from the agent's perspective); in-flight conversations continue normally on the next turn.

Verification queries (run against production DB post-migration):

```sql
-- New columns exist
SELECT column_name FROM information_schema.columns
WHERE table_name='customers' AND column_name IN ('policy_accepted_at', 'policy_version');
-- expect: 2 rows

-- Audit table exists and is empty right after migration
SELECT COUNT(*) FROM customer_consents;
-- expect: 0

-- Smoke: a consent row after first WhatsApp acceptance
SELECT customer_id, policy_version, accepted_at, accepted_via
FROM customer_consents ORDER BY accepted_at DESC LIMIT 5;
```

Rollback:
```bash
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic downgrade -1
```

Revision: `b9d4e8f1c2a3` (parent: `c7d8e9f0a1b2`).

---

### Deploy Runbook (customer-notes-vs-memories)

Renames `memories.notes` → `memories.agent_notes` in the JSONB column and wires customer memory read/write into the booking flow. **DB migration must run BEFORE deploying the new agent/API images.**

```bash
# Step 1: Apply the data migration (renames memories.notes → memories.agent_notes)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Step 2: Restart API and agent containers (no checkpoint flush needed — additive state field)
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api agent
```

No checkpoint flush required. The `customer_memories` AgentState field is `NotRequired` — in-flight conversations see it as absent on the next turn (which is safe). The admin panel rename (agent_notes) is backward-compatible via the API field rename.

---

### Deploy Runbook (service-disambiguation-data-fixes)

Additive data-only migration: tags `Tinte.audience = 'adult_female'`, renames the `Depilación de Piernas Enteras` principal to `Depilación` (UUID unchanged), patches 11 child variants' `metadata_[parent_service_name]` via `jsonb_set`, and inserts a new `Piernas Enteras` variant. **No restart needed** — no app code changed.

```bash
# Apply the migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head
```

Verification queries (run against production DB post-migration):

```sql
-- 1. Tinte must have audience = adult_female
SELECT name, audience FROM services WHERE name = 'Tinte';
-- expect: 1 row, audience = 'adult_female'

-- 2. Wax principal renamed; UUID unchanged
SELECT name, metadata_->>'service_type' FROM services
WHERE metadata_->>'dimension' = 'wax' AND metadata_->>'service_type' = 'principal';
-- expect: 1 row, name = 'Depilación'

-- 3. All wax variants now point to new parent name
SELECT COUNT(*) FROM services WHERE metadata_->>'parent_service_name' = 'Depilación';
-- expect: 12 (11 existing + new "Piernas Enteras")

-- 4. No orphans pointing to old principal name
SELECT COUNT(*) FROM services WHERE metadata_->>'parent_service_name' = 'Depilación de Piernas Enteras';
-- expect: 0
```

Rollback:
```bash
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic downgrade -1
```

No checkpoint flush required. Revision: `e9d1f2b8c7a4` (parent: `a7b8c9d0e1f2`).

---

### Deploy Runbook (disambiguation-resilience)

Data-only migration: reclassifies `Corte de Flequillo` (variant→principal), `Barba` and `Perilla` (variant→addon), and `Manicura de Hombre` (variant→principal with `audience=adult_male`). **No restart needed** — no app code changed.

```bash
# Apply the migration (revision f0a1b2c3d4e5, parent f7e8d9c0b1a2)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic upgrade head
```

Verification queries (run against production DB post-migration):

```sql
-- 1. Corte de Flequillo must be principal, no parent
SELECT name, metadata->>'service_type' AS service_type, metadata->>'parent_service_name' AS parent
FROM services WHERE name = 'Corte de Flequillo';
-- expect: service_type='principal', parent=null

-- 2. Barba and Perilla must be addon, no parent
SELECT name, metadata->>'service_type' AS service_type, metadata->>'parent_service_name' AS parent
FROM services WHERE name IN ('Barba', 'Perilla');
-- expect: both rows: service_type='addon', parent=null

-- 3. Manicura de Hombre must be principal, audience=adult_male, no parent
SELECT name, audience, metadata->>'service_type' AS service_type, metadata->>'parent_service_name' AS parent
FROM services WHERE name = 'Manicura de Hombre';
-- expect: service_type='principal', audience='adult_male', parent=null

-- 4. No cross-dimension variant parenting (invariant I7)
SELECT v.name, v.metadata->>'dimension' AS v_dim, p.metadata->>'dimension' AS p_dim
FROM services v
JOIN services p ON p.name = v.metadata->>'parent_service_name'
  AND p.metadata->>'service_type' = 'principal'
WHERE v.metadata->>'service_type' = 'variant'
  AND v.metadata->>'dimension' != p.metadata->>'dimension';
-- expect: 0 rows
```

Rollback:
```bash
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic downgrade -1
```

Revision: `f0a1b2c3d4e5` (parent: `f7e8d9c0b1a2`). No checkpoint flush required.

---

### Deploy Runbook (catalog-axis-classification-audit)

Data-only migration: reclassifies 7 duration-delta services from `variant→addon` (clearing `parent_service_name`) and promotes `Barro Gold Extra` to standalone `principal` (was incorrectly parented under `Tratamiento Facial`). Also removes the `variant (duración)` row from `agent/prompts/shared/glossary.md` and adds R-34 to `critical_rules.md`. **No restart needed** — no app code changed beyond prompts.

```bash
# Step 1: Apply the migration (revision a3b4c5d6e7f8, parent f0a1b2c3d4e5)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic upgrade head
```

Verification queries (run against production DB post-migration):

```sql
-- 1. 7 reclassified services must be addon with no parent
SELECT name, metadata->>'service_type' AS service_type, metadata->>'parent_service_name' AS parent
FROM services
WHERE name IN (
  'Tinte Extra',
  'Mechas Extras',
  'Barro Extra',
  'Tratamiento Facial + Radiofrecuencia (15 min)',
  'Tratamiento Facial + Radiofrecuencia (30 min)',
  'Tratamiento Anticelulítico + Radiofrecuencia (30 min)',
  'Piernas Perfectas + Presoterapia (30 min)'
);
-- expect: all 7 rows: service_type='addon', parent=null

-- 2. Barro Gold Extra must be standalone principal with dimension=facial
SELECT name, metadata->>'service_type' AS service_type, metadata->>'parent_service_name' AS parent, metadata->>'dimension' AS dimension
FROM services WHERE name = 'Barro Gold Extra';
-- expect: service_type='principal', parent=null, dimension='facial'

-- 3. Tinte must have zero variant children (no duration-delta orphans)
SELECT COUNT(*) FROM services
WHERE metadata->>'parent_service_name' = 'Tinte'
  AND metadata->>'service_type' = 'variant';
-- expect: 0

-- 4. No duration-delta variants remain in color/treatment dimensions (I8 clean baseline)
SELECT name, metadata->>'dimension' AS dim, metadata->>'service_type' AS service_type
FROM services
WHERE metadata->>'service_type' = 'variant'
  AND metadata->>'dimension' IN ('color', 'treatment', 'highlights', 'body_contour');
-- expect: only legitimate zone/specialization variants (Mechas Localizadas, Barro Gold, etc.)
```

Idempotency verification:
```bash
# Downgrade then upgrade again — must produce no errors, no state change
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic downgrade -1
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic upgrade head
# Re-run upgrade head a second time — zero rows changed, no error
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic upgrade head
```

Rollback:
```bash
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" alembic downgrade -1
```

Revision: `a3b4c5d6e7f8` (parent: `f0a1b2c3d4e5`). No checkpoint flush required. Prompt changes (`glossary.md`, `critical_rules.md`) take effect on next agent container restart.

---

### Deploy Runbook (papercut-fixes)

Pure text changes: two voseo strings in `agent/tools/_booking_validators.py` replaced with castellano forms, and R-35 (`partial_resolved_ids` round-trip rule) added to `agent/prompts/shared/booking_flow.md` + `tools_contract.md`. No DB migration, no schema change, no checkpoint flush required.

```bash
# Restart api and agent containers to pick up new prompts and validator strings
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api agent
```

Rollback: `git revert HEAD~n` (revert commits on this branch) + restart containers.

---

### Deploy Runbook (conversaciones-inbox PR-1)

Additive migration only: adds `conversation_messages.author_user_id` (UUID NULL FK → `admin_users.id` ON DELETE SET NULL + index) and three TIMESTAMPTZ columns to `conversation_history` (`paused_at`, `resumed_at`, `context_injected_at`). Also ships service module stubs (`conversation_inbox_service.py`, `window_service.py`, `template_catalog.py`) — no endpoints exposed yet. No checkpoint flush required.

```bash
# Step 1: Apply the migration (a4b5c6d7e8f9 → b5c6d7e8f9a0)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Step 2: No restart needed for PR-1 alone — no new endpoints or code serving the columns.
# Verify the columns were created:
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_name='conversation_messages' AND column_name='author_user_id';"
# expect: 1 row

PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_name='conversation_history'
   AND column_name IN ('paused_at','resumed_at','context_injected_at');"
# expect: 3 rows
```

Rollback: `alembic downgrade -1`. No checkpoint flush required. No in-flight conversation is affected (all new columns are nullable; existing rows are unchanged).

**Template env flags**: A new env flag `INBOX_TEMPLATE_REENGAGEMENT_APPROVED=false` is added to `shared/config.py`. Set to `true` only after Meta approves the re-engagement template on the developer portal. Default is `false` (safe — templates show as "Plantillas en aprobación" in the composer UI).

---

### Deploy Runbook (window-status chatwoot can_reply mirror)

Additive migration only: adds `conversation_history.can_reply` (BOOLEAN NULL) and `conversation_history.can_reply_captured_at` (TIMESTAMPTZ NULL). The Chatwoot webhook handler now mirrors `payload.conversation.can_reply` on every inbound `message_created` event. `window_service.compute_window_open()` reads the cache first and falls back to the legacy `MAX(created_at) WHERE role='user'` only when the cache is missing or older than 24h.

```bash
# Step 1: Apply the migration (c6d7e8f9a0b1 → d7e8f9a0b1c2)
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml exec -T api alembic upgrade head

# Step 2: Rebuild api (volume-less — baked code) to pick up the webhook capture
# and the new window_service logic.
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml up -d --build api

# Step 3 (optional): rebuild admin-panel only if you also changed UI client code.
# This change is backend-only, so admin-panel does NOT need a rebuild.
```

Verification:

```bash
# Columns exist
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml exec -T postgres \
  psql -U atrevete -d atrevete_db -c "\d conversation_history" | grep -E "can_reply"
# expect: can_reply boolean | can_reply_captured_at timestamp with time zone

# After the next inbound from a real customer, the row populates:
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml exec -T postgres \
  psql -U atrevete -d atrevete_db -c \
  "SELECT conversation_id, can_reply, can_reply_captured_at FROM conversation_history
   WHERE can_reply_captured_at IS NOT NULL ORDER BY can_reply_captured_at DESC LIMIT 5;"
```

Rollback: `alembic downgrade -1`. No checkpoint flush. Existing conversations without populated cache transparently fall through to the legacy timestamp computation.

---

### Deploy Runbook (conversaciones-inbox PR-2)

7 new admin endpoints (`send-message`, `send-template`, `pause`, `resume`, `escalate`, `window-status`, `templates`), `resume_injection` service, and webhook gate refactor (persist-before-gate). **PR-1 migration must be applied first.** No new DB migration, no checkpoint flush required.

**Gate refactor policy change (FR-WEBHOOK-4)**: Inbound messages are now persisted to `ConversationMessage` even when `ai_agent_enabled=False` or `atencion_automatica=False`. Only the Redis Stream publish is gated.

```bash
# Requires PR-1 migration already applied (b5c6d7e8f9a0 must be current head).

# Restart api container to pick up new endpoints, service implementations, and gate refactor.
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api

# Smoke tests:
# a) GET window-status (replace <id> with a real Chatwoot conversation ID)
curl -b "admin_token=<your_token>" \
  https://your-api-host/api/admin/conversations/<id>/window-status
# expect: 200 + {"window_open": bool, "last_user_message_at": ..., "hours_until_close": ...}

# b) GET templates
curl -b "admin_token=<your_token>" \
  https://your-api-host/api/admin/conversations/templates
# expect: 200 + {"items": [{"name": "reengagement", "status": "pending", ...}]}

# c) POST pause (admin role required)
curl -X POST -b "admin_token=<your_token>" \
  -H "Content-Type: application/json" \
  -d '{"source": "toggle"}' \
  https://your-api-host/api/admin/conversations/<id>/pause
# expect: 200 + {"paused_at": "..."}

# d) POST resume (verify pending_injection Redis key is set)
curl -X POST -b "admin_token=<your_token>" \
  https://your-api-host/api/admin/conversations/<id>/resume
# expect: 200 + {"resumed_at": "...", "pending_injection_ttl_seconds": 600}
# redis-cli TTL "pending_injection:v2:<id>" → ~600

# e) Bot-off inbound regression: send a WhatsApp message to a paused conversation,
#    confirm no Redis Stream entry (redis-cli XLEN INCOMING_STREAM unchanged),
#    but DB row exists (SELECT * FROM conversation_messages WHERE role='user' ORDER BY created_at DESC LIMIT 1).
```

**Resume injection**: On the first customer inbound after `/resume`, `maybe_inject_pending_context()` runs in the webhook handler. Check logs for `"Resume injection complete — context_injected_at set"` and verify `conversation_history.context_injected_at` is populated and the `pending_injection:v2:{id}` Redis key is deleted.

Rollback: `git revert` the PR-2 commits + `docker compose restart api`. No DB rollback needed (no schema change in PR-2).

---

### Deploy Runbook (conversaciones-inbox PR-3)

Full inbox UI rewrite: 3-column `/conversations` page, 8 inbox components, `useConversationPolling` hook, `/escalations` 308 redirect, sidebar badge merge, and `paused_24h` notification handler. **Requires PR-2 endpoints live.** No DB migration, no schema change, no checkpoint flush required.

```bash
# Step 1: Rebuild and redeploy admin-panel (on deploy server)
cd /home/pepe/Proyectos/atrevete-bot/admin-panel && npm run build
# Then serve the new build (e.g. via your Next.js start command or nginx static)

# Step 2: Restart agent container to pick up paused_24h handler registration
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart agent

# Step 3: Smoke tests
# a) Navigate to /escalations → should 308-redirect to /conversations?filter=escalated
# b) Open /conversations → confirm 3-column layout: list | thread | customer card
# c) Confirm "Escalaciones" sidebar entry is absent; Conversaciones badge is visible
# d) Select a conversation → PausedBanner shows if bot is paused
# e) Send a message while bot is ON → TakeoverModal appears, confirm → bot paused
# f) Click "Reanudar bot" → bot resumes, pending_injection Redis key set
# g) paused_24h handler: check logs for "paused_24h: created N reminder notifications"
#    after running notifications_worker (triggered automatically on next poll cycle)
```

Rollback: `git revert` the PR-3 commits + rebuild admin-panel previous version + `docker compose restart agent`.

---

### Deploy Runbook (inbox-customer-context)

Admin inbox enrichment: "Conversaciones" moved to PRINCIPAL sidebar section with badge, delete-conversation button (⋯ → AlertDialog), CustomerCard enriched with Política / Última actividad / Preferencias / Notas / Resumen sections, and `pending_injection:v2:{id}` Redis key cleanup added to conversation delete flow. **No DB migration, no schema change.**

```bash
# Step 1: Rebuild and redeploy admin-panel
cd /home/pepe/Proyectos/atrevete-bot/admin-panel && npm run build
# Then serve the new build (e.g. via your Next.js start command or nginx static)

# Step 2: Restart api container to pick up the Redis cleanup change
# (shared/redis_conversation_cleanup.py now deletes pending_injection:v2:{id})
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api

# Step 3: Smoke tests
# a) Sidebar: "Conversaciones" entry visible under PRINCIPAL with badge count
# b) Open /conversations → select a conversation → ⋯ button visible in thread header
# c) Click ⋯ → "Eliminar conversación" → AlertDialog with customer name
# d) Confirm delete → conversation disappears from list, thread clears
# e) Right panel: linked customer shows Política badge (green/gray), last 3 appointments,
#    preferred stylist, truncated notes, total_spent, and "Cliente desde" date
# f) Right panel: unlinked customer → "Sin identificar" state preserved
# g) Delete a resumed conversation and verify pending_injection:v2:{id} key is gone:
#    redis-cli EXISTS "pending_injection:v2:{conversation_id}"  # expect: 0
```

Rollback: `git revert` this PR's commits + rebuild admin-panel + `docker compose restart api`.

---

### Deploy Runbook (inbox-operator-takeover)

UI polish only: window-status polling cadence fix, `hours_until_close` label above composer, 409/502 error toasts on pause/resume, `display_name` in template picker, improved closed-window message, and BotToggle `aria-label`. **No DB migration, no schema change, no checkpoint flush required.**

```bash
# Rebuild and redeploy admin-panel only
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml up -d --build admin-panel
```

Rollback: `git revert` this PR's commits + rebuild admin-panel.

---

### Deploy Runbook (inbox-polish)

Two orthogonal fixes: (Fix #5) tab counters on `/conversations` — backend list endpoint now returns `atencion_automatica`, `paused_at`, `unread_message_count` per item plus a `counts` key with per-filter totals; admin-panel tab buttons show a numeric badge. (Fix #6) orphan `Notification` cleanup — `delete_conversation()` now deletes `entity_type='conversation_history'` rows after removing the `ConversationHistory` parent. **No DB migration, no schema change, no checkpoint flush required.**

```bash
# Step 1: Restart api to pick up notification cleanup + list endpoint counts
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api

# Step 2: Rebuild admin-panel to pick up tab counter badges
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml up -d --build admin-panel
```

Verification:
- Open `/conversations` — tab buttons should now show numeric badges (e.g. "Bot ON · 3").
- Delete a conversation that has a `paused_24h` notification — confirm the notification is also removed (`SELECT * FROM notifications WHERE entity_type='conversation_history' AND entity_id='<uuid>'` should return 0 rows).

Rollback: `git revert` this PR's commits + `docker compose restart api` + rebuild admin-panel.

---

### Deploy Runbook (gcal-sync-resilience)

Adds 4 new columns to `appointments` (`gcal_sync_status`, `gcal_last_attempt_at`, `gcal_last_error`, `gcal_operation`), writes sync state inside the push functions, exposes a `POST /api/admin/appointments/{id}/gcal-retry` endpoint, and adds a red badge + retry button in the appointments table. **DB migration must run BEFORE deploying the new api/agent/admin-panel images.**

```bash
# Step 1: Apply the migration (revision e1f2a3b4c5d6, parent b9d4e8f1c2a3)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Step 2: Verify columns
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_name='appointments' AND column_name LIKE 'gcal_%';"
# expect: 5 rows (existing google_calendar_event_id + 4 new)

# Step 3: Restart api and agent containers + rebuild admin-panel
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart api agent
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml up -d --build admin-panel
```

No checkpoint flush required. Revision: `e1f2a3b4c5d6` (parent: `b9d4e8f1c2a3`).

Rollback: `alembic downgrade -1` + revert image. Existing rows lose the columns; no user-visible data loss (GCal+DB are the source of truth).

---

### Deploy Runbook (inbox-reliability)

Pure frontend/config change: escalations redirect moved from `route.ts` to `next.config.ts` (fixes localhost leak behind reverse proxy); `EscalationItem` now clickable deep-links into the inbox; `useConversationPolling` now does one **unconditional initial fetch on mount** (so the inbox loads even when opened in a hidden/background tab); `ConversationList` loading hygiene (`setLoading(true)` at fetch start, logged catch, `useMemo` on unreadCount, spinner gated on first load only); `use-api-query` abort-guard on `setIsLoading` removed. **No DB migration. No checkpoint flush. No API/agent restart required — admin-panel only.**

> NOTE: an earlier draft framed the inbox "infinite Cargando…" as a P0 fixed by switching to the prod build. That symptom was a **test-harness artifact** (automation tab ran as `document.hidden=true`, and polling skipped the initial fetch when hidden). The real inbox works for visible tabs; the only genuine fix here is the unconditional initial fetch for the hidden-tab edge case. The prod-build switch below is still recommended for **production parity**, not as a P0 fix.

**OVERRIDE FOOTGUN WARNING**: Running plain `docker compose up` on the server auto-merges `docker-compose.override.yml`, which swaps to `Dockerfile.admin-panel.dev` (`next dev`, hot-reload, source-mounted, React StrictMode double-invokes effects). That is developer-iteration tooling, not a UAT/production build. ALWAYS use `docker compose -f docker-compose.yml` on the server so the override is excluded and the optimized production build (`node server.js`, `NODE_ENV=production`) is served.

```bash
# On pepe@server, in /home/pepe/Proyectos/atrevete-bot
docker compose -f docker-compose.yml up -d --build admin-panel
```

Verify `NEXT_PUBLIC_API_URL` was baked correctly at build time:

```bash
docker compose -f docker-compose.yml exec admin-panel printenv NEXT_PUBLIC_API_URL
# expect: https://api.zonavix.com
```

UAT smoke checks (run after deploy, on the public host):

1. Navigate to `/conversations` (visible tab) — list renders with conversations + tab counters; throttle network / force API 500 → browser console shows `[ConversationList] fetchList failed:` and the empty state appears (no infinite spinner).
2. Navigate to `/escalations` — server responds 308 and browser lands on `/conversations?filter=escalated` with no `localhost` in the Location header. **Caveat**: the OLD route emitted a 308 *permanent* redirect to `localhost:3000`; browsers that hit it cached it hard. Test with a fresh profile or a cache-busting query (`/escalations?cb=1`) — a stale browser may still short-circuit to the cached localhost target until its cache is cleared.
3. Dashboard "Necesitan atención" section — click any item → browser navigates to `/conversations?conversation_id=<uuid>&filter=escalated` with that conversation pre-selected in the thread panel.
4. No unexpected console errors on any of the above pages.

Rollback: `git revert` the inbox-reliability commits + rebuild admin-panel image. No data loss.

---

### Deploy Runbook (pause-state-internal-ssot)

Replaces Chatwoot `atencion_automatica` as the pause-state SSOT with `conversation_history.paused_at` (DB-only gate). **No DB migration needed** — `paused_at` / `resumed_at` columns already exist from prior changes. Two-phase cutover keeps the bot serving active conversations throughout; a `ai_agent_enabled=False` blackout is the zero-leak alternative.

**Phase ordering matters.** The old gate reads Chatwoot; the new gate reads DB. Seeding paused_at BEFORE the new images go live is harmless (old gate ignores DB). Clearing Chatwoot BEFORE the new images go live would un-pause bot conversations since the old gate still reads Chatwoot.

```bash
# Prerequisites: venv activated, DATABASE_URL set, CHATWOOT_* env vars set.
# The script reads all config from shared/config.py — never set them inline.

# -------------------------------------------------------------------
# Phase A — SEED (run BEFORE deploying new images)
# Old gate ignores DB; seeding paused_at is completely harmless.
# -------------------------------------------------------------------

# Dry-run first to review scope:
python scripts/backfill_paused_at.py --phase seed --dry-run

# Seed paused_at for all conversations where atencion_automatica=false:
python scripts/backfill_paused_at.py --phase seed

# -------------------------------------------------------------------
# Final pre-flip SEED — run IMMEDIATELY before the image swap.
# Captures any conversation escalated under the OLD code between
# the Phase A scan and the image swap (admin pauses are already safe —
# pause() writes paused_at to DB directly).
# ALWAYS use --no-resume here: the page-offset checkpoint is ordered by
# Chatwoot's mutable activity list and can skip newly-active drift rows
# on a resumed run.  Full rescan guarantees nothing is missed.
# -------------------------------------------------------------------
python scripts/backfill_paused_at.py --phase seed --no-resume

# -------------------------------------------------------------------
# Deploy new api/agent images (new DB gate goes live, fail-closed).
# Zero-leak alternative: engage a bot blackout BEFORE Phase A via:
#
#   psql: UPDATE system_settings
#           SET value = 'false'::jsonb
#           WHERE key = 'ai_agent_enabled';
#
# Then flip it back after Phase A + deploy + Phase B complete:
#
#   psql: UPDATE system_settings
#           SET value = 'true'::jsonb
#           WHERE key = 'ai_agent_enabled';
#
# (value column is JSONB — SettingsService reads ai_agent_enabled from
#  system_settings.value with value_type='boolean')
# NOTE: SettingsService caches settings for up to 60s (CACHE_TTL_SECONDS) and
#  the cache is NOT invalidated by a raw psql UPDATE. After running the blackout
#  SQL, wait >=60s (or restart the api container) before trusting the blackout —
#  the running image may keep serving ai_agent_enabled=true until the cache expires.
# This trades a full bot blackout for absolute ordering safety.
# -------------------------------------------------------------------
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml up -d --build api agent

# -------------------------------------------------------------------
# Phase B — CLEAR (run AFTER deploy)
# New gate ignores Chatwoot; clearing atencion_automatica can no longer
# un-pause anything.
# -------------------------------------------------------------------

# Dry-run first to review scope:
python scripts/backfill_paused_at.py --phase clear --dry-run

# Remove atencion_automatica from all Chatwoot conversations:
python scripts/backfill_paused_at.py --phase clear
```

**Verification queries (run after Phase B):**

```sql
-- How many conversations have paused_at set (expect > 0 if any were paused)
SELECT COUNT(*) AS paused_count
FROM conversation_history
WHERE paused_at IS NOT NULL;

-- Spot-check: verify no paused_at is incorrectly NULL for known-paused conversations
-- (run immediately after Phase A, before Phase B)
SELECT conversation_id, paused_at, resumed_at
FROM conversation_history
WHERE paused_at IS NULL
ORDER BY created_at DESC
LIMIT 20;
```

**Chatwoot cleanup verification** (confirm atencion_automatica is cleared — run via Chatwoot API or admin panel; there is no DB table for Chatwoot custom_attributes):

```bash
# Quick sample: fetch a known conversation and inspect custom_attributes
curl -s -H "api_access_token: $CHATWOOT_API_TOKEN" \
  "$CHATWOOT_API_URL/api/v1/accounts/$CHATWOOT_ACCOUNT_ID/conversations/<id>" \
  | python3 -m json.tool | grep atencion_automatica
# expect: no output (key absent)
```

**Resumable runs.** If the script is interrupted, re-run the same command — it resumes from the last completed page via a checkpoint file (`.backfill_paused_at_checkpoint.json` in the cwd). Use `--max-pages N` to bound a run for testing. Use `--no-resume` to force a full rescan from page 1 (ignores and clears any existing checkpoint); always use `--no-resume` for the final pre-flip seed to avoid stale page-offset drift on Chatwoot's mutable activity-ordered list.

Rollback: `git revert` the pause-state-internal-ssot commits + restart api/agent. The `paused_at` column retains its seeded values (harmless if the old images are restored — the old gate ignores it). If needed, reset seeded rows: `UPDATE conversation_history SET paused_at = NULL WHERE ...` scoped to the relevant conversation IDs.

---

### Deploy Runbook (reactivate-confirmation-lifecycle Slice 3)

Flag-gated auto-cancel tail: `final_warning` + `auto_cancel` notification handlers,
`_active_handlers()` refactor in `notifications_worker.py`, `final_warning_sent_at` column,
and 5 new config settings. **Slices 1 and 2 must be live before this deploy.** `AUTO_CANCEL_ENABLED`
defaults to `false` — handlers register but never fire until explicitly enabled.

**Pre-condition**: The Meta template `whatsapp_template_final_warning` MUST be approved and
its name configured in `system_settings` BEFORE setting `AUTO_CANCEL_ENABLED=true`. Enabling
the flag with an empty/missing template causes `final_warning` to apply backoff (appointments
remain PENDING) instead of sending the warning — auto-cancel will never fire without a
successful warning send.

```bash
# Step 1: Apply the migration (revision f1a2b3c4d5e6, parent e1f2a3b4c5d6)
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# Step 2: Verify the column was added
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_name='appointments' AND column_name='final_warning_sent_at';"
# expect: 1 row

# Step 3: Deploy the new agent image (AUTO_CANCEL_ENABLED=false — handlers are registered
# in the worker but _active_handlers() excludes them until the flag is toggled)
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart agent

# Step 4 (after Meta approval): Set the template name in system_settings
# Run via psql or the admin API:
#   INSERT INTO system_settings (key, value, value_type, description)
#   VALUES ('whatsapp_template_final_warning', '"<approved-template-name>"', 'string',
#           'Meta-approved template for the auto-cancel final warning')
#   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

# Step 5 (after Meta approval + Step 4): Enable the flag and restart agent
# In production .env:
#   AUTO_CANCEL_ENABLED=true
docker compose -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml restart agent
# No migration needed for the flag change.
# NOTE: Toggling AUTO_CANCEL_ENABLED requires a notifications-worker restart.
# Settings are process-cached via lru_cache (shared/config.py get_settings).
# This is acceptable because the flag is enabled as part of a coordinated deploy
# alongside the Meta-approved template — both steps happen in the same runbook.
# Do NOT expect the flag change to take effect without restarting the agent container.
```

Verification queries (run after Step 5 — agent restarted with AUTO_CANCEL_ENABLED=true):

```sql
-- Confirm final_warning_sent_at is being stamped (after ~12h grace elapses on PENDING appts)
SELECT id, confirmation_sent_at, final_warning_sent_at, status
FROM appointments
WHERE final_warning_sent_at IS NOT NULL
ORDER BY final_warning_sent_at DESC
LIMIT 10;

-- Confirm auto-cancel is running (cancellation_reason distinguishes auto vs operator vs customer)
SELECT id, status, cancellation_reason, cancelled_at
FROM appointments
WHERE cancellation_reason = 'auto_cancelled_no_confirmation'
ORDER BY cancelled_at DESC
LIMIT 10;
```

Rollback: Set `AUTO_CANCEL_ENABLED=false` in `.env` + restart agent — no migration needed,
no checkpoint flush required. Already-CANCELLED appointments remain cancelled (terminal state).
To roll back the schema: `alembic downgrade -1`. Existing PENDING rows are unaffected (column
is nullable).

---

### Service Catalog Integrity Guard

CI guard that asserts 7 structural invariants over the seeded `services` table. Introduced after the orphan-variant drift found at deploy 2026-05-11 (Engram obs #5260). I7 added by disambiguation-resilience PR-1.

**What it catches:** orphan variants (I1), dimension mismatch between variant and parent (I2), invalid audience value (I3), duplicate principals with same (name, dimension) (I4), variant with null parent_service_name (I5), dimension not present in principals (I6), cross-dimension variant parenting (I7).

**How to run locally:**
```bash
DATABASE_URL="postgresql+asyncpg://..." pytest tests/integration/test_service_catalog_integrity.py -v
```

**Files:**
- `tests/integration/test_service_catalog_integrity.py` — 6 parametrized green-guard cases
- `tests/integration/test_service_catalog_integrity_failures.py` — 3 synthetic violation injection cases
- `tests/integration/_service_catalog_invariants.py` — pure SQL helper functions + `CHECKERS` registry

**CI:** runs automatically via pytest discovery after `alembic upgrade head`; no workflow YAML change needed. Tests skip gracefully when Postgres is not reachable.

**How to extend:** add `_check_invariant_7` in `_service_catalog_invariants.py`, register it in `CHECKERS`, and add a corresponding failure scenario in the failures file.

---

### Running Services

```bash
# Start all services (PostgreSQL, Redis, API, Agent, Archiver)
docker-compose up -d

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api      # FastAPI webhook receiver
docker-compose logs -f agent    # LangGraph orchestrator
docker-compose logs -f archiver # Conversation archival worker

# Restart specific service
docker-compose restart api
```

### Database Operations

```bash
# Create new migration
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic revision --autogenerate -m "description"

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic upgrade head

# Check current migration version
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/alembic current

# Access PostgreSQL directly
PGPASSWORD="changeme_min16chars_secure_password" psql -h localhost -U atrevete -d atrevete_db

# Access via Docker
docker exec -it atrevete-postgres psql -U atrevete -d atrevete_db
```

### Testing

```bash
# Run all tests with coverage (minimum 85% required)
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest

# Run unit tests only
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/

# Run integration tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/integration/

# Run specific test file
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py

# Run specific test with verbose output
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" ./venv/bin/pytest tests/unit/test_customer_tools.py::test_create_customer -v
```

### Code Quality

```bash
# Format code (line length: 100, Python 3.11)
black .

# Lint code
ruff check .

# Type check (strict for shared/ and database/, relaxed for agent/ and admin/)
mypy .
```

### Confirmation Flow

`agent/tools/book.py` applies a lead-time gate at appointment creation:

- **> 48h before the appointment** → `AppointmentStatus.PENDING`. The `notifications_worker`
  (via the `confirm_48h` handler) sends a WhatsApp confirmation request (template
  `atrevete_confirm_48h`) approximately 48h before the appointment. The customer replies "sí" and `manage_appointments_tool` routes
  it through `confirmation_service.handle_tool_action(CONFIRM_APPOINTMENT)`, which
  transitions the appointment to `AppointmentStatus.CONFIRMED`.
- **≤ 48h before the appointment** → `AppointmentStatus.CONFIRMED` directly. No separate
  confirmation request is sent — the live WhatsApp booking conversation is sufficient.

`book()` includes `appointment_status` (`"pending"` or `"confirmed"`) and
`requires_confirmation` (bool) in its response payload so the agent can adapt its reply
without a DB re-query. No checkpoint flush required when deploying this change.

`agent/services/confirmation_service.py` contains an SMS/notification path that is
**DORMANT** — no cron job, no worker, and no runtime caller invokes it for new bookings.
Do NOT call it from any new code.

Appointment reminders (24h before) are handled by the `reminder_24h` notification handler
and delivered via the WhatsApp/bot channel, not SMS.

#### Auto-cancel tail (Slice 3, flag-gated)

When `AUTO_CANCEL_ENABLED=true`, the `notifications_worker` runs a two-phase proactive tail
for PENDING appointments that receive no reply to the confirmation request:

| Phase | Action | Default trigger |
|-------|--------|-----------------|
| `confirm_48h` | Sends `atrevete_confirm_48h` WhatsApp template | ~48h before appointment |
| `final_warning` | Sends `whatsapp_template_final_warning` Meta template | ≥12h after `confirmation_sent_at` (`AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS=12`) |
| `auto_cancel` | Sets `status=CANCELLED`, frees the slot | ≥6h after `final_warning_sent_at` (`AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS=6`) |

The `AUTO_CANCEL_MIN_LEAD_HOURS=24` guard prevents both `final_warning` and `auto_cancel`
from firing within 24h of the appointment start time — imminent appointments are left
untouched and must be handled manually by the operator.

**Kill switch**: `AUTO_CANCEL_ENABLED` defaults to `False` and is separate from
`NOTIFICATIONS_WORKER_ENABLED`. Setting it to `false` stops both `final_warning` and
`auto_cancel` after restarting the agent container (settings are lru_cache-d at process
start — a process restart is required for the flag change to take effect). Already-CANCELLED
appointments remain cancelled (terminal state). No checkpoint flush required.

**`cancellation_reason` marker values**:

| Value | Set by |
|-------|--------|
| `'auto_cancelled_no_confirmation'` | `auto_cancel` handler (worker, Slice 3) |
| `'operator_cancelled'` | Admin `PUT /appointments/{id}` with `status=cancelled` |
| `'customer_declined'` | `manage_appointments_tool` → `confirmation_service.handle_tool_action(DECLINE_APPOINTMENT)` |

**Meta template dependency**: `AUTO_CANCEL_ENABLED` MUST NOT be set to `true` until the
`whatsapp_template_final_warning` Meta template is approved and its name stored in
`system_settings` (key: `whatsapp_template_final_warning`). An empty/missing setting causes
`final_warning.send_fn` to return `False` and apply exponential backoff
(`notification_failed=True`) — the appointment stays PENDING and auto-cancel never fires.

**Configurable timing settings** (confirm with owner before activation):

| Setting | Default | Range |
|---------|---------|-------|
| `AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS` | 12h | 1–36h |
| `AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS` | 6h | 1–24h |
| `AUTO_CANCEL_MIN_LEAD_HOURS` | 24h | 12–48h |

See `shared/config.py` for all five `AUTO_CANCEL_*` settings introduced in Slice 3.
The deploy runbook for Slice 3 is in the `### Deploy Runbook (reactivate-confirmation-lifecycle Slice 3)`
section above.

---

### Admin Panel Development

```bash
# Navigate to admin panel
cd admin-panel

# Install dependencies
npm install

# Run development server (with hot reload)
npm run dev

# Build for production
npm run build

# Lint frontend code
npm run lint
```

---

## Critical Rules

These rules apply across ALL components:

1. **ALWAYS use `shared/config.py`** — NEVER use `os.getenv()` directly
2. **ALWAYS use `add_message()` helper** — NEVER mutate state directly
3. **NEVER use `{**state}` spread** in node return values — causes message duplication
4. **ALWAYS use `Annotated[T, reducer_fn]`** for custom reducers in state schema
5. **ALWAYS use async/await** for all I/O operations
6. **ALWAYS maintain Spanish** for user-facing content, English for code/docs
7. **NEVER start services** (docker, npm, etc.) unless explicitly requested
8. **ALWAYS use Pydantic Settings** for environment variables
9. **ALWAYS use UUID** for primary keys (not auto-increment)
10. **ALWAYS use `DateTime(timezone=True)`** for timestamps

---

## Deploy

The testing deploy of this project is by SSH server by *pepe@server* in the folder */home/pepe/Proyectos/atrevete-bot* by **docker compose**

YOU CAN'T RUN THIS PROJECT IN OTHER MACHINES, just in the up said
---

## QA Test Harness

Declarative scenario runner for regression testing the live bot pipeline.
Skills: `atrevete-qa-runner` (single scenario) and `atrevete-qa-auditor` (batch audit).

### Sandbox Conventions

- `TEST_MODE_GCAL_SKIP=true` — MUST be set before any run. Bypasses all Google Calendar
  API calls; created appointments get `gcal_sync_status = 'not_applicable'`.
- `TEST_PHONE_PREFIX=+34999` — All sandbox customer phones MUST start with `+34999`.
  Phones in `tests/e2e/harness/scenarios.yaml` use `+34999000001` through `+34999000015`.
  The `+349` guard in `cleanup.py` and `state_reset.py` prevents accidental deletion of
  real production customers.

### Where Runs Live

```
tests/e2e/runs/{YYYYMMDD_HHMMSS}/
  {scenario_id}.json          # turn log, db_delta, bugs, final_state, outcome
  {scenario_id}_traces.json   # Langfuse traces (nullable if Langfuse unavailable)
  audit.md                    # batch audit report (written by atrevete-qa-auditor)
  diff.md                     # regression diff vs baseline (optional)
```

### Running a Full Regression Batch

```bash
# 1. Set sandbox env
export TEST_MODE_GCAL_SKIP=true
export TEST_PHONE_PREFIX=+34999

# 2. Clean up any prior sandbox data
python tests/e2e/harness/cleanup.py --dry-run  # confirm counts first
python tests/e2e/harness/cleanup.py

# 3. Generate a timestamp for this run
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p tests/e2e/runs/$TS

# 4. Spawn one atrevete-qa-runner subagent per scenario (parallelizable).
#    The orchestrator reads tests/e2e/harness/scenarios.yaml, generates a UUID4
#    per scenario, passes scenario JSON + conv_id + output path to each runner.

# 5. After all runners complete, spawn one atrevete-qa-auditor subagent:
#    Input: run directory tests/e2e/runs/$TS/
#    Output: tests/e2e/runs/$TS/audit.md
```

Approximate cost: ~$2.50 per full 15-scenario run (15 runners + 1 auditor).

### Reading Audit Output

`tests/e2e/runs/{ts}/audit.md` contains:
- Summary table: scenario | outcome | expected | verdict | L1–L5 scores
- CRITICAL / WARNING / detailed FAIL findings with `file:line` root causes
- Regression list vs baseline (if `--baseline` was provided to auditor)
- Prioritized recommendations

A scenario is **PASS** when all of L1–L4 pass and L5 >= 3.0.
A scenario is **WARN** when L1–L4 pass but traces are missing (L2 skipped) or L5 < 3.0.
A scenario is **FAIL** when any deterministic check in L1–L4 fails.

For regression comparison between two runs:

```bash
python tests/e2e/harness/diff.py \
  --base tests/e2e/runs/<baseline_ts>/ \
  --head tests/e2e/runs/<new_ts>/ \
  --out tests/e2e/runs/<new_ts>/diff.md
```

---

## Resources

- **[CLAUDE.md](CLAUDE.md)** — Comprehensive development guide (most up-to-date)
- **[README.md](README.md)** — Project overview and quick start
- **[skills/](skills/)** — AI agent skills for detailed patterns

---

**Last Updated**: March 2026  
**Version**: 1.0 (Mode-based architecture v6.0)