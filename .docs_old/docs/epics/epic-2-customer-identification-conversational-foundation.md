# Epic 2: Customer Identification & Conversational Foundation

**Epic Goal:** Implement intelligent customer identification (new vs returning), warm greeting protocol with "Maite" persona, name confirmation flow, and conversational memory system—enabling natural back-and-forth dialogue that remembers context across multiple message exchanges.

## Implementation Notes

**Enhanced FAQ System (Story 2.6):** The implemented FAQ system exceeds original specifications with a hybrid AI approach. While the basic static FAQ retrieval meets all original acceptance criteria, the production system includes intelligent multi-FAQ detection, query complexity classification, and AI-powered personalized response generation for compound queries. This enhancement improves conversational fluidity without affecting other Epic 2 stories. See Story 2.6 ACs 11-19 for details.

## Story 2.1: CustomerTools Implementation

**As a** system,
**I want** CustomerTools that provide complete database operations for customer lifecycle management,
**so that** the agent can identify, create, update, and query customer records including name corrections.

**Prerequisites:** Story 1.3a (Customers table)

**Acceptance Criteria:**

1. CustomerTools class created in `/agent/tools/customer_tools.py`
2. Tool `get_customer_by_phone(phone: str)` queries database and returns customer or None
3. Tool `create_customer(phone: str, first_name: str, last_name: str = "")` creates new customer
4. Tool `update_customer_name(customer_id: int, first_name: str, last_name: str)` updates name
5. Tool `update_customer_preferences(customer_id: int, preferred_stylist_id: int)` updates preferences
6. Tool `get_customer_history(customer_id: int, limit: int = 5)` returns last N appointments
7. All tools use async SQLAlchemy sessions
8. Tools integrated with LangChain's `@tool` decorator
9. Phone number normalization applied (E.164 format)
10. Error handling: Database failures return graceful error messages
11. Unit tests with mocked database
12. Integration test: Create → query → update → verify persistence

## Story 2.2: New Customer Greeting & Name Confirmation

**As a** new customer,
**I want** the bot to greet me warmly, introduce itself as "Maite", and confirm my name with fallback handling,
**so that** I feel welcomed and the bot has accurate information even if I provide unclear responses.

**Prerequisites:** Story 2.1 (CustomerTools), Story 1.5 (Basic StateGraph)

**Acceptance Criteria:**

1. LangGraph node `identify_customer` queries CustomerTools by phone
2. If customer NOT found → triggers `greet_new_customer` node
3. Greeting message: "¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es {metadata_name}?"
4. If WhatsApp name unreliable → asks: "¿Me confirmas tu nombre para dirigirme a ti correctamente?"
5. State updated with `awaiting_name_confirmation: true`
6. `confirm_name` node processes response
7. If confirmed → create_customer with name
8. If different name provided → create_customer with corrected name
9. If ambiguous response (max 2 attempts) → escalate with note
10. After confirmation, state updated `customer_identified: true`
11. Integration test: New customer → greeting → name confirmation → database record
12. Emoji 🌸 validated in greeting

## Story 2.3: Returning Customer Recognition

**As a** returning customer,
**I want** the bot to recognize me and skip the introduction while intelligently routing to my request,
**so that** I can quickly get assistance without repetitive onboarding.

**Prerequisites:** Story 2.1 (CustomerTools), Story 2.2 (New customer flow)

**Acceptance Criteria:**

1. `identify_customer` node checks if customer exists
2. If FOUND → state updated with customer details and `is_returning: true`
3. `extract_intent` node uses Claude to analyze message for intent
4. Intent passed to router (booking, modification, cancellation, inquiry, faq)
5. If clear intent → personalized response directly addressing request
6. If greeting-only → "¡Hola, {first_name}! Soy Maite 🌸. ¿En qué puedo ayudarte hoy?"
7. No name confirmation for returning customers
8. Customer history retrieved for "lo de siempre" logic
9. Integration test: Returning customer → no name confirmation → intent routing
10. Edge case: Incomplete profile → still recognized, proceed

## Story 2.4: Maite System Prompt & Personality

**As a** system,
**I want** the "Maite" persona defined in a comprehensive system prompt with escalation instructions,
**so that** all responses maintain consistent tone and the agent knows how to handle edge cases.

**Acceptance Criteria:**

