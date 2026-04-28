# Booking Flow — Narrative Companion

> Developer-only reference. Do NOT include in the live prompt.
> See `agent/prompts/shared/booking_flow.md` for the terse rule card used in production.

---

## Why the `<availability>` block takes precedence

The `<availability>` block is pre-computed from the DB every ~60 seconds by
`DynamicPromptMiddleware`. Using it avoids a redundant `check_availability` round-trip on
every turn, reducing latency and tool call count. The only time `check_availability` is still
needed is to re-validate the exact slot the client chose (race condition guard) or when
the service is not yet resolved and the availability block is absent.

---

## Why audience must be resolved before any tool call (Paso 0)

Services like "Corte" map to multiple catalog entries: Corte Dama, Corte Caballero,
Corte Niña, etc. Each has a distinct UUID. If the agent calls `check_availability` with
the wrong UUID the slots returned are meaningless and the subsequent `book` will fail.
One disambiguation turn is always cheaper than a failed booking.

---

## Why `offer_slots` triggers an immediate tool call (not an open question)

The `offer_slots` signal means the stylist is already resolved. Asking "¿qué día te viene bien?"
at that point is always wrong: (a) the client doesn't know the stylist's actual free days,
(b) we'd waste a turn. Calling `get_next_available_options` immediately gives the client a
concrete numbered menu, which is faster and reduces abandonment.

Edge case — zero options returned:
When `get_next_available_options` returns 0 slots the agent must NOT present an empty menu.
It should tell the client there is no near-term availability and invite them to pick a
specific date (falling back to `date_required` flow).

---

## Why `closed_day` / `advance_policy_violated` re-present the previous menu

Asking "¿qué día prefieres?" after a policy rejection re-opens a free-text date input,
which is likely to produce another rejection. Re-presenting the last valid menu keeps the
client anchored to known-good options and shortens the correction cycle.

---

## Why `update_booking` must be called before narrating

`update_booking` is the source of truth for `next_step`. Narrating first risks telling the
client the wrong next action. Always call the tool, then narrate based on its `next_step`.

---

## Why the confirmation gate requires two turns (R21)

Slot selection ("las 9:00") is intent, not consent. The confirmation turn ("¿te lo confirmo?")
ensures the client sees the full summary (date + time + stylist + services + notes) before
a DB write happens. This prevents silent mismatches from speech recognition or abbreviation.

---

## Historical rationale for the `extras_loop_required` step

Early versions of the bot booked without asking about extras, leading to clients calling back
to add a color treatment after a cut. The extras loop was added to capture compound appointments
in one flow. It is deliberately one question per turn (not a list) to keep the conversation
feeling natural.

---

## `category_mix_required` — why mixed appointments are not allowed in one booking

The salon schedules peluquería and estética in separate capacity buckets. A single `book`
call with services from both categories would either fail validation or double-count capacity.
The split-and-ask design is the correct workaround until the scheduling engine supports
cross-category appointments.
