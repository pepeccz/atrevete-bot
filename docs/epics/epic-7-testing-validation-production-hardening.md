# Epic 7: Testing, Validation & Production Hardening

**Epic Goal:** Comprehensive validation of all 18 conversational scenarios through automated integration tests, manual stylist testing, concurrency/race condition testing, security hardening, performance validation, and production deployment preparation.

## Story 7.1: Integration Tests for 18 Conversational Scenarios

**As a** QA engineer,
**I want** automated integration tests for all 18 scenarios,
**so that** every conversational path is validated before production.

**Prerequisites:** All Epics 1-6 completed

**Acceptance Criteria:**

1. Integration test suite `/tests/integration/scenarios/` with 18 files
2. Each test uses pytest-asyncio
3. Tests use staging environment with mocked external APIs
4. Test harness simulates complete conversation flows
5-22. Each scenario test validates specific flow (Scenario 1-18)
23. All tests must pass for deployment
24. Full suite completes in <10 minutes
25. CI/CD integration

## Story 7.2: Concurrency & Race Condition Testing

**As a** system architect,
**I want** to validate concurrent booking attempts don't cause double-booking,
**so that** the system safely handles simultaneous requests.

**Prerequisites:** Story 4.2 (Provisional blocks), Story 4.5 (Payment confirmation)

**Acceptance Criteria:**

1. Concurrency test suite created
2. Test: Two customers book same slot simultaneously (<100ms apart)
3. Expected: Only ONE succeeds
4. Validates atomic transactions (PostgreSQL locking)
5. Test: Customer 1 has provisional, Customer 2 tries same slot
6. Expected: Customer 2 blocked or gets "unavailable"
7. Test: Two payment webhooks for same appointment_id
8. Expected: Idempotency - only first processes
9. Test: 50 concurrent requests across different slots
10. Expected: All succeed, <10s response time (95th percentile)
11. Test: Provisional block expires when payment arrives
12. Expected: Graceful handling
13. Test logs timing data
14. Integration test: Run 10 times → verify 0 double-bookings
15. No database timeout errors

## Story 7.3: Security Validation & Penetration Testing

**As a** security engineer,
**I want** to validate all security controls,
**so that** customer data and payments are protected.

**Prerequisites:** Story 1.4 (Webhook validation), Epic 4 (Payment flows)

**Acceptance Criteria:**

1. Security test suite created
2. Test: Invalid Stripe signature → 401
3. Test: Invalid Chatwoot auth → rejection
4. Test: Rate limiting → 429 after 10 requests
5. Test: SQL injection protection
6. Test: No API keys in git
7. Test: HTTPS requirement
8. Test: GDPR data deletion
9. Test: PCI compliance (no card data stored)
10. Test: Redis security (password required)
11. Test: Session hijacking resistance
12. Manual penetration test or OWASP ZAP scan
13. 0 critical/high severity issues
14. Security documentation created
15. Secrets rotation procedure tested

## Story 7.4: Performance Testing & Optimization

**As a** performance engineer,
**I want** to validate system meets all NFR performance targets,
**so that** customer experience remains fast under load.

**Prerequisites:** All functional epics complete

**Acceptance Criteria:**

1. Performance test suite using locust or pytest-benchmark
2. Test: Standard query response time
3. Target: 95th percentile <5s
4. Test: Complex operation (multi-calendar check)
5. Target: 95th percentile <10s
6. Test: 100 concurrent conversations
7. Target: No degradation
8. Test: Database query optimization
9. Index optimization validated
10. Test: Redis checkpoint performance
11. Target: <100ms checkpoint save
12. Test: Claude API latency
13. Typical: 1-3s (external dependency)
14. Load test: 30 conversations/hour for 8 hours
15. Target: 99.5% uptime, no crashes/leaks
16. Monitoring: Memory, CPU, connection pool
17. Optimization: Profile and fix bottlenecks if needed

## Story 7.5: Production Environment Setup & Deployment

**As a** DevOps engineer,
**I want** production infrastructure configured with HTTPS, monitoring, and backups,
**so that** the system is secure, observable, and recoverable.

**Prerequisites:** All testing complete (Stories 7.1-7.4 passing)

**Acceptance Criteria:**

1. VPS/Cloud server provisioned (4GB RAM, 2 vCPU, 50GB SSD)
2. Docker and Docker Compose installed
3. HTTPS: Nginx + Let's Encrypt with auto-renewal
4. Domain configured pointing to server
5. Production `.env` with all secrets
6. Firewall: Only 80, 443, 22 open
7. PostgreSQL automated daily backups (S3/Spaces)
8. Backup retention: 30 days
9. Redis RDB snapshots every 15 minutes
10. Docker Compose production config (restart: always)
11. Deployment script: zero-downtime
12. Monitoring: LangSmith + structured logs
13. Logging: JSON format, /var/log/, 14-day rotation
14. Health check monitored by UptimeRobot
15. Smoke test after deployment
16. Rollback procedure documented
17. Deployment completed with 0 downtime

## Story 7.6: Manual Stylist Validation & Soft Launch

**As a** product manager,
**I want** stylists to test the system with real scenarios before full launch,
**so that** we catch usability issues and validate MVP success criteria.

**Prerequisites:** Story 7.5 (Production deployment), All scenario tests passing

**Acceptance Criteria:**

1. Beta testing plan: 2-week validation with 5 stylists
2. Training session: 30-min walkthrough
3. Test scenarios provided
4. Real WhatsApp integration
5. Stylist feedback collection: daily check-ins, end-of-week survey
6. Success metrics tracking: ≥70% automation, ≥80% escalation precision, ≥99.5% uptime, ≥20 real bookings, ≥7/10 satisfaction
7. Bug tracking and prioritization
8. Data analysis: conversation logs review
9. Iteration: prompt adjustments, FAQ additions
10. Go/No-Go decision after 2 weeks
11. If criteria not met → extend beta
12. Final validation: ≥20 successful end-to-end bookings
13. Stylist sign-off: All 5 approve

## Story 7.7: Monitoring Dashboard & Operational Runbook

**As a** system operator,
**I want** a monitoring dashboard and runbook for common issues,
**so that** I can quickly diagnose and resolve problems.

**Prerequisites:** Story 7.5 (Production deployment)

**Acceptance Criteria:**

1. Monitoring dashboard (Grafana/Datadog/custom)
2. Key metrics: conversations/hour, automation rate, escalation rate, response time, payment success, uptime, error rate
3. Database metrics: connection pool, slow queries, table sizes
4. Redis metrics: memory, keyspace, checkpoint count
5. External API health tracking
6. Alerting rules: uptime, error rate, escalation rate, worker failures, disk usage
7. Operational runbook: restart, logs, manual escalation, refund, restore, outage handling, stuck checkpoints, emergency contacts
8. Incident response procedure
9. On-call rotation defined
10. Dashboard read-only for stakeholders
11. Weekly metrics review scheduled

---