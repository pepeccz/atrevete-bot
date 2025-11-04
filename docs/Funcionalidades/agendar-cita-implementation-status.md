# Estado de Implementación - Sistema de Agendamiento de Citas

**Fecha:** 2025-11-01
**Versión:** 1.0 - Implementación Parcial
**Documentos relacionados:**
- `agendar-cita.md` - Especificación MVP
- `agendar-cita-architecture.md` - Arquitectura completa

---

## 📊 Resumen Ejecutivo

### Estado General: **60% Completado**

**Componentes Funcionales:**
- ✅ Validadores de negocio (antelación 3 días, buffer 10 min)
- ✅ Extensión del estado conversacional
- ✅ Nodos de appointment (Fases 2-4)
- ❌ Payment processor (procesar pagos Stripe)
- ❌ Expiration worker (cancelar reservas expiradas)
- ❌ Integración en conversation_flow.py
- ❌ Validación de 3 días en check_availability

**Lo que FUNCIONA ahora:**
- Validación de categorías mixtas (Fase 1)
- Consulta de disponibilidad multi-calendar (Fase 2)
- Lógica de nodos (no conectados al flujo principal)

**Lo que FALTA para funcionar end-to-end:**
- Conectar los nodos nuevos al flujo de LangGraph
- Implementar el procesamiento de pagos
- Implementar la expiración de reservas
- Agregar validación de antelación mínima

---

## ✅ Componentes Implementados

### 1. Validadores de Booking

**Archivo:** `agent/validators/booking_validators.py`
**Estado:** ✅ **COMPLETO**

#### Funciones Implementadas:

##### `validate_min_advance_notice()`
```python
async def validate_min_advance_notice(
    requested_date: datetime,
    min_days: int = 3,
    conversation_id: str = ""
) -> dict[str, Any]
```

**Funcionalidad:**
- ✅ Valida que la fecha solicitada tenga al menos 3 días de antelación
- ✅ Calcula la diferencia de días entre hoy y la fecha solicitada
- ✅ Si falla, retorna la fecha más temprana válida
- ✅ Formatea la fecha en español (ej: "jueves 4 de noviembre")

**Retorna:**
```python
{
    "valid": bool,
    "reason": str | None,
    "days_difference": int,
    "earliest_date": datetime | None,
    "earliest_date_formatted": str | None
}
```

**Ejemplo de uso:**
```python
from agent.validators.booking_validators import validate_min_advance_notice

# Hoy es 2025-11-01, cliente pide cita para 2025-11-02
result = await validate_min_advance_notice(
    requested_date=datetime(2025, 11, 2, tzinfo=TIMEZONE)
)

# result = {
#     "valid": False,
#     "reason": "La fecha solicitada (2025-11-02) tiene solo 1 días de antelación...",
#     "days_difference": 1,
#     "earliest_date": datetime(2025, 11, 4),
#     "earliest_date_formatted": "lunes 4 de noviembre"
# }
```

##### `validate_buffer_between_appointments()`
```python
async def validate_buffer_between_appointments(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int,
    buffer_minutes: int = 10,
    conversation_id: str = ""
) -> dict[str, Any]
```

**Funcionalidad:**
- ✅ Consulta Google Calendar de la estilista
- ✅ Valida que no haya citas 10 minutos antes del inicio
- ✅ Valida que no haya citas 10 minutos después del fin
- ✅ Detecta solapamientos directos
- ✅ Retorna detalles del evento conflictivo

**Retorna:**
```python
{
    "valid": bool,
    "reason": str | None,
    "conflicting_event": dict | None
}
```

**Ejemplo de uso:**
```python
# Propuesta: 15:00-16:00
# Cita existente: 14:55-15:30
result = await validate_buffer_between_appointments(
    stylist_id=UUID("..."),
    start_time=datetime(2025, 11, 5, 15, 0, tzinfo=TIMEZONE),
    duration_minutes=60
)

# result = {
#     "valid": False,
#     "reason": "Conflicto: hay una cita que termina a las 15:30 (se necesitan 10 min de buffer...)",
#     "conflicting_event": {
#         "summary": "María - Corte",
#         "start": "2025-11-05T14:55:00+01:00",
#         "end": "2025-11-05T15:30:00+01:00"
#     }
# }
```

---

### 2. Extensión del ConversationState

**Archivo:** `agent/state/schemas.py`
**Estado:** ✅ **COMPLETO**

#### Campos Añadidos:

