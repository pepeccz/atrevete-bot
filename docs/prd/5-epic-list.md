# 5. Epic List

## Epic 1: Foundation & Core Infrastructure
**Goal:** Establish project foundation including Docker environment, database schema, API webhook receiver, and basic LangGraph orchestrator that can receive and respond to a simple WhatsApp message, demonstrating end-to-end connectivity.

## Epic 2: Customer Identification & Conversational Foundation
**Goal:** Implement intelligent customer identification (new vs returning), warm greeting protocol with "Maite" persona, name confirmation flow, and conversational memory system—enabling natural back-and-forth dialogue that remembers context.

## Epic 3: Service Discovery & Calendar Availability
**Goal:** Enable customers to inquire about services, view pricing, receive intelligent pack suggestions, and check real-time availability across 5 stylist Google Calendars with filtering by service category (Hairdressing/Aesthetics).

## Epic 4: Booking Flow & Payment Processing
**Goal:** Complete the booking lifecycle from provisional calendar blocking through Stripe payment processing to confirmed appointment creation, including timeout management, payment retry logic, and booking confirmation notifications.

## Epic 5: Modification & Cancellation Management
**Goal:** Handle post-booking changes including appointment modifications, cancellations with refund logic (>24h), rescheduling offers (<24h), customer delay notifications, and intelligent escalation to stylists for edge cases.

## Epic 6: Notifications & Intelligent Escalation
**Goal:** Implement automated 48-hour advance reminders, same-day booking urgent notifications, intelligent escalation system for medical consultations, payment failures, and complex queries, with rich context passed to the human team.

## Epic 7: Testing, Validation & Production Hardening
**Goal:** Comprehensive validation of all 18 conversational scenarios through automated integration tests, manual stylist testing, concurrency/race condition testing, security hardening, and production deployment preparation including monitoring and backup systems.

---
