# Atrévete Bot Documentation

**Welcome to the Atrévete Bot documentation hub.** This directory contains all technical and operational documentation for the project.

**Last Updated:** 2025-11-13

---

## 🚀 Quick Start (5 minutes)

**New to the project?** Start here:

1. **[QUICK-CONTEXT.md](QUICK-CONTEXT.md)** ⭐ - 5-minute overview of the entire project
2. **[CHANGELOG.md](CHANGELOG.md)** - Recent changes and historical context
3. **Root [CLAUDE.md](../CLAUDE.md)** - Complete development guide (updated for v3.2)

---

## 📚 Documentation Structure

### 01-core/ - Fundamental Architecture
*Core concepts that rarely change*

- **architecture.md** - High-level system architecture (⚠️ being deprecated, see DEPRECATION NOTICE)
- **data-models.md** - Database entities and relationships *(planned)*
- **tech-stack.md** - Technology decisions and versions *(planned)*
- **state-schema.md** - ConversationState detailed reference *(planned)*

### 02-specs/ - Technical Specifications
*Detailed specifications and requirements*

- **scenarios.md** - 18 conversation flows end-to-end
- **api-specification.md** - REST API and webhook specs *(planned)*
- **workflows.md** - Sequence diagrams and process flows *(planned)*

### 03-features/ - Feature Documentation
*Implementation details by feature area*

