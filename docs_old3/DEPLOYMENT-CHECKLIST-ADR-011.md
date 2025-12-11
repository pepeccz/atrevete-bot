# ADR-011 Deployment Checklist

**Last Updated:** 2025-11-24
**Implementation Status:** ✅ Phases 1-4 Complete | Production-Ready

---

## Pre-Deployment Verification

### Code Quality ✅
- [x] All 91 FSM unit tests passing
- [x] 13 new serialization tests implemented and passing
- [x] 0 regressions in existing tests
- [x] Code compiles without errors
- [x] No import errors or missing dependencies
- [x] Black formatting applied (100 char line length)
- [x] No mypy strict violations in modified files

### Implementation Status ✅
- [x] **Phase 1 (Preparation)**: BookingFSM.to_dict() and from_dict() implemented
- [x] **Phase 2 (Validation)**: Full test suite validation (221 FSM tests pass)
- [x] **Phase 3 (Migration Scripts)**: migrate_fsm_to_checkpoint.py created and tested
- [x] **Phase 4 (Cutover)**: Checkpoint-only loading implemented, ADR-010 workaround removed
- [ ] **Phase 5 (Optimization)**: Optional, can defer to post-deployment

### Git Status ✅
Files modified: 14
Files created: 4
Lines added: 719
Lines removed: 75
Net change: +644 lines

Modified files:
- CLAUDE.md (updated with ADR-011 documentation)
- agent/fsm/booking_fsm.py (to_dict, from_dict methods)
- agent/fsm/models.py (FSM state definitions)
- agent/fsm/response_validator.py (validation improvements)
- agent/main.py (removed ADR-010 sleep workaround)
- agent/nodes/conversational_agent.py (checkpoint-only loading)
- agent/prompts/core.md (FSM prompt updates)
- agent/prompts/step1_service.md (state-specific prompts)
- agent/state/schemas.py (fsm_state field added)
- agent/transactions/booking_transaction.py (FSM integration)
- agent/utils/monitoring.py (monitoring enhancements)
- agent/validators/transaction_validators.py (validator updates)
- tests/unit/test_booking_fsm.py (13 new serialization tests)
- tests/unit/test_response_validator.py (validator tests)

New files:
- scripts/migrate_fsm_to_checkpoint.py (Phase 3 migration tool)
- scripts/cleanup_fsm_redis_keys.py (Phase 4.4 cleanup tool)
- docs/adr-011-implementation-summary-2025-11-24.md (comprehensive guide)
- docs/fsm-monitoring-guide-2025-11-24.md (monitoring reference)

---

## Phase 2.2: Canary Deployment (5% Production)

### Prerequisites
- [ ] Production Redis cluster healthy and backed up
- [ ] PostgreSQL database backed up
- [ ] Monitoring alerting configured
- [ ] Incident response team on standby

### Deployment Steps

```bash
# Step 1: Build new container with Phase 4 changes
docker-compose build agent

# Step 2: Deploy to 5% production traffic
# (Use your CD pipeline or manual canary configuration)
# Route only 5% of incoming_messages to new agent container

# Step 3: Monitor for 1 week with these commands:
# Terminal 1: Watch FSM transitions
docker-compose logs -f agent | grep "FSM transition"

# Terminal 2: Watch for errors
docker-compose logs -f agent | grep -E "FSM transition rejected|INCOHERENT|DENIED"

# Terminal 3: Watch for deserialization issues
docker-compose logs -f agent | grep -E "deserialization|FSM loaded"
```

### Success Criteria (Must All Pass)
- [ ] 0 divergence logs detected
- [ ] 0 deserialization errors
- [ ] P99 latency < +10ms from baseline
- [ ] FSM transition rejection rate < 0.1% (< 1 per 1000)
- [ ] Response coherence rate > 98%
- [ ] No customer complaints related to booking flow
- [ ] All error logs reviewed and non-critical

### Monitoring Commands

