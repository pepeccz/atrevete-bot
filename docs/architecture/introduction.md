# Introduction

This document outlines the complete fullstack architecture for **Atrévete Bot**, including backend systems, frontend implementation, and their integration. It serves as the single source of truth for AI-driven development, ensuring consistency across the entire technology stack.

This unified approach combines what would traditionally be separate backend and frontend architecture documents, streamlining the development process for modern fullstack applications where these concerns are increasingly intertwined.

The system is designed to automate 85%+ of customer reservation conversations via WhatsApp through an AI conversational agent ("Maite") powered by LangGraph + Anthropic Claude, handling the complete reservation lifecycle from initial inquiry through payment processing (via Stripe) to automated reminders—across 18 documented conversational scenarios. The architecture implements intelligent escalation to the human team via WhatsApp group notifications for complex cases, ensuring the bot augments rather than replaces human judgment.

## 1.1 Starter Template or Existing Project

**N/A - Greenfield project**

This is a greenfield implementation with no existing starter templates. The architecture is custom-designed to meet the specific requirements of a salon reservation automation system with stateful conversational AI orchestration.

## 1.2 Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2025-10-23 | v1.0 | Initial architecture document creation | Winston (Architect Agent) |

---
