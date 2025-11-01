# Architecture Update: Affected Stories
## Hybrid Architecture Simplification - Story Impact Analysis

**Date:** 2025-10-30
**Related Documents:**
- `docs/sprint-change-proposal-architecture-simplification.md`
- `docs/bmad/3.0-architecture-simplification-pivot.md`
- `docs/architecture.md` (Sections 2.5, 6.2, 10.1 updated)
- `docs/prd.md` (Section 3.2 updated)

---

## Purpose

This document identifies stories affected by the architectural simplification from rigid state machine (25 nodes, 158 state fields) to hybrid conversational + transactional architecture (12 nodes, 50 state fields).

**Key Change:** Conversational scenarios (Epic 2-3) no longer implemented as dedicated LangGraph nodes. Instead, handled by single `conversational_agent` node powered by Claude + tools.

---

## Summary of Architectural Change

### Before (Old Architecture)
- **Epic 2-3 Conversational Flows:** 13 dedicated nodes
  - `greet_customer`, `identify_customer`, `greet_new_customer`, `confirm_name`
  - `greet_returning_customer`, `extract_intent`
  - `detect_faq_intent`, `answer_faq`, `generate_faq_response`
  - `detect_indecision`, `offer_consultation`, `handle_consultation_response`
  - `handle_service_inquiry`
- **State Management:** 158 fields (30 conversational tracking flags)
- **Problem:** Rigid, bot gets "trapped" in awaiting states, needs topic change detection escapes

### After (New Architecture)
- **Tier 1 (Conversational Agent):** Single `conversational_agent` node
  - Claude reasons about conversation flow naturally
  - Access to 8 tools (customer, FAQ, services, availability, pack, consultation, escalate)
  - Minimal state (customer context only, ~20 fields)
- **Tier 2 (Transactional Flow):** 6 explicit nodes preserved
  - `validate_booking_request`, `create_provisional_booking`
  - `process_payment_confirmation`, `confirm_booking`
  - `handle_modification`, `handle_cancellation`
  - Comprehensive state (booking context, ~30 fields)
- **State Management:** 50 fields total (0 conversational tracking flags)
- **Benefit:** Natural, flexible, human-like responses; no "trapped" states

---

## Affected Stories by Epic

### Epic 2: Customer Identification & Conversational Foundation

#### Story 2.2: New Customer Greeting & Name Confirmation
**File:** `docs/stories/2.2.new-customer-greeting-name-confirmation.md`

**Original Implementation:**
- 2 dedicated nodes: `greet_new_customer`, `confirm_name`
- State flags: `awaiting_name_confirmation`, `customer_identified`, `clarification_attempts`
- Complex routing logic for name confirmation retry

**New Implementation:**
- Handled by `conversational_agent` with tool `create_customer(phone, name)`
- Claude extracts name from message conversationally
- No awaiting flags needed (Claude manages conversation context)

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System sets `awaiting_name_confirmation=True` after greeting"
- ❌ **Remove AC:** "System routes to `confirm_name` node when name response detected"
- ✅ **Keep AC:** "System greets new customers warmly with Maite personality"
- ✅ **Keep AC:** "System asks for customer name naturally"
- ✅ **Keep AC:** "System creates Customer record in database"
- ✅ **Add AC:** "System uses `create_customer()` tool to persist customer"

**Developer Action Required:**
- Delete `confirm_name()` function from `agent/nodes/identification.py`
- Move name extraction logic to `conversational_agent` (Claude prompting)
- Update tests to mock `create_customer` tool call instead of node state

---

#### Story 2.3: Returning Customer Recognition & Intent Extraction
**File:** `docs/stories/2.3.returning-customer-recognition.md`

**Original Implementation:**
- 2 dedicated nodes: `greet_returning_customer`, `extract_intent`
- State flags: `current_intent` with explicit classification
- Intent classification via dedicated Claude call

**New Implementation:**
- Handled by `conversational_agent` with tool `get_customer_by_phone(phone)`
- Claude greets returning customers naturally (no separate node)
- Intent detection implicit in Claude's conversation reasoning

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System routes to `greet_returning_customer` node when customer exists"
- ❌ **Remove AC:** "System invokes `extract_intent` node after greeting"
- ❌ **Remove AC:** "System classifies intent into booking|modification|cancellation|faq|greeting_only"
- ✅ **Keep AC:** "System recognizes returning customers by phone number"
- ✅ **Keep AC:** "System greets returning customers by first name"
- ✅ **Add AC:** "System uses `get_customer_by_phone()` tool to identify customer"
- ✅ **Add AC:** "Claude reasons about booking intent to trigger transactional flow"

