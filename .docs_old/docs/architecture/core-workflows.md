# 7. Core Workflows

This section illustrates key system workflows using sequence diagrams to show component interactions, including external APIs, error handling paths, and async operations.

## 7.1 Standard Booking Flow (Scenario 1: New Customer Booking)

```mermaid
sequenceDiagram
    participant C as Customer (WhatsApp)
    participant CW as Chatwoot
    participant API as FastAPI Webhook
    participant R as Redis
    participant LG as LangGraph Orchestrator
    participant CT as CalendarTools
    participant PT as PaymentTools
    participant BT as BookingTools
    participant DB as PostgreSQL
    participant GC as Google Calendar API
    participant ST as Stripe API
    participant CL as Claude API

    C->>CW: "Hola, quiero reservar mechas para mañana"
    CW->>API: POST /webhook/chatwoot (message event)
    API->>API: Validate signature
    API->>R: Publish to incoming_messages channel
    API-->>CW: 200 OK (200ms)

    R->>LG: Subscribe & receive message
    LG->>LG: Load checkpoint (or create new)
    LG->>DB: CustomerTools.get_customer_by_phone("+34612...")
    DB-->>LG: None (new customer)

    LG->>CL: Greet new customer prompt
    CL-->>LG: "¡Hola! Soy Maite... ¿Confirmas tu nombre María?"
    LG->>R: Publish to outgoing_messages
    R->>CW: Send message via Chatwoot API
    CW->>C: "¡Hola! Soy Maite..."

    C->>CW: "Sí, María García"
    CW->>API: POST /webhook/chatwoot
    API->>R: Publish message
    R->>LG: Receive confirmation

    LG->>DB: CustomerTools.create_customer("+34612...", "María", "García")
    DB-->>LG: Customer created (id: uuid-123)
    LG->>R: Checkpoint state

    LG->>CL: Analyze service request
    CL-->>LG: Intent: booking, Service: MECHAS
    LG->>DB: BookingTools.find_service("mechas")
    DB-->>LG: Service(id: svc-456, price: 50€, duration: 90min)

    LG->>DB: Check for packs containing MECHAS
    DB-->>LG: Pack "Mechas + Corte" (80€ vs 90€ individual)
    LG->>CL: Suggest pack prompt
    CL-->>LG: "Tenemos pack Mechas + Corte por 80€ (ahorras 10€)"
    LG->>CW: Send suggestion
    CW->>C: "Tenemos pack..."

    C->>CW: "Solo mechas, gracias"
    CW->>API: POST /webhook/chatwoot
    API->>R: Publish
    R->>LG: Receive decline

    LG->>CT: get_availability("Hairdressing", tomorrow, "10:00-20:00")
    CT->>DB: Query stylists WHERE category IN ('Hairdressing', 'Both')
    DB-->>CT: [Pilar, Marta, Harol, Víctor]
    CT->>GC: events.list() for each calendar (tomorrow)
    GC-->>CT: Busy times per stylist
    CT->>CT: Calculate free slots (30min intervals)
    CT-->>LG: [Slot(11:00, Pilar), Slot(14:00, Marta), Slot(16:00, Víctor)]

    LG->>CL: Format availability options
    CL-->>LG: "Tenemos libre: 11:00 con Pilar, 14:00 con Marta..."
    LG->>CW: Send options
    CW->>C: "Tenemos libre..."

    C->>CW: "A las 14:00 con Marta"
    CW->>API: POST /webhook/chatwoot
    API->>R: Publish
    R->>LG: Receive selection

    LG->>BT: create_provisional_booking(customer_id, stylist_id, 14:00, [svc-456], is_same_day=false)
    BT->>DB: BEGIN TRANSACTION (SERIALIZABLE)
    BT->>DB: Check slot still free (no confirmed appointments)
    DB-->>BT: Slot free
    BT->>CT: create_event(marta_cal, 14:00, 90min, "[PROVISIONAL] María - MECHAS", "provisional")
    CT->>GC: events.insert(yellow color, description)
    GC-->>CT: event_id: evt-789
    BT->>DB: INSERT Appointment (status=provisional, payment_status=pending, timeout=30min)
    DB-->>BT: Appointment created (id: apt-999)
    BT->>DB: COMMIT
    BT-->>LG: Booking created, expires at 14:25 (30min timeout)

    LG->>DB: Calculate advance payment (50€ * 20% = 10€)
    LG->>PT: create_payment_link(apt-999, 10.00, "María García", "Anticipo MECHAS")
    PT->>ST: payment_links.create(amount=1000 cents, metadata={appointment_id: apt-999})
    ST-->>PT: Payment URL
    PT-->>LG: https://checkout.stripe.com/pay/cs_abc123

    LG->>CL: Format confirmation with payment link
    CL-->>LG: "Perfecto María! Reserva provisional 14:00 mañana. Pagar 10€..."
    LG->>CW: Send message + payment link
    CW->>C: "Perfecto María!..." + [Payment Link]

    Note over C,ST: Customer pays via Stripe
    C->>ST: Click link, complete payment
    ST->>ST: Process payment
    ST->>API: POST /webhook/stripe (checkout.session.completed)
    API->>API: Validate Stripe signature
    API->>R: Publish to payment_events channel
    API-->>ST: 200 OK

    R->>LG: Payment event received
    LG->>DB: BookingTools.confirm_booking(apt-999, stripe_payment_id)
    DB->>DB: UPDATE Appointment SET status=confirmed, payment_status=confirmed
    LG->>CT: update_event(evt-789, status="confirmed")
    CT->>GC: events.patch(color=green, remove "[PROVISIONAL]")
    GC-->>CT: Success

    LG->>DB: CustomerTools.update(total_spent += 50€)
    LG->>CL: Format final confirmation
    CL-->>LG: "¡Reserva confirmada! Te esperamos mañana 14:00 con Marta..."
    LG->>CW: Send confirmation
    CW->>C: "¡Reserva confirmada!..."

    LG->>R: Checkpoint final state
```

---
