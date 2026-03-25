# Proposal: Fix Admin Panel CORS Blocking

## Intent

Production admin panel (`https://atrevete.zonavix.com`) cannot reach the API (`https://api.zonavix.com`) — browser blocks all requests with `No Access-Control-Allow-Origin`. This is a **P0 delivery blocker** — client delivery is today.

Root cause: `CORS_ORIGINS` env var is not set in production `.env`, so `shared/config.py` defaults to localhost-only origins. The middleware and global exception handler both read from this var.

## Scope

### In Scope
- Add production origins to `.env` (`CORS_ORIGINS` variable)
- Document `CORS_ORIGINS` in `.env.example` for future deployments

### Out of Scope
- No code changes — middleware already reads `CORS_ORIGINS` correctly
- No changes to `shared/config.py` or `api/main.py`
- No wildcard (`*`) origins — explicit allowlist only

## Approach

Environment-only fix: add the production frontend + API origins to `.env`, restart the `api` container. The existing `CORSMiddleware` (line 37-43) and global exception handler (line 103-132) in `api/main.py` already split `CORS_ORIGINS` by comma — no code path changes needed.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `.env` | Modified | Add `CORS_ORIGINS` with production + dev origins |
| `.env.example` | Modified | Document `CORS_ORIGINS` with example values |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Typo in origin URL breaks CORS | Low | Verify with `curl -H "Origin: ..." -I` after deploy |
| Missing trailing slash or scheme mismatch | Low | Use exact origins without trailing slash, always `https://` |
| Container restart drops in-flight requests | Low | Restart is <2s; admin panel retries automatically |

## Rollback Plan

Remove or comment out `CORS_ORIGINS` line from `.env` → `docker compose restart api`. System reverts to localhost-only defaults (same broken state, but no worse).

## Dependencies

- SSH access to production server to edit `.env`
- Docker Compose access to restart `api` service

## Success Criteria

- [ ] `curl -H "Origin: https://atrevete.zonavix.com" -I https://api.zonavix.com/health` returns `Access-Control-Allow-Origin: https://atrevete.zonavix.com`
- [ ] Admin panel loads data without CORS errors in browser console
- [ ] Preflight `OPTIONS` requests return 200 with correct CORS headers
