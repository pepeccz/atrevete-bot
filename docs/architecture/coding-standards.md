# 18. Coding Standards

## 18.1 Critical Fullstack Rules

- **Type Sharing:** Define shared types in `agent/state/schemas.py`, never duplicate
- **Environment Variables:** Access via `shared/config.py`, never direct `os.getenv()`
- **Error Handling:** All LangGraph nodes use try-except with logging
- **State Updates:** Never mutate ConversationState—return new dict for immutability
- **Database Transactions:** Multi-step operations use `async with session.begin()`
- **Tool Invocation:** Always use LangChain `@tool` decorator with Pydantic validation
- **Phone Normalization:** E.164 format via `phonenumbers` library
- **Timezone:** All datetimes use `ZoneInfo("Europe/Madrid")`
- **Webhook Validation:** Validate signatures BEFORE processing (401 on invalid)
- **Redis Keys:** Consistent patterns: `conversation:{id}:human_mode`
- **Logging:** Include `conversation_id` or `appointment_id` for traceability
- **API Retries:** Exponential backoff (3 attempts) via `tenacity` decorator

## 18.2 Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| API Routes | snake_case | `/webhook/chatwoot` |
| Database Tables | snake_case | `appointments` |
| Python Functions | snake_case | `get_customer_by_phone()` |
| Python Classes | PascalCase | `ConversationState` |
| LangGraph Nodes | snake_case | `identify_customer` |
| Environment Variables | SCREAMING_SNAKE_CASE | `STRIPE_SECRET_KEY` |
| Redis Keys | colon-separated | `conversation:thread-123:human_mode` |

---

**END OF ARCHITECTURE DOCUMENT**
