# Appointment Management Flow — Narrative Companion

> Developer-only reference. Do NOT include in the live prompt.
> See `agent/prompts/shared/appointment_management_flow.md` for the terse rule card.

---

## Why the 48-hour cancellation window exists

The salon needs at least 48 hours to reassign the slot to another client or free the stylist's
calendar in Google Calendar. Cancellations within 48 hours cause revenue loss (no-show) and
operational disruption. The window is enforced in `manage_appointments` and the agent must
surface the policy message verbatim when the tool returns it.

## Why the agent reads `## Citas próximas` instead of always calling `action="list"`

The `AppointmentContextMiddleware` injects upcoming appointments into every turn. This avoids
a redundant DB read on every "¿qué cita tengo?" question, reducing latency. The agent only
falls back to `action="list"` when the block is absent (e.g. new session without prior context)
or the client explicitly asks for a refresh.

## Why UUID is never shown to the client

Clients have no use for internal UUIDs and exposing them makes the conversation feel robotic
and technical. The agent always references appointments by date + time + stylist. The UUID is
only passed as a tool argument, never spoken.

## Why stylist changes require escalation

Stylist reassignment is a complex operation that may involve preference negotiation,
availability checks across the new stylist's calendar, and pricing adjustments. It is
out of scope for the automated agent and always escalated to a human.

## Why confirmation/decline replies use the tool's response verbatim

The `manage_appointments` tool may return salon-specific copy (e.g. "Cita confirmada para el
jueves 30 a las 10:00 con Pilar. ¡Hasta pronto!"). Using the tool's message ensures
consistency with the admin panel and avoids the agent paraphrasing policy incorrectly.

## Worked example — reschedule with slot conflict

```
Client: "quiero cambiar mi cita del viernes"
Bot: reads ## Citas próximas → finds appointment_id X on friday
Bot: "¿Qué día y hora te viene mejor?"
Client: "el lunes a las 11"
Bot: → check_availability(service_ids=[...], date="2026-04-28", stylist_id="...")
     ← [{start_iso: "2026-04-28T11:00:00+02:00", label: "lunes 28 de abril", ...}]
Bot (turno A): "Perfecto, te lo cambio al lunes 28 de abril a las 11:00 con Pilar. ¿Te lo confirmo?"
Client: "sí"
Bot (turno B): → manage_appointments(action="reschedule", appointment_id=X,
                    new_date="2026-04-28", new_time="11:00")
               ← {status: "ok", message: "Cita reprogramada para el lunes 28..."}
Bot: "Cita reprogramada para el lunes 28..."
```

Conflict case — if `manage_appointments` returns `SLOT_TAKEN`:
```
Bot: → check_availability again with same params
Bot: "Ese hueco ya no está disponible. Tengo las 12:00 o las 15:30. ¿Cuál prefieres?"
```
