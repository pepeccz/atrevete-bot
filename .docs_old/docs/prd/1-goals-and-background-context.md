# 1. Goals and Background Context

## 1.1 Goals

- Successfully automate 85%+ of customer reservation conversations via WhatsApp without human intervention
- Reduce operational time spent on booking management by 80% (from 15-20 min to 3-4 min per reservation requiring human touch)
- Increase conversion rate of inquiries to confirmed appointments by 25% by capturing after-hours demand
- Free 10-15 weekly hours of staff time currently spent on administrative tasks to focus on service delivery
- Maintain or improve customer satisfaction with instant 24/7 responses while introducing new 20% advance payment system
- Reduce no-shows by 30% through automated 48-hour advance reminders

## 1.2 Background Context

Atrévete Peluquería currently manages all customer reservations and inquiries manually through WhatsApp, requiring 15-20 minutes per booking across multiple message exchanges to confirm availability, services, pricing, schedule payment links, and send reminders. With 5 stylists (Pilar, Marta, Rosa, Harol, and Víctor) managing their own Google Calendars across Hairdressing and Aesthetics services, the manual coordination creates operational friction—especially during peak hours when staff should focus on in-person clients. An estimated 20-30% of inquiries arrive outside business hours and go unanswered, representing lost revenue.

Atrévete Bot addresses this by deploying "Maite," an AI conversational agent powered by LangGraph + Anthropic Claude, that handles the complete reservation lifecycle—from initial inquiry through payment processing (via Stripe) to automated reminders—across 18 documented conversational scenarios. The system intelligently escalates complex cases (medical consultations, payment issues, edge cases) to the human team via WhatsApp group notifications, ensuring the bot augments rather than replaces human judgment. This is the salon's first implementation of advance payment requirements (20% deposit), which the system will help introduce smoothly to customers.

## 1.3 Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2025-10-22 | v1.0 | Initial PRD creation from Project Brief | Claude (PM Agent) |

---
