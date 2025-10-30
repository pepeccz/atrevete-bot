# Phase 5: Test Refactoring Strategy - Hybrid Architecture

**Status**: 🟡 Pending Implementation
**Created**: 2025-01-30
**Phases Completed**: 1-4 (Architecture simplification complete)

---

## 📋 Executive Summary

Phases 1-4 successfully implemented the hybrid architecture, simplifying the system from 25 nodes to 12 nodes and from 158 state fields to 37. The **core architecture is functional and well-tested at the unit level** (92.19% coverage for `conversational_agent.py`).

**Phase 5 involves refactoring integration tests** to work with the new architecture. This document provides a **comprehensive strategy** for gradually migrating tests from the old node-based pattern to the new hybrid pattern.

---

## 🎯 Phase 5 Goals

1. **Refactor integration tests** to use `conversational_agent` instead of deleted nodes
2. **Update test patterns** from node state mocking to tool call mocking
3. **Maintain ≥85% code coverage** across the codebase
4. **Validate end-to-end flows** with the new hybrid architecture

---

## 📊 Current Test Status

### ✅ Passing Tests (Unit - Phase 1-4)
- `tests/unit/test_conversational_agent.py` - 12/12 tests passing ✅
  - Booking intent detection (positive/negative/edge cases)
  - Message formatting with summaries
  - Tool calling behavior
  - Error handling
  - State immutability

### ❌ Failing Tests (Integration - Require Refactoring)

**Story 2.2 - New Customer Flow:**
- `tests/integration/test_new_customer_flow.py`
  - Uses: `identify_customer`, `greet_new_customer`, `confirm_name` (deleted)
  - Needs: End-to-end graph test with `conversational_agent`

**Story 2.3 - Returning Customer Flow:**
- `tests/integration/test_returning_customer_flow.py`
  - Uses: `identify_customer`, `greet_returning_customer`, `extract_intent` (deleted)
  - Needs: Graph test with customer identification via tools

**Story 2.6 - FAQ Flow:**
- `tests/integration/test_faq_flow.py`
  - Uses: `detect_faq_intent`, `answer_faq`, `generate_faq_response` (deleted)
  - Needs: Graph test with `get_faqs` tool mocking

**Story 3.5 - Indecision & Consultation:**
- `tests/integration/test_scenario_08_indecision_consultation.py`
  - Uses: `detect_indecision`, `offer_consultation`, `handle_consultation_response` (deleted)
  - Needs: Graph test with `offer_consultation_tool` mocking

**General Agent Flow:**
- `tests/integration/test_agent_flow.py`
  - Uses multiple deleted nodes
  - Needs: Comprehensive graph flow tests

**Unit Tests (Old Nodes):**
- `tests/unit/test_identification_nodes.py` - Delete or refactor
- `tests/unit/test_classification_nodes.py` - Delete or refactor
- `tests/unit/test_faq_detection.py` - Delete or refactor

---

## 🔄 Test Refactoring Patterns

### Pattern 1: Node Tests → Graph Tests

**Old Pattern (Node-based):**
```python
# Test individual nodes directly
from agent.nodes.identification import identify_customer, greet_new_customer

async def test_identify_customer():
    state = {"customer_phone": "+34612345678", "messages": []}
    result = await identify_customer(state)
    assert result["is_returning_customer"] is False
```

**New Pattern (Graph-based):**
```python
# Test end-to-end graph flow
from agent.graphs.conversation_flow import create_conversation_graph

async def test_identify_customer_flow():
    graph = create_conversation_graph(checkpointer=None)

    # Initial state with customer message
    initial_state = {
        "conversation_id": "test-123",
        "customer_phone": "+34612345678",
        "messages": [
            {"role": "human", "content": "Hola", "timestamp": "2025-01-01T10:00:00"}
        ],
        "metadata": {},
    }

    # Mock LLM and tools
    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_llm, \
         patch("agent.tools.customer_tools.get_customer_by_phone") as mock_tool:

        # Mock tool response (customer not found)
        mock_tool.return_value = None

        # Mock LLM response
        mock_response = AIMessage(content="¡Hola! 🌸 Soy Maite. ¿Me confirmas tu nombre?")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)

        # Execute graph
        result = await graph.ainvoke(initial_state)

        # Validate conversational_agent handled greeting
        assert len(result["messages"]) >= 2
        assert "Maite" in result["messages"][-1]["content"]
```

