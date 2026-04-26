# VCR Cassettes — Refresh Policy

## When to re-record

Re-record cassettes when any of these files change in a way that affects
the LLM request/response contract:

- `agent/prompts/shared/booking_flow.md`
- `agent/prompts/shared/tools_contract.md`
- `agent/prompts/shared/critical_rules.md`
- `agent/prompts/catalog_builder.py`
- `agent/tools/update_booking.py`
- `agent/tools/check_availability.py`
- `agent/tools/book.py`
- `agent/tools/next_steps.py`
- `agent/tools/schemas.py`

## How to re-record

```bash
OPENROUTER_API_KEY=<real_key> \
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
./venv/bin/pytest tests/integration/test_booking_flow_real_llm.py \
  --record-mode=rewrite -v
```

Or use the helper script:

```bash
OPENROUTER_API_KEY=<real_key> ./scripts/refresh_booking_cassettes.sh
```

## Default (CI) mode

Cassettes play back in `record_mode="none"` — the test fails if a cassette
is missing or the request does not match. This prevents silent network calls in CI.

## Directory layout

```
cassettes/
  booking/
    s1_advance_policy.yaml
    s2_nada_mas_loop_break.yaml
    s3_one_shot_all_slots.yaml
    s4_off_topic_faq_mid_booking.yaml
    s5_confirmation_gate.yaml
```
