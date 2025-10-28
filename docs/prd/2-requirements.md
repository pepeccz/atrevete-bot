# 2. Requirements

## 2.1 Functional Requirements

**FR1:** The system shall identify customers as new or returning by querying the customer database using phone number from WhatsApp messages

**FR2:** The system shall present itself as "Maite, la asistenta virtual de Atrévete Peluquería" with warm, friendly tone including appropriate emoji usage (🌸💕😊) for first-time customer interactions

**FR3:** The system shall confirm customer name for first-time customers before proceeding with service discussion, especially when WhatsApp metadata name is unreliable or non-standard

**FR4:** The system shall omit greeting/introduction protocol for returning customers and proceed directly to addressing their request

**FR5:** The system shall maintain conversational memory across sessions using hybrid approach (recent message window + compressed historical summary + customer service history)

**FR6:** The system shall check real-time availability across 5 stylist Google Calendars, filtering by service category (Hairdressing/Aesthetics)

**FR7:** The system shall calculate total price and duration for individual services or service combinations requested by customers, displaying both in responses

**FR8:** The system shall offer multiple time slot options (minimum 2 when available) across different professionals or time ranges per customer request

**FR9:** The system shall detect when a customer requests a service included in a discounted package and proactively suggest the package option with price comparison

**FR10:** The system shall offer free consultation service (10-15 min, €0) when customer expresses indecision about service selection or requests technical product comparisons

**FR11:** The system shall enforce the business rule that Hairdressing and Aesthetics services cannot be combined in a single appointment

**FR12:** The system shall create provisional calendar blocks with 30-minute timeout (15 minutes for same-day bookings) during payment processing to prevent double-booking

**FR13:** The system shall request customer surnames (apellidos) for new customers before generating payment links to complete registration

**FR14:** The system shall generate Stripe payment links for 20% advance payment and send them via WhatsApp for all services with non-zero price

**FR15:** The system shall send payment reminder at 25 minutes (5 minutes before timeout) before automatically releasing provisional calendar blocks

**FR16:** The system shall generate new payment link on first retry when customer reports payment failure, escalating to human team after second failure

**FR17:** The system shall validate payment completion via Stripe webhook before confirming final booking

**FR18:** The system shall create, modify, and cancel Google Calendar events for stylists while respecting their individual working hours and blocked time

**FR19:** The system shall process cancellations with >24h notice by triggering automatic advance payment refund

**FR20:** The system shall process cancellations with <24h notice by offering rescheduling options without losing advance payment instead of refunds

**FR21:** The system shall detect holiday/closure events in Google Calendar and inform customers of closure with next available date suggestion

**FR22:** The system shall filter same-day availability to exclude time slots with <1 hour lead time to allow for payment processing and customer travel

**FR23:** The system shall send urgent notifications to professionals via email/SMS within 2 minutes for same-day bookings confirmed after payment

**FR24:** The system shall send automated WhatsApp reminders 48 hours before each appointment including service, stylist, time, duration, advance payment amount, and cancellation policy notice (24h threshold)

**FR25:** The system shall retrieve and present customer's last service combination when customer requests "lo de siempre" (the usual), including preferred professional

**FR26:** The system shall track and reinforce professional preferences in customer profiles based on booking history

**FR27:** The system shall handle group reservations by searching for simultaneous availability across multiple professionals for multiple services with combined pricing

**FR28:** The system shall support booking services for third parties, creating new customer profiles while associating the booking with the referring customer in database

**FR29:** The system shall provide conversational responses to FAQ queries (hours, parking, location, general info) stored in knowledge base

**FR30:** The system shall escalate medical/health consultation inquiries immediately to human team

**FR31:** The system shall escalate payment failures after 2 attempts to human team with conversation summary

**FR32:** The system shall escalate customer delay notifications with <1h notice to assigned professional and human team

**FR33:** The system shall escalate unresolved ambiguity or complex technical questions after reasonable conversational attempts to human team

**FR34:** The system shall send escalation notifications to the team WhatsApp group via Chatwoot including conversation summary, customer context, and reason for escalation

**FR35:** The system shall handle 18 documented conversational scenarios including: standard bookings, pack suggestions, professional preferences, group reservations, service inquiries, modifications, cancellations, delays, payment issues, indecision, urgent same-day bookings, third-party bookings, "lo de siempre" requests, and FAQ responses

## 2.2 Non-Functional Requirements

**NFR1:** System response time shall be <5 seconds for standard queries and <10 seconds for complex operations (multi-calendar checks, calculations) in 95% of cases

**NFR2:** System uptime shall maintain ≥99.5% availability (maximum 3.6 hours downtime per month)

**NFR3:** System shall handle up to 100 concurrent conversations without performance degradation

**NFR4:** The conversational tone shall maintain consistent warm, friendly personality across all interactions using Spanish language with proper regional conventions

**NFR5:** Payment timeout shall be 15 minutes for same-day bookings and 30 minutes for advance bookings

**NFR6:** Professional notifications for same-day bookings shall be sent within 2 minutes of payment confirmation

**NFR7:** The system shall implement rate limiting of maximum 10 messages per minute per customer to prevent spam

**NFR8:** System shall validate webhook signatures from Stripe and Chatwoot to prevent malicious requests

**NFR9:** All sensitive API keys (Claude, Stripe, Google) shall be stored as environment variables or Docker secrets, never in code

**NFR10:** System shall require HTTPS for all webhook endpoints as mandated by Stripe

**NFR11:** System shall implement atomic database transactions for booking operations to prevent race conditions during concurrent reservation attempts

**NFR12:** PostgreSQL database shall have automated daily backups with 30-day retention

**NFR13:** Redis state shall persist using RDB snapshots to enable conversation recovery after system restart

**NFR14:** System shall comply with GDPR requirements for customer data storage (name, phone) including privacy policy and data deletion capability

**NFR15:** All payment data shall remain PCI-compliant by using Stripe's hosted payment pages—no card data stored locally

**NFR16:** System architecture shall use Docker Compose for development/staging environments supporting easy deployment

**NFR17:** Conversation state shall automatically checkpoint to Redis after each LangGraph node execution to enable recovery from crashes

**NFR18:** System logs shall use structured format with appropriate severity levels for debugging and monitoring

---
