# Sprint Change Proposal: Architecture Simplification
## Hybrid Conversational + Transactional Architecture

**Date:** 2025-10-30
**Author:** Sarah (Product Owner Agent)
**Status:** PENDING USER APPROVAL
**Priority:** HIGH
**Effort:** 6 days (1 sprint)

---

## Executive Summary

**Proposed Change:** Refactor Atrévete Bot architecture from **rigid state machine** (25 nodes, 158 state fields) to **hybrid approach** with conversational flexibility for informational queries and transactional control for booking flows.

**Impact:**
- ✅ **Improved UX:** More natural, human-like responses for FAQs and service inquiries
- ✅ **Reduced Complexity:** 710 lines → ~200 lines in `conversation_flow.py`
- ✅ **Easier Maintenance:** 158 state fields → 50 fields
- ✅ **Future-Proof:** New conversational features don't require new nodes

**Scope:** Refactor Epic 2-3 conversational nodes, preserve Epic 4-5 transactional nodes, update documentation.

**Timeline:** 6 days (1 sprint)

---

## 1. Issue Analysis

### 1.1 Identified Problem

**Core Issue:**
> Over-controlled architecture with 13 conversational nodes + 158 state fields creates **rigidity** that prevents natural, human-like responses in non-transactional conversations.

**Evidence:**

**Code Smell #1: Routing Complexity**
```python
# conversation_flow.py:213-278 (65 lines to determine entry point)
def route_entry(state: ConversationState) -> str:
    if state.get("awaiting_name_confirmation"):
        return "confirm_name"
    if state.get("awaiting_category_choice"):
        return "handle_category_choice"
    if consultation_offered and not consultation_accepted:
        return "handle_consultation_response"
    # ... 7 more awaiting checks
```

**Code Smell #2: State Explosion**
```python
# schemas.py - 30+ fields just for tracking conversational state
awaiting_name_confirmation: bool
awaiting_category_choice: bool
consultation_offered: bool
consultation_accepted: bool
consultation_declined: bool
indecision_detected: bool
topic_changed_during_pack_response: bool
topic_changed_during_consultation_response: bool
# ... 22 more awaiting/tracking flags
```

**Code Smell #3: Topic Change Detection (Symptom of Problem)**
```python
# pack_suggestion_nodes.py - Had to add escape hatch
if topic_change_result.get("is_topic_change", False):
    return {
        "pack_declined": True,  # Force clear awaiting state
        "topic_changed_during_pack_response": True
    }
```

### 1.2 Root Cause

**Original Assumption (Incorrect):**
- "All conversations need explicit state machine control"
- "Every conversational decision requires a dedicated node"

**Reality:**
- Only **transactional flows** (booking, payment) need strict control
- **Informational conversations** (FAQs, inquiries) should be natural and flexible
- Claude can handle conversational logic without explicit state tracking

---

## 2. Epic Impact Summary

### 2.1 Current Epic (Epic 3)

**Status:** 6/6 stories implemented, but with obsolete architecture

**Impact:** ⚠️ **MODERATE - requires refactoring**

| Story | Current Implementation | Proposed Change |
|-------|------------------------|-----------------|
| 3.1 Service & Pack DB | Tools layer | ✅ No change |
| 3.2 Google Calendar API | Tools layer | ✅ No change |
| 3.3 Multi-Calendar Availability | Node: `check_availability` | ⚠️ Convert to tool |
| 3.4 Pack Suggestion | Nodes: `suggest_pack` + `handle_pack_response` | ⚠️ Convert to tool |
| 3.5 Consultation Offering | Nodes: `detect_indecision` + `offer_consultation` | ⚠️ Convert to tool |
| 3.6 Category Mixing Prevention | Node: `validate_booking_request` | ✅ Keep (transactional) |

### 2.2 Future Epics

**Epic 4-5 (Booking & Payment):** ✅ **MINIMAL IMPACT**
- Transactional nodes preserved (booking validation, payment, confirmation)
- Only entry point changes (from `extract_intent` → `conversational_agent`)

**Epic 6 (Escalation):** ⚠️ **MODERATE SIMPLIFICATION**
- Escalation detection consolidated into `escalate_to_human()` tool
- Claude decides when to escalate based on conversation context

**Epic 7 (Testing):** ⚠️ **TEST REFACTORING**
- Integration tests simplified (fewer state mocks)
- Focus on tool calls + transactional flows

