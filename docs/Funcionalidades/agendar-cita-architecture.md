# Arquitectura del Sistema de Agendamiento de Citas

**Fecha:** 2025-11-01
**Versión:** 1.0
**Estado:** En Implementación

---

## 📋 Resumen Ejecutivo

Este documento describe la arquitectura completa del sistema de agendamiento de citas para Atrévete Peluquería, integrando las especificaciones del MVP (docs/Funcionalidades/agendar-cita.md) con la arquitectura híbrida existente del bot conversacional.

### Objetivo

Permitir a los clientes agendar citas de manera conversacional a través de WhatsApp, gestionando:
- Selección de servicios/packs con validación de categorías
- Consulta de disponibilidad en tiempo real (5 calendarios Google)
- Recopilación de datos del cliente
- Procesamiento de pagos de anticipo (20%) vía Stripe
- Confirmación automática tras pago exitoso
- Cancelación automática de reservas no pagadas

---

## 🏗️ Arquitectura General

### Modelo: Arquitectura Híbrida de 2 Tiers (Extendida)

```
┌─────────────────────────────────────────────────────────────┐
│                    TIER 1: CONVERSACIONAL                    │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   Claude Sonnet 4 + ReAct Loop + 10 Tools             │  │
│  │   - FAQs, greetings, identificación                    │  │
│  │   - Detección de intención de reserva                  │  │
│  │   - start_booking_flow() → Trigger Tier 2              │  │
│  └───────────────────────────────────────────────────────┘  │
│                           ↓                                   │
└───────────────────────────┼───────────────────────────────────┘
                            ↓
┌───────────────────────────┼───────────────────────────────────┐
│                    TIER 2: TRANSACCIONAL                      │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  FASE 1: Selección de Servicio/Pack                    │ │
│  │  Nodos: validate_booking_request, suggest_pack,        │ │
│  │         handle_pack_response                           │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  FASE 2: Disponibilidad y Selección de Asistenta       │ │
│  │  Nodos: check_availability, handle_slot_selection      │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  FASE 3: Recopilación de Datos del Cliente            │ │
│  │  Nodo: collect_customer_data                           │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  FASE 4: Pago y Confirmación                          │ │
│  │  Nodos: create_provisional_booking,                    │ │
│  │         generate_payment_link                          │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ↓                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  PROCESAMIENTO ASÍNCRONO                               │ │
│  │  - Payment Processor (Redis → BD → Calendar)           │ │
│  │  - Expiration Worker (Timeouts)                        │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

---

## 📊 Análisis del Estado Actual

### ✅ Componentes Funcionales Existentes

| Componente | Archivo | Estado | Descripción |
|------------|---------|--------|-------------|
| **Base de Datos** | `database/models.py` | ✅ Completo | Modelo `Appointment` con estados PROVISIONAL/CONFIRMED/EXPIRED |
| **Google Calendar** | `agent/tools/calendar_tools.py` | ✅ Completo | Create/delete events, holiday detection |
| **Disponibilidad** | `agent/nodes/availability_nodes.py` | ✅ Completo | Multi-calendar query, prioritization, alternatives |
| **Validación Categorías** | `agent/nodes/booking_nodes.py` | ✅ Completo | validate_booking_request, handle_category_choice |
| **Pack Suggestion** | `agent/nodes/pack_suggestion_nodes.py` | ✅ Completo | suggest_pack, handle_pack_response |
| **Stripe Webhook** | `api/routes/stripe.py` | ✅ Completo | Webhook validation y enqueue a Redis |

### ❌ Componentes Faltantes (A Implementar)

| Componente | Archivo (Nuevo) | Descripción |
|------------|-----------------|-------------|
| **Validadores** | `agent/validators/booking_validators.py` | validate_min_advance_notice (3 días), validate_buffer |
| **Slot Selection** | `agent/nodes/appointment_nodes.py` | handle_slot_selection() |
| **Customer Data** | `agent/nodes/appointment_nodes.py` | collect_customer_data() |
| **Provisional Booking** | `agent/nodes/appointment_nodes.py` | create_provisional_booking() |
| **Payment Link** | `agent/nodes/appointment_nodes.py` | generate_payment_link() |
| **Payment Processor** | `agent/payment_processor.py` | Redis subscriber → Update BD/Calendar |
| **Expiration Worker** | `agent/workers/booking_expiration_worker.py` | Cancel expired provisional bookings |

---

## 🔄 Flujo Completo de Agendamiento

### Diagrama de Secuencia

```
Cliente          Conversational Agent       Tier 2 Nodes        Google Calendar    Stripe        Payment Processor
  │                      │                         │                   │              │                  │
  │  "Quiero mechas"     │                         │                   │              │                  │
  ├─────────────────────>│                         │                   │              │                  │
  │                      │ start_booking_flow()    │                   │              │                  │
  │                      ├────────────────────────>│                   │              │                  │
  │                      │                         │                   │              │                  │
  │                      │   validate_services     │                   │              │                  │
  │                      │<────────────────────────┤                   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Pack sugerido"     │   suggest_pack          │                   │              │                  │
  │<─────────────────────┤<────────────────────────┤                   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Sí, con corte"     │                         │                   │              │                  │
  ├─────────────────────>│ handle_pack_response    │                   │              │                  │
  │                      ├────────────────────────>│                   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Disponibilidad"    │   check_availability    │                   │              │                  │
  │<─────────────────────┤<────────────────────────┤ Query calendars   │              │                  │
  │                      │                         ├──────────────────>│              │                  │
  │                      │                         │<──────────────────┤              │                  │
  │                      │                         │                   │              │                  │
  │  "15:00 con Marta"   │                         │                   │              │                  │
  ├─────────────────────>│ handle_slot_selection   │                   │              │                  │
  │                      ├────────────────────────>│                   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Confirma nombre"   │ collect_customer_data   │                   │              │                  │
  │<─────────────────────┤<────────────────────────┤                   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Juan Pérez"        │                         │                   │              │                  │
  ├─────────────────────>│                         │                   │              │                  │
  │                      │ create_provisional      │                   │              │                  │
  │                      ├────────────────────────>│ Create PROVISIONAL│              │                  │
  │                      │                         ├──────────────────>│              │                  │
  │                      │                         │   (Yellow event)  │              │                  │
  │                      │                         │<──────────────────┤              │                  │
  │                      │                         │   Insert BD       │              │                  │
  │                      │                         │   (status=PROV)   │              │                  │
  │                      │                         │                   │              │                  │
  │  "Payment link"      │ generate_payment_link   │                   │  Create link │                  │
  │<─────────────────────┤<────────────────────────┤─────────────────────────────────>│                  │
  │                      │                         │                   │              │                  │
  │  [Paga en Stripe]    │                         │                   │              │                  │
  ├──────────────────────────────────────────────────────────────────────────────────>│                  │
  │                      │                         │                   │   Webhook    │                  │
  │                      │                         │                   │<─────────────┤                  │
  │                      │                         │                   │  Redis pub   │                  │
  │                      │                         │                   ├─────────────────────────────────>│
  │                      │                         │                   │              │   Update BD      │
  │                      │                         │                   │              │   PROV→CONFIRMED │
  │                      │                         │                   │<─────────────┤   Update Calendar│
  │                      │                         │                   │   (Green)    │   (Green event)  │
  │                      │                         │                   │              │                  │
  │  "✅ Confirmada"     │                         │                   │              │   Send message   │
  │<─────────────────────────────────────────────────────────────────────────────────────────────────────┤