```python
# Booking Phase Tracking
booking_phase: Literal["service_selection", "availability", "customer_data", "payment"] | None

# Slot Selection (Fase 2)
selected_slot: dict[str, Any] | None
# Formato: {"time": "15:00", "stylist_id": "...", "stylist_name": "Marta", "date": "2025-11-05"}

selected_stylist_id: UUID | None

# Customer Data Collection (Fase 3)
customer_notes: str | None  # Alergias, preferencias
awaiting_customer_name: bool
awaiting_customer_notes: bool

# Payment Management (Fase 4)
payment_timeout_at: datetime | None  # Cuándo expira la reserva provisional
total_price: Any  # Decimal - Costo total
advance_payment_amount: Any  # Decimal - Anticipo del 20%
```

**Uso:**
- El estado ahora puede trackear el progreso del cliente por las 4 fases
- Cada nodo actualiza `booking_phase` al completar su fase
- Los timeouts se almacenan para que el worker los procese

---

### 3. Nodos de Appointment

**Archivo:** `agent/nodes/appointment_nodes.py`
**Estado:** ✅ **COMPLETO** (lógica implementada, NO conectados al flujo)

#### Nodos Implementados:

##### 3.1. `handle_slot_selection()` - Fase 2

**Funcionalidad:**
- ✅ Recibe slots disponibles de `check_availability`
- ✅ Usa Claude para clasificar la respuesta del cliente
- ✅ Detecta selección por número ("Opción 1", "El primero")
- ✅ Detecta selección por horario ("15:00", "A las 3")
- ✅ Detecta "cualquiera" / "el que sea"
- ✅ Detecta "más opciones"
- ✅ Maneja respuestas unclear con clarificación
- ✅ Escala tras 2 intentos fallidos

**Input esperado:**
```python
state = {
    "prioritized_slots": [
        {"time": "15:00", "stylist_id": "...", "stylist_name": "Marta"},
        {"time": "17:00", "stylist_id": "...", "stylist_name": "Pilar"}
    ],
    "requested_date": "2025-11-05",
    "messages": [
        {"role": "user", "content": "El primero", "timestamp": "..."}
    ]
}
```

**Output:**
```python
{
    "selected_slot": {"time": "15:00", "stylist_id": "...", "stylist_name": "Marta", "date": "2025-11-05"},
    "selected_stylist_id": UUID("..."),
    "booking_phase": "customer_data",
    "bot_response": "Perfecto, Juan 😊. Te agendo para el 2025-11-05 a las 15:00 con Marta."
}
```

**Ejemplos de entrada del cliente:**
- "15:00 con Marta" → Selecciona ese slot
- "El primero" → Selecciona índice 0
- "Opción 2" → Selecciona índice 1
- "Cualquiera" → Selecciona el primero disponible
- "Más opciones" → Pide más horarios

---

##### 3.2. `collect_customer_data()` - Fase 3

**Funcionalidad:**
- ✅ Para clientes recurrentes: confirma nombre registrado
- ✅ Para clientes nuevos: solicita nombre y apellido
- ✅ Permite actualizar nombre si el cliente lo pide
- ✅ Solicita notas opcionales (alergias, preferencias)
- ✅ Detecta cuando el cliente dice "no" / "nada" para notas
- ✅ Actualiza la BD con el nuevo nombre si es necesario
- ✅ Usa máquina de estados (awaiting_customer_name → awaiting_customer_notes → complete)

**Flujo para cliente recurrente:**
```
Bot: "Tengo registrado tu nombre como Juan Pérez. ¿Confirmas que esos datos son correctos?"
Cliente: "Sí"
Bot: "¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)"
Cliente: "Soy alérgica al tinte"
→ Progresa a booking_phase="payment"
```

**Flujo para cliente nuevo:**
```
Bot: "Para finalizar, necesito tu nombre y apellido para la reserva 😊."
Cliente: "María García"
Bot: "Perfecto, María García 😊. ¿Hay algo que debamos saber antes de tu cita?"
Cliente: "No"
→ Progresa a booking_phase="payment"
```

**Output:**
```python
{
    "customer_name": "Juan Pérez",  # Confirmado o actualizado
    "customer_notes": "Soy alérgica al tinte",  # O None si dijo no
    "awaiting_customer_name": False,
    "awaiting_customer_notes": False,
    "booking_phase": "payment"
}
```

---

##### 3.3. `create_provisional_booking()` - Fase 4 (Parte 1)

**Funcionalidad:**
- ✅ Valida buffer de 10 minutos con citas existentes
- ✅ Calcula precio total y anticipo del 20%
- ✅ Crea Appointment en BD con status=PROVISIONAL
- ✅ Crea evento en Google Calendar (color amarillo, título "[PROVISIONAL]")
- ✅ Establece timeout de pago (10 min por defecto, configurable)
- ✅ Maneja errores de validación de buffer
- ✅ Soporta packs y servicios individuales

