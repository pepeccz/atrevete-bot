# AI Agent Skills

This directory contains **Agent Skills** following the [Agent Skills open standard](https://agentskills.io). Skills provide domain-specific patterns, conventions, and guardrails that help AI coding assistants understand project-specific requirements.

## What Are Skills?

Skills teach AI assistants how to perform specific tasks. When an AI loads a skill, it gains context about:

- Critical rules (what to always/never do)
- Code patterns and conventions
- Project-specific workflows
- References to detailed documentation

## Setup

Run the setup script to configure skills for your AI coding assistants.

### Linux/macOS/WSL/Git Bash

```bash
./skills/setup.sh              # Interactive mode
./skills/setup.sh --all        # All AI assistants
./skills/setup.sh --claude     # Only Claude Code
./skills/setup.sh --help       # Show help
```

### Windows (PowerShell)

```powershell
.\skills\setup.ps1             # Interactive mode
.\skills\setup.ps1 -All        # All AI assistants
.\skills\setup.ps1 -Claude     # Only Claude Code
.\skills\setup.ps1 -Help       # Show help
```

> **Note**: On Windows, run as Administrator or enable Developer Mode for symlinks.

### Supported AI Assistants

| AI Assistant | Directory/Files Created |
|--------------|------------------------|
| Claude Code | `.claude/skills/` + `CLAUDE.md` copies |
| Gemini CLI | `.gemini/skills/` + `GEMINI.md` copies |
| Codex (OpenAI) | `.codex/skills/` (uses AGENTS.md natively) |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Cursor IDE | `.cursor/rules/` + `.cursorrules` |

## How to Use Skills

Skills are automatically discovered by the AI agent via `AGENTS.md`. To manually load a skill:

```
Read skills/{skill-name}/SKILL.md
```

## Available Skills

### Generic Skills

Reusable patterns for common technologies:

| Skill | Description |
|-------|-------------|
| `langgraph` | StateGraph, nodes, edges, checkpointers, tools |
| `fastapi` | Routers, Pydantic, dependency injection, middleware |
| `sqlalchemy-async` | Async models, relationships, queries |
| `pytest-async` | Async fixtures, mocking, parametrize |
| `skill-creator` | Create new AI agent skills |

### Atrévete Specific Skills

Patterns tailored for this project:

| Skill | Description |
|-------|-------------|
| `atrevete` | Project overview, architecture, component navigation |
| `atrevete-agent` | LangGraph flow, nodes, state, tools, prompts |
| `atrevete-api` | FastAPI routes, services, Chatwoot webhooks |
| `atrevete-database` | SQLAlchemy models, Alembic migrations, seeds |

## Directory Structure

```
skills/
├── {skill-name}/
│   ├── SKILL.md              # Required - main instruction and metadata
│   ├── assets/               # Optional - templates, schemas, resources
│   └── references/           # Optional - links to local docs
└── README.md                 # This file
```

## Creating New Skills

### SKILL.md Template

```markdown
---
name: {skill-name}
description: >
  {One-line description}.
  Trigger: {When the AI should load this skill}.
metadata:
  author: atrevete-bot
  version: "1.0"
  scope: [root, api, agent, database]
  auto_invoke: "Action that triggers this skill"
---

## When to Use

{Bullet points of when to use this skill}

## Critical Patterns

{The most important rules - what AI MUST know}

## Code Examples

{Minimal, focused examples}

## Commands

```bash
{Common commands}
```
```

### Naming Conventions

| Type | Pattern | Examples |
|------|---------|----------|
| Generic skill | `{technology}` | `fastapi`, `langgraph`, `pytest-async` |
| Atrévete specific | `atrevete-{component}` | `atrevete-api`, `atrevete-agent`, `atrevete-database` |

## Design Principles

- **Concise**: Only include what AI doesn't already know
- **Progressive disclosure**: Point to detailed docs, don't duplicate
- **Critical rules first**: Lead with ALWAYS/NEVER patterns
- **Minimal examples**: Show patterns, not tutorials

## Resources

- [Agent Skills Standard](https://agentskills.io) - Open standard specification
- [skill-sync](skill-sync/SKILL.md) - Keep AGENTS.md Auto-invoke tables in sync
- [AGENTS.md](../AGENTS.md) - Main repository guidelines