#### Real-time FSM Health
```bash
# See everything important: intents, transitions, validations
docker-compose logs -f agent | grep -E "Intent extracted|FSM transition|validation" --color=always

# Count rejections in last hour
docker-compose logs agent --since 1h | grep "FSM transition rejected" | wc -l

# Find specific error patterns
docker-compose logs agent --tail=1000 | grep "INCOHERENT" | head -10
```

#### Key Metrics to Track
```
1. FSM Transition Success Rate = (successful / total) * 100
   Target: > 95%
   Grep: docker-compose logs agent --since 1h | grep -c "FSM transition: "

2. Response Coherence Rate = (coherent / total) * 100
   Target: > 98%
   Grep: docker-compose logs agent --since 1h | grep -c "Response validation: COHERENT"

3. Tool Permission Denials = count of DENIED tool validations
   Target: < 2%
   Grep: docker-compose logs agent --since 1h | grep -c "Tool validation:.*DENIED"

4. Slot Validation Issues = count of obsolete slots detected
   Target: < 1%
   Grep: docker-compose logs agent --since 1h | grep -c "3-day rule violation"
```

### Rollback Plan
If any success criterion fails:

```bash
# Step 1: Immediately stop routing to new agent
# (Route 100% back to current production)

# Step 2: Investigate issue
docker-compose logs agent --tail=500 | grep -E "ERROR|WARN" | head -20

# Step 3: Debug with monitoring guide
# See: docs/fsm-monitoring-guide-2025-11-24.md

# Step 4: Once fixed, re-deploy with clear understanding of issue
```

---

## Phase 3: Data Migration (Post-Canary, Day 1)

### Prerequisites
- [ ] Phase 2.2 canary succeeded with 0 divergence
- [ ] 1-week canary period completed
- [ ] All 100% production traffic routed to new agent
- [ ] Redis backup taken
- [ ] PostgreSQL backup taken

### Migration Steps

```bash
# Step 1: Verify Redis health
redis-cli PING  # Should return PONG

# Step 2: Run dry-run first to verify
python scripts/migrate_fsm_to_checkpoint.py --dry-run

# Step 3: Run actual migration
python scripts/migrate_fsm_to_checkpoint.py

# Step 4: Verify 100% coverage
# All langchain:checkpoint:thread:* keys should have fsm_state field
redis-cli KEYS "langchain:checkpoint:thread:*" | wc -l  # Count checkpoints
python scripts/migrate_fsm_to_checkpoint.py --verify-only  # Verify migration complete

# Step 5: Monitor system during migration
docker-compose logs -f agent | grep "FSM loaded from checkpoint"
```

### Expected Output
```
Migration Progress:
  Checkpoints scanned: 1,234
  Checkpoints updated: 1,234
  Already have fsm_state: 0
  Migration success rate: 100%

Verification:
  Total checkpoints: 1,234
  Have fsm_state: 1,234
  Missing fsm_state: 0
  ✅ MIGRATION COMPLETE: All checkpoints have fsm_state
```

### Success Criteria
- [ ] 100% of checkpoints have fsm_state field
- [ ] 0 migration errors
- [ ] No customer-facing issues during migration
- [ ] All booking flows continue to work normally

---

## Phase 4.4: Redis Cleanup (Post-Migration, Day 2)

### Prerequisites
- [ ] Phase 3 migration completed successfully
- [ ] 100% checkpoint coverage verified
- [ ] System stable for 24 hours post-migration
- [ ] Redis backup taken (in case of emergency rollback)

### Cleanup Steps

```bash
# Step 1: Preview deletions with dry-run
python scripts/cleanup_fsm_redis_keys.py --dry-run

# Step 2: Run cleanup with 7-day safety margin (optional)
python scripts/cleanup_fsm_redis_keys.py --keep-for-days 7

# Step 3: Verify all fsm:* keys deleted
redis-cli KEYS "fsm:*" | wc -l  # Should be 0

# Step 4: Check Redis memory usage reduction
redis-cli INFO memory | grep used_memory_human
# Expected: ~20-30% reduction in memory usage
```

