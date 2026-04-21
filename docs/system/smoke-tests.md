# Smoke Test Plans

Manually-executable smoke scenarios for critical regression paths.
Each scenario documents the input, the expected bot behaviour, and how to run it.

---

## SMOKE-1 — Audience Disambiguation (conv_id=5 regression)

**Introduced by**: SDD `booking-tool-grounding-contract` (2026-04)
**Covers**: REQ-15 — `pending_disambiguations` list shape, `service_audience_hint` handoff,
grounding snapshot rebind (post-resolver `booking_context` visible to middleware).

### Problem history

Before this SDD the bot responded to "quiero cortarme el pelo" by immediately offering
a list of available stylists instead of asking whether the appointment is for a señora,
caballero, or niño. Root cause: `_audience_ambiguity` (now `pending_disambiguations`) was
written as a single dict instead of `list[dict]`, and the grounding middleware was reading
a stale copy of `booking_context` from the LangGraph checkpoint rather than the post-resolver
version.

### Input

```
quiero cortarme el pelo
```

### Expected bot response

The bot asks for audience disambiguation **before** offering stylists. Example:

> "¡Claro! Antes de seguir, ¿el turno es para señora, caballero o niño?"

The bot **must NOT** offer a stylist list (Caro, Mari, Fabi, etc.) as its first response.

### How to run manually via Chatwoot

1. Open Chatwoot and start a new conversation on the WhatsApp inbox.
2. Send the single message: `quiero cortarme el pelo`
3. Observe the bot's first reply:
   - PASS: bot asks señora/caballero/niño
   - FAIL: bot offers a list of stylists

### Automated regression test

```bash
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/integration/test_booking_audience_disambiguation.py -v
```

The integration test (`tests/integration/test_booking_audience_disambiguation.py`) uses
LangGraph's `MemorySaver` checkpoint + the real booking graph to assert that the bot's
first reply to "quiero cortarme el pelo" does NOT contain any stylist name and DOES
contain an audience-choice phrase.

### Registry consistency check

```bash
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_booking_state_contract.py -v
```

### AST orphan lint

```bash
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
  ./venv/bin/pytest tests/unit/test_no_orphan_booking_context_fields.py -v
```

---

## SMOKE-2 — Direct booking_context mutation gate

**Covers**: prevents direct `booking_context[k] = v` mutations outside the patch pipeline.

```bash
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_no_direct_booking_context_writes.py -v
```
