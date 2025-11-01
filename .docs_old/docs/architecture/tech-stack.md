# 3. Tech Stack

This is the **DEFINITIVE** technology selection for the entire project. All development must use these exact versions. This table is the single source of truth for dependencies.

## 3.1 Technology Stack Table

| Category | Technology | Version | Purpose | Rationale |
|----------|-----------|---------|---------|-----------|
| **Frontend Language** | Python | 3.11+ | Admin panel templates (Django) | Type hints, async/await, performance improvements over 3.10; Django 5.0+ requires 3.10+ |
| **Frontend Framework** | Django Admin | 5.0+ | Staff admin interface | Auto-generated CRUD forms reduce development time by 80%; built-in authentication; read-only views for calendar |
| **UI Component Library** | Django Admin Default Theme | 5.0 (built-in) | Admin UI components | Sufficient for MVP; no custom design needed; responsive out-of-box |
| **State Management** | Django Session Framework | 5.0 (built-in) | Admin user sessions | Server-side session management for staff authentication; secure by default |
| **Backend Language** | Python | 3.11+ | API, Agent, Workers | Async/await native support for FastAPI; LangGraph/LangChain ecosystem; type safety with Pydantic 2.0+ |
| **Backend Framework** | FastAPI | 0.116.1 | Webhook API server | Async-native for high concurrency; automatic OpenAPI docs; Pydantic validation; <3s webhook response times |
| **API Style** | REST (webhooks) | N/A | Chatwoot/Stripe webhooks | Industry standard for webhook integrations; no GraphQL needed for simple event-driven flows |
| **Database** | PostgreSQL | 15+ | Primary data store (7 tables) | ACID compliance for booking atomicity; JSONB for metadata; pg_trgm for fuzzy service search; timezone support |
| **Cache** | Redis | 7.0+ | LangGraph checkpoints + Pub/Sub | In-memory speed (<5ms) for hot state; persistence via RDB snapshots; pub/sub for async messaging; TTL for state expiration |
| **File Storage** | Local Filesystem | N/A | Logs and backups | No user-uploaded files; logs rotate to `/var/log/`; PostgreSQL dumps to local → S3/Spaces daily |
| **Authentication** | Django Authentication | 5.0 (built-in) | Admin panel auth | Username/password for staff; no customer auth needed (WhatsApp handles identity) |
| **Frontend Testing** | N/A | N/A | No frontend tests | Admin panel is auto-generated; manual QA sufficient for CRUD forms |
| **Backend Testing** | pytest + pytest-asyncio | 8.3.0 / 0.24.0 | Unit & integration tests | Async test support for FastAPI/LangGraph; fixture-based testing; 85%+ coverage target |
| **E2E Testing** | pytest with mocked APIs | 8.3.0 | 18 scenario tests | Mock external APIs (Stripe, Google, Chatwoot) to test full conversation flows; deterministic test execution |
| **Build Tool** | pip | 24.0+ | Dependency management | Standard Python package manager; requirements.txt for reproducible builds |
| **Bundler** | N/A | N/A | No JS bundling | Django Admin serves pre-bundled static assets; no custom frontend build step |
| **IaC Tool** | Docker Compose | 2.20+ | Infrastructure definition | Multi-container orchestration (api, agent, data); environment parity dev/prod; simple deployment |
| **CI/CD** | GitHub Actions | N/A | Automated testing & deployment | Free for public repos; pytest + linting on PRs; deploy via SSH to VPS on main branch merge |
| **Monitoring** | LangSmith (optional) + Structured Logs | N/A / Python logging | LangGraph tracing + system logs | LangSmith for conversation flow debugging; JSON logs for error tracking; BetterStack/Grafana for prod |
| **Logging** | Python logging (JSON formatter) | 3.11 (stdlib) | Application logs | Structured JSON logs (timestamp, level, message, context); 14-day rotation; stderr to Docker logs |
| **CSS Framework** | Django Admin Default CSS | 5.0 (built-in) | Admin panel styling | No custom CSS needed; responsive grid; accessible by default (WCAG AA) |
| **Agent Orchestration** | LangGraph | 0.6.7+ | Stateful conversation flows | StateGraph for 18 scenarios; automatic checkpointing; conditional routing; human-in-the-loop support; crash recovery |
| **LLM Integration** | LangChain + LangChain-Anthropic | 0.3.0+ / 0.3.0+ | Tool abstraction + Claude SDK | LangChain @tool decorator for 5 tool categories; langchain-anthropic for Claude Sonnet 4 integration |
| **LLM Provider** | Anthropic Claude API | SDK 0.40.0+ | Natural language reasoning | Claude Sonnet 4 for cost/performance balance; 200k token context; tool use native; Spanish fluency |
| **ORM** | SQLAlchemy | 2.0+ | Database abstraction | Async support; type-safe queries; migration support via Alembic; repository pattern implementation |
| **Database Migrations** | Alembic | 1.13.0+ | Schema version control | Auto-generate migrations from SQLAlchemy models; rollback support; seed data scripts |
| **HTTP Client** | httpx | 0.27.0+ | External API calls | Async HTTP client for Google/Stripe/Chatwoot; connection pooling; retry logic |
| **Task Queue** | Redis Pub/Sub + asyncio | 7.0+ / 3.11 stdlib | Background workers | Lightweight pub/sub for reminders/timeouts; no Celery overhead; asyncio for in-process workers |
| **Payment Processing** | Stripe API | Python SDK 10.0+ | Payment links & webhooks | PCI-compliant hosted checkout; webhook signature validation; refund API; test mode for development |
| **Calendar Integration** | Google Calendar API | google-api-python-client 2.150+ | Event management | Service account auth; read/write events; multi-calendar support; timezone handling |
| **WhatsApp Integration** | Chatwoot API | httpx (no official SDK) | Message sending/receiving | Self-hosted or cloud Chatwoot; webhook for incoming messages; REST API for outgoing; conversation management |

---