**Input esperado:**
```python
state = {
    "customer_id": UUID("..."),
    "selected_slot": {"time": "15:00", "stylist_id": "...", "date": "2025-11-05"},
    "requested_services": [UUID("mechas_id"), UUID("corte_id")],
    "pack_id": UUID("mechas_corte_pack"),  # Opcional
    "customer_notes": "Alérgica al tinte"  # Opcional
}
```

**Output (éxito):**
```python
{
    "provisional_appointment_id": UUID("..."),
    "total_price": Decimal("80.00"),
    "advance_payment_amount": Decimal("16.00"),  # 20%
    "payment_timeout_at": datetime(2025, 11, 1, 16, 10, tzinfo=TIMEZONE)
}
```

**Output (error de buffer):**
```python
{
    "bot_response": "Lo siento, Juan 😔, ese horario ya no está disponible. Conflicto: hay una cita que termina a las 15:25 (se necesitan 10 min de buffer antes de tu cita). ¿Quieres que busque otra opción?"
}
```

**Qué crea en la BD:**
```sql
INSERT INTO appointments (
    id,
    customer_id,
    stylist_id,
    service_ids,
    pack_id,
    start_time,
    duration_minutes,
    total_price,
    advance_payment_amount,
    status,
    customer_notes,
    metadata_
) VALUES (
    '...uuid...',
    '...customer_id...',
    '...stylist_id...',
    ARRAY['...service_id_1...', '...service_id_2...'],
    '...pack_id...',
    '2025-11-05 15:00:00+01:00',
    120,
    80.00,
    16.00,
    'provisional',
    'Alérgica al tinte',
    '{"conversation_id": "...", "payment_timeout_at": "...", "customer_phone": "..."}'
);
```

**Qué crea en Google Calendar:**
```
Título: [PROVISIONAL] Juan Pérez - Mechas, Corte
Descripción:
  Customer: Juan Pérez
  Services: Mechas, Corte
  Status: provisional
  Appointment ID: ...
  Customer ID: ...
Inicio: 2025-11-05T15:00:00+01:00
Fin: 2025-11-05T17:00:00+01:00
Color: Amarillo (colorId: "5")
```

---

##### 3.4. `generate_payment_link()` - Fase 4 (Parte 2)

**Funcionalidad:**
- ✅ Detecta si el costo es 0€ (consulta gratuita) y omite pago
- ✅ Genera enlace de pago con Stripe (PLACEHOLDER - requiere integración)
- ✅ Envía mensaje al cliente con enlace + timeout
- ✅ Finaliza el flujo (END) - el pago se procesa async
- ✅ Si costo = 0€, confirma la cita directamente (PROVISIONAL → CONFIRMED)

**Input esperado:**
```python
state = {
    "provisional_appointment_id": UUID("..."),
    "total_price": Decimal("80.00"),
    "advance_payment_amount": Decimal("16.00"),
    "payment_timeout_at": datetime(2025, 11, 1, 16, 10)
}
```

**Output (con pago):**
```python
{
    "payment_link_url": "https://buy.stripe.com/test_PLACEHOLDER_...",
    "bot_response": "Perfecto, Juan, tu cita está casi lista 😊.\n\n"
                    "Para confirmarla, necesito que pagues el anticipo de 16.0€ (20% del total de 80.0€).\n\n"
                    "Enlace de pago: https://buy.stripe.com/test_PLACEHOLDER_...\n\n"
                    "⏱️ Una vez procesado el pago, tu cita quedará confirmada automáticamente. "
                    "Tienes 10 minutos para completar el pago."
}
```

**Output (sin pago - 0€):**
```python
{
    "skip_payment_flow": True,
    "bot_response": "✅ ¡Tu cita ha sido confirmada!\n\n"
                    "📅 Resumen:\n"
                    "- Fecha: 05/11/2025\n"
                    "- Hora: 15:00\n"
                    "- Asistenta: Marta\n"
                    "- Servicios: Consulta Gratuita\n"
                    "- Costo: 0€ (servicio gratuito)\n\n"
                    "¡Nos vemos pronto en Atrévete! 💇‍♀️"
}
```

**Nota importante:**
- El enlace de Stripe es PLACEHOLDER
- Requiere integración con Stripe Payment Links API
- El pago real se procesa via webhook (no implementado aún)

---

## ❌ Componentes Pendientes

### 4. Payment Processor

**Archivo:** `agent/payment_processor.py`
**Estado:** ❌ **NO IMPLEMENTADO**