```

---

## 📁 Estructura de Archivos (Nuevos + Modificados)

```
agent/
├── nodes/
│   ├── appointment_nodes.py        # 🆕 NUEVO - Nodos Fase 2-4
│   ├── availability_nodes.py       # ✏️ MODIFICAR - Añadir validación 3 días
│   └── booking_nodes.py            # ✅ Existente - Ya implementado
├── validators/
│   └── booking_validators.py       # 🆕 NUEVO - Validaciones de negocio
├── workers/
│   ├── booking_expiration_worker.py # 🆕 NUEVO - Expirar reservas
│   └── conversation_archiver.py    # ✅ Existente
├── payment_processor.py            # 🆕 NUEVO - Procesar pagos Stripe
├── state/
│   └── schemas.py                  # ✏️ MODIFICAR - Añadir campos booking
└── graphs/
    └── conversation_flow.py        # ✏️ MODIFICAR - Añadir nodos + routing

database/
└── models.py                       # ✅ Existente - Ya completo

docs/Funcionalidades/
├── agendar-cita.md                 # ✅ Especificación MVP
└── agendar-cita-architecture.md    # 📄 Este documento
```

---

## 🔧 Componentes Detallados

### 1. Validadores de Booking

**Archivo:** `agent/validators/booking_validators.py`

```python
async def validate_min_advance_notice(requested_date: datetime, min_days: int = 3) -> dict:
    """
    Valida que la fecha solicitada tenga al menos 3 días de antelación.

    Returns:
        {"valid": bool, "reason": str | None, "earliest_date": str | None}
    """

