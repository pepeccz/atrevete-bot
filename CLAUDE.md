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
├── agent/                 # LangGraph orchestrator
│   ├── AGENTS.md          # Agent-specific guidance
│   ├── main.py            # Redis Streams consumer
│   ├── graphs/            # StateGraph definitions
│   │   └── conversation_flow.py   # v6.0 mode-based graph
│   ├── modes/             # Mode nodes (v6.0)
│   │   ├── greeting_mode.py       # GREETING mode
│   │   ├── booking_mode.py        # BOOKING mode
│   │   ├── general_mode.py        # GENERAL mode
│   │   └── escalation_mode.py     # ESCALATION mode
│   ├── routing/           # Intent router
│   │   └── intent_router.py       # Keyword + LLM hybrid classifier
│   ├── tools/             # 4 LangChain tools
│   │   ├── availability_tools.py  # check_availability
│   │   ├── booking_tools.py       # book
│   │   ├── manage_appointments_tool.py  # manage_appointments
│   │   └── escalation_tools.py    # escalate
│   ├── prompts/           # System prompts
│   │   ├── shared/        # Core prompts (identity, rules, glossary)
│   │   └── modes/         # Mode-specific overlays
│   ├── state/             # State schemas and checkpointer
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
│   ├── logging_config.py  # Structured logging
│   └── circuit_breaker.py # Circuit breaker pattern
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

## Architecture Status (2026-04-21)

StateGraph v6.0 migration complete. Graph: `preprocess → router → [greeting | general | booking | escalation | appointment_management | confirmation_reply] → summarize → END`. All modes, tools, prompts, services wired.

E1 scaffolding partially reverted:
- `agent/core/` — REMOVED (commit 02acbea, 2026-04-20). `state_delivery.py` + `status_line.py` never wired; concepts covered by `ConversationState` TypedDict + mode_context.
- `infra/resolvers/negation.py` — kept (hard-rename of `shared/negation_phrases.py`, P8).
- `scripts/check_layers.py` — kept (AST layer-import gate, CI-only).

Full architecture docs: `docs/system/`.

---

## Component Map

Each component has its own AGENTS.md with specific guidance:

| Component | Location | AGENTS.md | Purpose |
|-----------|----------|-----------|---------|
| **Agent** | `agent/` | [agent/AGENTS.md](agent/AGENTS.md) | LangGraph orchestrator, modes, routing, tools |
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
| Creating/modifying mode nodes | `atrevete-agent` |
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

## Resources

- **[CLAUDE.md](CLAUDE.md)** — Comprehensive development guide (most up-to-date)
- **[README.md](README.md)** — Project overview and quick start
- **[skills/](skills/)** — AI agent skills for detailed patterns

---

**Last Updated**: March 2026  
**Version**: 1.0 (Mode-based architecture v6.0)