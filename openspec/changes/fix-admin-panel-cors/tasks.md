# Tasks: Fix Admin Panel CORS Blocking

**Change**: fix-admin-panel-cors
**Estimate**: XS (< 15 minutes total)
**Priority**: P0-urgent (delivery blocker)

## Checklist

### Part 1 — Production Fix

- [ ] **T1**: Edit `.env` — add `CORS_ORIGINS` variable
  - **File**: `.env`
  - **Action**: Add line:
    ```
    CORS_ORIGINS=http://localhost:3000,http://localhost:8000,http://localhost:8001,http://api:8000,https://atrevete.zonavix.com,https://api.zonavix.com
    ```
  - **Verify**: `grep CORS_ORIGINS .env` shows the full value
  - **Size**: XS

- [ ] **T2**: Restart API container
  - **Command**: `docker compose restart api`
  - **Verify**: `docker compose ps api` shows `running` + `healthy`
  - **Size**: XS
  - **Depends on**: T1

### Part 2 — Documentation

- [ ] **T3**: Edit `.env.example` — document `CORS_ORIGINS`
  - **File**: `.env.example`
  - **Action**: Add after the "Application Settings" section:
    ```
    # ----------------------------------------------------------------------------
    # CORS Configuration
    # ----------------------------------------------------------------------------
    # Comma-separated allowed origins for CORS. Include all frontend domains.
    # IMPORTANT: Production deployments MUST add their frontend domain here.
    # Example: http://localhost:3000,https://admin.yourdomain.com
    CORS_ORIGINS=http://localhost:3000,http://localhost:8000,http://localhost:8001,http://api:8000
    ```
  - **Verify**: File includes `CORS_ORIGINS` with descriptive comment
  - **Size**: XS

### Part 3 — Verification

- [ ] **T4**: Verify CORS headers with curl
  - **Command**:
    ```bash
    curl -s -I -H "Origin: https://atrevete.zonavix.com" https://api.zonavix.com/health | grep -i access-control
    ```
  - **Expected**: `Access-Control-Allow-Origin: https://atrevete.zonavix.com`
  - **Size**: XS
  - **Depends on**: T2

- [ ] **T5**: Verify preflight OPTIONS request
  - **Command**:
    ```bash
    curl -s -I -X OPTIONS \
      -H "Origin: https://atrevete.zonavix.com" \
      -H "Access-Control-Request-Method: POST" \
      -H "Access-Control-Request-Headers: Content-Type,Authorization" \
      https://api.zonavix.com/health | grep -i access-control
    ```
  - **Expected**: 200 with `Access-Control-Allow-Origin` + `Access-Control-Allow-Methods`
  - **Size**: XS
  - **Depends on**: T2

- [ ] **T6**: Verify admin panel in browser
  - **Action**: Open `https://atrevete.zonavix.com`, check DevTools Network tab — zero CORS errors
  - **Size**: XS
  - **Depends on**: T2

## Dependency Graph

```
T1 (edit .env) ──► T2 (restart api) ──► T4 (curl verify)
                                    ──► T5 (OPTIONS verify)
                                    ──► T6 (browser verify)
T3 (edit .env.example) — independent, can run in parallel
```

## Rollback

If CORS still fails after T2:
1. Check `docker compose logs api | grep CORS` for startup errors
2. Verify no typo: `docker compose exec api env | grep CORS`
3. If needed, revert `.env` change and `docker compose restart api`