async def validate_buffer_between_appointments(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int,
    buffer_minutes: int = 10
) -> dict:
    """
    Valida que haya 10 minutos de buffer entre citas.

    Consulta Google Calendar para verificar que:
    - No hay cita inmediatamente antes (start_time - buffer)
    - No hay cita inmediatamente después (end_time + buffer)

    Returns:
        {"valid": bool, "reason": str | None}
    """
```

### 2. Extensiones al ConversationState

**Archivo:** `agent/state/schemas.py`

```python
# Añadir a ConversationState TypedDict:

# Booking flow tracking
booking_phase: NotRequired[Literal["service_selection", "availability", "customer_data", "payment"]]
selected_slot: NotRequired[dict[str, Any] | None]  # {"time": "15:00", "stylist_id": "...", "date": "2025-11-05"}
selected_stylist_id: NotRequired[UUID | None]
selected_date: NotRequired[str | None]  # YYYY-MM-DD
selected_time: NotRequired[str | None]  # HH:MM

# Appointment tracking
provisional_appointment_id: NotRequired[UUID | None]
payment_link_url: NotRequired[str | None]
payment_timeout_at: NotRequired[datetime | None]
customer_notes: NotRequired[str | None]

# Customer data collection
awaiting_customer_name: NotRequired[bool]
awaiting_customer_notes: NotRequired[bool]
```

### 3. Nodos de Appointment

**Archivo:** `agent/nodes/appointment_nodes.py`

#### 3.1. handle_slot_selection

```python
async def handle_slot_selection(state: ConversationState) -> dict[str, Any]:
    """
    Procesa la selección del cliente de un slot específico tras check_availability.

    Input esperado:
    - state["available_slots"]: Lista de slots disponibles
    - messages[-1]: Mensaje del cliente eligiendo slot

    Usa Claude para clasificar la respuesta:
    - Slot específico seleccionado
    - "Cualquiera" / "El primero"
    - Pide más opciones
    - Unclear

    Output:
    - selected_slot: {"time": "15:00", "stylist_id": "...", "date": "..."}
    - selected_stylist_id: UUID
    - selected_date: "2025-11-05"
    - selected_time: "15:00"
    """
```

#### 3.2. collect_customer_data

```python
async def collect_customer_data(state: ConversationState) -> dict[str, Any]:
    """
    Recopila/confirma datos del cliente (Fase 3).

    Para clientes recurrentes:
    - Muestra datos registrados (nombre, apellido)
    - Pregunta si son correctos o quiere cambiarlos

    Para clientes nuevos:
    - Solicita nombre y apellido

    Para todos:
    - Solicita notas opcionales (alergias, preferencias)

    Output:
    - customer_name: Confirmado/actualizado
    - customer_notes: String o None
    - awaiting_customer_notes: bool
    """
