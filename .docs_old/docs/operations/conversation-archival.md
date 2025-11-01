# Conversation Archival Operations Guide

## Overview

The conversation archival worker is a background service that preserves customer interaction history beyond Redis's 24-hour TTL by archiving expired conversation checkpoints to PostgreSQL.

## Architecture

### Data Flow

```
Redis Checkpoint (TTL=24h)
    ↓ (hourly, age >23h)
Archive Worker
    ↓ (parse messages)
PostgreSQL conversation_history table
    ↓ (after successful insert)
Delete from Redis
```

### Worker Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| **Schedule** | Hourly at :00 | Runs every hour on the hour |
| **Cutoff Time** | 23 hours | Archives checkpoints older than this |
| **TTL Buffer** | 1 hour | Safety margin before 24h Redis expiration |
| **Retry Attempts** | 2 | Max attempts for database failures |
| **Retry Delay** | 5 seconds | Wait between retry attempts |
| **Timezone** | Europe/Madrid | All timestamp operations |

### Key Pattern

Redis checkpoint keys follow this pattern:
```
langgraph:checkpoint:{conversation_id}:{checkpoint_ns}
```

Example:
```
langgraph:checkpoint:wa-msg-abc123:1698765432
```

## TTL Strategy

### Why 23 Hours?

The archival worker runs every hour and archives checkpoints **older than 23 hours**. This provides:

- **1-hour buffer** before Redis TTL expiration (24h)
- **Race condition prevention** between archival and expiration
- **Guaranteed data preservation** before Redis auto-deletes checkpoints

### Timeline Example

| Time | Event |
|------|-------|
| T+0h | Conversation starts, checkpoint created in Redis (TTL=24h) |
| T+23h | Worker finds checkpoint (age >23h), archives to PostgreSQL |
| T+23h | Worker deletes checkpoint from Redis |
| T+24h | _(Would have expired, but already archived and deleted)_ |

## Monitoring

### Health Check File

**Location:** `/tmp/archiver_health.json`

**Format:**
```json
{
  "last_run": "2025-10-28T14:00:00+01:00",
  "status": "healthy",
  "checkpoints_archived": 12,
  "messages_archived": 143,
  "errors": 0
}
```

**Status Values:**
- `healthy`: All archival operations successful
- `unhealthy`: Errors occurred during archival

### Monitoring Alerts

Set up alerts for:

1. **Worker Health**
   - Alert if `last_run` > 90 minutes ago (worker stuck/crashed)
   - Check: `(now - last_run) > 90 minutes`
   - Action: Restart worker, investigate logs

2. **Error Rate**
   - Alert if `errors > 0` consistently
   - Check: `health_data['errors'] > 0`
   - Action: Review worker logs, check database connectivity

3. **Database Growth**
   - Monitor `conversation_history` table size
   - Alert if growth rate anomalous
   - Action: Review retention policy, consider archival

### Log Locations

**Docker Logs:**
```bash
docker-compose logs archiver
docker-compose logs -f archiver  # Follow mode
```

**Key Log Messages:**
- `Starting conversation archival run at {timestamp}` - Worker started
- `Found {count} expired checkpoints to archive` - Checkpoints identified
- `Completed archival run in {duration}s` - Worker finished
- `Failed to archive {conversation_id} after retry, skipping` - Permanent failure

## Troubleshooting

### Worker Not Running

**Symptoms:**
- `last_run` in health check > 90 minutes
- No recent logs

**Diagnosis:**
```bash
# Check if worker container is running
docker-compose ps archiver

# Check worker logs for crash
docker-compose logs --tail=100 archiver
```

**Resolution:**
```bash
# Restart worker
docker-compose restart archiver

# If persists, rebuild
docker-compose up -d --build archiver
```

### Database Connection Failures

**Symptoms:**
- Health check `status: unhealthy`
- Logs show `Redis connection failed` or database errors
- Checkpoints not being archived

**Diagnosis:**
```bash
# Check database connectivity from worker
docker-compose exec archiver ping data

# Check Redis connectivity
docker-compose exec archiver redis-cli -h redis ping

# Review connection error logs
docker-compose logs archiver | grep -i "connection"
```

**Resolution:**
1. Verify database container is running: `docker-compose ps data`
2. Check database credentials in `.env` file
3. Restart database: `docker-compose restart data`
4. Restart worker: `docker-compose restart archiver`

### Messages Missing from conversation_history

**Symptoms:**
- Expected conversation not in PostgreSQL
- Customer reports lost conversation history

**Diagnosis:**
```bash
# Check if checkpoint exists in Redis
docker-compose exec redis redis-cli KEYS "langgraph:checkpoint:*"

# Check worker logs for specific conversation_id
docker-compose logs archiver | grep "conversation-id-here"

# Query PostgreSQL for conversation
docker-compose exec data psql -U atrevete -d atrevete_db \
  -c "SELECT * FROM conversation_history WHERE conversation_id='conversation-id-here';"
```

**Common Causes:**
1. **Checkpoint malformed** - Worker logs show deserialization errors
2. **customer_id missing** - Check if early conversation (before identification)
3. **Worker failed during archival** - Check logs for errors at timestamp
4. **Checkpoint deleted before archival** - Race condition (rare)

**Prevention:**
- Monitor worker error logs
- Set up alerts for archival failures
- Consider reducing cutoff time to 22h (increases buffer)

### PostgreSQL Storage Full

**Symptoms:**
- Worker logs show database insertion errors
- Health check `status: unhealthy`
- High error count

