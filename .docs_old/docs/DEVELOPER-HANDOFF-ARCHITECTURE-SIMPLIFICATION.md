# Developer Handoff: Architecture Simplification Implementation
## Hybrid Conversational + Transactional Architecture Refactoring

**Date:** 2025-10-30
**Product Owner:** Sarah (PO Agent)
**Developer:** [Developer Agent - Assign on execution]
**Estimated Effort:** 6 days (5 implementation + 1 validation)
**Status:** READY FOR IMPLEMENTATION

---

## Executive Summary

**Objective:** Refactor Atrévete Bot from rigid 25-node state machine (158 state fields) to hybrid 12-node architecture (50 state fields) that balances conversational flexibility with transactional safety.

**User Problem Addressed:**
> "El bot se pierde en ciertas consultas porque de tanto control no es capaz de entender la consulta o de procesarla correctamente y responder de manera personalizada, humana" - Pepe (User/Owner)

**Solution:** Two-tier architecture:
- **Tier 1:** Single `conversational_agent` node (Claude + 8 tools) for flexible informational conversations
- **Tier 2:** 6 explicit transactional nodes (booking, payment, modification) for atomic operations

---

## Required Reading (MUST READ BEFORE CODING)

**Priority 1 - Read These FIRST:**

1. ✅ **Sprint Change Proposal** (30 min read)
   - File: `docs/sprint-change-proposal-architecture-simplification.md`
   - Contains: Full rationale, impact analysis, implementation plan, success criteria

2. ✅ **BMAD 3.0** (20 min read)
   - File: `docs/bmad/3.0-architecture-simplification-pivot.md`
   - Contains: Behavior-Measure-Act-Document analysis, code examples, deviations

3. ✅ **Architecture Update for Stories** (15 min read)
   - File: `docs/architecture-update-affected-stories.md`
   - Contains: Story-by-story breakdown, AC changes, test guidance

**Priority 2 - Reference Documents:**

4. **Updated Architecture Doc**
   - File: `docs/architecture.md`
   - Sections updated: 2.5 (Hybrid Pattern), 6.2 (Components split), 10.1 (State schema)

5. **Updated PRD**
   - File: `docs/prd.md`
   - Section updated: 3.2 (Conversational flexibility clarification)

---

## Implementation Plan (6 Days)

### **Phase 1: Conversational Agent Creation (2 days)**

#### Day 1: Core Conversational Agent

**File to Create:** `agent/nodes/conversational_agent.py`

**Responsibilities:**
- Single node handling all informational conversations
- Claude LLM with tool access (8 tools)
- Booking intent detection for Tier 2 transition

**Key Functions:**
```python
async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Tier 1 conversational agent powered by Claude + tools.

    Handles: FAQs, greetings, service inquiries, indecision, consultation
    Transition: Sets booking_intent_confirmed=True when customer ready to book
    """
    # Load system prompt with conversational guidance
    system_prompt = get_maite_system_prompt()

    # Bind tools to Claude
    tools = [
        get_customer_by_phone,
        create_customer,
        get_faqs,
        get_services,
        check_availability_tool,
        suggest_pack_tool,
        offer_consultation_tool,
        escalate_to_human,
    ]

    llm = ChatAnthropic(model="claude-sonnet-4-20250514")
    llm_with_tools = llm.bind_tools(tools)

    # Format messages
    messages = format_llm_messages_with_summary(state, system_prompt)

    # Invoke LLM
    response = await llm_with_tools.ainvoke(messages)

    # Detect booking intent
    booking_intent_confirmed = detect_booking_intent(response)

    return {
        "messages": state["messages"] + [response],
        "booking_intent_confirmed": booking_intent_confirmed,
        "updated_at": datetime.now(ZoneInfo("Europe/Madrid"))
    }


def detect_booking_intent(response: AIMessage) -> bool:
    """
    Detect if customer has expressed clear booking intent.

    Signals:
    - "Quiero reservar [service]"
    - "Dame cita para [date]"
    - Customer confirms specific time slot

    NOT signals:
    - "¿Cuánto cuesta?" (inquiry only)
    - "¿Tenéis libre?" (checking, not confirming)
    """
    content = response.content.lower()

    booking_keywords = [
        "quiero reservar",
        "dame cita",
        "reserva ",
        "confirmo la cita",
        "perfecto, reserva"
    ]

    return any(keyword in content for keyword in booking_keywords)
```

**Deliverables:**
- ✅ `agent/nodes/conversational_agent.py` created (~150 lines)
- ✅ `detect_booking_intent()` helper function implemented
- ✅ Unit tests: `tests/unit/test_conversational_agent.py`