**Developer Action Required:**
- Delete `greet_returning_customer()` from `agent/nodes/identification.py`
- Delete `extract_intent()` from `agent/nodes/classification.py`
- Update system prompt to guide Claude on greeting returning customers
- Update tests to verify tool call instead of node transitions

---

#### Story 2.6: FAQ Knowledge Base Responses
**File:** `docs/stories/2.6.faq-knowledge-base-responses.md`

**Original Implementation:**
- 3 dedicated nodes: `detect_faq_intent`, `answer_faq`, `generate_faq_response`
- State flags: `faq_detected`, `detected_faq_ids`, `query_complexity`
- Hybrid static/AI FAQ answering with complex routing

**New Implementation:**
- Handled by `conversational_agent` with tool `get_faqs(keywords=None)`
- Claude decides when to lookup FAQs naturally
- Claude generates answer using FAQ data (no separate generation node)

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System detects FAQ queries via `detect_faq_intent` node"
- ❌ **Remove AC:** "System sets `faq_detected=True` and `detected_faq_ids=[...]`"
- ❌ **Remove AC:** "System routes to `answer_faq` for simple queries"
- ❌ **Remove AC:** "System routes to `generate_faq_response` for compound queries"
- ✅ **Keep AC:** "System answers questions about hours, location, parking, policies"
- ✅ **Keep AC:** "System provides accurate FAQ answers from database"
- ✅ **Add AC:** "System uses `get_faqs()` tool when customer asks FAQ-type questions"
- ✅ **Add AC:** "Claude incorporates FAQ data into natural conversational response"

**Developer Action Required:**
- Delete `detect_faq_intent()`, `answer_faq()`, `generate_faq_response()` from `agent/nodes/faq.py`
- Convert `get_faqs()` to @tool decorator for Claude tool use
- Update system prompt with guidance on when to use FAQ tool
- Update tests to verify FAQ tool call + response quality

---

### Epic 3: Service Discovery & Calendar Availability

#### Story 3.3: Multi-Calendar Availability Checking
**File:** `docs/stories/3.3.multi-calendar-availability-checking.md`

**Original Implementation:**
- Dedicated node: `check_availability`
- Complex routing after availability check (prioritization, holiday detection)
- State updates: `available_slots`, `prioritized_slots`, `holiday_detected`

**New Implementation:**
- Tool: `check_availability_tool(service_category, date, time_range)`
- Called by `conversational_agent` when customer asks about availability
- OR called by transactional flow when booking intent confirmed
- Returns availability data, Claude formats response naturally

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System invokes `check_availability` node when booking flow starts"
- ❌ **Remove AC:** "System routes to END after presenting availability"
- ✅ **Keep AC:** "System queries Google Calendar API for multiple stylists"
- ✅ **Keep AC:** "System detects holidays via 'Festivo'/'Cerrado' calendar events"
- ✅ **Keep AC:** "System prioritizes slots (preferred stylist, closest to requested time)"
- ✅ **Keep AC:** "System presents 2-3 top slots to customer"
- ✅ **Add AC:** "`check_availability_tool` returns availability data structure"
- ✅ **Add AC:** "Conversational agent calls tool for informational queries"
- ✅ **Add AC:** "Transactional flow calls tool when booking intent confirmed"

**Developer Action Required:**
- Convert `check_availability()` node to `check_availability_tool()` @tool
- Move logic from node to tool (preserve calendar query + prioritization)
- Update `conversational_agent` system prompt to guide tool usage
- Keep transactional flow calling tool explicitly (not via Claude)

---

#### Story 3.4: Pack Suggestion Logic & Acceptance Flow
**File:** `docs/stories/3.4.pack-suggestion-logic-acceptance-flow.md`

**Original Implementation:**
- 2 dedicated nodes: `suggest_pack`, `handle_pack_response`
- State flags: `suggested_pack`, `pack_id`, `pack_declined`, `awaiting_pack_response`
- Topic change detection escape hatch (symptom of rigidity)

**New Implementation:**
- Tool: `suggest_pack_tool(service_ids)`
- Called by `conversational_agent` when customer mentions multiple services
- Claude presents pack naturally, handles accept/decline conversationally
- No awaiting state needed (Claude tracks conversation context)

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System invokes `suggest_pack` node after service extraction"
- ❌ **Remove AC:** "System sets `awaiting_pack_response=True` and waits for user"
- ❌ **Remove AC:** "System invokes `handle_pack_response` on next message"
- ❌ **Remove AC:** "System detects topic changes during pack response"
- ✅ **Keep AC:** "System queries Pack table for services matching requested services"
- ✅ **Keep AC:** "System calculates savings (individual_price - pack_price)"
- ✅ **Keep AC:** "System presents pack offer with savings highlighted"
- ✅ **Keep AC:** "System accepts 'sí', 'perfecto', 'vale' as pack acceptance"
- ✅ **Keep AC:** "System declines 'no', 'solo individual' as pack decline"
- ✅ **Add AC:** "`suggest_pack_tool` returns pack data (name, price, savings)"
- ✅ **Add AC:** "Claude calls tool when customer requests multiple services"
- ✅ **Add AC:** "Claude handles pack acceptance/decline conversationally without state flags"