---

## 3. Artifact Adjustment Needs

### 3.1 Code Artifacts

| File | Change Type | Lines Changed |
|------|-------------|---------------|
| `agent/graphs/conversation_flow.py` | Major refactor | 710 → ~200 lines |
| `agent/state/schemas.py` | Schema reduction | 158 → 50 fields |
| `agent/nodes/conversational_agent.py` | **New file** | +150 lines |
| `agent/nodes/greeting.py` | Delete | -50 lines |
| `agent/nodes/identification.py` | Partial delete | -100 lines |
| `agent/nodes/faq.py` | Delete | -150 lines |
| `agent/nodes/classification.py` | Partial delete | -200 lines |
| `agent/prompts/maite_system_prompt.md` | Expand | +200 lines guidance |
| `agent/tools/availability_tools.py` | **New file** | +80 lines |
| `agent/tools/pack_tools.py` | **New file** | +60 lines |
| `tests/integration/scenarios/` | Rewrite | ~500 lines refactor |

### 3.2 Documentation Artifacts

| Document | Section | Change Type | Effort |
|----------|---------|-------------|--------|
| **PRD** | 3.2 Key Interaction Paradigms | Add clarification | 15 min |
| **Architecture** | 2.5 Architectural Patterns | Add Hybrid Pattern | 2 hours |
| **Architecture** | 6.2 Components | Split into Conversational + Transactional | 1 hour |
| **Architecture** | 10.1 ConversationState Schema | Update schema | 1 hour |
| **Stories** | 2.2, 2.3, 2.6, 3.3, 3.4, 3.5 | Rewrite Acceptance Criteria | 5 hours |
| **BMAD** | New: 3.0 Architecture Simplification | Create new document | 1 hour |

**Total Documentation Effort:** ~10 hours

---

## 4. Recommended Path Forward

### 4.1 Proposed Solution: Hybrid Architecture

**Architecture Principle:**
> **"Strict control for transactions, conversational freedom for information"**

**Two-Tier Design:**

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Conversational Agent (Claude + Tools)             │
│  ────────────────────────────────────────────────────────  │
│  Handles: FAQs, greetings, service inquiries, indecision   │
│  Orchestration: Claude decides using available tools       │
│  State: Minimal (customer_id, customer_name, messages)     │
│                                                             │
│  Tools Available:                                           │
│  - get_customer_by_phone()                                  │
│  - create_customer()                                        │
│  - get_faqs()                                               │
│  - get_services()                                           │
│  - check_availability()        [NEW - from node]           │
│  - suggest_pack()              [NEW - from node]           │
│  - offer_consultation()        [NEW - from node]           │
│  - escalate_to_human(reason)                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
                 User confirms booking intent
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  TIER 2: Transactional Flow (LangGraph Nodes)              │
│  ────────────────────────────────────────────────────────  │
│  Handles: Booking validation, payment, confirmation        │
│  Orchestration: Explicit nodes with state validation       │
│  State: Comprehensive (50 fields)                           │
│                                                             │
│  Nodes Preserved:                                           │
│  - validate_booking_request                                 │
│  - create_provisional_booking                               │
│  - process_payment_confirmation                             │
│  - confirm_booking                                          │
│  - handle_modification                                      │
│  - handle_cancellation                                      │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 ConversationState Schema Reduction

**Before (158 fields):**
```python
# Conversational tracking (30 fields) - REMOVED
awaiting_name_confirmation: bool
awaiting_category_choice: bool
consultation_offered: bool
consultation_accepted: bool
indecision_detected: bool
confidence: float
topic_changed_during_pack_response: bool
# ... 23 more

# Customer context (20 fields) - KEPT
customer_id: UUID
customer_name: str
customer_phone: str
is_returning_customer: bool
# ... 16 more

# Booking context (30 fields) - KEPT
requested_services: list[UUID]
provisional_appointment_id: UUID
payment_link_url: str
# ... 27 more
```

**After (50 fields):**
```python
# Customer context (20 fields) ✅
customer_id: UUID
customer_name: str
customer_phone: str
is_returning_customer: bool
preferred_stylist_id: UUID | None
customer_history: list[dict]

# Booking context (30 fields) ✅
requested_services: list[UUID]
requested_date: str | None
requested_time: str | None
provisional_appointment_id: UUID | None
payment_link_url: str | None
booking_validation_passed: bool
mixed_category_detected: bool
is_same_day: bool
# ... 22 more booking-specific fields
```