**Diagnosis:**
```bash
# Check PostgreSQL disk usage
docker-compose exec data df -h

# Check conversation_history table size
docker-compose exec data psql -U atrevete -d atrevete_db \
  -c "SELECT pg_size_pretty(pg_total_relation_size('conversation_history'));"

# Count total messages
docker-compose exec data psql -U atrevete -d atrevete_db \
  -c "SELECT COUNT(*) FROM conversation_history;"
```

**Resolution:**
1. **Immediate:** Increase disk space
2. **Short-term:** Run retention cleanup (see Data Retention below)
3. **Long-term:** Implement automated retention policy

### Redis Checkpoint Overflow

**Symptoms:**
- Redis memory usage high
- Checkpoints older than 24h still present
- Worker logs show many expired checkpoints

**Diagnosis:**
```bash
# Check Redis memory usage
docker-compose exec redis redis-cli INFO memory

# Count checkpoints
docker-compose exec redis redis-cli KEYS "langgraph:checkpoint:*" | wc -l

# Check oldest checkpoint
docker-compose exec redis redis-cli KEYS "langgraph:checkpoint:*" | head -1
```

**Resolution:**
1. Verify worker is running: `docker-compose ps archiver`
2. Check worker can connect to Redis: `docker-compose logs archiver | grep -i redis`
3. Manual cleanup (if needed):
   ```bash
   # List old checkpoints
   docker-compose exec redis redis-cli --scan --pattern "langgraph:checkpoint:*"

   # Delete manually (use with caution!)
   docker-compose exec redis redis-cli DEL "langgraph:checkpoint:old-key-here"
   ```

## Data Retention

### Retention Policy Recommendations

| Data Type | Recommended Retention | Rationale |
|-----------|----------------------|-----------|
| **Active conversations** | 24 hours (Redis) | Real-time operations |
| **Recent history** | 30 days (PostgreSQL) | Customer support, debugging |
| **Long-term history** | 6 months (PostgreSQL) | Compliance, analytics |
| **Archived history** | Archive to cold storage or delete | Cost optimization |

### Manual Retention Cleanup

**Delete messages older than 6 months:**
```sql
DELETE FROM conversation_history
WHERE timestamp < NOW() - INTERVAL '6 months';
```

**Archive to cold storage before deletion:**
```bash
# Export conversations older than 6 months
docker-compose exec data pg_dump -U atrevete -d atrevete_db \
  --table=conversation_history \
  --where="timestamp < NOW() - INTERVAL '6 months'" \
  > archived_conversations_$(date +%Y%m%d).sql

# Then delete from database (after verifying export)
docker-compose exec data psql -U atrevete -d atrevete_db \
  -c "DELETE FROM conversation_history WHERE timestamp < NOW() - INTERVAL '6 months';"
```

### Automated Retention (Future Enhancement)

Consider implementing a separate retention worker:
- Runs daily/weekly
- Archives old messages to S3/cold storage
- Deletes messages beyond retention period
- Updates metadata table with archive locations

## Deployment

### Running the Worker

The archival worker runs as a separate Docker service:

```yaml
# docker-compose.yml
services:
  archiver:
    build:
      context: .
      dockerfile: docker/Dockerfile.agent
    command: python agent/workers/conversation_archiver.py
    depends_on:
      - data
      - redis
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    restart: unless-stopped
```

**Start worker:**
```bash
docker-compose up -d archiver
```

**View logs:**
```bash
docker-compose logs -f archiver
```

**Restart worker:**
```bash
docker-compose restart archiver
```

### Environment Variables

| Variable | Example | Required |
|----------|---------|----------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@data:5432/dbname` | Yes |
| `REDIS_URL` | `redis://redis:6379/0` | Yes |

### Deployment Checklist

- [ ] Environment variables configured in `.env`
- [ ] Worker container builds successfully
- [ ] Worker can connect to Redis
- [ ] Worker can connect to PostgreSQL
- [ ] Health check file location writable
- [ ] Monitoring alerts configured
- [ ] Log aggregation configured (if using)
- [ ] Tested manual restart procedure

## Performance Considerations

### Expected Load

| Metric | Typical Value | Notes |
|--------|---------------|-------|
| **Checkpoints/hour** | 10-100 | Depends on conversation volume |
| **Messages/checkpoint** | 5-50 | Average conversation length |
| **Archival duration** | 10-60 seconds | Depends on checkpoint count |
| **Database writes** | 50-5000/hour | Depends on message count |
| **Redis deletes** | 10-100/hour | Matches checkpoint count |

### Scaling Recommendations

**Low volume (<100 conversations/hour):**
- Single worker instance sufficient
- Default configuration adequate

**Medium volume (100-1000 conversations/hour):**
- Consider more frequent archival (every 30 minutes)
- Monitor database connection pool size
- Increase worker resources (CPU/memory)

**High volume (>1000 conversations/hour):**
- Run archival every 15-30 minutes
- Implement sharding by conversation_id hash
- Use dedicated archival database (read replica)
- Consider async bulk inserts

## Related Documentation

- **Story 2.5a:** Redis Checkpointing & Message Memory
- **Story 2.5b:** Conversation Summarization
- **Story 1.3b:** Transactional History Tables (database schema)
- **Epic 7 Story 7.7:** Monitoring & Observability

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review worker logs: `docker-compose logs archiver`
3. Check health status: `cat /tmp/archiver_health.json`
4. Escalate to engineering team with logs and context