**Developer Action Required:**
- Convert `suggest_pack()` node to `suggest_pack_tool()` @tool
- Delete `handle_pack_response()` node (Claude handles naturally)
- Remove `topic_changed_during_pack_response` escape hatch logic
- Update tests to mock tool call + verify conversational handling

---

#### Story 3.5: Indecision Detection & Consultation Offering
**File:** `docs/stories/3.5.indecision-detection-consultation-offering.md`

**Original Implementation:**
- 3 dedicated nodes: `detect_indecision`, `offer_consultation`, `handle_consultation_response`
- State flags: `indecision_detected`, `confidence`, `indecision_type`, `consultation_offered`, `consultation_accepted`, `consultation_declined`
- Structured output from Claude for classification
- Topic change detection escape hatch

**New Implementation:**
- Tool: `offer_consultation_tool(reason)`
- Claude reasons about indecision naturally (no explicit classification)
- Claude calls tool when customer shows indecision patterns
- Claude handles consultation accept/decline conversationally

**Acceptance Criteria Changes:**
- ❌ **Remove AC:** "System invokes `detect_indecision` node after service extraction"
- ❌ **Remove AC:** "System classifies indecision with confidence > 0.7"
- ❌ **Remove AC:** "System sets `indecision_detected=True`, `indecision_type=...`"
- ❌ **Remove AC:** "System invokes `offer_consultation` node when indecision detected"
- ❌ **Remove AC:** "System sets `consultation_offered=True` and waits for response"
- ❌ **Remove AC:** "System invokes `handle_consultation_response` on next message"
- ❌ **Remove AC:** "System detects topic changes during consultation response"
- ✅ **Keep AC:** "System detects indecision patterns: '¿cuál recomiendas?', 'no sé si...'"
- ✅ **Keep AC:** "System queries CONSULTA GRATUITA service (15min, free)"
- ✅ **Keep AC:** "System offers consultation with personalized message"
- ✅ **Keep AC:** "System accepts 'sí, prefiero consulta' as acceptance"
- ✅ **Keep AC:** "System declines 'no gracias' and returns to service selection"
- ✅ **Add AC:** "Claude reasons about indecision based on conversation context"
- ✅ **Add AC:** "Claude calls `offer_consultation_tool(reason)` when appropriate"
- ✅ **Add AC:** "Claude handles consultation acceptance/decline conversationally"

**Developer Action Required:**
- Delete `detect_indecision()`, `offer_consultation()`, `handle_consultation_response()` from `agent/nodes/classification.py`
- Create `offer_consultation_tool()` that returns consultation service data
- Update system prompt with indecision pattern examples
- Remove topic change detection escape hatch
- Update tests to verify Claude reasoning + tool call

---

## Story 3.6: NOT AFFECTED (Transactional Node)

**Story 3.6: Service Category Mixing Prevention**
**File:** `docs/stories/3.6.service-category-mixing-prevention.md`

**Status:** ✅ **NO CHANGES REQUIRED**

**Reason:** This story implements `validate_booking_request` node which is part of Tier 2 (Transactional Flow) and is **preserved** in the new architecture.

**Implementation Unchanged:**
- Node: `validate_booking_request`
- State flags: `booking_validation_passed`, `mixed_category_detected`, `services_by_category`
- Explicit validation logic (HAIRDRESSING vs AESTHETICS separation)

This node is called when transactional flow starts (after `booking_intent_confirmed=True` set by conversational agent).

---

## Summary Table

| Story | Epic | Original Nodes | New Implementation | Developer Effort |
|-------|------|----------------|-------------------|------------------|
| 2.2 | 2 | `greet_new_customer`, `confirm_name` | `conversational_agent` + `create_customer` tool | 0.5 days |
| 2.3 | 2 | `greet_returning_customer`, `extract_intent` | `conversational_agent` + `get_customer_by_phone` tool | 0.5 days |
| 2.6 | 2 | `detect_faq_intent`, `answer_faq`, `generate_faq_response` | `conversational_agent` + `get_faqs` tool | 0.5 days |
| 3.3 | 3 | `check_availability` | `check_availability_tool` (used by both tiers) | 0.5 days |
| 3.4 | 3 | `suggest_pack`, `handle_pack_response` | `suggest_pack_tool` | 0.5 days |
| 3.5 | 3 | `detect_indecision`, `offer_consultation`, `handle_consultation_response` | `offer_consultation_tool` | 0.5 days |
| **3.6** | **3** | **`validate_booking_request`** | **NO CHANGE (Tier 2 node preserved)** | **0 days** |

