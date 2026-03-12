# Migration Guide: Prompt System Optimization v6.1

## Overview

This migration introduces the optimized prompt system for Atrévete Bot v6.1, featuring:

- **Modular shared prompts** in `agent/prompts/shared/`
- **Mode-specific prompts** in `agent/prompts/modes/`
- **Caching layer** with 10-minute TTL
- **Feature flag** for gradual rollout

## Changes Made

### 1. New Directory Structure

```
agent/prompts/
├── shared/                    # NEW: Reusable prompt components
│   ├── identity.md           # Bot personality and identity
│   ├── critical_rules.md     # Safety and formatting rules
│   ├── glossary.md          # Terminology definitions
│   └── recovery.md          # Error recovery instructions
├── modes/                    # EXISTING: Mode-specific prompts
│   ├── greeting.md
│   ├── booking.md
│   ├── general.md
│   └── escalation.md
├── legacy/                   # NEW: Archived step-based prompts
│   ├── step1_service.md
│   ├── step2_availability.md
│   ├── step3_customer.md
│   ├── step3_5_confirmation.md
│   ├── step4_booking.md
│   └── step5_post_booking.md
├── loader.py                 # NEW: Centralized prompt loading with caching
├── dynamic_context.py        # EXISTING: Context variable injection
└── __init__.py              # MODIFIED: Backward compatibility
```

### 2. New Files Created

| File | Purpose |
|------|---------|
| `agent/prompts/shared/identity.md` | Bot identity, tone, and personality |
| `agent/prompts/shared/critical_rules.md` | Safety rules and formatting guidelines |
| `agent/prompts/shared/glossary.md` | Terminology and definitions |
| `agent/prompts/shared/recovery.md` | Error recovery strategies |
| `agent/prompts/loader.py` | Prompt loading with caching (10min TTL) |
| `agent/prompts/legacy/*.md` | Archived step-based prompts |

### 3. Modified Files

| File | Changes |
|------|---------|
| `agent/prompts/__init__.py` | Added loader imports, backward compatibility |
| `CLAUDE.md` | Updated prompt system documentation |
| `.env.example` | Added `USE_OPTIMIZED_PROMPTS` flag |

### 4. Environment Variables

Add to `.env`:

```bash
# Feature flag for optimized prompt system
# Set to "true" to enable new prompt system
# Set to "false" to use legacy prompts (v6.0 behavior)
USE_OPTIMIZED_PROMPTS=true
```

## Rollback Instructions

### Quick Rollback (Immediate)

If issues are detected:

1. **Disable feature flag**:
   ```bash
   # Edit .env
   USE_OPTIMIZED_PROMPTS=false
   
   # Restart agent service
   docker-compose restart agent
   ```

2. **Verify legacy mode**:
   ```bash
   docker-compose logs -f agent | grep "prompt"
   ```
   Should show: "Using legacy prompt system"

### Full Rollback (Code)

If code-level rollback is needed:

1. Restore legacy prompt references in `agent/prompts/__init__.py`:
   - Uncomment `STEP_PROMPTS` dictionary
   - Restore `load_step_prompt()` function

2. Move prompts back from legacy/:
   ```bash
   mv agent/prompts/legacy/*.md agent/prompts/
   ```

3. Restart services:
   ```bash
   docker-compose restart agent api
   ```

## Verification Steps

### Pre-Deployment

- [ ] All unit tests pass: `pytest tests/unit/test_prompt_loader.py -v`
- [ ] All integration tests pass: `pytest tests/integration/test_prompts.py -v`
- [ ] Feature flag is set in production `.env`
- [ ] Legacy prompts are in `agent/prompts/legacy/` (not deleted)
- [ ] No broken imports: `python -c "from agent.prompts import get_system_prompt"`

### Post-Deployment

- [ ] Agent starts without errors: `docker-compose logs agent | tail -20`
- [ ] Prompt cache is working: `docker-compose logs agent | grep "cache hit"`
- [ ] Response quality is maintained (spot-check conversations)
- [ ] No regression in booking flow completion rate

## Troubleshooting

### Issue: Prompt file not found

**Symptoms**: 
```
ERROR: Prompt file not found: agent/prompts/shared/identity.md
```

**Solution**:
1. Verify files exist: `ls agent/prompts/shared/`
2. Check file permissions: `chmod 644 agent/prompts/shared/*.md`
3. If missing, restore from git: `git checkout HEAD -- agent/prompts/shared/`

### Issue: Cache not working

**Symptoms**: 
```
Cache miss - loading system prompt from disk
```
(appearing on every request)

**Solution**:
1. Check cache TTL: Verify `CACHE_TTL_MINUTES = 10` in `loader.py`
2. Clear cache manually: Restart agent service
3. Check logs: `docker-compose logs agent | grep "cached"`

### Issue: Legacy prompts still being used

**Symptoms**: Booking flow uses old step-based prompts

**Solution**:
1. Verify feature flag: `grep USE_OPTIMIZED_PROMPTS .env`
2. Check mode routing: Verify `booking_mode.py` uses `load_markdown("booking.md", "modes")`
3. Clear Python cache: `find . -type d -name __pycache__ -exec rm -rf {} +`

### Issue: Import errors

**Symptoms**:
```
ImportError: cannot import name 'get_system_prompt' from 'agent.prompts'
```

**Solution**:
1. Verify `loader.py` exists: `ls agent/prompts/loader.py`
2. Check `__init__.py` exports: `grep __all__ agent/prompts/__init__.py`
3. Reinstall package: `pip install -e .`

## Performance Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Prompt load time | ~50ms | ~5ms (cached) | 90% |
| Memory usage | Baseline | +2MB (cache) | Minimal |
| Token count | ~5,000 | ~2,200 | 56% |

## Support

For issues or questions:

1. Check logs: `docker-compose logs -f agent`
2. Verify configuration: `python -c "from agent.prompts.loader import get_system_prompt; import asyncio; print(asyncio.run(get_system_prompt())[:200])"`
3. Review this migration guide
4. Escalate to: [team lead / devops]

## Rollout Checklist

### Pre-Deployment (Staging)
- [ ] Run full test suite
- [ ] Verify feature flag works in both modes
- [ ] Check prompt cache functionality
- [ ] Validate mode prompts load correctly
- [ ] Test rollback procedure

### Production Deployment
- [ ] Deploy with `USE_OPTIMIZED_PROMPTS=false` (monitoring mode)
- [ ] Monitor for 30 minutes
- [ ] Enable `USE_OPTIMIZED_PROMPTS=true`
- [ ] Monitor for 2 hours
- [ ] Check error rates and response quality

### Post-Deployment (24h)
- [ ] Review conversation logs
- [ ] Compare booking completion rates
- [ ] Check for customer complaints
- [ ] Verify cache hit rates
- [ ] Document any issues

---

**Migration Date**: 2025-03-11  
**Version**: v6.1.0  
**Author**: Atrévete Bot Team
