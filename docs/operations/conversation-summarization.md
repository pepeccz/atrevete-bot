# Conversation Summarization Strategy

## Overview

The conversation summarization system automatically compresses older messages to prevent token overflow and maintain manageable context size for Claude API calls. This enables long conversations (30+ messages) without losing critical booking context.

**Story Reference:** Story 2.5b - Conversation Summarization with Claude

## Architecture

### Component Interaction

```
User Message (21st message)
    ↓
add_message() → increments total_message_count
    ↓
Conversation Flow Graph → checks should_summarize()
    ↓
summarize_conversation node → calls Claude to compress messages
    ↓
Updated State → conversation_summary field populated
    ↓
Redis Checkpoint → persists summary + total_message_count
    ↓
Future LLM calls → include summary as context
```

### Summarization Strategy

The system uses a two-tier memory management approach:

1. **FIFO Windowing (Story 2.5a)**: Recent 10 messages retained in full
2. **Summarization (Story 2.5b)**: Messages beyond 10 compressed into summary
3. **Combined Context**: system_prompt + conversation_summary + recent 10 messages

### Trigger Frequency

- **Triggers:** Every 10 messages after first 10 (at message counts 20, 30, 40, 50, etc.)
- **Rationale:** With 10-message windowing, summarizing every 10 prevents thrashing
- **Tracking:** `total_message_count` field tracks ALL messages (including removed ones)

Example timeline:
- Messages 1-10: No summarization (building initial context)
- Message 20: **First summarization** (compress messages 1-10)
- Message 30: **Second summarization** (compress messages 11-20, combine with first summary)
- Message 40: **Third summarization** (compress messages 21-30, combine with previous)

## Summarization Prompt

The system uses a Spanish language prompt optimized for booking context:

**Focuses on:**
- Customer identity (name, returning status)
- Current intent (booking, modification, cancellation)
- Decisions made (services, date/time, payment status)
- Pending actions (awaiting payment, confirmation, etc.)

**Omits:**
- Conversational pleasantries
- Resolved questions
- Redundant confirmations

**Output:** 2-3 sentence summary in Spanish (~100-200 tokens)

**Template Location:** `agent/prompts/summarization_prompt.md`

## Token Management

### Token Budget

- **Claude Sonnet 4 Context Limit:** 200,000 tokens
- **Warning Threshold:** 140,000 tokens (70%)
- **Critical Threshold:** 180,000 tokens (90%)

### Token Estimation Formula

```python
total_tokens = system_prompt + summary + recent_messages
            = 500 + (summary_words * 1.3) + (message_words * 1.3)
```

Rough approximation: 1 word ≈ 1.3 tokens (English/Spanish average)

### Overflow Protection

#### Level 1: Aggressive Summarization (>70% tokens)
- **Trigger:** Token count exceeds 140,000
- **Action:** Reduce recent messages from 10 → 5
- **Effect:** Compress more context, free up tokens

#### Level 2: Escalation (>90% tokens)
- **Trigger:** Token count exceeds 180,000 (even after aggressive summarization)
- **Action:** Flag conversation for human takeover
- **Reason:** Conversation too complex for automated handling

### Typical Token Usage

| Scenario | Messages | Summary | Total Tokens |
|----------|----------|---------|--------------|
| Short conversation | 10 | None | ~800 |
| Medium conversation | 30 | ~200 tokens | ~1,200 |
| Long conversation | 50+ | ~400 tokens | ~2,000 |
| Very long conversation | 100+ | ~800 tokens | ~3,500 |

## State Fields

### New Fields (Story 2.5b)

| Field | Type | Purpose | Default |
|-------|------|---------|---------|
| `conversation_summary` | `str \| None` | Compressed history beyond recent 10 messages | `None` |
| `total_message_count` | `int` | Total messages sent (including summarized) | `0` |

### Checkpoint Persistence

Both fields are automatically persisted to Redis checkpoints via LangGraph's `AsyncRedisSaver`.

- **Key Pattern:** `langgraph:checkpoint:{thread_id}:{checkpoint_ns}`
- **TTL:** 24 hours (86400 seconds)
- **Crash Recovery:** Summary and count restored when resuming conversation

## Monitoring

### Key Metrics to Track

1. **Summarization Frequency**
   - Log event: "Summarization triggered at {total_message_count} messages"
   - Indicates conversation length distribution

2. **Summary Length**
   - Track `len(conversation_summary)` in characters
   - Alerts if summaries grow too long (>1000 chars)

3. **Token Overflow Events**
   - Warning logs: "Token overflow warning for conversation {id}"
   - Error logs: "Critical token overflow for conversation {id}"
   - Indicates need for tuning

4. **Escalation Rate**
   - Count of `escalation_reason: "token_overflow"`
   - High rate indicates summarization strategy needs adjustment

### Monitoring Queries (Example)

```bash
# Count summarization triggers in last hour
grep "Summarization triggered" /var/log/atrevete/agent.log | grep "$(date -d '1 hour ago' +%Y-%m-%d)" | wc -l

# Find conversations with token overflow
grep "Token overflow warning" /var/log/atrevete/agent.log | tail -n 20

# Check average summary length
grep "summary length:" /var/log/atrevete/agent.log | awk '{print $NF}' | awk '{sum+=$1; count++} END {print sum/count}'
```

## Troubleshooting

### Problem: Summary Quality is Poor

**Symptoms:**
- Claude loses context in long conversations
- Customers have to repeat information
- Booking details get lost

