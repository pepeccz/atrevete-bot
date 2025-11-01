# Story Update Notes - Architecture Simplification
## Quick Reference for Stories Affected by Hybrid Architecture

**Date:** 2025-10-30
**Context:** Architecture simplified from rigid 25-node state machine to hybrid conversational + transactional (12 nodes)

---

## Purpose of This Document

This document provides **quick update notes** to prepend to affected story files WITHOUT rewriting them completely. This preserves project history while documenting architectural changes.

---

## How to Use This Document

### Option 1: Add Note Header to Each Story (5 minutes)
Copy the appropriate note below and paste it at the **top** of each affected story file.

### Option 2: Reference This Document (0 minutes)
Leave stories unchanged and have developers read this document alongside original stories.

**Recommendation:** Option 2 (no changes needed, this document has all context)

---

## Stories Affected + Update Notes

### Story 2.2: New Customer Greeting & Name Confirmation
**File:** `docs/stories/2.2.new-customer-greeting-name-confirmation.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `greet_new_customer` and `confirm_name` nodes).

**New Implementation (Hybrid Architecture):**
- Handled by single `conversational_agent` node with tool `create_customer(phone, name)`
- No `awaiting_name_confirmation` state flag (Claude manages conversation context)
- No dedicated `confirm_name` node (Claude extracts name conversationally)

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 2.2" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 1-2 for implementation guide

**Core functionality unchanged:**
- ✅ Bot greets new customers warmly with Maite personality
- ✅ Bot asks for customer name naturally
- ✅ Bot creates Customer record in database
- ✅ Bot handles ambiguous name responses

---

### Story 2.3: Returning Customer Recognition & Intent Extraction
**File:** `docs/stories/2.3.returning-customer-recognition.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `greet_returning_customer` and `extract_intent` nodes).

**New Implementation (Hybrid Architecture):**
- Handled by single `conversational_agent` node with tool `get_customer_by_phone(phone)`
- No explicit intent classification node (Claude reasons about intent naturally)
- No `current_intent` state flag with explicit enum values

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 2.3" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 1-2 for implementation guide

**Core functionality unchanged:**
- ✅ Bot recognizes returning customers by phone number
- ✅ Bot greets returning customers by first name
- ✅ Bot accesses customer history for context
- ✅ Bot understands booking vs inquiry vs FAQ intents

---

### Story 2.6: FAQ Knowledge Base Responses
**File:** `docs/stories/2.6.faq-knowledge-base-responses.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `detect_faq_intent`, `answer_faq`, and `generate_faq_response` nodes).

**New Implementation (Hybrid Architecture):**
- Handled by single `conversational_agent` node with tool `get_faqs(keywords=None)`
- No `faq_detected`, `detected_faq_ids`, or `query_complexity` state flags
- No routing between static vs AI FAQ answering (Claude decides naturally)

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 2.6" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 2 for tool conversion guide

**Core functionality unchanged:**
- ✅ Bot answers questions about hours, location, parking, policies
- ✅ Bot provides accurate FAQ answers from database
- ✅ Bot handles compound FAQ queries naturally
- ✅ Bot incorporates FAQ data into conversational responses

---

### Story 3.3: Multi-Calendar Availability Checking
**File:** `docs/stories/3.3.multi-calendar-availability-checking.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `check_availability` node).

**New Implementation (Hybrid Architecture):**
- **Node converted to Tool:** `check_availability_tool(service_category, date, time_range)`
- Tool can be called by:
  - **Conversational agent** (for informational queries: "¿cuándo tenéis libre?")
  - **Transactional flow** (when booking intent confirmed)
- No complex routing after availability check (Claude handles naturally)

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 3.3" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 2 for tool creation guide

**Core functionality unchanged:**
- ✅ System queries Google Calendar API for multiple stylists
- ✅ System detects holidays via 'Festivo'/'Cerrado' calendar events
- ✅ System prioritizes slots (preferred stylist, closest to requested time)
- ✅ System presents 2-3 top slots to customer