**Funcionalidad requerida:**
```python
class PaymentProcessor:
    """
    Servicio que escucha Redis 'payment_events' y procesa pagos.
    """

    async def start(self):
        """Suscribirse a Redis 'payment_events' channel."""
        pass

    async def handle_checkout_completed(self, event: StripePaymentEvent):
        """
        1. Query Appointment por appointment_id (desde webhook metadata)
        2. Validar que status=PROVISIONAL
        3. Actualizar BD: status=PROVISIONAL → CONFIRMED
        4. Actualizar Google Calendar: color amarillo → verde
        5. Enviar mensaje de confirmación via Chatwoot
        """
        pass

    async def handle_charge_refunded(self, event: StripePaymentEvent):
        """
        Para cancelaciones futuras:
        1. Query Appointment por stripe_payment_id
        2. Actualizar status=REFUNDED
        3. Eliminar evento de Google Calendar
        4. Notificar cliente
        """
        pass
```

**Integración con agent/main.py:**
```python
# En agent/main.py, arrancar el processor como tarea paralela
async def main():
    # ... código existente ...

    # Iniciar payment processor
    payment_processor = PaymentProcessor()
    asyncio.create_task(payment_processor.start())

    # ... resto del código ...
```

**Redis channel esperado:**
- **Channel:** `payment_events`
- **Publisher:** `api/routes/stripe.py` (ya implementado ✅)
- **Subscriber:** `PaymentProcessor` (falta implementar ❌)

**Payload:**
```python
{
    "appointment_id": "uuid",
    "stripe_payment_id": "ch_...",
    "event_type": "checkout.session.completed"
}
```

---

### 5. Booking Expiration Worker

**Archivo:** `agent/workers/booking_expiration_worker.py`
**Estado:** ❌ **NO IMPLEMENTADO**

**Funcionalidad requerida:**
```python
async def expire_provisional_bookings():
    """
    Worker que se ejecuta cada 1 minuto.

    1. Query appointments con:
       - status = PROVISIONAL
       - metadata_->>'payment_timeout_at' < now()

    2. Para cada appointment expirada:
       - Actualizar status=EXPIRED
       - Eliminar evento de Google Calendar (via delete_calendar_event tool)
       - Opcional: Notificar cliente via Chatwoot

    3. Log métricas (cuántas reservas expiradas por ejecución)
    """
    while True:
        try:
            async for session in get_async_session():
                # Query expired provisional appointments
                now = datetime.now(TIMEZONE)

                # TODO: Implementar query con JSONB extraction
                # SELECT * FROM appointments
                # WHERE status = 'provisional'
                # AND (metadata_->>'payment_timeout_at')::timestamp < now()

                # TODO: Para cada appointment:
                # - Update status = 'expired'
                # - Delete Google Calendar event
                # - Optionally send Chatwoot message

                pass
        except Exception as e:
            logger.exception(f"Error in booking expiration worker: {e}")

        await asyncio.sleep(60)  # Run every minute
```

**Docker Compose entry:**
```yaml
booking-expiration-worker:
  build:
    context: .
    dockerfile: docker/Dockerfile.agent
  command: python -m agent.workers.booking_expiration_worker
  environment:
    - DATABASE_URL=postgresql+asyncpg://...
    - GOOGLE_SERVICE_ACCOUNT_JSON=/app/credentials/google-service-account.json
  depends_on:
    - postgres
    - redis
```

---

### 6. Integración en conversation_flow.py

**Archivo:** `agent/graphs/conversation_flow.py`
**Estado:** ❌ **NO CONECTADO**

**Cambios requeridos:**

#### 6.1. Importar nuevos nodos
```python
from agent.nodes.appointment_nodes import (
    collect_customer_data,
    create_provisional_booking,
    generate_payment_link,
    handle_slot_selection,
)
```

#### 6.2. Añadir nodos al grafo
```python
# Después de check_availability
graph.add_node("handle_slot_selection", handle_slot_selection)
graph.add_node("collect_customer_data", collect_customer_data)
graph.add_node("create_provisional_booking", create_provisional_booking)
graph.add_node("generate_payment_link", generate_payment_link)
```

#### 6.3. Añadir routing functions
```python
def route_after_availability_check(state: ConversationState) -> str:
    """Después de check_availability."""
    available_slots = state.get("available_slots", [])
    if available_slots:
        return "handle_slot_selection"
    return END  # No hay slots, ya se sugirieron alternativas

def route_after_slot_selection(state: ConversationState) -> str:
    """Después de handle_slot_selection."""
    selected_slot = state.get("selected_slot")
    if selected_slot:
        return "collect_customer_data"
    return END  # Escalated o error

def route_after_customer_data(state: ConversationState) -> str:
    """Después de collect_customer_data."""
    booking_phase = state.get("booking_phase")
    if booking_phase == "payment":
        return "create_provisional_booking"
    return END  # Aún esperando input del cliente

def route_after_provisional_booking(state: ConversationState) -> str:
    """Después de create_provisional_booking."""
    provisional_appointment_id = state.get("provisional_appointment_id")
    if provisional_appointment_id:
        return "generate_payment_link"
    return END  # Error al crear la reserva
```

