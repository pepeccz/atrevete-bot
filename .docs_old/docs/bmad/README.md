# BMAD Documentation Index

**Methodology:** Behavior, Measure, Act, Document

Este directorio contiene documentación detallada de todos los issues críticos descubiertos y resueltos durante la implementación del proyecto Atrévete Bot, siguiendo la metodología BMAD para debugging estructurado.

---

## Story 1.5: Basic LangGraph State & Echo Bot

Durante la implementación de Story 1.5, se descubrieron **4 issues críticos** que bloqueaban el flujo end-to-end de mensajes. Todos fueron resueltos y documentados.

### BMAD 1.5a: AsyncRedisSaver Initialization Pattern Fix

**File:** `1.5a-asyncredissaver-initialization-pattern.md`
**Severity:** Critical (Blocking)
**Status:** ✅ Resolved
**Date:** 2025-10-28

**Problem:**
Direct instantiation of `AsyncRedisSaver` caused indefinite hang during agent initialization.

**Solution:**
Implemented async context manager pattern with `async with AsyncRedisSaver.from_conn_string()`.

**Files Modified:**
- `/agent/main.py:46-157`

**Impact:** Agent startup time: ∞ → 4 seconds

---

### BMAD 1.5b: Redis Stack Requirement for RedisSearch

**File:** `1.5b-redis-stack-requirement.md`
**Severity:** Critical (Blocking)
**Status:** ✅ Resolved
**Date:** 2025-10-28

**Problem:**
LangGraph's `AsyncRedisSaver` requires RedisSearch module (FT.* commands), not available in vanilla Redis.

**Solution:**
Changed Docker image from `redis:7-alpine` to `redis/redis-stack:latest`.

**Files Modified:**
- `/docker-compose.yml:26-43`

**Impact:** Redis image size: 30MB → 450MB (acceptable for local dev)

---

### BMAD 1.5c: Chatwoot API URL Trailing Slash Fix

**File:** `1.5c-chatwoot-api-url-trailing-slash.md`
**Severity:** High (Blocking outbound messages)
**Status:** ✅ Resolved
**Date:** 2025-10-28

**Problem:**
Trailing slash in `CHATWOOT_API_URL` environment variable caused double-slash concatenation (`https://...//api/v1/...`), resulting in 404 errors on POST requests.

**Solution:**
Normalize base URL by removing trailing slash: `settings.CHATWOOT_API_URL.rstrip("/")`.

**Files Modified:**
- `/agent/tools/notification_tools.py:36`

**Impact:** API calls reduced from failing (404) to successful (200 OK)

**Interesting Discovery:** GET requests with double slash returned 200 OK, but POST returned 404 (Chatwoot API behavior).

---

### BMAD 1.5d: Use Existing Conversation ID from Webhook

**File:** `1.5d-use-existing-conversation-id.md`
**Severity:** Critical (Blocking outbound messages)
**Status:** ⏳ In Progress (Code complete, pending deployment)
**Date:** 2025-10-28

**Problem:**
Agent attempted to CREATE new conversations instead of using existing `conversation_id` provided by Chatwoot webhooks, resulting in 404 errors and unnecessary API calls.

**Solution:**
Modified `send_message()` to accept optional `conversation_id` parameter and use it directly when provided.

**Files Modified:**
- `/agent/tools/notification_tools.py:195-262`
- `/agent/main.py:195-212`

**Impact:**
- API calls per message: 3 (search, get, create) → 1 (send)
- Response time: ~3 seconds → ~0.5 seconds (estimated)
- Error rate: 100% (404) → 0% (expected after deployment)

---

## BMAD Methodology

### What is BMAD?

BMAD is a structured debugging and documentation methodology with four phases:

1. **Behavior:** Observe and describe symptoms, user impact, and root cause analysis
2. **Measure:** Quantify the problem with logs, metrics, and evidence
3. **Act:** Implement solution, deploy, and validate results
4. **Document:** Record lessons learned, patterns, testing strategy, and prevention measures

### When to Create a BMAD Document

Create a BMAD document for:
- Critical issues that block core functionality
- Issues requiring >1 hour investigation
- Issues with non-obvious root causes
- Issues likely to recur if not properly documented
- Issues that reveal architectural or design flaws

### BMAD Document Template

```markdown
# BMAD: [Issue Title]

**Story:** [Story Number & Name]
**Date:** [YYYY-MM-DD]
**Severity:** [Critical/High/Medium/Low] [(Impact Description)]
**Status:** [✅ Resolved / ⏳ In Progress / ❌ Not Started]

---

## Behavior

### Observed Symptoms
[What was seen, error messages, logs]

### User Impact
[How this affected users/developers]

### Analysis
[Root cause investigation, why it happened]

---

## Measure

### Before Fix - [Code/Infrastructure/Configuration]
[Code snippets, configuration files, evidence of problem]

### Evidence of [Problem Name]
[Logs, metrics, test results showing the problem]

---

## Act

### Solution Implemented
[Strategy and changes made]

### Deployment
[How solution was deployed]

### Validation Results
[Proof that solution works]

---

## Document

### Lessons Learned
[What we learned from this issue]

### Knowledge Base
[Patterns, best practices, recommendations]

### Testing Strategy
[Test cases to prevent regression]

### Related Issues
[Links to related BMAD docs, stories, tasks]

### Prevention
[How to prevent this in the future]

---

**Resolution Time:** [Time spent]
**Related Files:** [List of modified files]
**Impact:** [Summary of impact]
**References:** [External docs, links, resources]
```

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total BMAD Documents | 4 |
| Critical Issues | 4 |
| Total Resolution Time | ~6 hours |
| Files Modified | 3 |
| Files Created | 4 (documentation) |
| Epic Progress Impact | Unblocked Story 1.5 (72% → targeting 100%) |

---

## Quick Reference

### By Severity

**Critical (Blocking):**
- BMAD 1.5a: AsyncRedisSaver Initialization
- BMAD 1.5b: Redis Stack Requirement
- BMAD 1.5d: Conversation ID Handling

**High (Blocking outbound messages):**
- BMAD 1.5c: URL Trailing Slash

### By Component

**Infrastructure:**
- BMAD 1.5b: Redis Stack

**Agent:**
- BMAD 1.5a: AsyncRedisSaver
- BMAD 1.5d: Conversation ID

**API Integration:**
- BMAD 1.5c: URL Normalization
- BMAD 1.5d: Conversation ID

### By Type

**Initialization Issues:**
- BMAD 1.5a: AsyncRedisSaver async context manager
- BMAD 1.5b: Redis Stack modules

**Integration Issues:**
- BMAD 1.5c: Chatwoot API URL construction
- BMAD 1.5d: Chatwoot conversation ID usage

---

## Related Documentation

- **Story 1.5 Completion Summary:** `/docs/STORY-1.5-COMPLETION-SUMMARY.md`
- **Epic Details:** `/docs/epic-details.md` (Lines 184-205)
- **Story 1.5 Acceptance Criteria:** `/docs/stories/1.5.basic-langgraph-echo-bot.md`

---

**Last Updated:** 2025-10-28
**Maintainer:** Development Team
**Contact:** See project README for team contacts