---

#### Day 2: System Prompt Expansion + Tool Conversion

**File to Update:** `agent/prompts/maite_system_prompt.md`

**Add Section:** "Tool Usage Guidelines" (~200 lines)

**Content to Add:**
- When to use each of 8 tools
- Booking intent detection criteria
- Personality guidance for tool responses
- Examples of natural tool integration

**See:** `docs/bmad/3.0-architecture-simplification-pivot.md` Section "1.3 Expand System Prompt" for full content

**Files to Convert (Node → Tool):**

1. **`agent/tools/availability_tools.py`** (NEW)
```python
@tool
async def check_availability_tool(
    service_category: str,
    date: str,
    time_range: str | None = None,
    stylist_id: str | None = None
) -> dict[str, Any]:
    """
    Check availability across multiple stylist calendars.

    Args:
        service_category: "Hairdressing" or "Aesthetics"
        date: Date in YYYY-MM-DD format
        time_range: Optional "morning", "afternoon", or "14:00-18:00"
        stylist_id: Optional specific stylist UUID

    Returns:
        {
            "available_slots": [...],
            "is_same_day": bool,
            "holiday_detected": bool
        }
    """
    # Move logic from agent/nodes/availability_nodes.py:check_availability
    # Reuse CalendarTools underneath
```

2. **`agent/tools/pack_tools.py`** (NEW)
```python
@tool
async def suggest_pack_tool(service_ids: list[str]) -> dict[str, Any]:
    """
    Find money-saving packs for requested services.

    Returns:
        {
            "pack_found": bool,
            "pack_name": str,
            "pack_price": float,
            "savings": float,
            "pack_id": str
        }
    """
    # Move logic from agent/nodes/pack_suggestion_nodes.py:suggest_pack
```

3. **`agent/tools/consultation_tools.py`** (NEW)
```python
@tool
async def offer_consultation_tool(reason: str) -> dict[str, Any]:
    """
    Offer free 15-minute consultation when customer indecisive.

    Returns:
        {
            "consultation_service_id": str,
            "duration_minutes": int,
            "price_euros": float
        }
    """
    # Query CONSULTA GRATUITA service from database
```

4. **Convert existing tools to @tool decorator:**
   - `agent/tools/customer_tools.py`: Add @tool to `get_customer_by_phone`, `create_customer`
   - `agent/tools/faq_tools.py`: Add @tool to `get_faqs`
   - `agent/tools/booking_tools.py`: Add @tool to `get_services`

**Deliverables:**
- ✅ System prompt expanded (+200 lines)
- ✅ 3 new tool files created
- ✅ 4 existing tools decorated with @tool
- ✅ Unit tests for each tool

---

### **Phase 2: State Schema Simplification (1 day)**

#### Day 3: ConversationState Reduction

**File to Update:** `agent/state/schemas.py`

**Changes:**
1. Remove 30 conversational tracking fields
2. Add 1 new field: `booking_intent_confirmed: bool`
3. Keep 50 total fields (10 core + 10 customer + 30 booking)

**Fields to DELETE:**
```python
# DELETE THESE (Claude handles conversationally)
awaiting_name_confirmation: bool
awaiting_category_choice: bool
consultation_offered: bool
consultation_accepted: bool
consultation_declined: bool
indecision_detected: bool
confidence: float
indecision_type: str
detected_services: list[str]
faq_detected: bool
detected_faq_ids: list[str]
query_complexity: str
topic_changed_during_pack_response: bool
topic_changed_during_consultation_response: bool
clarification_attempts: int
# ... 15 more conversational flags
```

**Field to ADD:**
```python
booking_intent_confirmed: bool  # Transition flag: Tier 1 → Tier 2
```

**Validation:**
```bash
# Grep for deleted field usage
for field in awaiting_name_confirmation awaiting_category_choice consultation_offered; do
  grep -r "$field" agent/ --exclude-dir=__pycache__
done

# Should return 0 matches after cleanup
```

**Deliverables:**
- ✅ `schemas.py` updated (158 → 50 fields)
- ✅ No references to deleted fields in codebase
- ✅ Schema validation tests passing

---

### **Phase 3: LangGraph Refactoring (1 day)**

#### Day 4: Simplify conversation_flow.py

**File to Update:** `agent/graphs/conversation_flow.py`

**Changes:**