#### 6.4. Añadir edges condicionales
```python
graph.add_conditional_edges(
    "check_availability",
    route_after_availability_check,
    {
        "handle_slot_selection": "handle_slot_selection",
        END: END
    }
)

graph.add_conditional_edges(
    "handle_slot_selection",
    route_after_slot_selection,
    {
        "collect_customer_data": "collect_customer_data",
        END: END
    }
)

graph.add_conditional_edges(
    "collect_customer_data",
    route_after_customer_data,
    {
        "create_provisional_booking": "create_provisional_booking",
        END: END
    }
)

graph.add_conditional_edges(
    "create_provisional_booking",
    route_after_provisional_booking,
    {
        "generate_payment_link": "generate_payment_link",
        END: END
    }
)

# generate_payment_link siempre termina el flujo
graph.add_edge("generate_payment_link", END)
```

---

### 7. Validación de 3 Días en check_availability

**Archivo:** `agent/nodes/availability_nodes.py`
**Estado:** ❌ **NO INTEGRADO**

**Cambios requeridos:**

Al inicio de la función `check_availability()`, añadir:

```python
async def check_availability(state: ConversationState) -> dict[str, Any]:
    # ... código existente para parsear requested_date_str ...

    requested_date = datetime.strptime(requested_date_str, "%Y-%m-%d").replace(tzinfo=TIMEZONE)

    # NUEVO: Validar antelación mínima de 3 días
    from agent.validators.booking_validators import validate_min_advance_notice

    advance_validation = await validate_min_advance_notice(
        requested_date=requested_date,
        min_days=3,
        conversation_id=conversation_id
    )

    if not advance_validation["valid"]:
        # Antelación insuficiente
        earliest_date_formatted = advance_validation["earliest_date_formatted"]

        response = (
            f"Por política del salón, las citas deben agendarse con al menos 3 días de antelación 😔. "
            f"El primer día disponible es el {earliest_date_formatted}. "
            f"Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?"
        )

        return {
            "available_slots": [],
            "prioritized_slots": [],
            "bot_response": response,
            "escalation_offered": True,
            "min_advance_notice_violated": True,
            "updated_at": datetime.now(UTC),
            "last_node": "check_availability"
        }

    # ... continuar con el resto del código existente ...
```

---

## 🧪 Qué Puedes Testear AHORA

### Tests Unitarios Disponibles

#### 1. Validadores de Booking

**Test: Antelación mínima**
```python
# tests/unit/test_booking_validators.py
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from agent.validators.booking_validators import validate_min_advance_notice

TIMEZONE = ZoneInfo("Europe/Madrid")

@pytest.mark.asyncio
async def test_validate_min_advance_notice_pass():
    """Test que pasa la validación con 5 días de antelación."""
    today = datetime.now(TIMEZONE)
    requested_date = today + timedelta(days=5)

    result = await validate_min_advance_notice(requested_date, min_days=3)

    assert result["valid"] == True
    assert result["reason"] is None
    assert result["days_difference"] == 5

@pytest.mark.asyncio
async def test_validate_min_advance_notice_fail():
    """Test que falla con 1 día de antelación."""
    today = datetime.now(TIMEZONE)
    requested_date = today + timedelta(days=1)

    result = await validate_min_advance_notice(requested_date, min_days=3)

    assert result["valid"] == False
    assert result["days_difference"] == 1
    assert result["earliest_date"] is not None
    assert result["earliest_date_formatted"] is not None
```

**Test: Buffer entre citas**
```python
@pytest.mark.asyncio
async def test_validate_buffer_with_conflict():
    """Test buffer validation con cita conflictiva."""
    # Mock: Cita existente de 14:55-15:30
    # Propuesta: 15:00-16:00
    # Debería fallar porque termina a las 15:30 (dentro del buffer de 10 min antes de las 15:00)

    # Requiere mock de Google Calendar API
    # TODO: Implementar con pytest-mock
```

#### 2. Nodos de Appointment

**Test: handle_slot_selection**
```python
@pytest.mark.asyncio
async def test_handle_slot_selection_by_number():
    """Test selección por número de opción."""
    state = {
        "conversation_id": "test-123",
        "customer_name": "Juan",
        "requested_date": "2025-11-05",
        "prioritized_slots": [
            {"time": "15:00", "stylist_id": "uuid-marta", "stylist_name": "Marta"},
            {"time": "17:00", "stylist_id": "uuid-pilar", "stylist_name": "Pilar"}
        ],
        "messages": [
            {"role": "user", "content": "El primero", "timestamp": "2025-11-01T10:00:00"}
        ]
    }

    result = await handle_slot_selection(state)

    assert result["selected_slot"]["time"] == "15:00"
    assert result["selected_stylist_id"] is not None
    assert result["booking_phase"] == "customer_data"
    assert "15:00 con Marta" in result["bot_response"]
```