```

#### 3.3. create_provisional_booking

```python
async def create_provisional_booking(state: ConversationState) -> dict[str, Any]:
    """
    Crea reserva provisional en BD y Google Calendar (Fase 4 - parte 1).

    1. Valida buffer de 10 minutos con citas existentes
    2. Calcula precio total y anticipo (20%)
    3. Crea Appointment en BD (status=PROVISIONAL, payment_timeout_at=now+10min)
    4. Crea evento en Google Calendar (color amarillo, título "[PROVISIONAL] Cliente - Servicios")
    5. Guarda appointment_id y timeout en state

    Output:
    - provisional_appointment_id: UUID
    - payment_timeout_at: datetime
    - total_price: Decimal
    - advance_payment_amount: Decimal
    """
```

#### 3.4. generate_payment_link

```python
async def generate_payment_link(state: ConversationState) -> dict[str, Any]:
    """
    Genera enlace de pago con Stripe (Fase 4 - parte 2).

    1. Crea Stripe Payment Link con:
       - amount: advance_payment_amount
       - metadata: {"appointment_id": "..."}
       - success_url: URL de confirmación
       - cancel_url: URL de cancelación

    2. Envía mensaje al cliente con enlace y timeout

    3. Termina el flujo (END) - el pago se procesa async

    Output:
    - payment_link_url: str
    - bot_response: Mensaje con enlace + timeout
    """
```

### 4. Payment Processor

**Archivo:** `agent/payment_processor.py`

```python
class PaymentProcessor:
    """
    Servicio que escucha Redis 'payment_events' y procesa pagos de Stripe.
    """

    async def start(self):
        """Inicia subscriber de Redis."""

    async def handle_checkout_completed(self, event: StripePaymentEvent):
        """
        Procesa checkout.session.completed:

        1. Query Appointment por appointment_id
        2. Validar que status=PROVISIONAL
        3. Actualizar BD: status=PROVISIONAL → CONFIRMED
        4. Actualizar Google Calendar: color amarillo → verde
        5. Enviar mensaje de confirmación via Chatwoot
        """

    async def handle_charge_refunded(self, event: StripePaymentEvent):
        """
        Procesa charge.refunded (cancelaciones futuras):

        1. Query Appointment por stripe_payment_id
        2. Actualizar status=REFUNDED
        3. Eliminar evento de Google Calendar
        4. Notificar cliente
        """
```

### 5. Expiration Worker

**Archivo:** `agent/workers/booking_expiration_worker.py`

```python
async def expire_provisional_bookings():
    """
    Worker que se ejecuta cada 1 minuto.

    1. Query appointments con:
       - status = PROVISIONAL
       - payment_timeout_at < now

    2. Para cada appointment expirada:
       - Actualizar status=EXPIRED
       - Eliminar evento de Google Calendar
       - Notificar cliente via Chatwoot (opcional)

    3. Log métricas
    """
```

### 6. Actualización del Flujo LangGraph

**Archivo:** `agent/graphs/conversation_flow.py`

```python
# AÑADIR nodos:
graph.add_node("handle_slot_selection", handle_slot_selection)
graph.add_node("collect_customer_data", collect_customer_data)
graph.add_node("create_provisional_booking", create_provisional_booking)
graph.add_node("generate_payment_link", generate_payment_link)

# ACTUALIZAR routing después de check_availability:
def route_after_availability_check(state: ConversationState) -> str:
    """
    Si hay slots disponibles → handle_slot_selection
    Si no hay slots → end (alternativas ya sugeridas)
    """
    available_slots = state.get("available_slots", [])
    if available_slots:
        return "handle_slot_selection"
    return "end"

# AÑADIR routing después de slot selection:
def route_after_slot_selection(state: ConversationState) -> str:
    """
    Si slot seleccionado → collect_customer_data
    Si unclear → end (pedir clarificación)
    """
    selected_slot = state.get("selected_slot")
    if selected_slot:
        return "collect_customer_data"
    return "end"

# AÑADIR routing después de customer data:
def route_after_customer_data(state: ConversationState) -> str:
    """
    Si datos completos → create_provisional_booking
    Si awaiting_customer_notes → end (esperar respuesta)
    """
    awaiting = state.get("awaiting_customer_notes", False) or state.get("awaiting_customer_name", False)
    if not awaiting:
        return "create_provisional_booking"
    return "end"