---

### Pattern 2: State Field Assertions → Behavior Assertions

**Old Pattern (State field checks):**
```python
# Check deleted state fields
assert result["faq_detected"] is True
assert result["current_intent"] == "booking"
assert result["awaiting_name_confirmation"] is True
```

**New Pattern (Behavior checks):**
```python
# Check conversational behavior and tool calls
assert "booking_intent_confirmed" in result  # NEW field for Tier 1 → Tier 2
assert result["booking_intent_confirmed"] is True

# Check AI response content
last_message = result["messages"][-1]["content"]
assert "reserva" in last_message.lower()

# Check tool was called (via mock verification)
mock_tool.assert_called_once_with(phone="+34612345678")
```

---

### Pattern 3: Multi-Node Flow → Single Agent Flow

**Old Pattern (Step through multiple nodes):**
```python
# Step 1: Identify
identify_result = await identify_customer(state)
state_after_identify = {**state, **identify_result}

# Step 2: Greet
greet_result = await greet_new_customer(state_after_identify)
state_after_greet = {**state_after_identify, **greet_result}

# Step 3: Confirm
confirm_result = await confirm_name(state_after_greet)
```

**New Pattern (Single graph invocation):**
```python
# Single graph invocation - conversational_agent handles all logic
graph = create_conversation_graph(checkpointer=None)

# Simulate multi-turn conversation
conversation_states = []

# Turn 1: Customer says "Hola"
state1 = await graph.ainvoke(initial_state)
conversation_states.append(state1)

# Turn 2: Customer confirms name
state1["messages"].append({"role": "human", "content": "Sí, soy María"})
state2 = await graph.ainvoke(state1)
conversation_states.append(state2)

# Validate entire conversation flow
assert any("Maite" in msg["content"] for msg in state2["messages"])
```

---

### Pattern 4: Tool Call Mocking

**New Pattern (Mock LangChain tool calls):**
```python
from unittest.mock import patch, AsyncMock

async def test_faq_handling():
    """Test conversational_agent handles FAQ via get_faqs tool."""

    graph = create_conversation_graph(checkpointer=None)

    initial_state = {
        "conversation_id": "test-faq",
        "customer_phone": "+34612345678",
        "messages": [
            {"role": "human", "content": "¿A qué hora abrís?", "timestamp": "2025-01-01T10:00:00"}
        ],
        "metadata": {},
    }

    # Mock get_faqs tool to return FAQ data
    with patch("agent.tools.faq_tools.get_faqs") as mock_faq_tool, \
         patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_llm:

        # Mock tool returns FAQ
        mock_faq_tool.return_value = {
            "faqs": [
                {"category": "hours", "question": "¿A qué hora abrís?", "answer": "Abrimos de 9:00 a 20:00"}
            ],
            "count": 1
        }

        # Mock LLM response using FAQ data
        mock_response = AIMessage(content="Abrimos de 9:00 a 20:00 de lunes a sábado 🌸")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)

        # Execute graph
        result = await graph.ainvoke(initial_state)

        # Validate FAQ was answered
        last_message = result["messages"][-1]["content"]
        assert "9:00" in last_message or "20:00" in last_message

        # Verify tool was called
        mock_faq_tool.assert_called_once()
```

---

### Pattern 5: Booking Intent Detection

**New Pattern (Test Tier 1 → Tier 2 transition):**
```python
async def test_booking_intent_transition():
    """Test conversational_agent detects booking intent and transitions to Tier 2."""

    graph = create_conversation_graph(checkpointer=None)

    initial_state = {
        "conversation_id": "test-booking",
        "customer_phone": "+34612345678",
        "messages": [
            {"role": "human", "content": "Quiero reservar mechas para el viernes", "timestamp": "2025-01-01T10:00:00"}
        ],
        "metadata": {},
    }

    with patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_llm:
        # Mock LLM response with booking intent
        mock_response = AIMessage(content="Perfecto, vamos a reservar mechas. ¿Qué horario prefieres?")
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response)

        # Execute graph
        result = await graph.ainvoke(initial_state)

        # CRITICAL: Verify booking_intent_confirmed is set (Tier 1 → Tier 2 signal)
        assert result.get("booking_intent_confirmed") is True

        # Verify last node was conversational_agent
        assert result.get("last_node") == "conversational_agent"
```