- **booking/** - Booking functionality
  - `flow.md` - Complete booking process *(migrated from Funcionalidades/)*
  - `business-rules.md` - Booking policies *(planned)*
- **payments/** *(removed - see CHANGELOG Nov 10, 2025)*
- **escalation/** - Human handoff documentation *(planned)*

### 04-implementation/ - Current Code State
*Living documents reflecting actual codebase*

- **current-state.md** - Implementation status by component *(in progress)*
- **components-map.md** - Quick reference for code locations *(in progress)*
- **booking-transaction-flow.md** - Complete technical flow of booking transaction (✅ Nov 13, 2025)
- **coding-patterns.md** - Common patterns with examples *(planned)*

### 05-operations/ - Operational Runbooks
*Day-to-day operations and troubleshooting*

- **prompt-optimization-v3.2.md** - v3.2 optimization guide
- **monitoring.md** - Metrics and alerting *(planned)*
- **troubleshooting.md** - Common issues and solutions *(planned)*

### 06-evolution/ - Historical Context
*Proposals, reports, and decision history*

- **proposals/**
  - `v3.0-simplification.md` - Architecture v3.0 proposal
- **reports/**
  - `2025-11-03-prompt-optimization.md` - Prompt optimization analysis
- **epics/**
  - `epic-1-foundation.md` - Initial implementation *(planned)*

### 07-data/ - Reference Data
*Static reference data and catalogs*

- **services.csv** - Service catalog (92 services)
- **stylists.md** - Stylist information *(planned)*

### templates/ - Documentation Templates
*Reusable templates for new documents*

- **feature-template.md** - Template for new features *(in progress)*
- **changelog-entry.md** - Template for changelog entries *(in progress)*
- **update-docs-checklist.md** - Update checklist *(in progress)*

---

## 🎯 Documentation by Audience

### For Developers
**Essential reading:**
1. [QUICK-CONTEXT.md](QUICK-CONTEXT.md) - System overview
2. [../CLAUDE.md](../CLAUDE.md) - Development commands and patterns
3. [CHANGELOG.md](CHANGELOG.md) - Recent changes
4. [02-specs/scenarios.md](specs/scenarios.md) - Test scenarios

**Deep dives:**
- [01-core/architecture.md](architecture.md) - System design (⚠️ being updated)
- [04-implementation/components-map.md](04-implementation/components-map.md) - Code navigation *(in progress)*
- [05-operations/prompt-optimization-v3.2.md](PROMPT_OPTIMIZATION.md) - v3.2 optimizations

### For Product Owners
**Essential reading:**
1. [02-specs/scenarios.md](specs/scenarios.md) - User flows
2. [03-features/booking/flow.md](Funcionalidades/agendar-cita.md) - Booking feature
3. [CHANGELOG.md](CHANGELOG.md) - Feature history

### For Operations/DevOps
**Essential reading:**
1. [../CLAUDE.md](../CLAUDE.md) - Deployment commands
2. [05-operations/prompt-optimization-v3.2.md](PROMPT_OPTIMIZATION.md) - Performance optimization
3. [QUICK-CONTEXT.md](QUICK-CONTEXT.md) - Quick troubleshooting reference

---

## 📖 Key Documents Quick Reference

| Document | Purpose | Last Updated | Status |
|----------|---------|--------------|--------|
| [QUICK-CONTEXT.md](QUICK-CONTEXT.md) | 5-min project overview | 2025-11-13 | ✅ Current |
| [CHANGELOG.md](CHANGELOG.md) | Historical changes | 2025-11-13 | ✅ Current |
| [../CLAUDE.md](../CLAUDE.md) | Development guide | 2025-11-13 | ✅ Current (v3.2) |
| [04-implementation/booking-transaction-flow.md](04-implementation/booking-transaction-flow.md) | Booking transaction internals | 2025-11-13 | ✅ Current |
| [architecture.md](architecture.md) | System architecture | 2025-10-28 | ⚠️ Being deprecated |
| [specs/scenarios.md](specs/scenarios.md) | 18 conversation flows | 2025-10-23 | ✅ Current |
| [PROMPT_OPTIMIZATION.md](PROMPT_OPTIMIZATION.md) | v3.2 optimization guide | 2025-11-03 | ✅ Current |

---

## 🔄 Documentation Maintenance

### Update Protocol

When making code changes, update these docs:

**ALWAYS update:**
- `CHANGELOG.md` - Add entry with date, files affected, context
- `../CLAUDE.md` - If changes affect development workflows

**Update if relevant:**
- `QUICK-CONTEXT.md` - If architecture/concepts change
- `04-implementation/current-state.md` - If implementation status changes
- `04-implementation/components-map.md` - If files move or new components added

**See:** `templates/update-docs-checklist.md` for detailed guidance *(in progress)*

### Documentation Versioning

- **v1.0** (Oct 28, 2025): Initial architecture document
- **v3.0** (Nov 3, 2025): Architecture simplification (proposal)
- **v3.2** (Nov 3, 2025): Prompt optimization (implemented)
- **Current** (Nov 13, 2025): Modular documentation structure

---

## 🐛 Known Documentation Issues

1. **architecture.md** is being deprecated and split into smaller files (see DEPRECATION NOTICE)
2. Several planned documents marked *(planned)* are not yet created
3. Some file paths reference old locations (e.g., `Funcionalidades/` being migrated to `03-features/`)

---

## 📝 Contributing to Documentation

### Adding New Documentation

1. Choose appropriate directory based on content type
2. Use templates from `templates/` directory
3. Update this README.md with the new document
4. Add entry to `CHANGELOG.md`

### Reporting Documentation Issues

- Outdated information: Update directly + add CHANGELOG entry
- Missing documentation: Create issue or add to *(planned)* list
- Unclear sections: Add clarifying comments or examples

---

## 🔗 External Resources

- **Project Root:** [../](../)
- **Source Code:** `../agent/`, `../api/`, `../database/`
- **Tests:** `../tests/`
- **Docker Config:** `../docker-compose.yml`

---

## 📞 Need Help?

1. **Quick answers:** Check [QUICK-CONTEXT.md](QUICK-CONTEXT.md)
2. **Development help:** See [../CLAUDE.md](../CLAUDE.md)
3. **Recent changes:** Review [CHANGELOG.md](CHANGELOG.md)
4. **Specific features:** Browse `03-features/` directory
5. **Code locations:** Check `04-implementation/components-map.md` *(in progress)*

---

**Last maintenance:** 2025-11-13
**Maintainer:** Development Team
**Status:** 🚧 Active migration from monolithic to modular structure
