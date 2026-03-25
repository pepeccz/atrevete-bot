# Design: Fix Admin Panel CORS Blocking

## CORS Architecture

```
Browser (atrevete.zonavix.com)
  │
  ├─ Preflight OPTIONS ──────────────────────────┐
  │                                               ▼
  │                                    ┌─────────────────────┐
  │                                    │   CORSMiddleware     │
  │                                    │  (api/main.py:37-43) │
  │                                    │                       │
  │                                    │  origins = settings   │
  │                                    │  .CORS_ORIGINS        │
  │                                    │  .split(",")          │
  │                                    └──────────┬────────────┘
  │                                               │
  ├─ GET/POST with Origin header ─────────────────┤
  │                                               ▼
  │                                    ┌─────────────────────┐
  │                                    │  Route Handler       │
  │                                    │                       │
  │                                    │  On success:          │
  │                                    │    CORSMiddleware     │
  │                                    │    adds headers       │
  │                                    │                       │
  │                                    │  On unhandled error:  │
  │                                    │    global_exception   │
  │                                    │    _handler           │
  │                                    │   (main.py:104-132)   │
  │                                    │    adds CORS headers  │
  │                                    │    manually           │
  │                                    └──────────┬────────────┘
  │                                               │
  ◄───────── Response with CORS headers ──────────┘
```

### Data Flow

1. `shared/config.py:271-274` — `Settings.CORS_ORIGINS` (Pydantic `str` Field, default = localhost origins)
2. `.env` file → Pydantic Settings loads `CORS_ORIGINS` env var at startup (overrides default)
3. `api/main.py:30` — `settings.CORS_ORIGINS.split(",")` → list of origin strings
4. `api/main.py:37-43` — `CORSMiddleware(allow_origins=origins)` handles normal responses + preflight
5. `api/main.py:114-116` — Global exception handler re-reads `CORS_ORIGINS` for error responses

### Two CORS Header Insertion Points

| Point | Location | When | How |
|-------|----------|------|-----|
| **Middleware** | `api/main.py:37-43` | All successful responses + OPTIONS preflight | `CORSMiddleware` automatic |
| **Exception handler** | `api/main.py:104-132` | Unhandled exceptions (500s) | Manual header injection after origin allowlist check |

Both read from the same `CORS_ORIGINS` env var — consistency is guaranteed by the single source of truth.

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fix via env var vs code change | **Env var** | Middleware already supports comma-separated origins; no code gap exists |
| Explicit allowlist vs wildcard `*` | **Explicit** | `allow_credentials=True` is incompatible with `*` per CORS spec; explicit is also more secure |
| Restart vs full rebuild | **`docker compose restart api`** | Env vars are read at process startup; restart is sufficient and faster |
| Include `https://api.zonavix.com` | **Yes** | Self-origin inclusion prevents edge cases with same-origin-but-different-port scenarios |

## Verification Approach

### Pre-deployment (local)
```bash
# Verify .env has the correct value
grep CORS_ORIGINS .env
```

### Post-deployment (production)
```bash
# Test 1: Simple CORS header check
curl -s -I -H "Origin: https://atrevete.zonavix.com" https://api.zonavix.com/health \
  | grep -i access-control

# Test 2: Preflight OPTIONS
curl -s -I -X OPTIONS \
  -H "Origin: https://atrevete.zonavix.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type,Authorization" \
  https://api.zonavix.com/health \
  | grep -i access-control

# Expected output for both:
# Access-Control-Allow-Origin: https://atrevete.zonavix.com
# Access-Control-Allow-Credentials: true
```

### Browser verification
1. Open `https://atrevete.zonavix.com` in Chrome
2. Open DevTools → Network tab
3. Verify API requests show `200` (not CORS blocked)
4. Console should have zero CORS-related errors
