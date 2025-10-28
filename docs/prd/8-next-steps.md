# 8. Next Steps

## UX Expert Prompt

"Hi UX Expert! The Product Requirements Document for **Atrévete Bot** is complete and validated. I need you to create the UX architecture using this PRD (`docs/prd.md`) as your foundation.

**Key context:**
- **Primary interface:** Conversational AI via WhatsApp (customer-facing)
- **Secondary interface:** Web admin panel (Django/Flask Admin)
- **Target users:** Spanish-speaking salon customers (mobile-first) + 5 stylists (desktop admin)

**Your deliverables:**
1. Conversational Flow Diagrams for all 18 scenarios
2. Message Templates with tone guidelines (Maite persona)
3. Error State Handling and fallback responses
4. Escalation Handoff UX design
5. Admin Interface Wireframes (optional for MVP)

**Reference:** PRD Section 3 (UI Design Goals), Section 2 (FR2-FR4), `docs/specs/scenarios.md`

Please review and let me know if you need clarifications!"

## Architect Prompt

"Hi Architect! The Product Requirements Document for **Atrévete Bot** is complete and validated (95% checklist pass, READY FOR ARCHITECT ✅). I need you to create the technical architecture using this PRD (`docs/prd.md`) and Project Brief (`docs/brief.md`).

**Critical technical decisions (non-negotiable):**
- **Agent:** LangGraph 0.6.7+ (stateful, checkpointing)
- **LLM:** Anthropic Claude via LangChain
- **API:** FastAPI 0.116+
- **Databases:** PostgreSQL 15+ + Redis 7+
- **Deployment:** Docker Compose (3 containers)
- **Timezone:** Europe/Madrid

**Your deliverables:**
1. System Architecture Diagram (3 containers, data flows)
2. Database Schema (ER diagram for 7 tables)
3. LangGraph StateGraph Design (nodes/edges for 18 scenarios)
4. ConversationState Schema (complete TypedDict)
5. API Contracts (webhook specs)
6. Tool Specifications (5 tool categories)
7. Integration Architecture (Google/Stripe/Chatwoot)
8. Error Handling Strategy
9. Security Architecture
10. Testing Strategy

**Key challenges to solve:**
1. Concurrent booking prevention
2. Conversation state persistence with crash recovery
3. Payment timeout management (25-min reminder, 30-min auto-release)
4. Escalation mechanism (bot pause and handoff)
5. Same-day vs standard timeout logic

**Timeline:** 3-4 weeks development + 2 weeks beta = 5-6 weeks total MVP

Please review PRD and Brief, then create the Architecture Document!"

## Immediate Next Actions

**For Product Manager:**

1. ✅ Fix docs/specs/scenarios.md Scenario 1: Change "6 horas" to "24 horas"
2. ✅ Create traceability matrix mapping 18 scenarios to Epic/Story coverage
3. ✅ Update timeline: 5-6 weeks total (3-4 dev + 2 beta validation)
4. ✅ Output full PRD to docs/prd.md

**For UX Expert:**

1. Review PRD Section 3 and scenarios.md
2. Create conversational flow diagrams
3. Design message templates
4. Validate with PM before architect handoff

**For Architect:**

1. Review PRD, Brief, Tech Analysis
2. Design complete system architecture
3. Create Architecture Document (docs/architecture.md)
4. Flag any ambiguities to PM

**For Development Team:**

1. Setup environment per Story 1.1
2. Begin Epic 1 (Foundation)
3. Use ACs as test specifications
4. Run integration tests after each epic

## Project Handoff Checklist

- [x] PRD complete with 46 detailed user stories
- [x] 35 functional requirements documented
- [x] 18 non-functional requirements specified
- [x] PM Checklist executed - 95% pass, READY FOR ARCHITECT
- [ ] Scenario documentation aligned (fix 6h→24h) **← TODO**
- [ ] Traceability matrix created **← TODO**
- [ ] Timeline updated (5-6 weeks) **← TODO**
- [ ] PRD output to docs/prd.md **← COMPLETE**
- [ ] UX Expert briefed
- [ ] Architect briefed

---

**🎉 PRD COMPLETE - READY FOR ARCHITECTURE PHASE 🎉**