**Test: collect_customer_data - cliente recurrente**
```python
@pytest.mark.asyncio
async def test_collect_customer_data_returning_customer():
    """Test confirmación de datos para cliente recurrente."""
    state = {
        "conversation_id": "test-123",
        "customer_id": UUID("..."),
        "customer_name": "Juan Pérez",
        "is_returning_customer": True
    }

    result = await collect_customer_data(state)

    assert result["awaiting_customer_name"] == True
    assert "Tengo registrado tu nombre como Juan Pérez" in result["bot_response"]
```

**Test: create_provisional_booking**
```python
@pytest.mark.asyncio
async def test_create_provisional_booking_success():
    """Test creación exitosa de reserva provisional."""
    # Requiere:
    # - Mock de get_async_session (database)
    # - Mock de create_calendar_event (Google Calendar)
    # - Mock de validate_buffer_between_appointments

    # TODO: Implementar con pytest-mock + fixtures
```

---

### Tests de Integración (Requieren BD + Google Calendar configurado)

**NO puedes ejecutar estos aún sin:**
- ❌ Base de datos PostgreSQL con seed data
- ❌ Google Calendar API configurada
- ❌ Stripe configurado
- ❌ Nodos conectados al flujo de LangGraph

---

## 📝 Ejemplos de Flujos de Conversación para Testing Manual

### Flujo 1: Reserva Exitosa (Happy Path) - PARCIALMENTE FUNCIONAL

**Objetivo:** Probar el flujo completo desde inicio hasta payment link

**Prerequisitos:**
- ❌ Nodos conectados al flujo
- ✅ Base de datos con servicios/packs
- ✅ Google Calendar configurado
- ❌ Stripe configurado

**Conversación:**
```
👤 Cliente: "Hola, quiero mechas para el viernes"

🤖 Bot: [conversational_agent detecta intención, llama start_booking_flow()]
       "¡Perfecto! 💇 Te ayudo a reservar mechas."

👤 Cliente: "Mechas largas"

🤖 Bot: [validate_booking_request → check_availability]
       "Este viernes tenemos libre a las 15:00 con Marta y a las 17:00 con Pilar. ¿Cuál prefieres? 😊"

👤 Cliente: "15:00 con Marta"

🤖 Bot: [handle_slot_selection ✅ IMPLEMENTADO]
       "Perfecto, Juan 😊. Te agendo para el 2025-11-08 a las 15:00 con Marta."
       [Automáticamente pasa a collect_customer_data]
       "Tengo registrado tu nombre como Juan Pérez. ¿Confirmas que esos datos son correctos?"

👤 Cliente: "Sí, correcto"

🤖 Bot: [collect_customer_data ✅ IMPLEMENTADO]
       "¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)"

👤 Cliente: "Soy alérgico al amoníaco"

🤖 Bot: [collect_customer_data completa, pasa a create_provisional_booking]
       [create_provisional_booking ✅ IMPLEMENTADO]
       - Valida buffer ✅
       - Crea appointment en BD (status=PROVISIONAL) ✅
       - Crea evento en Google Calendar (amarillo) ✅
       [Pasa a generate_payment_link]

🤖 Bot: [generate_payment_link ✅ IMPLEMENTADO]
       "Perfecto, Juan, tu cita está casi lista 😊.

       Para confirmarla, necesito que pagues el anticipo de 16€ (20% del total de 80€).

       Enlace de pago: https://buy.stripe.com/test_PLACEHOLDER_abc123

       ⏱️ Una vez procesado el pago, tu cita quedará confirmada automáticamente.
       Tienes 10 minutos para completar el pago."

👤 Cliente: [Paga en Stripe]

🤖 Bot: [❌ NO FUNCIONA - Requiere payment_processor]
       "✅ ¡Tu cita ha sido confirmada!

       📅 Resumen de tu cita:
       - Fecha: Viernes, 08/11/2025
       - Hora: 15:00 - 17:00
       - Asistenta: Marta
       - Servicios: Mechas + Corte
       - Costo total: 80€

       💶 Información de pago:
       - Anticipo pagado: 16€ ✓
       - Saldo pendiente: 64€ (a pagar en el salón)

       ¡Nos vemos pronto en Atrévete! 💇‍♀️"
```