**1. Remove 13 conversational nodes:**
```python
# DELETE THESE LINES
graph.add_node("greet_customer", greet_customer)
graph.add_node("identify_customer", identify_customer)
graph.add_node("greet_new_customer", greet_new_customer)
graph.add_node("confirm_name", confirm_name)
graph.add_node("greet_returning_customer", greet_returning_customer)
graph.add_node("extract_intent", extract_intent)
graph.add_node("detect_faq_intent", detect_faq_intent)
graph.add_node("answer_faq", answer_faq)
graph.add_node("generate_faq_response", generate_personalized_faq_response)
graph.add_node("detect_indecision", detect_indecision)
graph.add_node("offer_consultation", offer_consultation)
graph.add_node("handle_consultation_response", handle_consultation_response)
graph.add_node("handle_service_inquiry", handle_service_inquiry)
```

**2. Add 1 conversational node:**
```python
# ADD THIS
graph.add_node("conversational_agent", conversational_agent)
```

**3. Keep 6 transactional nodes:**
```python
# KEEP THESE (no changes)
graph.add_node("validate_booking_request", validate_booking_request)
graph.add_node("create_provisional_booking", create_provisional_booking)
graph.add_node("process_payment_confirmation", process_payment_confirmation)
graph.add_node("confirm_booking", confirm_booking)
graph.add_node("handle_modification", handle_modification)
graph.add_node("handle_cancellation", handle_cancellation)
```

**4. Simplify entry routing:**
```python
# REPLACE route_entry() with simplified version
def route_entry(state: ConversationState) -> str:
    """
    Route entry based on conversation state.

    - If in transactional flow (has provisional_appointment_id) → resume transaction
    - Otherwise → start with conversational agent
    """
    if state.get("provisional_appointment_id"):
        return "process_payment_confirmation"

    return "conversational_agent"

graph.set_conditional_entry_point(
    route_entry,
    {
        "conversational_agent": "conversational_agent",
        "process_payment_confirmation": "process_payment_confirmation"
    }
)
```

**5. Add transition routing:**
```python
# REPLACE complex routing with simple transition check
def route_from_conversational(state: ConversationState) -> str:
    """Route from conversational to transactional when booking intent confirmed."""
    if state.get("booking_intent_confirmed"):
        return "validate_booking_request"
    else:
        return END

graph.add_conditional_edges(
    "conversational_agent",
    route_from_conversational,
    {
        "validate_booking_request": "validate_booking_request",
        END: END
    }
)
```

**6. Preserve transactional routing (NO CHANGES):**
```python
# KEEP ALL TRANSACTIONAL EDGES (Epic 4-5)
graph.add_edge("validate_booking_request", "create_provisional_booking")
graph.add_edge("create_provisional_booking", "process_payment_confirmation")
# ... etc
```

**Files to DELETE:**
- `agent/nodes/greeting.py` (entire file)
- `agent/nodes/faq.py` (entire file)
- Parts of `agent/nodes/identification.py` (keep `identify_customer` if needed for transactional)
- Parts of `agent/nodes/classification.py` (delete `extract_intent`, `detect_indecision`)

**Deliverables:**
- ✅ `conversation_flow.py` reduced (710 → ~200 lines)
- ✅ 12 total nodes (1 conversational + 6 transactional + 5 placeholder/other)
- ✅ Graph compiles without errors
- ✅ Routing simplified (10 checks → 2 checks)

---

### **Phase 4: Test Refactoring (1 day)**

#### Day 5: Update Integration Tests

**Stories to Update Tests:**
- Story 2.2: New Customer Greeting
- Story 2.3: Returning Customer Recognition
- Story 2.6: FAQ Answering
- Story 3.3: Availability Checking
- Story 3.4: Pack Suggestion
- Story 3.5: Consultation Offering

**Pattern for New Tests:**
```python
# OLD TEST (node-based)
async def test_new_customer_greeting():
    state = {"customer_phone": "+34612345678", "awaiting_name_confirmation": False}
    result1 = await greet_customer(state)
    result2 = await identify_customer(result1)
    assert result2["awaiting_name_confirmation"] == True

# NEW TEST (tool-based)
async def test_new_customer_greeting(mocker):
    mock_create_customer = mocker.patch("agent.tools.customer_tools.create_customer")
    mock_create_customer.return_value = Customer(...)

    state = {
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Hola, soy María")]
    }

    result = await conversational_agent(state)

    assert mock_create_customer.called
    assert "María" in result["messages"][-1].content
```

**See:** `docs/architecture-update-affected-stories.md` Section "Testing Guidance" for full examples

**Deliverables:**
- ✅ 6 integration test files rewritten
- ✅ All unit tests passing
- ✅ Coverage maintained (≥85%)

---

### **Phase 5: Validation & Documentation (1 day)**