---

## 5. PRD MVP Impact

### 5.1 MVP Scope Changes

**Original MVP (PRD Section 2.1):**
- ✅ Automate 85%+ customer conversations ← **IMPROVED** (more natural = higher automation)
- ✅ Reduce booking time 80% (15-20min → 3-4min) ← **UNCHANGED**
- ✅ Capture after-hours demand ← **UNCHANGED**
- ✅ 24/7 instant responses ← **IMPROVED** (faster, more natural)

**No scope reduction** - all functional requirements preserved, implementation simplified.

### 5.2 Goals Alignment

**PRD Goal (Section 1.1):**
> "Maintain or improve customer satisfaction with **instant 24/7 responses**"

**Change Impact:** ✅ **POSITIVE**
- More natural responses improve satisfaction
- Faster responses (fewer node transitions)
- Better handling of "off-script" queries

---

## 6. High-Level Action Plan

### Phase 1: Conversational Agent Creation (2 days)

**Tasks:**
1. Create `agent/nodes/conversational_agent.py`
   - Single node with Claude LLM
   - Access to all 8 tools
   - Transition detection for booking intent
2. Expand `agent/prompts/maite_system_prompt.md`
   - Conversational guidance (when to use tools)
   - Personality reinforcement
   - Escalation criteria
3. Convert nodes → tools:
   - `check_availability()` tool
   - `suggest_pack()` tool
   - `offer_consultation()` tool

**Deliverables:**
- ✅ `conversational_agent.py` functional
- ✅ 3 new tools implemented
- ✅ System prompt updated

---

### Phase 2: State Schema Simplification (1 day)

**Tasks:**
1. Update `agent/state/schemas.py`
   - Remove 30 conversational tracking fields
   - Keep 20 customer + 30 booking fields
2. Remove references to deleted fields in existing nodes
3. Update helper functions (`add_message`, `should_summarize`)

**Deliverables:**
- ✅ ConversationState reduced to 50 fields
- ✅ No broken references in codebase

---

### Phase 3: LangGraph Refactoring (1 day)

**Tasks:**
1. Update `agent/graphs/conversation_flow.py`
   - Set entry point: `conversational_agent`
   - Add conditional edge: `conversational_agent` → `validate_booking_request` (if booking intent)
   - Remove 13 conversational nodes
   - Preserve 6 transactional nodes (Epic 4-5)
2. Simplify routing logic (10 checks → 2 checks)
3. Delete obsolete node files:
   - `greeting.py`
   - Parts of `identification.py`
   - `faq.py`
   - Parts of `classification.py`

**Deliverables:**
- ✅ `conversation_flow.py` reduced to ~200 lines
- ✅ Graph compiles without errors
- ✅ Routing simplified

---

### Phase 4: Test Refactoring (1 day)

**Tasks:**
1. Update `tests/integration/scenarios/`
   - Rewrite conversational tests (2.2, 2.3, 2.6, 3.3, 3.4, 3.5)
   - Mock tool calls instead of node state
   - Keep transactional tests as-is
2. Update `tests/unit/`
   - Remove tests for deleted nodes
   - Add tests for new tools
3. Run full test suite
4. Fix failing tests

**Deliverables:**
- ✅ All tests passing
- ✅ Coverage maintained (>85%)

---

### Phase 5: Documentation Update (1 day)

**Tasks:**
1. Update **Architecture Document**:
   - Section 2.5: Add Hybrid Pattern
   - Section 6.2: Split into Conversational + Transactional components
   - Section 10.1: Update ConversationState schema
2. Update **PRD**:
   - Section 3.2: Add conversational flexibility clarification
3. Rewrite **Stories**:
   - 2.2, 2.3, 2.6 (Epic 2 conversational)
   - 3.3, 3.4, 3.5 (Epic 3 conversational)
4. Create **BMAD 3.0**:
   - Document architectural pivot
   - Rationale, implementation, deviations

**Deliverables:**
- ✅ Architecture doc updated
- ✅ PRD updated
- ✅ 6 stories rewritten
- ✅ BMAD 3.0 created

---

## 7. Agent Handoff Plan

### 7.1 Immediate Next Steps (PO/SM)

**Role:** Product Owner (Sarah) + Scrum Master

