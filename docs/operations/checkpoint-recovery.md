# Checkpoint Recovery Operations Guide

## Overview

Atrévete Bot uses Redis-backed LangGraph checkpointing to persist conversation state, enabling automatic recovery from agent crashes or restarts. This document provides operational guidance for monitoring, troubleshooting, and manually recovering from checkpoint-related issues.

## Architecture

### Checkpoint System Components

1. **Redis Backend**: In-memory storage with RDB persistence
2. **LangGraph AsyncRedisSaver**: Handles checkpoint serialization/deserialization
3. **Automatic Checkpointing**: State saved after each node execution
4. **TTL Management**: 24-hour expiration for automatic cleanup

### Key Patterns

- **Checkpoint Keys**: `langgraph:checkpoint:{thread_id}:{checkpoint_ns}:*`
- **Example**: `langgraph:checkpoint:wa-msg-abc123:default:checkpoint_id`
- **Thread ID**: Maps to `conversation_id` in ConversationState
- **Checkpoint Namespace**: Usually "default" for standard conversations

## Normal Operation

### Automatic Recovery Process

When the agent container restarts:

1. Agent loads checkpointer configuration on startup
2. When a conversation resumes, LangGraph automatically:
   - Queries Redis for latest checkpoint using `thread_id`
   - Deserializes checkpoint state
   - Resumes conversation from last known state
3. **No manual intervention required**

### Expected Behavior

- **Successful Recovery**: Conversation continues seamlessly after restart
- **No Data Loss**: All messages within 24-hour window preserved
- **Checkpoint Save Frequency**: After each node execution (automatic)
- **Redis Persistence**: RDB snapshots every 15 minutes

## Monitoring

### Health Checks

#### 1. Verify Redis is Running

```bash
# Check Redis container status
docker compose ps redis

# Ping Redis
docker compose exec redis redis-cli ping
# Expected: PONG
```

#### 2. Check Checkpoint Storage

```bash
# Count active checkpoints
docker compose exec redis redis-cli DBSIZE
# Shows total keys in Redis (includes checkpoints + pub/sub data)

# List checkpoint keys (sample)
docker compose exec redis redis-cli --scan --pattern "langgraph:checkpoint:*" | head -10
```

#### 3. Monitor Redis Memory Usage

```bash
# Check memory stats
docker compose exec redis redis-cli INFO memory | grep used_memory_human

# Check for memory pressure
docker compose exec redis redis-cli INFO stats | grep evicted_keys
# Should be 0 (no evictions with RDB persistence)
```

### Key Metrics to Track

| Metric | Command | Healthy Range |
|--------|---------|---------------|
| Checkpoint Count | `redis-cli DBSIZE` | Varies (1-1000s depending on traffic) |
| Memory Usage | `redis-cli INFO memory \| grep used_memory_human` | < 1GB for MVP |
| Evicted Keys | `redis-cli INFO stats \| grep evicted_keys` | 0 (no evictions) |
| RDB Last Save Time | `redis-cli LASTSAVE` | < 900 seconds (15 min) |

## Troubleshooting

### Issue 1: Agent Fails to Resume Conversation

**Symptoms**:
- Agent starts fresh conversation instead of resuming
- Logs show "No checkpoint found for thread_id"

**Diagnosis**:
```bash
# Check if checkpoint exists for conversation
docker compose exec redis redis-cli KEYS "langgraph:checkpoint:wa-msg-{id}:*"
```

**Possible Causes**:
1. Checkpoint expired (>24 hours old) → Expected behavior
2. Redis was restarted and RDB not saved → Data loss
3. Wrong `thread_id` used in graph invocation → Check logs

**Resolution**:
- If >24h: Conversation should be archived to PostgreSQL (Story 2.5c)
- If recent: Check Redis RDB file exists: `docker compose exec redis ls -lh /data/dump.rdb`
- If missing: Redis crashed before RDB save → Up to 15 min data loss (acceptable for MVP)

### Issue 2: Redis Out of Memory

**Symptoms**:
- Redis logs: "OOM command not allowed when used memory > 'maxmemory'"
- Agent fails to save checkpoints

**Diagnosis**:
```bash
# Check memory limit
docker compose exec redis redis-cli CONFIG GET maxmemory

# Check current usage
docker compose exec redis redis-cli INFO memory | grep used_memory_human
```

**Resolution**:
```bash
# Increase Redis memory limit (temporary)
docker compose exec redis redis-cli CONFIG SET maxmemory 2gb

# Permanent fix: Update docker-compose.yml
# Add to redis service:
#   environment:
#     - REDIS_MAXMEMORY=2gb
#     - REDIS_MAXMEMORY_POLICY=volatile-ttl  # Evict expired keys first

# Restart Redis
docker compose restart redis
```

### Issue 3: Corrupted Checkpoint Data

**Symptoms**:
- Agent fails to load checkpoint
- Logs: "Error deserializing checkpoint" or similar

**Diagnosis**:
```bash
# Retrieve checkpoint data (binary)
docker compose exec redis redis-cli --raw GET "langgraph:checkpoint:{thread_id}:{checkpoint_ns}:{id}"
```

**Resolution**:
```bash
# Delete corrupted checkpoint (forces fresh start)
docker compose exec redis redis-cli DEL "langgraph:checkpoint:{thread_id}:*"

# Restart agent to clear cache
docker compose restart agent
```

**Note**: This causes data loss for that conversation. Customer must restart conversation.

### Issue 4: High Checkpoint Count (Memory Pressure)

**Symptoms**:
- Redis memory usage growing unbounded
- Checkpoint TTL not expiring old keys