---

### Story 3.4: Pack Suggestion Logic & Acceptance Flow
**File:** `docs/stories/3.4.pack-suggestion-logic-acceptance-flow.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `suggest_pack` and `handle_pack_response` nodes with `awaiting_pack_response` state flag).

**New Implementation (Hybrid Architecture):**
- **Nodes converted to Tool:** `suggest_pack_tool(service_ids)`
- No `awaiting_pack_response` state flag (Claude tracks conversation context)
- No `handle_pack_response` node (Claude handles accept/decline conversationally)
- No topic change detection escape hatch needed (Claude handles naturally)

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 3.4" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 2 for tool creation guide

**Core functionality unchanged:**
- ✅ System queries Pack table for services matching requested services
- ✅ System calculates savings (individual_price - pack_price)
- ✅ System presents pack offer with savings highlighted
- ✅ System accepts 'sí', 'perfecto', 'vale' as pack acceptance
- ✅ System declines 'no', 'solo individual' as pack decline

---

### Story 3.5: Indecision Detection & Consultation Offering
**File:** `docs/stories/3.5.indecision-detection-consultation-offering.md`

**🔄 ARCHITECTURE UPDATE NOTE (2025-10-30):**

This story's **acceptance criteria refer to old architecture** (dedicated `detect_indecision`, `offer_consultation`, and `handle_consultation_response` nodes with multiple state flags).

**New Implementation (Hybrid Architecture):**
- **Nodes converted to Tool:** `offer_consultation_tool(reason)`
- No `indecision_detected`, `confidence`, `indecision_type` state flags
- No `consultation_offered`, `consultation_accepted`, `consultation_declined` state flags
- Claude reasons about indecision naturally based on conversation context
- No topic change detection escape hatch needed

**What to implement:**
- See `docs/architecture-update-affected-stories.md` Section "Story 3.5" for detailed AC changes
- See `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` Day 2 for tool creation guide

**Core functionality unchanged:**
- ✅ System detects indecision patterns: '¿cuál recomiendas?', 'no sé si...'
- ✅ System queries CONSULTA GRATUITA service (15min, free)
- ✅ System offers consultation with personalized message
- ✅ System accepts 'sí, prefiero consulta' as acceptance
- ✅ System declines 'no gracias' and returns to service selection

---

### Story 3.6: Service Category Mixing Prevention
**File:** `docs/stories/3.6.service-category-mixing-prevention.md`

**✅ NO ARCHITECTURE CHANGES - STORY UNCHANGED**

This story implements `validate_booking_request` node which is part of **Tier 2 (Transactional Flow)** and is **fully preserved** in the new architecture.

**Implementation remains exactly as documented in original story.**

---

## Master Reference Documents

When implementing ANY of the stories above, developers should reference these documents in order:

1. **Primary Implementation Guide:**
   - `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md`
   - Contains day-by-day plan, code examples, success criteria

2. **Detailed Story Changes:**
   - `docs/architecture-update-affected-stories.md`
   - Contains story-by-story AC changes, test examples

3. **Architecture Context:**
   - `docs/bmad/3.0-architecture-simplification-pivot.md`
   - Contains rationale, before/after comparison, code patterns

4. **High-Level Proposal:**
   - `docs/sprint-change-proposal-architecture-simplification.md`
   - Contains problem statement, solution overview, impact analysis

---

## Quick Decision Matrix for Developers

**When implementing a story that mentions old architecture:**

| Story References | New Implementation | Where to Find Details |
|------------------|-------------------|----------------------|
| `greet_customer`, `greet_new_customer`, `confirm_name` nodes | `conversational_agent` + `create_customer` tool | DEVELOPER-HANDOFF Day 1-2 |
| `greet_returning_customer`, `extract_intent` nodes | `conversational_agent` + `get_customer_by_phone` tool | DEVELOPER-HANDOFF Day 1-2 |
| `detect_faq_intent`, `answer_faq`, `generate_faq_response` nodes | `conversational_agent` + `get_faqs` tool | DEVELOPER-HANDOFF Day 2 |
| `check_availability` node | `check_availability_tool` | DEVELOPER-HANDOFF Day 2 |
| `suggest_pack`, `handle_pack_response` nodes | `suggest_pack_tool` | DEVELOPER-HANDOFF Day 2 |
| `detect_indecision`, `offer_consultation`, `handle_consultation_response` nodes | `offer_consultation_tool` | DEVELOPER-HANDOFF Day 2 |
| `validate_booking_request` node | **NO CHANGE** (implement as documented) | Original story is correct |
| Any `awaiting_*` state flag | **DELETE** (Claude manages context) | BMAD 3.0 Section "State Reduction" |

---

## Session Context Preservation

**Problem:** How to maintain context between sessions when developer returns to work?

**Solution:** Use this "Context Restoration Checklist"

### Context Restoration Checklist (Start of Each Session)

Developer should read (5-10 minutes):

1. ✅ **This document** (`STORY-UPDATE-NOTES.md`) - Quick reference for story changes
2. ✅ **DEVELOPER-HANDOFF** (`DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md`) - Where am I in the 6-day plan?
3. ✅ **Git log** (`git log --oneline -10`) - What did I complete yesterday?
4. ✅ **Current phase tasks** (from DEVELOPER-HANDOFF) - What's next today?

### Work-in-Progress Tracking

At **end of each session**, developer should:

```bash
# Commit progress with descriptive message
git add .
git commit -m "Day 3/6: State schema simplification - Completed ConversationState reduction (158→50 fields)"

