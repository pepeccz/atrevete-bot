# Atrévete Bot

![CI Status](https://github.com/pepe/atrevete-bot/actions/workflows/test.yml/badge.svg)

AI-powered WhatsApp booking assistant for a beauty salon, built with LangGraph, Claude Sonnet 4, and FastAPI.

## Overview

This bot handles customer bookings via WhatsApp through Chatwoot, managing appointments across 5 stylists using Google Calendar and escalating to staff when needed. The agent uses LangGraph for stateful conversation orchestration and Claude Sonnet 4 for natural language understanding in Spanish.

## Prerequisites

- **Python 3.11+** - Required for type hints and async/await support
- **Docker & Docker Compose** - For running PostgreSQL, Redis, and containerized services
- **External Service Accounts** - API keys and credentials for:
  - Google Calendar API (service account)
  - Chatwoot API (self-hosted or cloud)
  - Anthropic Claude API

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd atrevete-bot
```

### 2. Configure Environment Variables

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials. For detailed instructions on obtaining API keys, see [docs/external-services-setup.md](docs/external-services-setup.md).

**Required Variables:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Path to Google service account JSON key
- `GOOGLE_CALENDAR_IDS` - Comma-separated calendar IDs for 5 stylists
- `CHATWOOT_API_URL`, `CHATWOOT_API_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_INBOX_ID`
- `ANTHROPIC_API_KEY` - Claude API key
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string

### 3. Create Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Run Services Locally

See [docs/stories/1.2.docker-compose-setup.md](docs/stories/1.2.docker-compose-setup.md) for Docker Compose configuration to run PostgreSQL and Redis locally.

## Project Structure

```
atrevete-bot/
├── api/                    # FastAPI webhook receiver
├── agent/                  # LangGraph orchestrator
│   ├── graphs/            # Conversation flow graphs
│   ├── state/             # State schemas
│   ├── nodes/             # LangGraph nodes
│   ├── tools/             # LangChain tools
│   ├── prompts/           # System prompts
│   └── workers/           # Background workers
├── admin/                  # Django Admin interface
├── database/               # SQLAlchemy models & migrations
├── shared/                 # Shared utilities & config
├── docker/                 # Docker configurations
├── tests/                  # Test suite
│   ├── unit/              # Unit tests
│   ├── integration/       # Integration tests
│   └── mocks/             # API mocks
├── scripts/                # Utility scripts
└── docs/                   # Documentation
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests
pytest tests/integration/

# Run with coverage
pytest --cov=. --cov-report=html
```

### Code Quality

```bash
# Format code
black .

# Lint code
ruff check .

# Type check
mypy .
```

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## External Services Setup

For detailed instructions on setting up external service accounts and obtaining API keys, see:

- [docs/external-services-setup.md](docs/external-services-setup.md) - Complete setup guide
- [.env.example](.env.example) - Environment variable template

## Documentation

- [docs/prd/](docs/prd/) - Product Requirements Document (sharded)
- [docs/architecture/](docs/architecture/) - Architecture documentation (sharded)
- [docs/stories/](docs/stories/) - Development stories
- [docs/qa/](docs/qa/) - QA documentation

## Technology Stack

- **Agent:** LangGraph 0.6.7+, LangChain 0.3.0+, Claude Sonnet 4
- **API:** FastAPI 0.116.1, Uvicorn 0.30.0+
- **Database:** PostgreSQL 15+, SQLAlchemy 2.0+, Alembic 1.13+
- **Cache:** Redis 7.0+
- **Admin:** Django 5.0+
- **Testing:** pytest 8.3.0+, pytest-asyncio 0.24.0+
- **External APIs:** Google Calendar API, Chatwoot API

## License

[Add license information]

## Support

For issues, questions, or contributions, please [add contact information or link to issue tracker].
