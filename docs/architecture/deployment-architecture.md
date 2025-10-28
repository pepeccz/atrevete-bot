# 13. Deployment Architecture

## 13.1 Deployment Strategy

**Platform:** VPS (Hetzner CPX21: 4GB RAM, 2 vCPU, ~€7/month)

**Deployment Method:** SSH + Docker Compose

## 13.2 CI/CD Pipeline

GitHub Actions workflow runs tests on PR, deploys to VPS on main branch merge.

## 13.3 Environments

| Environment | Frontend URL | Backend URL | Purpose |
|-------------|--------------|-------------|---------|
| Development | http://localhost:8001 | http://localhost:8000 | Local development |
| Production | https://admin.atrevete.com | https://api.atrevete.com | Live environment |

---
