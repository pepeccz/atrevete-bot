# VCR Cassettes — Booking Real-LLM Scenarios

## Current status (2026-04-27)

**Cassettes recorded**: 5/5 against real GPT-5.4-mini on production server.
**Tests skipped**: ALL via module-level `pytestmark = pytest.mark.skip(...)`.
**Reason**: VCR playback determinism unsolved.

During recording, S2 and S3 reached PASS assertions; S1/S4/S5 surfaced behavior
that needed prompt tweaks (`fix(prompt)` commits in branch). All 5 cassettes
are committed as evidence of the captured real-LLM behavior.

Playback (`--record-mode=none`) hangs because OpenRouter request bodies vary
across runs (token IDs, message ordering nuances) and our matchers — including
the custom `json_body` matcher in `conftest.py` — cannot reliably re-match
captured cassette bodies against fresh requests.

## Follow-up (separate PR)

Three candidate paths:

1. **Call-index matcher**: replace body matching with deterministic
   "first request → first response, second → second" by-position replay.
2. **Replace pytest-recording**: write a thin response-replay shim that ignores
   request bodies entirely. Simplest, least general.
3. **Debug request body divergence**: capture which keys differ across runs
   (suspect `seed`, `tool_choice` defaults, LangChain message metadata) and
   strip them in `before_record_request`.

The architecture work (tool contract, prompt simplification, helpers) is
complete and ships in this PR. The VCR test gate is infrastructure-only and
isolated to `tests/integration/test_booking_real_llm.py`.

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

## How to re-record (server only — needs real OpenRouter key + DB)

```bash
ssh pepe@server
cd /home/pepe/Proyectos/atrevete-bot
docker run --rm \
  --network=atrevete-bot_atrevete-network \
  --env-file .env \
  -v $(pwd):/app \
  --entrypoint bash atrevete-bot-agent \
  -c 'pip install -q pytest-recording && pytest tests/integration/test_booking_real_llm.py --record-mode=rewrite -v -o addopts='
```

Then commit + push the regenerated cassettes.

## Directory layout

```
cassettes/
  test_booking_real_llm/
    test_s1_advance_policy_violation.yaml
    test_s2_nada_mas_loop_break.yaml
    test_s3_one_shot_all_slots.yaml
    test_s4_off_topic_faq_mid_booking.yaml
    test_s5_confirmation_gate.yaml
```
