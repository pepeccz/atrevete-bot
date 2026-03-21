# Design: Escalation mode — structured intake

## Architecture Decision

### Current State
- One-turn escalation with canned response loop
- Broken tool parameters: `conversation_id` and `customer_phone` instead of `_conversation_id` and `_customer_phone`
- No capture of issue context before handoff
- After first escalation, remains in ESCALATION mode forever, providing only canned responses

### New State
- Multi-step intake flow: `issue_intake` → `contact_preference` → `ready_to_handoff`
- Correct tool parameter injection: `_conversation_id`, `_customer_phone`, plus new fields `issue_summary` and `contact_preference`
- Captures customer issue description and preferred contact method before handoff
- After successful handoff, allows transition out of ESCALATION mode via `escalation_completed` flag

### Why
- Human agents need context (issue description and contact preference) to provide effective support
- Current tool contract mismatch prevents proper escalation workflow
- Structured intake improves customer experience by gathering necessary information before handoff
- Prevents infinite canned response loop after escalation

### Tradeoffs
- More state fields to track (escalation_step, issue_summary, contact_preference, escalation_timestamp)
- More complex mode logic with substep handling
- Slightly longer conversation before handoff, but better outcomes

## State Schema Changes

Add to ConversationState in `agent/state/schemas.py`:

```python
# Add to ConversationState TypedDict:
escalation_step: Literal["issue_intake", "contact_preference", "ready_to_handoff"] | None
issue_summary: str | None
contact_preference: Literal["phone", "whatsapp", "email"] | None
escalation_timestamp: datetime | None
```

These fields will be stored in `mode_context` since they are escalation-mode specific transient data.

## Escalation Mode Substeps

Like BOOKING mode substeps, ESCALATION mode will have three distinct steps:

### ISSUE_INTAKE
- Ask: "¿Cuál es el motivo por el que necesitás hablar con una persona?"
- Capture customer's description of their issue/need
- Store in `mode_context["issue_summary"]`
- Transition to `contact_preference`

### CONTACT_PREFERENCE
- Ask: "¿Cómo prefieres que el equipo se comunique contigo? (teléfono, WhatsApp o email)"
- Parse response to determine preference: "phone", "whatsapp", or "email"
- Default to "phone" if unclear
- Store in `mode_context["contact_preference"]`
- Transition to `ready_to_handoff`

### READY_TO_HANDOFF
- Confirm: "Perfecto, tengo anotado: [issue_summary]. Te contactaremos por [contact_preference]."
- Call escalation tool with full context
- Show success message: "Nuestro equipo te atenderá en breve."
- Set `mode_context["escalation_completed"] = True`
- Return state with `escalation_triggered: True`

## Tool Contract Fix

### Current Call (incorrect)
```python
await escalate_to_human.ainvoke({
    "reason": "customer_request",
    "customer_name": customer_name_internal,
    "customer_phone": customer_phone,
    "conversation_id": conversation_id,
})
```

### New Call (correct)
```python
tool_result = await escalate_to_human.ainvoke({
    "_conversation_id": state["conversation_id"],
    "_customer_phone": state["customer_phone"],
    "issue_summary": mode_context["issue_summary"],
    "contact_preference": mode_context["contact_preference"],
    "reason": "manual_request"
})
```

### Required Changes
1. **agent/tools/escalation_tools.py**: Verify line 44-50 has correct parameter names:
   ```python
   async def escalate_to_human(
       reason: str,
       _conversation_id: str | None = None,
       _customer_phone: str | None = None,
       _conversation_context: list[dict[str, Any]] | None = None,
       issue_summary: str | None = None,
       contact_preference: Literal["phone", "whatsapp", "email"] | None = None,
   ) -> dict[str, Any]:
   ```

2. **agent/services/escalation_service.py**: Verify `trigger_escalation` and `create_escalation_notification` accept and log these new fields

## Pseudocode for EscalationMode.handle()