# AÑADIR routing después de provisional booking:
def route_after_provisional_booking(state: ConversationState) -> str:
    """
    Si costo > 0 → generate_payment_link
    Si costo = 0 → finalize_booking (sin pago)
    """
    total_price = state.get("total_price", 0)
    if total_price > 0:
        return "generate_payment_link"
    return "finalize_booking"  # Caso de consulta gratuita

# CONEXIONES:
graph.add_conditional_edges(
    "check_availability",
    route_after_availability_check,
    {"handle_slot_selection": "handle_slot_selection", "end": END}
)

graph.add_conditional_edges(
    "handle_slot_selection",
    route_after_slot_selection,
    {"collect_customer_data": "collect_customer_data", "end": END}
)

graph.add_conditional_edges(
    "collect_customer_data",
    route_after_customer_data,
    {"create_provisional_booking": "create_provisional_booking", "end": END}
)

graph.add_conditional_edges(
    "create_provisional_booking",
    route_after_provisional_booking,
    {"generate_payment_link": "generate_payment_link", "finalize_booking": "finalize_booking"}
)

graph.add_edge("generate_payment_link", END)
graph.add_edge("finalize_booking", END)
```

---

## 🔒 Reglas de Negocio Implementadas

### 1. Antelación Mínima: 3 Días

**Ubicación:** `agent/nodes/availability_nodes.py` - función `check_availability`

```python
# Al inicio del nodo, antes de consultar calendarios:
requested_date = datetime.strptime(requested_date_str, "%Y-%m-%d").replace(tzinfo=TIMEZONE)
current_date = datetime.now(TIMEZONE)
days_difference = (requested_date - current_date).days

if days_difference < 3:
    # Calcular fecha mínima (hoy + 3 días)
    min_date = current_date + timedelta(days=3)
    formatted_min_date = format_spanish_date(min_date)

    response = (
        f"Por política del salón, las citas deben agendarse con al menos 3 días de antelación 😔. "
        f"El primer día disponible es el {formatted_min_date}. "
        f"Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?"
    )

    return {
        "available_slots": [],
        "min_advance_notice_violated": True,
        "bot_response": response,
        "escalation_offered": True
    }
```

### 2. Buffer de 10 Minutos Entre Citas

**Ubicación:** `agent/validators/booking_validators.py`

- Validar en `create_provisional_booking` antes de crear la cita
- Consultar Google Calendar para citas adyacentes
- Rechazar si hay conflicto con buffer

### 3. Restricción de Categorías Mixtas

**Ubicación:** `agent/nodes/booking_nodes.py` - Ya implementado ✅

- `validate_booking_request` rechaza mezcla de Hairdressing + Aesthetics
- Ofrece alternativas: reservar por separado o elegir una categoría

### 4. Anticipo del 20%

**Ubicación:** `agent/nodes/appointment_nodes.py` - `create_provisional_booking`

```python
total_price = calculate_total(service_ids)
advance_payment_amount = total_price * Decimal("0.20")

# Excepción: Si total = 0€, no requiere anticipo
if total_price == 0:
    # Saltar pago, crear appointment CONFIRMED directamente
    status = AppointmentStatus.CONFIRMED
else:
    status = AppointmentStatus.PROVISIONAL
```

### 5. Timeout de Pago: 5-10 Minutos

**Configuración:** Variable de entorno `BOOKING_PAYMENT_TIMEOUT_MINUTES` (default: 10)

**Implementación:**
- `create_provisional_booking`: Establece `payment_timeout_at = now + timeout`
- `booking_expiration_worker`: Revisa cada 1 minuto y cancela expiradas

---

## 🔄 Procesamiento Asíncrono

### Redis Channels Utilizados

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `incoming_messages` | API (Chatwoot) | Agent Main | Chatwoot message |
| `outgoing_messages` | Agent Nodes | API | Bot response |
| `payment_events` | API (Stripe) | Payment Processor | StripePaymentEvent |

### Workers en Ejecución

| Worker | Archivo | Frecuencia | Función |
|--------|---------|------------|---------|
| Conversation Archiver | `agent/workers/conversation_archiver.py` | 5 min | Archivar conversaciones |
| Booking Expiration | `agent/workers/booking_expiration_worker.py` | 1 min | Cancelar reservas expiradas |

---

## 🎯 Ejemplos de Flujo Completo

### Caso 1: Reserva Exitosa con Pago

```
Cliente: "Quiero mechas para el viernes"
Bot: "¡Perfecto! 💇 Tenemos un pack de Mechas + Corte por 80€ (ahorras 10€). ¿Te interesa?"

