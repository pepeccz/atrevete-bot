# Atrévete Bot - Documentation Index

## Project Overview

- **Type**: Monolith - Backend API with AI Agent
- **Primary Language**: Python 3.11+
- **Architecture**: Service/API-centric with LangGraph orchestration (v3.2)

## Quick Reference

| Attribute | Value |
|-----------|-------|
| **Tech Stack** | LangGraph 0.6.7+, FastAPI 0.116.1, SQLAlchemy 2.0+, Django 5.0+ |
| **LLM** | GPT-4.1-mini via OpenRouter |
| **Database** | PostgreSQL 15+ |
| **Cache** | Redis Stack (RedisSearch, RedisJSON) |
| **Entry Points** | `api/main.py`, `agent/main.py`, `admin/atrevete_admin/wsgi.py` |

---

## Generated Documentation

### Core Documentation

- [Project Overview](./project-overview.md) - Executive summary, tech stack, architecture
- [Architecture Document](./architecture.md) - System design, data flow, components
- [Source Tree Analysis](./source-tree-analysis.md) - Annotated directory structure

### Technical References

- [API Contracts](./api-contracts.md) - REST endpoints, request/response formats
- [Data Models](./data-models.md) - Database schema, relationships, migrations
- [Admin Panel](./admin-panel.md) - Django Admin interface, models, features

### Developer Resources

- [Development Guide](./development-guide.md) - Setup, commands, best practices

---

## Existing Documentation

- [README.md](../README.md) - Project overview and quick start
- [CLAUDE.md](../CLAUDE.md) - Comprehensive AI assistant context (~21KB)
- [.github/workflows/test.yml](../.github/workflows/test.yml) - CI/CD pipeline

---

## Getting Started

### For AI-Assisted Development

1. Start with [Architecture Document](./architecture.md) for system understanding
2. Reference [CLAUDE.md](../CLAUDE.md) for development commands and patterns
3. Use [API Contracts](./api-contracts.md) for endpoint details
4. Check [Data Models](./data-models.md) for database schema

### For New Features

1. Review [Project Overview](./project-overview.md) for system capabilities
2. Check [Source Tree Analysis](./source-tree-analysis.md) for file locations
3. Follow patterns in [Development Guide](./development-guide.md)

### Quick Commands

```bash
# Start all services
docker-compose up -d

# Run tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest

# Apply migrations
DATABASE_URL="postgresql+psycopg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/alembic upgrade head

# View logs
docker-compose logs -f agent
```

---

## Key Files Reference

| Purpose | Location |
|---------|----------|
| Configuration | `shared/config.py` |
| State Schema | `agent/state/schemas.py` |
| Graph Definition | `agent/graphs/conversation_flow.py` |
| Database Models | `database/models.py` |
| Agent Tools | `agent/tools/*.py` |
| System Prompts | `agent/prompts/*.md` |
| API Routes | `api/routes/*.py` |

---

## Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| API | http://localhost:8000 | Webhook receiver |
| Admin | http://localhost:8001/admin | Django Admin |
| pgAdmin | http://localhost:5050 | Database management |
| Health | http://localhost:8000/health | Service health check |

---

## Document Metadata

- **Generated**: 2025-11-19
- **Scan Level**: Exhaustive
- **Workflow Version**: 1.2.0
- **Agent**: BMad Analyst (Mary)
