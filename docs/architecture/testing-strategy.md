# 15. Testing Strategy

## 15.1 Testing Pyramid

```
       E2E Tests (18 scenarios)
      /                        \
  Integration Tests (API + Agent)
 /                                \
Unit Tests (Tools, Nodes, Models)
```

## 15.2 Test Organization

- **Unit Tests:** Mock external APIs (Google, Stripe, Chatwoot)
- **Integration Tests:** Real FastAPI + Redis, mocked external APIs
- **E2E Tests:** Full conversation flows (18 PRD scenarios)

---