Cliente: "Sí"
[validate_booking_request, suggest_pack, handle_pack_response]

Bot: "Este viernes tenemos libre a las 15:00 con Marta y a las 17:00 con Pilar. ¿Cuál prefieres? 😊"
[check_availability]

Cliente: "15:00 con Marta"
[handle_slot_selection]

Bot: "Tengo registrado tu nombre como Juan Pérez. ¿Confirmas que esos datos son correctos?"
[collect_customer_data]

Cliente: "Sí, correcto"

Bot: "¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)"
[collect_customer_data - notas]

Cliente: "No, nada"

Bot: "Perfecto, tu cita está casi lista. Para confirmarla, necesito que pagues el anticipo de 16€ (20% del total de 80€).
Enlace de pago: [stripe.com/pay/123]
Una vez procesado el pago, tu cita quedará confirmada automáticamente. Tienes 10 minutos para completar el pago."
[create_provisional_booking, generate_payment_link]

[Cliente paga en Stripe]
[Stripe webhook → Redis → Payment Processor]

Bot: "✅ ¡Tu cita ha sido confirmada!

📅 Resumen de tu cita:
- Fecha: Viernes, 05/11/2025
- Hora: 15:00 - 17:00
- Asistenta: Marta
- Servicios: Mechas + Corte
- Duración: 120 minutos
- Costo total: 80€

💶 Información de pago:
- Anticipo pagado: 16€ ✓
- Saldo pendiente: 64€ (a pagar en el salón)

⚠️ Política de cancelación:
Para modificar o cancelar tu cita, debes hacerlo con al menos 24 horas de antelación.

📍 Ubicación: [Google Maps]

¡Nos vemos pronto en Atrévete! 💇‍♀️"
[Payment Processor envía confirmación]
```

### Caso 2: Reserva con Timeout (No Paga)

```
[... mismo flujo hasta generate_payment_link ...]

Bot: "Enlace de pago: [stripe.com/pay/123]. Tienes 10 minutos."

[Cliente NO paga]
[Pasan 10 minutos]
[Expiration Worker cancela reservation]

Bot: "Lo siento, no recibí la confirmación de tu pago en el tiempo establecido 😔.
La reserva ha sido cancelada para liberar el horario.
Si aún deseas agendar esta cita, puedo ayudarte a reintentar el proceso. ¿Deseas volver a intentarlo?"
```

### Caso 3: Antelación Menor a 3 Días

```
Cliente: "Quiero cita para mañana"

Bot: "Por política del salón, las citas deben agendarse con al menos 3 días de antelación 😔.
El primer día disponible es el jueves 7 de noviembre.
Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?"
[check_availability detecta violación de regla]
```

---

## 📈 Métricas y Monitoreo

### Logs Críticos

```python
# En cada nodo:
logger.info(
    f"Node executed: {node_name}",
    extra={
        "conversation_id": state.get("conversation_id"),
        "customer_id": state.get("customer_id"),
        "appointment_id": state.get("provisional_appointment_id"),
        "booking_phase": state.get("booking_phase")
    }
)
```

### Métricas a Trackear

- **Conversiones:** Tasa de reservas confirmadas / reservas iniciadas
- **Timeouts:** Tasa de reservas expiradas por no pago
- **Antelación:** Distribución de días de antelación (para ajustar política)
- **Disponibilidad:** Tasa de "sin disponibilidad" por fecha
- **Duración:** Tiempo promedio desde inicio hasta confirmación

---

## 🧪 Testing Strategy

### Unit Tests

- `test_validators.py`: Validaciones de antelación y buffer
- `test_appointment_nodes.py`: Cada nodo de appointment
- `test_payment_processor.py`: Procesamiento de eventos Stripe
- `test_expiration_worker.py`: Lógica de expiración

### Integration Tests

- `test_booking_flow_e2e.py`: Flujo completo de reserva
- `test_payment_timeout.py`: Timeout y cancelación
- `test_min_advance_notice.py`: Validación de 3 días

### Manual Testing

- Reserva exitosa con pago
- Reserva sin pago (timeout)
- Reserva con fecha < 3 días
- Reserva con categorías mixtas
- Reserva con buffer violation

---

## 🚀 Deployment

### Docker Compose

```yaml
services:
  # ... servicios existentes ...

  booking-expiration-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.agent
    command: python -m agent.workers.booking_expiration_worker
    environment:
      - DATABASE_URL=postgresql+asyncpg://...
      - GOOGLE_SERVICE_ACCOUNT_JSON=/app/credentials/google-service-account.json
    volumes:
      - ./credentials:/app/credentials:ro
    depends_on:
      - postgres
      - redis