# Push to branch
git push origin architecture-simplification

# Document blockers/notes (if any)
echo "Day 3 Complete. Next: Day 4 - LangGraph refactoring" >> IMPLEMENTATION-LOG.md
```

---

## Summary: What YOU (Pepe) Need to Do

### Option 1: MINIMAL WORK (Recommended)

**Do NOTHING to stories** ✅

- Stories remain as-is (historical record)
- Developers use this document (`STORY-UPDATE-NOTES.md`) as adapter
- All implementation details in `DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md`

**Effort:** 0 minutes

---

### Option 2: ADD HEADER NOTES

**Add header note to 6 story files** (5 minutes total)

For each affected story (2.2, 2.3, 2.6, 3.3, 3.4, 3.5), prepend this:

```markdown
---
**🔄 ARCHITECTURE UPDATE (2025-10-30):** This story's acceptance criteria refer to old architecture. See `docs/STORY-UPDATE-NOTES.md` Section "[Story Number]" for updated implementation guidance.
---
```

**Effort:** 5 minutes

---

### Option 3: FULL REWRITE (Not Recommended)

**Rewrite 6 story files completely** with new ACs

**Effort:** 3-4 hours
**Value:** Low (documentation already exists in other files)

---

## My Recommendation (Sarah - PO)

✅ **Option 1: Do NOTHING**

**Rationale:**
- Developer Agent has ALL necessary documentation in handoff package
- Stories are historical artifacts showing evolution of thinking
- Rewriting wastes time when info exists in other docs
- MVP focus: ship fast, document minimally

**Alternative naming:** You could rename old stories to `2.2.new-customer-greeting-name-confirmation-OLD.md` and note they're "pre-simplification" if you want clarity, but even this is optional.

---

## Final Answer to Your Question

**Q: "¿Debo actualizar las Stories? O crearlas de nuevo?"**

**A: NO necesitas hacer nada con las stories.**

✅ El Developer Agent tiene TODO lo necesario en:
- `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md` (plan de implementación)
- `docs/architecture-update-affected-stories.md` (cambios por story)
- `docs/STORY-UPDATE-NOTES.md` (este documento, referencia rápida)

Las stories originales sirven como **contexto histórico** de por qué se diseñó así originalmente, y ahora la nueva documentación explica por qué cambió.

---

**¿Te parece bien mantener las stories como están y usar los nuevos documentos como guía de implementación?** 🌸