---

## 📝 Test Refactoring Checklist

For each failing test file:

- [ ] **Identify deleted node dependencies**
  - List all `from agent.nodes.X import Y` that reference deleted nodes
  - List all deleted state fields used in assertions

- [ ] **Replace node imports with graph imports**
  ```python
  # Old
  from agent.nodes.identification import identify_customer

  # New
  from agent.graphs.conversation_flow import create_conversation_graph
  ```

- [ ] **Replace node calls with graph invocations**
  - Change from `await node_function(state)` to `await graph.ainvoke(state)`

- [ ] **Update state field assertions**
  - Remove assertions on deleted fields (`current_intent`, `faq_detected`, etc.)
  - Add assertions on new fields (`booking_intent_confirmed`)
  - Add assertions on conversational behavior (message content, tool calls)

- [ ] **Add tool mocking**
  - Mock LangChain `@tool` decorated functions
  - Mock LLM responses via `get_llm_with_tools`

- [ ] **Update test docstrings**
  - Reflect new testing approach (graph-based, not node-based)

- [ ] **Run test and validate**
  - Ensure test passes
  - Verify coverage is maintained

---

## 🗂️ Test Files Refactoring Priority

### Priority 1: Core Flows (Required for MVP)
1. **`test_new_customer_flow.py`** - Story 2.2
   - Replace: `identify_customer`, `greet_new_customer`, `confirm_name`
   - Add: Graph test with `get_customer_by_phone` tool mocking
   - Validate: Customer creation in database

2. **`test_faq_flow.py`** - Story 2.6
   - Replace: `detect_faq_intent`, `answer_faq`, `generate_faq_response`
   - Add: Graph test with `get_faqs` tool mocking
   - Validate: FAQ answers in conversational response

### Priority 2: Booking Flows (High Value)
3. **`test_scenario_08_indecision_consultation.py`** - Story 3.5
   - Replace: `detect_indecision`, `offer_consultation`, `handle_consultation_response`
   - Add: Graph test with `offer_consultation_tool` mocking
   - Validate: Consultation offering and booking flow

4. **`test_returning_customer_flow.py`** - Story 2.3
   - Replace: `identify_customer`, `greet_returning_customer`, `extract_intent`
   - Add: Graph test with customer history loading
   - Validate: Personalized greeting for returning customers

### Priority 3: Complex Flows (Nice to Have)
5. **`test_agent_flow.py`** - General flow
   - Replace: Multiple node calls
   - Add: Comprehensive end-to-end graph tests
   - Validate: Full conversation scenarios

6. **Integration tests for Stories 3.3, 3.4, 3.6**
   - Most of these should work with minimal changes (use Tier 2 nodes that still exist)
   - May need to adjust entry points (now via `conversational_agent`)

### Priority 4: Unit Tests (Delete or Refactor)
7. **`test_identification_nodes.py`** - DELETE (nodes deleted)
8. **`test_classification_nodes.py`** - DELETE (nodes deleted)
9. **`test_faq_detection.py`** - DELETE (nodes deleted)

---

## 🛠️ Example: Complete Test Refactoring

### Before (Old Node-Based Test):
```python
# tests/integration/test_new_customer_flow.py (OLD)

@pytest.mark.asyncio
async def test_full_new_customer_flow_with_confirmation(initial_state):
    # Step 1: Identify customer (should not be found)
    identify_result = await identify_customer(initial_state)
    assert identify_result["is_returning_customer"] is False

    state_after_identify = {**initial_state, **identify_result}

    # Step 2: Greet new customer
    greet_result = await greet_new_customer(state_after_identify)
    assert greet_result["awaiting_name_confirmation"] is True
    assert len(greet_result["messages"]) == 1

    state_after_greet = {**state_after_identify, **greet_result}

    # Step 3: User confirms name
    user_confirmation = HumanMessage(content="Sí, correcto")
    state_after_greet["messages"].append(user_confirmation)

    with patch("agent.nodes.identification.llm") as mock_llm:
        mock_llm_response = MagicMock()
        mock_llm_response.content = "confirmed"
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

        confirm_result = await confirm_name(state_after_greet)

    assert confirm_result["customer_identified"] is True
    assert confirm_result["customer_id"] is not None
```

