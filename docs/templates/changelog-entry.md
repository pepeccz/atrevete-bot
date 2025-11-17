# Changelog Entry Template

Copy this template when adding a new entry to `docs/CHANGELOG.md`.

---

## [YYYY-MM-DD] - Brief Title of Change
### Added/Changed/Removed
- Item 1: Description
- Item 2: Description
- Item 3: Description

**Commit(s):** `abc1234` - Commit message

**Files affected:**
- `path/to/file.py:line-numbers` - What changed
- `another/file.py:line-numbers` - What changed
- `config/file.yml` - What changed

**Context:** Why was this change made? What problem does it solve? What's the impact?

**Impact:**
- Performance: +X% improvement / -X% degradation
- Cost: +$X/mo / -$X/mo
- Breaking changes: Yes/No - Details if yes
- Migration required: Yes/No - Steps if yes

---

## Examples

### Example 1: Feature Addition

## [2025-11-06] - Django Admin Implementation
### Added
- Complete Django Admin interface at `http://localhost:8001/admin`
- Admin models: Customers, Stylists, Services, Appointments, Policies, Conversation History, Business Hours
- Custom purple gradient theme with Spanish interface
- Import/Export functionality (CSV, Excel, JSON)

**Commit:** `cf0029d` - DJ Ango 0.1

**Files affected:**
- `admin/` directory (entire Django app)
- `admin/core/admin.py:1-452` (7 ModelAdmin classes)
- `admin/core/models.py:1-355` (unmanaged models)

**Context:** Provides salon staff with user-friendly interface to manage business data without direct database access.

**Impact:**
- Staff productivity: +50% (estimated)
- No breaking changes
- No migration required (uses existing database)

---

### Example 2: Major Refactoring

## [2025-11-03] - Prompt Optimization v3.2
### Changed
- Prompt size: 27KB → 8-10KB (-63%)
- Tokens/request: ~7,000 → ~2,500-3,000 (-60%)
- Cost/1K conversations: $1,350/mo → $280/mo (-79%)

### Added
- Modular prompt loading (8 files)
- 6-state granular detection
- In-memory stylist caching (10min TTL)

**Commits:**
- Multiple commits over 3 days

**Files affected:**
- `agent/prompts/__init__.py:197-327`
- `agent/nodes/conversational_agent.py:318-424`
- `agent/state/schemas.py:21-122`
- `agent/tools/*.py` (truncation)

**Context:** Major optimization to reduce costs while maintaining quality. OpenRouter auto-caching + modular prompts.

**Impact:**
- Cost: -$1,070/mo savings
- Performance: -90% DB queries (caching)
- No breaking changes
- No migration required

---

### Example 3: Bug Fix

## [2025-11-13] - Fix service_resolver price_euros reference
### Removed
- Reference to deleted `price_euros` field in `service_resolver.py`

**Commit:** Part of documentation overhaul

**Files affected:**
- `agent/utils/service_resolver.py:148` (1 line removed)

**Context:** Field was removed in payment elimination (Nov 10) but code still referenced it, causing AttributeError.

**Impact:**
- Bug severity: High (blocking ambiguous service resolution)
- Breaking changes: No
- Migration required: No

---

## Checklist Before Adding Entry

- [ ] Date is correct (YYYY-MM-DD)
- [ ] Title is clear and concise
- [ ] Section (Added/Changed/Removed) is correct
- [ ] Commit hash(es) included
- [ ] Files affected listed with line numbers
- [ ] Context explains WHY, not just WHAT
- [ ] Impact quantified where possible
- [ ] Placed in chronological order (newest first)