#### Day 6: Testing & Final Updates

**Tasks:**
1. Run full test suite: `pytest tests/ -v`
2. Manual validation:
   - Test FAQ query: "¿A qué hora abrís?"
   - Test service inquiry: "¿Cuánto cuestan las mechas?"
   - Test booking flow: "Quiero reservar mechas para mañana"
   - Test indecision: "No sé si elegir mechas o balayage"
3. Update BMAD 3.0 with any deviations
4. Create implementation summary

**Deliverables:**
- ✅ All tests passing (target: 100% pass rate)
- ✅ Manual validation complete (4 scenarios)
- ✅ BMAD 3.0 updated with actual implementation notes
- ✅ Implementation complete document

---

## Success Criteria (MUST ACHIEVE)

### Technical Validation

- [ ] ✅ All pytest tests passing (unit + integration)
- [ ] ✅ `conversation_flow.py` reduced to <250 lines
- [ ] ✅ ConversationState reduced to ≤60 fields
- [ ] ✅ Graph compiles without errors
- [ ] ✅ Transactional nodes (Epic 4-5) unchanged

### Functional Validation

- [ ] ✅ Bot handles FAQ queries naturally (no rigid states)
- [ ] ✅ Bot handles service inquiries conversationally
- [ ] ✅ Bot transitions to booking flow when intent confirmed
- [ ] ✅ Booking validation + payment flows unchanged
- [ ] ✅ Escalation logic preserved

### Documentation Validation

- [ ] ✅ Architecture doc reflects hybrid architecture
- [ ] ✅ PRD clarifies conversational flexibility
- [ ] ✅ BMAD 3.0 documents the change
- [ ] ✅ This handoff document marked complete

---

## Rollback Plan (If Needed)

**Trigger Conditions:**
- Tests fail after 2 days of debugging
- Claude cannot handle >50% of conversational scenarios
- User requests rollback

**Rollback Procedure (1 hour):**
```bash
# 1. Revert git branch
git checkout master
git branch -D architecture-simplification
git pull origin master

# 2. Verify tests
pytest tests/

# 3. Notify PO (Sarah)
echo "Architecture simplification rolled back" | mail -s "Rollback Complete" po@atrevete.com
```

---

## Communication Protocol

**Daily Standups (Async):**
- Post progress update in project channel
- Format: "Day X/6: [Phase Name] - [Status] - [Blockers]"
- Example: "Day 3/6: State Schema Simplification - Complete - No blockers"

**Blocker Escalation:**
- If blocked >4 hours → escalate to PO (Sarah)
- If blocked >8 hours → pause and request guidance

**Completion Notification:**
- When Phase 5 complete → notify PO + User (Pepe)
- Include: test results, manual validation summary, deployment readiness

---

## Questions & Clarifications

**Q: What if Claude doesn't detect booking intent correctly?**
A: Refine `detect_booking_intent()` function with more keywords. Fallback: add explicit check in system prompt.

**Q: What if tests take >1 day to refactor?**
A: Prioritize critical paths (Stories 2.2, 3.4). Defer edge case tests to Day 6.

**Q: Should I refactor Story 3.6 (Category Mixing)?**
A: NO - Story 3.6 is Tier 2 (transactional), preserve as-is.

**Q: What if I find bugs in transactional nodes?**
A: Fix them, but do NOT refactor structure. Report to PO.

---

## Final Checklist for Developer

**Before Starting:**
- [ ] Read Sprint Change Proposal (30 min)
- [ ] Read BMAD 3.0 (20 min)
- [ ] Read Architecture Update for Stories (15 min)
- [ ] Create git branch: `architecture-simplification`
- [ ] Notify PO: "Starting implementation"

**Daily (End of Day):**
- [ ] Commit progress with descriptive message
- [ ] Push to remote branch
- [ ] Post standup update
- [ ] Review next day's tasks

**After Completion:**
- [ ] Run full test suite
- [ ] Manual validation (4 scenarios)
- [ ] Update BMAD 3.0 with deviations
- [ ] Create PR: `architecture-simplification` → `master`
- [ ] Notify PO + User: "Implementation complete, ready for review"

---

## Contact Information

**Product Owner (Sarah):** [PO Agent - available via chat]
**User/Owner (Pepe):** [User - available for questions]
**Architecture Reference:** `docs/architecture.md`
**Original Requirements:** `docs/prd.md`

---

**Good luck with the implementation! This is a significant architectural improvement that will make the bot more natural and maintainable. 🌸**

---

**END OF DEVELOPER HANDOFF DOCUMENT**