### After (New Graph-Based Test):
```python
# tests/integration/test_new_customer_flow.py (NEW)

@pytest.mark.asyncio
async def test_full_new_customer_flow_with_confirmation(cleanup_test_customer):
    """
    Test complete new customer flow via conversational_agent:
    1. Customer sends greeting
    2. conversational_agent identifies customer (not found)
    3. conversational_agent greets and asks for name confirmation
    4. Customer confirms name
    5. conversational_agent creates customer in database
    """
    graph = create_conversation_graph(checkpointer=None)

    # Turn 1: Customer says "Hola"
    initial_state = {
        "conversation_id": "test-new-customer",
        "customer_phone": cleanup_test_customer,
        "messages": [
            {"role": "human", "content": "Hola", "timestamp": "2025-01-01T10:00:00"}
        ],
        "metadata": {"whatsapp_name": "María García"},
    }

    # Mock tools and LLM for first turn
    with patch("agent.tools.customer_tools.get_customer_by_phone") as mock_get_customer, \
         patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_llm:

        # Mock: Customer not found in database
        mock_get_customer.return_value = None

        # Mock: LLM asks for name confirmation
        mock_response_1 = AIMessage(
            content="¡Hola! 🌸 Soy Maite. Veo que te llamas María García, ¿es correcto?"
        )
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response_1)

        # Execute Turn 1
        state1 = await graph.ainvoke(initial_state)

        # Validate greeting and name confirmation request
        assert len(state1["messages"]) >= 2
        last_message = state1["messages"][-1]["content"]
        assert "Maite" in last_message
        assert "María García" in last_message or "confirmas" in last_message.lower()

    # Turn 2: Customer confirms name "Sí, correcto"
    state1["messages"].append({
        "role": "human",
        "content": "Sí, correcto",
        "timestamp": "2025-01-01T10:00:05"
    })

    with patch("agent.tools.customer_tools.create_customer") as mock_create, \
         patch("agent.nodes.conversational_agent.get_llm_with_tools") as mock_llm:

        # Mock: Customer creation returns UUID
        test_customer_id = uuid4()
        mock_create.return_value = {
            "customer_id": test_customer_id,
            "created": True,
        }

        # Mock: LLM confirms customer creation
        mock_response_2 = AIMessage(
            content="¡Perfecto, María! Ya estás registrada. ¿En qué puedo ayudarte hoy? 😊"
        )
        mock_llm.return_value.ainvoke = AsyncMock(return_value=mock_response_2)

        # Execute Turn 2
        state2 = await graph.ainvoke(state1)

        # Validate customer creation
        assert state2.get("customer_id") is not None
        mock_create.assert_called_once()

        # Validate confirmation message
        last_message = state2["messages"][-1]["content"]
        assert "María" in last_message or "registrada" in last_message.lower()
```

---

## 🚀 Implementation Steps

1. **Start with Priority 1 tests** (`test_new_customer_flow.py`, `test_faq_flow.py`)
2. **Follow the refactoring checklist** for each file
3. **Run tests incrementally** to catch issues early
4. **Update coverage report** after each test file
5. **Move to Priority 2 and 3** as time allows
6. **Delete obsolete unit tests** (Priority 4)

---

## 📈 Success Criteria

- [ ] **All Priority 1 tests passing** (Core flows)
- [ ] **Code coverage ≥85%** maintained
- [ ] **No imports of deleted nodes** in any test file
- [ ] **All tests use graph-based pattern** (not node-based)
- [ ] **Documentation updated** with new testing approach

---

## 🔗 Related Documentation

- **Architecture Overview**: `docs/DEVELOPER-HANDOFF-ARCHITECTURE-SIMPLIFICATION.md`
- **Hybrid Architecture Analysis**: `docs/architecture/hybrid-architecture-analysis.md`
- **Sprint Change Proposal**: `docs/sprint-change-proposal-architecture-simplification.md`
- **Story Updates**: `docs/architecture-update-affected-stories.md`

---

## 📞 Questions & Support

For questions about this refactoring strategy:
1. Review the **Test Refactoring Patterns** section above
2. Check the **Example: Complete Test Refactoring** for reference
3. Refer to existing passing tests in `tests/unit/test_conversational_agent.py`

---

**Document Version**: 1.0
**Last Updated**: 2025-01-30
**Author**: Architecture Simplification Team