1. System prompt file created in `/agent/prompts/maite_system_prompt.md`
2. Prompt includes role: "Eres Maite, la asistenta virtual de Atrévete Peluquería..."
3. Tone guidelines: warm, friendly, Spanish (tú form), emoji usage (🌸💕😊🎉💇)
4. Business context: 5 stylists, service categories, advance payment policy
5. Tool usage instructions: "SIEMPRE consulta herramientas, NUNCA inventes"
6. Escalation instructions with tool calls: medical → `escalate_to_human(reason='medical_consultation')`, payment failures → after 2 attempts, ambiguity → after 3 exchanges
7. Example interactions demonstrating tone
8. Prompt loaded as initial system message in StateGraph
9. Integration test: Generate 5 responses → manual tone/emoji/Spanish validation
10. Unit test: Verify prompt file loads correctly

## Story 2.5a: Redis Checkpointing & Recent Message Memory

**As a** system,
**I want** LangGraph conversation state persisted to Redis with recent message windowing,
**so that** conversations can recover from crashes and maintain short-term context.

**Prerequisites:** Story 1.5 (Basic LangGraph setup)

**Acceptance Criteria:**

1. State schema includes `recent_messages` (last 10 message exchanges)
2. LangGraph `MemorySaver` uses Redis backend
3. Checkpoints saved after each node with key pattern `langgraph:checkpoint:{conversation_id}:{timestamp}`
4. `add_message` helper maintains max 10 messages (FIFO)
5. Redis RDB snapshots every 15 minutes
6. State TTL: 24 hours
7. On resume, StateGraph loads latest checkpoint
8. Crash recovery test: 3 messages → kill agent → restart → send message → verify 3 previous messages retained
9. Unit test: add_message maintains exactly 10 messages
10. Integration test: Verify checkpoint in Redis, retrieve, validate structure

## Story 2.5b: Conversation Summarization with Claude

**As a** system,
**I want** long conversations automatically summarized to compress token usage,
**so that** the agent can maintain context without exceeding Claude's token limits.

**Prerequisites:** Story 2.5a (Message windowing)

**Acceptance Criteria:**

1. State includes `conversation_summary` field
2. `summarize_conversation` node triggers after every 5 message exchanges
3. Node calls Claude to compress messages beyond recent 10
4. Summary prompt: "Resume la siguiente conversación en 2-3 oraciones..."
5. Summary stored, older messages removed
6. All LLM calls receive: system_prompt + summary + recent_messages
7. Token overflow protection: If >70% context → aggressive summarization or escalation flag
8. Unit test: 25 messages → verify summaries at message 15 and 25
9. Integration test: 30 messages → verify final context <10k tokens

## Story 2.5c: PostgreSQL Archiving Worker & TTL Management

**As a** system,
**I want** expired conversation state archived from Redis to PostgreSQL for historical analysis,
**so that** customer interaction history is preserved beyond 24-hour Redis TTL.

**Prerequisites:** Story 2.5a (Redis checkpointing), Story 1.3b (conversation_history table)

**Acceptance Criteria:**

1. Background worker `/agent/workers/conversation_archiver.py`
2. Runs hourly on cron schedule
3. Queries Redis for checkpoints older than 23 hours
4. For each: retrieve state → insert messages to conversation_history → delete checkpoint
5. Records include customer_id, conversation_id, timestamp, role, content, metadata
6. Worker logs archiving activity
7. Error handling: Retry once on PostgreSQL failure, then skip
8. Health check endpoint/file for monitoring
9. Integration test: Create 23.5h old checkpoint → run worker → verify in conversation_history → verify deleted from Redis
10. Unit test: Mock expired checkpoints → verify processing

## Story 2.6: FAQ Knowledge Base Responses

**As a** customer,
**I want** to ask common questions and receive instant answers in Maite's tone,
**so that** I get information quickly without escalation.

**Prerequisites:** Story 1.3b (Policies table), Story 2.4 (Maite prompt)

**Acceptance Criteria:**

1. FAQ data stored in `policies` table with JSON structure
2. Seed script populates minimum 5 FAQs: hours, parking, address, cancellation policy, payment
3. `detect_faq_intent` node uses Claude for classification
4. If FAQ detected → `answer_faq` retrieves from database
5. Answers formatted with Maite's tone + emojis
6. After FAQ → proactive: "¿Hay algo más en lo que pueda ayudarte? 😊"
7. Sample FAQs implemented per AC
8. If location FAQ → optionally offer Google Maps link
9. Integration test: "¿Abrís los sábados?" → verify answer → verify follow-up
10. Unit test: 10 variations per FAQ → verify detection

---