**Diagnosis**:
```bash
# Count checkpoints
docker compose exec redis redis-cli --scan --pattern "langgraph:checkpoint:*" | wc -l

# Check if TTL is set on checkpoints
docker compose exec redis redis-cli TTL "langgraph:checkpoint:{sample_thread_id}:*"
# Should return seconds remaining (max 86400 for 24h)
```

**Resolution**:
```bash
# If TTL is -1 (no expiration), checkpoints were created without TTL
# This is a bug - verify checkpointer configuration includes TTL

# Manual cleanup of old checkpoints (emergency)
docker compose exec redis redis-cli --eval cleanup_old_checkpoints.lua

# cleanup_old_checkpoints.lua (create this script):
# for _,k in ipairs(redis.call('keys', 'langgraph:checkpoint:*')) do
#   if redis.call('ttl', k) == -1 then
#     redis.call('expire', k, 86400)
#   end
# end
```

## Manual Recovery Procedures

### Procedure 1: Force Checkpoint Cleanup

**When to Use**: Redis memory full, need to purge old conversations

```bash
# Backup Redis data first
docker compose exec redis redis-cli BGSAVE

# Delete all checkpoints older than 24h (automatic via TTL, but can force)
docker compose exec redis redis-cli --scan --pattern "langgraph:checkpoint:*" | xargs docker compose exec redis redis-cli DEL

# Restart agent
docker compose restart agent
```

### Procedure 2: Inspect Checkpoint Contents (Debugging)

```bash
# List checkpoints for a conversation
docker compose exec redis redis-cli KEYS "langgraph:checkpoint:wa-msg-abc123:*"

# Retrieve checkpoint metadata (if using LangGraph's structured format)
# Note: Checkpoint data is binary, use Redis insight or custom script to decode

# Check checkpoint size
docker compose exec redis redis-cli MEMORY USAGE "langgraph:checkpoint:wa-msg-abc123:default:checkpoint_id"
```

### Procedure 3: Restore from RDB Backup

**When to Use**: Redis data loss, need to restore from RDB snapshot

```bash
# Stop Redis
docker compose stop redis

# Copy backup RDB file to Redis volume
docker cp backup_dump.rdb atrevete-redis:/data/dump.rdb

# Start Redis (will load from dump.rdb)
docker compose start redis

# Verify data restored
docker compose exec redis redis-cli DBSIZE
```

## Backup Strategy

### RDB Snapshots

- **Frequency**: Every 15 minutes (configured in docker-compose.yml)
- **Location**: `/data/dump.rdb` inside Redis container
- **Persistence**: Stored in Docker volume `redis_data`

### Manual Backup

```bash
# Trigger immediate snapshot
docker compose exec redis redis-cli BGSAVE

# Wait for completion
docker compose exec redis redis-cli LASTSAVE

# Copy RDB file to host
docker cp atrevete-redis:/data/dump.rdb ./backups/redis_dump_$(date +%Y%m%d_%H%M%S).rdb
```

### Backup Rotation

Recommended schedule:
- **Hourly**: Keep last 24 hours (manual or via cron)
- **Daily**: Keep last 7 days
- **Weekly**: Keep last 4 weeks

```bash
# Example cron job (add to host crontab)
0 * * * * docker cp atrevete-redis:/data/dump.rdb /backups/redis/hourly/dump_$(date +\%H).rdb
0 0 * * * docker cp atrevete-redis:/data/dump.rdb /backups/redis/daily/dump_$(date +\%Y\%m\%d).rdb
```

## Related Systems

### PostgreSQL Archival (Story 2.5c)

- Conversations older than 24 hours archived to PostgreSQL
- Redis checkpoints automatically expire via TTL
- Long-term conversation history queryable from PostgreSQL

### Monitoring Integration (Epic 7)

- BetterStack/Grafana dashboards for Redis metrics
- Alerts on:
  - Redis memory > 80%
  - Checkpoint save failures
  - Redis container restarts

## FAQ

### Q: What happens if Redis crashes?

**A**: Up to 15 minutes of conversation data may be lost (since last RDB snapshot). Agent will start fresh conversations after restart. For critical conversations, consider reducing RDB snapshot interval.

### Q: Can I clear all checkpoints?

**A**: Yes, but this will reset all conversations. Use:
```bash
docker compose exec redis redis-cli FLUSHDB
```
**Warning**: Only do this in non-production environments.

### Q: How do I migrate checkpoints to a new Redis instance?

**A**:
1. Stop agent: `docker compose stop agent`
2. Backup RDB from old Redis: `docker cp old-redis:/data/dump.rdb ./dump.rdb`
3. Copy to new Redis: `docker cp ./dump.rdb new-redis:/data/dump.rdb`
4. Start new Redis: `docker compose start redis`
5. Start agent: `docker compose start agent`

### Q: Why do checkpoints expire after 24 hours?

**A**: To prevent unbounded Redis memory growth. Conversations older than 24h are archived to PostgreSQL (Story 2.5c) for long-term storage and remain queryable.

## Support Escalation

If issues persist after following troubleshooting steps:

1. Collect diagnostic info:
   ```bash
   docker compose logs redis > redis_logs.txt
   docker compose logs agent > agent_logs.txt
   docker compose exec redis redis-cli INFO > redis_info.txt
   ```

2. Check checkpoint configuration in `agent/state/checkpointer.py`

3. Escalate to development team with logs and description

---

**Document Version**: 1.0
**Last Updated**: 2025-10-28
**Author**: Dev Agent (Story 2.5a)
**Related Stories**: Epic 2, Story 2.5a, 2.5b, 2.5c
