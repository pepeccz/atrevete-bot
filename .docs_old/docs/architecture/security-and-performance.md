# 14. Security and Performance

## 14.1 Security Requirements

- Webhook signature validation (HMAC-SHA256 for Chatwoot, Stripe SDK verification)
- Rate limiting: 10 requests/minute per IP
- HTTPS via Nginx + Let's Encrypt
- Django Admin: 12+ char passwords, HTTP-only session cookies
- PostgreSQL connections via SSL (production)
- Environment secrets via Docker secrets or `.env` (never in code)

## 14.2 Performance Optimization

- Response Time Target: <5s for standard queries (95th percentile)
- Database: Composite indexes, connection pooling (pool_size=10)
- Caching: Redis for policies (1 hour TTL), LangGraph checkpoints (<5ms)

---