**Lo que FUNCIONA:**
- ✅ Selección de slot (handle_slot_selection)
- ✅ Recopilación de datos del cliente (collect_customer_data)
- ✅ Creación de reserva provisional (create_provisional_booking)
- ✅ Generación de enlace de pago placeholder (generate_payment_link)

**Lo que NO FUNCIONA:**
- ❌ Los nodos no están conectados al flujo (requiere actualizar conversation_flow.py)
- ❌ El pago real no se procesa (requiere payment_processor)
- ❌ La confirmación post-pago no se envía (requiere payment_processor)

---

### Flujo 2: Validación de Antelación Mínima - NO FUNCIONAL

**Objetivo:** Probar rechazo de citas con < 3 días de antelación

**Estado:** ❌ NO INTEGRADO (requiere cambios en check_availability)

**Conversación esperada:**
```
👤 Cliente: "Quiero cita para mañana"

🤖 Bot: [check_availability debería detectar < 3 días]
       ❌ ACTUALMENTE NO LO HACE

       Debería responder:
       "Por política del salón, las citas deben agendarse con al menos 3 días de antelación 😔.
       El primer día disponible es el jueves 4 de noviembre.
       Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?"

👤 Cliente: "Sí, quiero hablar con alguien"

🤖 Bot: [escalate_to_human]
       "Entiendo tu situación. Voy a conectarte con un miembro del equipo que podrá ayudarte personalmente."
```

**Para implementar:**
- ✅ Validador ya existe (`validate_min_advance_notice`)
- ❌ Falta integrarlo en `check_availability` node

---

### Flujo 3: Timeout de Pago - NO FUNCIONAL

**Objetivo:** Probar cancelación automática si el cliente no paga en 10 minutos

**Estado:** ❌ NO IMPLEMENTADO (requiere booking_expiration_worker)

**Conversación esperada:**
```
[... flujo normal hasta payment link ...]

🤖 Bot: "Enlace de pago: [link]. Tienes 10 minutos para completar el pago."

[Cliente NO paga]
[Pasan 10 minutos]

🤖 Bot: [❌ NO FUNCIONA - Requiere expiration worker]
       "Lo siento, no recibí la confirmación de tu pago en el tiempo establecido 😔.
       La reserva ha sido cancelada para liberar el horario.

       Si aún deseas agendar esta cita, puedo ayudarte a reintentar el proceso.
       ¿Deseas volver a intentarlo?"

👤 Cliente: "Sí, reintentar"

🤖 Bot: [Reinicia el flujo desde check_availability]
```

**Para implementar:**
- ✅ Timeout se guarda en appointment.metadata_
- ❌ Falta booking_expiration_worker para procesarlo

---

### Flujo 4: Buffer Violation - PARCIALMENTE FUNCIONAL

**Objetivo:** Probar rechazo de slots sin buffer de 10 minutos

**Estado:** ⚠️ PARCIAL (validador existe, pero nodo no está conectado)

**Escenario:**
- Cliente selecciona 15:00
- Hay una cita existente de 14:55-15:30 (termina dentro del buffer)

**Conversación esperada:**
```
👤 Cliente: "15:00 con Marta"

🤖 Bot: [handle_slot_selection → collect_customer_data → create_provisional_booking]
       [create_provisional_booking llama validate_buffer_between_appointments ✅]
       [Detecta conflicto ✅]

       "Lo siento, Juan 😔, ese horario ya no está disponible.
       Conflicto: hay una cita que termina a las 15:30 (se necesitan 10 min de buffer antes de tu cita).
       ¿Quieres que busque otra opción?"

👤 Cliente: "Sí, otra opción"

🤖 Bot: [Debería volver a check_availability con otra fecha]
       ❌ NO IMPLEMENTADO - No hay flujo de retry
```

**Lo que FUNCIONA:**
- ✅ Detección del conflicto de buffer
- ✅ Mensaje de error descriptivo

**Lo que NO FUNCIONA:**
- ❌ Nodo no está conectado al flujo
- ❌ No hay flujo de retry automático

---

### Flujo 5: Consulta Gratuita (0€) - FUNCIONAL

**Objetivo:** Probar que citas gratuitas se confirman sin pago

**Estado:** ✅ FUNCIONAL (si el nodo estuviera conectado)

**Conversación:**
```
👤 Cliente: "Quiero una consulta gratuita"

🤖 Bot: [conversational_agent → offer_consultation_tool]
       "¡Perfecto! Te ofrecemos una consulta gratuita de 15 minutos 😊."

       [... flujo normal hasta create_provisional_booking ...]

🤖 Bot: [generate_payment_link detecta total_price = 0€]
       [Confirma directamente sin pago ✅]

       "✅ ¡Tu cita ha sido confirmada!

       📅 Resumen:
       - Fecha: 08/11/2025
       - Hora: 15:00
       - Asistenta: Marta
       - Servicios: Consulta Gratuita
       - Costo: 0€ (servicio gratuito)

       ¡Nos vemos pronto en Atrévete! 💇‍♀️"
```