**Tasks:**
1. ✅ **Get user approval** for this Sprint Change Proposal
2. ✅ **Create BMAD 3.0** documenting the change
3. ✅ **Update Architecture Document** (Sections 2.5, 6.2, 10.1)
4. ✅ **Update PRD** (Section 3.2 clarification)
5. ✅ **Rewrite Stories** 2.2, 2.3, 2.6, 3.3, 3.4, 3.5

**Timeline:** 1 day (documentation updates)

---

### 7.2 Implementation (Developer Agent)

**Role:** Developer Agent

**Tasks:**
1. ✅ **Phase 1:** Create conversational_agent.py + 3 new tools (2 days)
2. ✅ **Phase 2:** Simplify ConversationState schema (1 day)
3. ✅ **Phase 3:** Refactor conversation_flow.py (1 day)
4. ✅ **Phase 4:** Refactor tests (1 day)

**Timeline:** 5 days (implementation)

---

### 7.3 Validation (QA + PM)

**Role:** QA Engineer + Product Manager

**Tasks:**
1. ✅ **Manual Testing:** Validate conversational flexibility
2. ✅ **Integration Tests:** Ensure transactional flows unchanged
3. ✅ **Regression Testing:** Epic 1-2 functionality preserved
4. ✅ **User Acceptance:** Test with real conversation samples

**Timeline:** 1 day (validation)

---

## 8. Success Criteria

### 8.1 Technical Validation

- ✅ All tests passing (unit + integration)
- ✅ `conversation_flow.py` reduced to <250 lines
- ✅ ConversationState reduced to ≤60 fields
- ✅ Graph compiles without errors
- ✅ Transactional nodes (Epic 4-5) unchanged

### 8.2 Functional Validation

- ✅ Bot handles FAQ queries naturally (no rigid states)
- ✅ Bot handles service inquiries conversationally
- ✅ Bot transitions to booking flow when intent confirmed
- ✅ Booking validation + payment flows unchanged
- ✅ Escalation logic preserved

### 8.3 Documentation Validation

- ✅ Architecture doc reflects hybrid architecture
- ✅ PRD clarifies conversational flexibility
- ✅ 6 stories rewritten with accurate ACs
- ✅ BMAD 3.0 documents the change

---

## 9. Risk Assessment

### 9.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Claude doesn't handle edge cases | Medium | Medium | Extensive prompt tuning, fallback to escalation |
| Tests fail after refactoring | Low | Low | Incremental refactoring, git branch for rollback |
| State schema breaks existing code | Low | High | Careful grep for field references, comprehensive testing |

### 9.2 Timeline Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Refactoring takes >6 days | Low | Low | Well-scoped tasks, clear deliverables per phase |
| User feedback requires changes | Medium | Medium | User approval before implementation starts |

---

## 10. Rollback Plan

### 10.1 Rollback Trigger Conditions

Rollback if:
- ✅ User disapproves proposal after review
- ⚠️ Tests fail after 2 days of debugging
- ⚠️ Claude cannot handle >50% of conversational scenarios

### 10.2 Rollback Procedure

1. ✅ Revert git branch to pre-refactoring state
2. ✅ Restore `conversation_flow.py` from backup
3. ✅ Restore `schemas.py` from backup
4. ✅ Delete new files (`conversational_agent.py`, new tools)
5. ✅ Re-run tests to confirm restoration

**Rollback Effort:** 1 hour

---

## 11. Final Recommendation

### ✅ **APPROVE THIS CHANGE**

**Rationale:**

1. **Addresses Root Cause:** Separates conversational flexibility from transactional control
2. **Preserves Valid Work:** 80% of Epic 1-3 work unchanged (tools, database, foundation)
3. **Manageable Scope:** 6 days refactoring vs 4-6 weeks restart
4. **Future-Proof:** Easier to add conversational features (no new nodes)
5. **Aligns with User Goal:** Natural, human responses for informational queries
6. **Low Risk:** Rollback plan in place, tests validate functionality

**Next Step:** 🟢 **Awaiting User Approval to Proceed**

---

**Approval Required:**

- [ ] User (Pepe) approves Sprint Change Proposal
- [ ] Confirm 6-day timeline acceptable
- [ ] Confirm documentation updates acceptable
- [ ] Confirm rollback plan acceptable

**Once approved, handoff to Developer Agent for implementation.**

---

**END OF SPRINT CHANGE PROPOSAL**
