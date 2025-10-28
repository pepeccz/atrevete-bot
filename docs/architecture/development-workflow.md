# 12. Development Workflow

## 12.1 Local Development Setup

### Prerequisites

```bash
# Required software
python --version  # 3.11+
docker --version  # 20.10+
docker-compose --version  # 2.20+
git --version

# Install Python dependencies
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### Initial Setup

```bash
# Clone repository
git clone https://github.com/atrevete/atrevete-bot.git
cd atrevete-bot

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Start infrastructure
docker-compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Seed initial data
python -m database.seeds.stylists
python -m database.seeds.services
python -m database.seeds.policies
```

## 12.2 Development Commands

```bash
# Start all services
docker-compose up

# Run tests
pytest tests/
pytest --cov=agent --cov=api --cov-report=html

# Code quality checks
ruff check .
ruff format .
mypy agent/ api/ admin/
```

---
