# 16. Error Handling Strategy

- **Retry Logic:** Exponential backoff for transient API errors (3 attempts)
- **Escalation:** Permanent errors → escalate to human team with context
- **Logging:** Structured JSON logs with conversation_id/appointment_id for traceability

---