```python
async def handle(self, state, context):
    mode_context = state.get("mode_context") or {}
    escalation_step = mode_context.get("escalation_step", "issue_intake")
    
    if escalation_step == "issue_intake":
        # Ask for issue description
        messages = [
            SystemMessage(content="Eres Maite, asistente de belleza. Tu rol es capturar el motivo por el cual el cliente necesita hablar con un humano. Sé empática y profesional."),
            HumanMessage(content=state["user_message"] or "")
        ]
        result = await self._run_agentic_loop(messages)
        
        # Extract issue from user response (simple approach: use user's message directly)
        issue_summary = state["user_message"] or "Cliente requiere atención humana"
        
        return {
            **add_message(state, "assistant", "Gracias. ¿Cuál es tu número de teléfono o WhatsApp?"),
            "mode_context": {
                **mode_context,
                "escalation_step": "contact_preference",
                "issue_summary": issue_summary,
                "escalation_timestamp": datetime.now().isoformat()
            }
        }
    
    elif escalation_step == "contact_preference":
        # Ask for contact method
        result = await self._run_agentic_loop([
            SystemMessage(content="Interpreta la respuesta del cliente para determinar su método de contacto preferido: teléfono, WhatsApp o email. Responde solo con una de estas tres opciones."),
            HumanMessage(content=state["user_message"] or "")
        ])
        
        contact_pref = result.strip().lower()
        if contact_pref not in ["phone", "whatsapp", "email"]:
            contact_pref = "phone"  # default
        
        return {
            **add_message(state, "assistant", "Perfecto. Voy a conectarte con nuestro equipo..."),
            "mode_context": {
                **mode_context,
                "escalation_step": "ready_to_handoff",
                "contact_preference": contact_pref
            }
        }
    
    elif escalation_step == "ready_to_handoff":
        # Call tool with full context
        try:
            from agent.tools.escalation_tools import escalate_to_human
            
            tool_result = await escalate_to_human.ainvoke({
                "_conversation_id": state["conversation_id"],
                "_customer_phone": state["customer_phone"],
                "issue_summary": mode_context["issue_summary"],
                "contact_preference": mode_context["contact_preference"],
                "reason": "manual_request"
            })
            
            return {
                **add_message(state, "assistant", "Nuestro equipo te atenderá en breve."),
                "mode_context": {
                    **mode_context,
                    "escalation_completed": True
                },
                "escalation_triggered": True
            }
        except Exception as exc:
            self.logger.error(
                "EscalationMode: escalate_to_human failed | conversation_id=%s | error=%s",
                state.get("conversation_id", "unknown"),
                exc,
            )
            return {
                **add_message(state, "assistant", "He notificado a nuestro equipo. Te contactarán en breve. 🙏"),
                "mode_context": {
                    **mode_context,
                    "escalation_completed": True
                },
                "escalation_triggered": True
            }
```

## Router Changes

### Current Rule (conversation_flow.py:212-214)
```python
# Rule 1: Already escalated
if escalation_triggered:
    return {"current_mode": "ESCALATION", "last_node": "router"}
```

### New Rule
```python
# Rule 1: Already escalated
escalation_triggered = state.get("escalation_triggered", False)
escalation_completed = state.get("mode_context", {}).get("escalation_completed", False)

if escalation_triggered and not escalation_completed:
    return {"current_mode": "ESCALATION", "last_node": "router"}
# If escalation_completed is True, allow normal routing to proceed
```

## Error Handling

- **Issue capture timeout**: If no response after 2 turns, escalate with empty issue_summary
- **Contact preference parse failure**: Default to "phone" if response unclear
- **Tool call failure**: Show error message, remain in READY_TO_HANDOFF, allow retry on next user message

## Code Locations

1. **agent/modes/escalation_mode.py** - Complete handle() refactor with substep logic
2. **agent/state/schemas.py** - Add escalation_step, issue_summary, contact_preference, escalation_timestamp to ConversationState
3. **agent/graphs/conversation_flow.py:212-214** - Update router rule to allow transition after escalation_completed
4. **agent/tools/escalation_tools.py** - Verify/add issue_summary and contact_preference parameters
5. **agent/services/escalation_service.py** - Verify new parameters are accepted and logged
6. **tests/integration/test_escalation_flow.py** - Update assertions for new flow (create if doesn't exist)

## Test Strategy

### Happy Path
1. User: "Quiero hablar con una persona"
2. Bot: "¿Cuál es el motivo por el que necesitás hablar con una persona?"
3. User: "Quiero cambiar mi turno de mañana"
4. Bot: "Gracias. ¿Cuál es tu número de teléfono o WhatsApp?"
5. User: "Mi WhatsApp es +34600112233"
6. Bot: "Perfecto. Voy a conectarte con nuestro equipo..."
7. Bot calls tool with issue_summary="Quiero cambiar mi turno de mañana", contact_preference="whatsapp"
8. Bot: "Nuestro equipo te atenderá en breve."

### Urgent Path
1. User: "PERSONA YA AHORA"
2. Bot: Skips questions, uses default values, escalates immediately

### Context-Rich Path
1. User already said: "Necesito cambiar mi turno" + "Mi teléfono es +34600112233"
2. Bot parses both issue and contact from context, goes straight to READY_TO_HANDOFF

### Already Escalated
1. After escalation_completed=True, subsequent messages show handoff status, not repeat questions