**Solutions:**
1. Review prompt template (`agent/prompts/summarization_prompt.md`)
2. Adjust temperature (currently 0.3 for determinism)
3. Increase max tokens from 300 → 500 for longer summaries
4. Test with sample conversations to validate output

### Problem: Token Overflow Frequent

**Symptoms:**
- Many "Token overflow warning" logs
- Aggressive summarization triggers often
- Escalations with reason "token_overflow"

**Solutions:**
1. Reduce message windowing from 10 → 8 messages
2. Trigger summarization earlier (every 8 messages instead of 10)
3. Make summarization more aggressive (shorter summaries)
4. Review conversations to identify common patterns causing overflow

### Problem: Claude API Failures

**Symptoms:**
- "Summarization failed for conversation {id}" errors
- Summaries not created despite trigger

**Solutions:**
1. Check Claude API status (https://status.anthropic.com)
2. Verify API key configuration (`ANTHROPIC_API_KEY`)
3. Review rate limits and quotas
4. Check network connectivity to Anthropic API

**Graceful Degradation:**
- System continues without summarization on API failure
- Conversation proceeds with full message history
- May hit token limits later in very long conversations

### Problem: Conversations Not Resuming After Crash

**Symptoms:**
- Redis checkpoints not restoring summary
- `total_message_count` resets to 0 after restart

**Solutions:**
1. Verify Redis is running and accessible
2. Check Redis TTL settings (should be 24 hours)
3. Ensure checkpointer is configured in graph creation
4. Review Redis logs for connection errors

**Verification:**
```bash
# Check Redis for checkpoint keys
redis-cli KEYS "langgraph:checkpoint:*"

# Verify TTL on checkpoints
redis-cli TTL "langgraph:checkpoint:{thread_id}:{checkpoint_ns}"
```

## Configuration Tuning

### Adjusting Summarization Frequency

**File:** `agent/state/helpers.py` → `should_summarize()`

```python
# Current: triggers every 10 messages after first 10
should_trigger = (total_message_count % 10 == 0 and total_message_count > 10)

# More frequent (every 8 messages):
should_trigger = (total_message_count % 8 == 0 and total_message_count > 8)

# Less frequent (every 15 messages):
should_trigger = (total_message_count % 15 == 0 and total_message_count > 15)
```

### Adjusting Message Window Size

**File:** `agent/state/helpers.py` → `MAX_MESSAGES`

```python
# Current: keep 10 recent messages
MAX_MESSAGES = 10

# Smaller window (better for short conversations):
MAX_MESSAGES = 8

# Larger window (better for complex conversations):
MAX_MESSAGES = 12
```

### Adjusting Token Thresholds

**File:** `agent/state/helpers.py` → `check_token_overflow()`

```python
# Current thresholds
WARNING_THRESHOLD = int(CONTEXT_LIMIT * 0.70)  # 140,000 tokens
CRITICAL_THRESHOLD = int(CONTEXT_LIMIT * 0.90)  # 180,000 tokens

# More conservative (trigger earlier):
WARNING_THRESHOLD = int(CONTEXT_LIMIT * 0.60)  # 120,000 tokens
CRITICAL_THRESHOLD = int(CONTEXT_LIMIT * 0.80)  # 160,000 tokens

# Less conservative (allow more context):
WARNING_THRESHOLD = int(CONTEXT_LIMIT * 0.80)  # 160,000 tokens
CRITICAL_THRESHOLD = int(CONTEXT_LIMIT * 0.95)  # 190,000 tokens
```

## Related Documentation

- **Story 2.5a:** Redis Checkpointing & Message Memory (FIFO windowing)
- **Story 2.5c:** Conversation Archival (long-term storage)
- **Architecture:** `docs/architecture/backend-architecture.md#10.1.1` (State Management)
- **Tech Stack:** `docs/architecture/tech-stack.md#3.1` (Claude Sonnet 4 specs)

## Implementation References

| Component | File Location |
|-----------|--------------|
| Summarization Node | `agent/nodes/summarization.py` |
| Helper Functions | `agent/state/helpers.py` |
| State Schema | `agent/state/schemas.py` |
| Prompt Template | `agent/prompts/summarization_prompt.md` |
| Graph Integration | `agent/graphs/conversation_flow.py` |
| Unit Tests | `tests/unit/test_conversation_summarization.py` |
| Integration Tests | `tests/integration/test_long_conversation_summarization.py` |

## FAQ

**Q: Why trigger every 10 messages and not every 5?**
A: With 10-message windowing, triggering every 5 would cause thrashing (summarizing messages still in the window). Every 10 ensures we summarize only removed messages.

**Q: What happens if summarization fails?**
A: Graceful degradation - conversation continues with full message history. System may hit token limits later in very long conversations.

**Q: Can I disable summarization?**
A: Not recommended. For very short conversations (<20 messages), summarization doesn't trigger anyway. For long conversations, disabling would cause token overflow.

**Q: How do I test summarization locally?**
A: Run integration test: `pytest tests/integration/test_long_conversation_summarization.py -v`

**Q: What's the cost impact of summarization?**
A: Minimal. Each summarization = 1 Claude API call (~200 tokens output). For a 50-message conversation, cost is ~2 summarization calls vs. sending all 50 messages repeatedly.

---

**Last Updated:** 2025-10-28
**Author:** James (Dev Agent)
**Story:** 2.5b - Conversation Summarization with Claude
