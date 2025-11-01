# 11. Unified Project Structure

```plaintext
atrevete-bot/
├── .github/                              # CI/CD workflows
│   └── workflows/
│       ├── test.yml                      # Run tests on PR
│       ├── lint.yml                      # Code quality checks
│       └── deploy.yml                    # Deploy to VPS on main merge
│
├── api/                                  # FastAPI webhook receiver
│   ├── __init__.py
│   ├── main.py                           # FastAPI app entry point
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── chatwoot.py                   # POST /webhook/chatwoot
│   │   ├── stripe.py                     # POST /webhook/stripe
│   │   └── health.py                     # GET /health
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── signature_validation.py      # Webhook signature verification
│   │   └── rate_limiting.py             # Redis-based rate limiter
│   └── models/
│       ├── __init__.py
│       ├── chatwoot_webhook.py          # Pydantic request models
│       └── stripe_webhook.py
│
├── agent/                                # LangGraph orchestrator
│   ├── __init__.py
│   ├── main.py                           # Agent entry point + Redis subscriber
│   ├── graphs/
│   │   ├── __init__.py
│   │   └── conversation_flow.py         # Main StateGraph definition
│   ├── state/
│   │   ├── __init__.py
│   │   └── schemas.py                   # ConversationState TypedDict
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── identification.py            # identify_customer, load_history
│   │   ├── classification.py            # classify_intent, detect_indecision
│   │   ├── availability.py              # check_availability, suggest_pack
│   │   ├── booking.py                   # create_provisional, confirm_booking
│   │   ├── payment.py                   # handle_payment, check_timeout
│   │   ├── modification.py              # modify_appointment, reschedule
│   │   ├── cancellation.py              # cancel_booking, process_refund
│   │   └── escalation.py                # escalate_to_human
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── calendar_tools.py            # Google Calendar API wrapper
│   │   ├── payment_tools.py             # Stripe API wrapper
│   │   ├── customer_tools.py            # Customer CRUD operations
│   │   ├── booking_tools.py             # Appointment business logic
│   │   └── notification_tools.py        # Chatwoot/Email/SMS
│   ├── prompts/
│   │   └── maite_system_prompt.md       # LLM system prompt
│   └── workers/
│       ├── __init__.py
│       ├── reminder_worker.py           # 48h advance reminders
│       ├── payment_timeout_worker.py    # Provisional block cleanup
│       └── conversation_archiver.py     # Redis → PostgreSQL archival
│
├── admin/                                # Django Admin interface
│   ├── __init__.py
│   ├── settings.py                       # Django settings
│   ├── urls.py                           # URL routing
│   ├── wsgi.py                           # WSGI entry point
│   ├── admin.py                          # ModelAdmin registrations
│   ├── forms.py                          # Custom form validations
│   ├── templates/
│   │   └── admin/
│   │       ├── base_site.html            # Custom branding
│   │       └── appointment_calendar.html # Read-only calendar view
│   └── static/
│       └── admin/
│           └── css/
│               └── custom.css            # Minimal styling overrides
│
├── database/                             # SQLAlchemy models + migrations
│   ├── __init__.py
│   ├── models.py                         # ORM models (7 tables)
│   ├── connection.py                     # Async engine + session factory
│   ├── alembic/                          # Alembic migration scripts
│   │   ├── versions/
│   │   ├── env.py
│   │   └── alembic.ini
│   └── seeds/
│       ├── __init__.py
│       ├── stylists.py                   # Seed 5 stylists
│       ├── services.py                   # Seed services from scenarios
│       └── policies.py                   # Seed business rules + FAQs
│
├── shared/                               # Shared utilities
│   ├── __init__.py
│   ├── config.py                         # Environment variable loading
│   ├── logging_config.py                 # Structured JSON logging setup
│   ├── redis_client.py                   # Redis connection singleton
│   └── constants.py                      # Shared enums, constants
│
├── docker/                               # Docker configurations
│   ├── Dockerfile.api                    # FastAPI container
│   ├── Dockerfile.agent                  # LangGraph + Workers container
│   ├── Dockerfile.admin                  # Django Admin container
│   ├── docker-compose.yml                # Development 3-service setup
│   ├── docker-compose.prod.yml           # Production with restart policies
│   └── nginx/
│       ├── nginx.conf                    # Reverse proxy config
│       └── ssl/                          # Let's Encrypt certificates
│
├── tests/                                # Test suite
│   ├── __init__.py
│   ├── conftest.py                       # Pytest fixtures (DB, Redis, mocks)
│   ├── unit/
│   │   ├── test_calendar_tools.py
│   │   ├── test_payment_tools.py
│   │   ├── test_customer_tools.py
│   │   └── test_booking_tools.py
│   ├── integration/
│   │   ├── test_api_webhooks.py
│   │   └── scenarios/                    # 18 scenario tests
│   │       ├── test_scenario_01_new_booking.py
│   │       ├── test_scenario_02_modification.py
│   │       ├── test_scenario_04_medical_escalation.py
│   │       └── ...
│   └── mocks/
│       ├── mock_stripe.py
│       ├── mock_google_calendar.py
│       └── mock_chatwoot.py
│
├── scripts/                              # Utility scripts
│   ├── setup_db.sh                       # Initialize PostgreSQL + run migrations
│   ├── seed_data.sh                      # Populate initial data
│   ├── backup_db.sh                      # PostgreSQL backup to S3
│   └── deploy.sh                         # SSH to VPS + docker-compose pull/up
│
├── docs/                                 # Documentation
│   ├── brief.md                          # Project brief
│   ├── prd.md                            # Product requirements
│   ├── architecture.md                   # This document
│   ├── tech-analysis.md                  # Technology evaluation
│   └── specs/
│       └── scenarios.md                  # 18 conversational scenarios
│
├── .env.example                          # Environment variable template
├── .gitignore                            # Ignore .env, __pycache__, .pytest_cache
├── requirements.txt                      # Python dependencies
├── pyproject.toml                        # Tool configs (black, ruff, mypy, pytest)
├── alembic.ini                           # Alembic migration config
├── README.md                             # Setup and deployment instructions
└── LICENSE                               # Project license
```

---