```

### Variables de Entorno Nuevas

```bash
# En .env:
BOOKING_PAYMENT_TIMEOUT_MINUTES=10  # Timeout de pago (default: 10)
STRIPE_PAYMENT_LINK_BASE_URL=https://buy.stripe.com/test_...  # Base URL para Payment Links
BOOKING_EXPIRATION_WORKER_INTERVAL_SECONDS=60  # Frecuencia del worker (default: 60)
```

---

## 📝 Notas de Implementación

### Decisiones de Diseño

1. **¿Por qué PROVISIONAL en lugar de "pendiente de pago"?**
   - Alineado con estados de Appointment existentes (PROVISIONAL, CONFIRMED, EXPIRED)
   - Semántica clara: "reserva provisional hasta confirmar pago"

2. **¿Por qué timeout de 10 minutos?**
   - Balance entre dar tiempo al cliente y no bloquear slots indefinidamente
   - Configurable via env var para ajustar según métricas

3. **¿Por qué Worker separado para expiración?**
   - Desacoplamiento: El flujo de agendamiento no se bloquea esperando timeouts
   - Escalabilidad: Puede procesarse en paralelo independientemente
   - Resiliencia: Si el worker falla, no afecta el flujo principal

4. **¿Por qué Payment Processor como servicio separado?**
   - El procesamiento de pago es asíncrono (webhook → processing)
   - Permite retry logic y error handling independiente
   - No bloquea el flujo conversacional principal

### Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Google Calendar API quota exceeded | Alto | Implementar rate limiting + retry con backoff |
| Stripe webhook no llega | Alto | Worker que verifica pagos pendientes cada 5 min |
| Cliente paga justo cuando expira | Medio | Ventana de gracia de 30 segundos antes de expirar |
| Conflicto de concurrencia (2 clientes mismo slot) | Alto | Lock distribuido con Redis al crear provisional |

---

## 🔮 Futuras Mejoras (Post-MVP)

1. **Modificación de citas** (Epic 5)
   - Cambiar fecha/hora
   - Cambiar servicios
   - Políticas de reembolso

2. **Cancelación con reembolso** (Epic 5)
   - >24h: Reembolso completo
   - <24h: Sin reembolso, ofrecer reprogramar

3. **Recordatorios automáticos** (Epic 6)
   - 24h antes: Recordatorio
   - 2h antes: Recordatorio final

4. **Lista de espera** (Futuro)
   - Si no hay disponibilidad, ofrecer lista de espera
   - Notificar cuando se libere slot

5. **Reservas recurrentes** (Futuro)
   - "Quiero mechas cada 2 meses"
   - Auto-agendar siguientes citas

---

## 📞 Contacto y Soporte

**Documentación relacionada:**
- `docs/Funcionalidades/agendar-cita.md` - Especificación MVP
- `docs/prd.md` - Product Requirements Document
- `CLAUDE.md` - Guía de desarrollo

**Responsable técnico:** Claude Code (claude.ai/code)

---

**Última actualización:** 2025-11-01
**Versión:** 1.0
**Estado:** En Implementación
