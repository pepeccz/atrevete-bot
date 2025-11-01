# 17. Monitoring and Observability

## 17.1 Monitoring Stack

- **Backend Monitoring:** LangSmith (LangGraph tracing) + Prometheus (system metrics)
- **Error Tracking:** Structured JSON logs → BetterStack or Grafana Loki
- **Performance Monitoring:** Prometheus + Grafana dashboards

## 17.2 Key Metrics

- Request rate (webhooks/minute)
- Error rate (API failures)
- Response time (p50, p95, p99)
- Automation rate (completed without escalation)
- Escalation rate by reason
- Appointments created/day
- Payment success rate

---
