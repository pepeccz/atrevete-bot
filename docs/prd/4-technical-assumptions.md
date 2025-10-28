# 4. Technical Assumptions

## 4.1 Repository Structure: **Monorepo**

**Decision:** Single repository with organized folder structure for API, Agent, Database, Docker, Tests, and Docs.

**Rationale:**
- Project scope is single-product, single-deployment (Atrévete Bot)
- Shared dependencies and tight coupling between API webhooks and Agent orchestration
- Simplified development workflow for solo developer
- Easier testing and CI/CD pipeline management

**Structure:**
```
atrevete-bot/
├── api/                 # FastAPI webhooks (Chatwoot, Stripe)
├── agent/               # LangGraph + LangChain + Claude
│   ├── graphs/          # StateGraph definitions
│   ├── state/           # TypedDict state schemas
│   ├── tools/           # CalendarTools, PaymentTools, etc.
│   ├── nodes/           # Graph node functions
│   └── prompts/         # System prompt for "Maite"
├── database/            # SQLAlchemy models, Alembic migrations
├── docker/              # Dockerfiles + docker-compose.yml
├── tests/               # Unit + integration tests (18 scenarios)
└── docs/                # Brief, PRD, Architecture, Scenarios
```

## 4.2 Service Architecture: **Monolith with 3 Docker Containers**

**Decision:** Monolithic application deployed as 3 specialized containers:
1. **API Container:** FastAPI receiving webhooks (Chatwoot, Stripe), enqueuing to Redis
2. **Agent Container:** LangGraph orchestrator + Workers (async tasks: reminders, timeouts, cleanup)
3. **Data Container:** PostgreSQL + Redis (can split in production if needed)

**Rationale:**
- **Not microservices:** Overkill for single-product with tight business logic coupling
- **Not serverless:** LangGraph requires stateful checkpointing and long-running conversations
- **Monolith advantages:** Simplified debugging, single deployment unit, no distributed system complexity

## 4.3 Testing Requirements: **Full Testing Pyramid**

**Decision:** Comprehensive testing strategy with unit, integration, and manual testing layers.

**Test Coverage:**
- **Unit Tests:** Individual tools tested in isolation with mocked external APIs
- **Integration Tests:** All 18 conversational scenarios tested end-to-end
- **Manual Testing:** Real stylist validation with actual customer scenarios
- **Concurrency Tests:** Race condition validation for double-booking prevention
- **Timeout Tests:** Payment timeout behavior validation

**Testing tools:**
- `pytest` + `pytest-asyncio` for async test support
- `pytest-cov` for coverage reporting (target: >85% code coverage)
- Mocking: `unittest.mock` for external API calls

## 4.4 Additional Technical Assumptions

**Languages & Frameworks:**
- **Backend:** Python 3.11+ (type hints, async/await support)
- **API Framework:** FastAPI 0.116+ (async native, Pydantic validation)
- **Agent Orchestration:** LangGraph 0.6.7+ (stateful conversation management, checkpointing)
- **LLM SDK:** Anthropic Claude SDK via LangChain integration
- **Admin Interface:** Django Admin or Flask-Admin (auto-generated CRUD forms)

**Databases:**
- **PostgreSQL 15+:** Primary data store (7 main tables)
- **Redis 7+:** Hot state (LangGraph checkpoints), Pub/Sub (message queue)

**External APIs & Integrations:**
- **Google Calendar API:** Service account with read/write permissions
- **Stripe API:** Payment Links generation, webhook validation
- **Chatwoot API:** Send WhatsApp messages, conversation management
- **Anthropic Claude API:** Sonnet 4 or Opus for conversational reasoning

**Infrastructure & Deployment:**
- **Development:** Docker Compose (3 services: api, agent, data)
- **Production:** Docker Compose on VPS (4GB RAM minimum)
- **HTTPS:** Required for Stripe webhooks—Nginx reverse proxy with Let's Encrypt
- **Timezone:** Europe/Madrid (explicit handling throughout)

**Monitoring & Observability:**
- **LangSmith:** Native LangGraph tracing (optional but recommended)
- **Structured Logs:** JSON format with log levels
- **Metrics:** Latency, escalation rate, checkpoint failures, API error rates

**Security & Compliance:**
- **Webhook Signature Validation:** Stripe and Chatwoot signatures verified
- **Rate Limiting:** 10 messages/min per customer
- **GDPR:** Customer data stored with consent, deletion endpoint available
- **PCI DSS:** Stripe-hosted payment pages (no local card data storage)

**Backup & Disaster Recovery:**
- **PostgreSQL:** Automated daily backups, 30-day retention
- **Redis:** RDB snapshots every 15 minutes
- **RTO:** <2 hours from catastrophic failure
- **RPO:** <15 minutes data loss maximum

---