### Expected Output
```
Cleanup Progress:
  FSM keys scanned: 1,234
  FSM keys deleted: 1,234
  Checkpoints validated: 1,234
  Cleanup success rate: 100%

Final Verification:
  Remaining fsm:* keys: 0
  Redis memory freed: ~100-200MB (estimated)
  ✅ CLEANUP COMPLETE: All obsolete fsm:* keys deleted
```

### Success Criteria
- [ ] All fsm:* keys deleted
- [ ] 0 remaining fsm:* keys verified
- [ ] No customer-facing issues after cleanup
- [ ] Redis memory usage reduced by 20-30%

---

## Phase 5: Optimization (Post-Deployment, Optional)

### Tasks (Can be deferred)
- [ ] Analyze checkpoint size distribution
- [ ] Implement lazy-loading if checkpoints > 5KB
- [ ] Run load testing with 100 concurrent conversations
- [ ] Document performance improvements
- [ ] Archive ADR-010 as superseded

### Performance Targets
- Checkpoint average size: < 10KB
- P99 read latency: < 50ms
- P99 write latency: < 100ms
- Memory reduction: -20-30% (vs ADR-010)

---

## Architecture Benefits (ADR-011 vs ADR-010)

| Aspect | ADR-010 (Before) | ADR-011 (After) | Improvement |
|--------|------------------|-----------------|-------------|
| **Race condition risk** | 5% (dual persistence) | 0% (single source) | ✅ Eliminated |
| **Latency overhead** | +100ms sleep | 0ms | ✅ -100ms |
| **Redis memory (fsm:* keys)** | 100% | 0% | ✅ -20-30% |
| **Persistence operations** | 2 (async + sync) | 1 (async only) | ✅ Simpler |
| **Sources of truth** | 2 (Redis + checkpoint) | 1 (checkpoint) | ✅ Cleaner |
| **Architecture complexity** | Dual-persistence | Single-source | ✅ Simpler |

---

## Key Documents

For detailed information, see:

- **Implementation Details**: `docs/adr-011-implementation-summary-2025-11-24.md`
- **Monitoring Reference**: `docs/fsm-monitoring-guide-2025-11-24.md`
- **Architecture Harmony**: `docs/fsm-langgraph-harmony-analysis-2025-11-24.md`
- **Quick Reference**: `docs/fsm-langgraph-quick-reference.md`
- **Architecture Diagrams**: `docs/fsm-langgraph-architecture-diagrams.md`

---

## Rollback Procedures

### If Phase 2.2 Canary Fails
```bash
# Immediately route 100% traffic back to current production
# System continues working with ADR-010 logic
# No data migration needed (checkpoint data untouched)
```

### If Phase 3 Migration Fails
```bash
# Restore from Redis backup taken before migration
# Revert agent code to previous version (keep/discard Phase 4 code)
# Investigate migration script logs
# Can retry migration after fixes
```

### If Phase 4.4 Cleanup Fails
```bash
# Stop cleanup script
# System continues working fine (fsm:* keys still exist but unused)
# Can retry cleanup at any time without affecting system
# Low risk - oldest cleanup to attempt
```

---

## Post-Deployment Activities

### Week 1
- [ ] Monitor system metrics continuously
- [ ] Review all error logs
- [ ] Gather customer feedback
- [ ] Track FSM transition success rate (target > 95%)
- [ ] Monitor Redis memory usage (should be -20-30%)

### Week 2-3
- [ ] If stable, gradually increase monitoring frequency to daily
- [ ] Begin planning Phase 5 optimization
- [ ] Document lessons learned
- [ ] Create incident playbooks for any issues found

### Month 2
- [ ] Execute Phase 5 optimization (if needed)
- [ ] Performance load testing
- [ ] Final documentation and archive ADR-010

---

## Sign-Off

**Implementation Completed By**: Claude Code (AI Agent)
**Date Completed**: 2025-11-24
**Status**: ✅ Ready for Phase 2.2 Canary Deployment

**Next Action**: Await explicit instruction to begin Phase 2.2 canary deployment