**Total Developer Effort:** 3 days (node-to-tool conversion + test updates)

---

## Implementation Order for Developer Agent

**Recommended Sequence:**

1. **Day 1-2: Create Conversational Agent Core**
   - `agent/nodes/conversational_agent.py` (new file, ~150 lines)
   - Expand `agent/prompts/maite_system_prompt.md` (+200 lines guidance)
   - Update `agent/state/schemas.py` (reduce 158 → 50 fields)

2. **Day 3: Convert Nodes to Tools**
   - `agent/tools/availability_tools.py` - `check_availability_tool()` (from node)
   - `agent/tools/pack_tools.py` - `suggest_pack_tool()` (from node)
   - `agent/tools/consultation_tools.py` - `offer_consultation_tool()` (from node)
   - Convert existing tools: `get_faqs()`, `create_customer()`, `get_customer_by_phone()` to @tool decorators

3. **Day 4: Refactor LangGraph**
   - Update `agent/graphs/conversation_flow.py` (710 → 200 lines)
   - Remove 13 conversational nodes
   - Keep 6 transactional nodes
   - Simplify routing (10 checks → 2 checks)

4. **Day 5: Update Tests**
   - Rewrite integration tests (Stories 2.2, 2.3, 2.6, 3.3, 3.4, 3.5)
   - Mock tool calls instead of node state
   - Keep transactional flow tests unchanged

5. **Day 6: Validation & Documentation**
   - Run full test suite
   - Manual validation of conversational flows
   - Update BMAD documents

---

## Testing Guidance

### Unit Tests (Per Story)

**Story 2.2 (New Customer Greeting):**
```python
@pytest.mark.asyncio
async def test_new_customer_greeting(mocker):
    mock_create_customer = mocker.patch("agent.tools.customer_tools.create_customer")
    mock_create_customer.return_value = Customer(id=uuid4(), name="María", phone="+34612345678")

    state = {
        "conversation_id": "test-123",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Hola, soy María")]
    }

    result = await conversational_agent(state)

    assert mock_create_customer.called
    assert "María" in result["messages"][-1].content
    assert "🌸" in result["messages"][-1].content  # Maite signature
```

**Story 3.4 (Pack Suggestion):**
```python
@pytest.mark.asyncio
async def test_pack_suggestion(mocker):
    mock_suggest_pack = mocker.patch("agent.tools.pack_tools.suggest_pack_tool")
    mock_suggest_pack.return_value = {
        "pack_found": True,
        "pack_name": "Pack Mechas + Corte",
        "pack_price": 80.0,
        "individual_price": 90.0,
        "savings": 10.0
    }

    state = {
        "conversation_id": "test-123",
        "customer_phone": "+34612345678",
        "messages": [HumanMessage(content="Quiero mechas y corte")]
    }

    result = await conversational_agent(state)

    assert mock_suggest_pack.called
    response = result["messages"][-1].content
    assert "80" in response  # Pack price
    assert "ahorro" in response.lower() or "10" in response  # Savings
```

---

## Migration Checklist for Developer Agent

- [ ] Read BMAD 3.0 completely
- [ ] Read Sprint Change Proposal completely
- [ ] Read this Architecture Update document
- [ ] Create `agent/nodes/conversational_agent.py`
- [ ] Expand `agent/prompts/maite_system_prompt.md`
- [ ] Update `agent/state/schemas.py` (reduce fields)
- [ ] Create `agent/tools/availability_tools.py`
- [ ] Create `agent/tools/pack_tools.py`
- [ ] Create `agent/tools/consultation_tools.py`
- [ ] Convert existing tools to @tool decorator
- [ ] Update `agent/graphs/conversation_flow.py`
- [ ] Delete obsolete nodes (greet, faq, classification parts)
- [ ] Rewrite tests for Stories 2.2, 2.3, 2.6, 3.3, 3.4, 3.5
- [ ] Run pytest (target: all tests passing)
- [ ] Manual validation (test conversational flows)
- [ ] Update story markdown files with new ACs (optional, documented here)

---

**END OF ARCHITECTURE UPDATE DOCUMENT**
