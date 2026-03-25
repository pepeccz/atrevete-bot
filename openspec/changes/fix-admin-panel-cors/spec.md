# Spec: Fix Admin Panel CORS Blocking

## Requirements

### MUST

| ID | Requirement |
|----|-------------|
| R1 | `.env` MUST contain `CORS_ORIGINS` with all production and development origins |
| R2 | `CORS_ORIGINS` MUST include `https://atrevete.zonavix.com` (admin panel) |
| R3 | `CORS_ORIGINS` MUST include `https://api.zonavix.com` (API self-origin for same-origin fallback) |
| R4 | `CORS_ORIGINS` MUST preserve existing localhost origins for local development |
| R5 | `.env.example` MUST document `CORS_ORIGINS` with description and example value |
| R6 | After container restart, `CORSMiddleware` MUST respond with `Access-Control-Allow-Origin` for allowed origins |
| R7 | Global exception handler (`api/main.py:103-132`) MUST also respect the updated origins on error responses |

### MUST NOT

| ID | Constraint |
|----|------------|
| C1 | MUST NOT use wildcard `*` as an allowed origin |
| C2 | MUST NOT require code changes to `api/main.py` or `shared/config.py` |
| C3 | MUST NOT include trailing slashes in origin URLs |
| C4 | MUST NOT require a full `docker compose up` — only `restart api` |

## BDD Scenarios

### Scenario 1: Admin panel origin is allowed

```gherkin
Given the API is running with CORS_ORIGINS containing "https://atrevete.zonavix.com"
When the browser sends a GET request from origin "https://atrevete.zonavix.com"
Then the response MUST include header "Access-Control-Allow-Origin: https://atrevete.zonavix.com"
And the response MUST include header "Access-Control-Allow-Credentials: true"
```

### Scenario 2: Preflight OPTIONS request succeeds

```gherkin
Given the API is running with CORS_ORIGINS containing "https://atrevete.zonavix.com"
When the browser sends an OPTIONS preflight request from origin "https://atrevete.zonavix.com"
  With header "Access-Control-Request-Method: POST"
  With header "Access-Control-Request-Headers: Content-Type, Authorization"
Then the response status MUST be 200
And the response MUST include "Access-Control-Allow-Methods" containing "POST"
And the response MUST include "Access-Control-Allow-Headers" containing "Content-Type"
```

### Scenario 3: Unknown origin is rejected

```gherkin
Given the API is running with CORS_ORIGINS set
When the browser sends a request from origin "https://evil.example.com"
Then the response MUST NOT include the "Access-Control-Allow-Origin" header
```

### Scenario 4: Error responses include CORS headers

```gherkin
Given the API is running with CORS_ORIGINS containing "https://atrevete.zonavix.com"
When an endpoint throws an unhandled exception for a request from "https://atrevete.zonavix.com"
Then the 500 response MUST include header "Access-Control-Allow-Origin: https://atrevete.zonavix.com"
And the 500 response MUST include header "Access-Control-Allow-Credentials: true"
```

### Scenario 5: Local development still works

```gherkin
Given the API is running with CORS_ORIGINS containing "http://localhost:3000"
When the browser sends a request from origin "http://localhost:3000"
Then the response MUST include header "Access-Control-Allow-Origin: http://localhost:3000"
```

## Acceptance Criteria

- [ ] Production `curl` test confirms CORS headers present for `https://atrevete.zonavix.com`
- [ ] Admin panel at `https://atrevete.zonavix.com` loads without CORS errors in DevTools
- [ ] Local dev (`http://localhost:3000`) continues to work after `.env` change
- [ ] `.env.example` includes `CORS_ORIGINS` with documentation comment
- [ ] No code files modified — env-only change
