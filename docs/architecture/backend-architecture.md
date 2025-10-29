# 10. Backend Architecture

The backend implements the core business logic through three architectural layers: API (webhook receivers), Agent (LangGraph orchestration), and Workers (background tasks).

## 10.1 Service Architecture - Agent Container (Stateful Architecture)

Atrévete Bot uses a **stateful agent architecture** (not serverless) running as a long-lived Python process in a Docker container.

### 10.1.1 ConversationState Schema (TypedDict)

```python
# agent/state/schemas.py
from typing import TypedDict, List, Optional, Literal
from datetime import datetime
from uuid import UUID

class ConversationState(TypedDict, total=False):
    # Conversation metadata
    conversation_id: str  # LangGraph thread_id
    customer_phone: str   # E.164 format

    # Customer context
    customer_id: Optional[UUID]
    customer_name: Optional[str]
    is_returning_customer: bool
    customer_history: List[dict]  # Last 5 appointments
    preferred_stylist_id: Optional[UUID]

    # Message management
    messages: List[dict]  # Recent 10 messages (HumanMessage, AIMessage)
    conversation_summary: Optional[str]  # Compressed history after 15+ messages

    # Intent classification
    current_intent: Optional[Literal[
        "booking", "modification", "cancellation",
        "faq",            # FAQ queries (hybrid: simple→static, compound→AI)
        "indecision",     # Customer unsure about service
        "usual_service",  # "lo de siempre" requests
        "escalation"      # Medical/complex queries requiring human
    ]]

    # Booking context
    requested_services: List[UUID]  # Service IDs
    suggested_pack_id: Optional[UUID]
    pack_accepted: bool
    selected_date: Optional[str]  # ISO 8601 date
    selected_time: Optional[str]  # HH:MM format
    selected_stylist_id: Optional[UUID]
    available_slots: List[dict]  # {time, stylist_id, stylist_name}

    # Provisional booking tracking
    provisional_appointment_id: Optional[UUID]
    appointment_expires_at: Optional[datetime]
    payment_link_url: Optional[str]
    payment_retry_count: int

    # Group booking context
    is_group_booking: bool
    group_size: int
    group_appointment_ids: List[UUID]

    # Third-party booking
    is_third_party_booking: bool
    third_party_name: Optional[str]
    third_party_customer_id: Optional[UUID]

    # Escalation tracking
    escalated: bool
    escalation_reason: Optional[Literal[
        "medical_consultation", "payment_failure",
        "ambiguity", "delay_notice", "manual_request"
    ]]
    clarification_attempts: int

    # Node execution tracking
    last_node: Optional[str]
    error_count: int

    # Metadata
    created_at: datetime
    updated_at: datetime
```

### 10.1.2 FAQ Handling Architecture

The FAQ system uses a **hybrid routing strategy** optimizing for both speed and intelligence:

**Detection Phase:**
- All queries analyzed by Claude for FAQ classification
- Returns: `detected_faq_ids` (list), `query_complexity` (simple/compound/none)

**Response Phase:**
- **Simple Path** (single FAQ, clear intent):
  - Route: `detect_faq_intent` → `answer_faq` → END
  - Method: Static database retrieval
  - Performance: <2s
  - Use case: "¿Qué horario tenéis?"

- **Smart Path** (compound queries, multiple FAQs):
  - Route: `detect_faq_intent` → `fetch_faq_context` → `generate_personalized_faq_response` → END
  - Method: AI synthesis with tone adaptation
  - Performance: <5s
  - Use case: "¿Dónde estáis y hay parking? Necesito cita mañana"

**State Fields:**
- `faq_detected`: bool
- `detected_faq_ids`: list[str]  (e.g., ["hours", "parking"])
- `detected_faq_id`: str  (backward compat - first FAQ)
- `query_complexity`: "simple" | "compound" | "contextual" | "none"
- `faq_context`: list[dict]  (FAQ data for AI generation)

---