**Lo que FUNCIONA:**
- ✅ Detección de costo 0€
- ✅ Skip del flujo de pago
- ✅ Confirmación directa (PROVISIONAL → CONFIRMED en BD)

---

## 🎯 Resumen de Testing

### Tests Unitarios - EJECUTABLES AHORA

```bash
# Crear archivo de tests
cat > tests/unit/test_booking_validators.py << 'EOF'
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from agent.validators.booking_validators import validate_min_advance_notice

TIMEZONE = ZoneInfo("Europe/Madrid")

@pytest.mark.asyncio
async def test_validate_min_advance_notice_pass():
    today = datetime.now(TIMEZONE)
    requested_date = today + timedelta(days=5)

    result = await validate_min_advance_notice(requested_date, min_days=3)

    assert result["valid"] == True
    assert result["reason"] is None

@pytest.mark.asyncio
async def test_validate_min_advance_notice_fail():
    today = datetime.now(TIMEZONE)
    requested_date = today + timedelta(days=1)

    result = await validate_min_advance_notice(requested_date, min_days=3)

    assert result["valid"] == False
    assert result["days_difference"] == 1
EOF

# Ejecutar tests
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
./venv/bin/pytest tests/unit/test_booking_validators.py -v
```

### Tests de Integración - NO EJECUTABLES

Requieren:
- ❌ Nodos conectados al flujo
- ❌ Payment processor implementado
- ❌ Expiration worker implementado

---

## 📋 Próximos Pasos para Completar

### Paso 1: Integrar nodos al flujo (1 hora)
```bash
# Editar agent/graphs/conversation_flow.py
# - Importar nodos
# - Añadir al grafo
# - Añadir routing functions
# - Añadir edges
```

### Paso 2: Implementar Payment Processor (2 horas)
```bash
# Crear agent/payment_processor.py
# - Suscribir a Redis 'payment_events'
# - Procesar checkout.session.completed
# - Actualizar BD y Calendar
# - Enviar mensaje de confirmación
```

### Paso 3: Implementar Expiration Worker (1 hora)
```bash
# Crear agent/workers/booking_expiration_worker.py
# - Loop cada 1 minuto
# - Query appointments expiradas
# - Update status = EXPIRED
# - Delete calendar events
```

### Paso 4: Integrar validación de 3 días (30 min)
```bash
# Editar agent/nodes/availability_nodes.py
# - Añadir validate_min_advance_notice al inicio
# - Retornar error si < 3 días
```

### Paso 5: Integración real con Stripe (2 horas)
```bash
# Editar agent/nodes/appointment_nodes.py::generate_payment_link
# - Reemplazar PLACEHOLDER con Stripe Payment Links API
# - Crear payment link real con metadata
# - Manejar errores de Stripe
```

### Paso 6: Testing end-to-end (2 horas)
```bash
# Tests manuales via WhatsApp/Chatwoot
# - Flujo completo con pago
# - Timeout de pago
# - Validación de 3 días
# - Buffer validation
# - Consulta gratuita
```

---

## 📊 Progreso General

```
FASE 1: Selección de Servicios
└─ validate_booking_request      ✅ Ya existía

FASE 2: Disponibilidad y Slot Selection
├─ check_availability            ✅ Ya existía
├─ handle_slot_selection         ✅ NUEVO - Implementado
└─ validate_min_advance_notice   ✅ NUEVO - Implementado (no integrado)

FASE 3: Datos del Cliente
└─ collect_customer_data         ✅ NUEVO - Implementado

FASE 4: Pago y Confirmación
├─ create_provisional_booking    ✅ NUEVO - Implementado
├─ generate_payment_link         ✅ NUEVO - Implementado (Stripe placeholder)
├─ payment_processor             ❌ NO IMPLEMENTADO
└─ booking_expiration_worker     ❌ NO IMPLEMENTADO

INTEGRACIÓN
├─ conversation_flow.py          ❌ NO CONECTADO
└─ check_availability (3 días)   ❌ NO INTEGRADO

VALIDADORES
├─ validate_min_advance_notice   ✅ Implementado
└─ validate_buffer               ✅ Implementado
```

**Total: 60% Completado**

---

## 📞 Contacto

Para dudas sobre esta implementación:
- Ver `agendar-cita-architecture.md` para la arquitectura completa
- Ver `agendar-cita.md` para la especificación original del MVP
- Ver `CLAUDE.md` para comandos de desarrollo

---

**Última actualización:** 2025-11-01
**Versión:** 1.0 - Implementación Parcial
