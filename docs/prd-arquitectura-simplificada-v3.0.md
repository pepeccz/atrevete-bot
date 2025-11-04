# Atrévete Bot - PRD Arquitectura Simplificada v3.0
## De Arquitectura Híbrida (12 nodos) a Arquitectura Tool-Based (1 nodo + 7 herramientas)

**Versión:** 3.0.1
**Fecha:** 2025-11-04
**Autor:** Análisis de Simplificación Arquitectónica
**Estado:** PROPUESTA PARA REVISIÓN
**Última actualización:** 2025-11-04 - Simplificada estrategia de migración (reemplazo directo sin carpetas v3)

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Análisis de la Arquitectura Actual](#2-análisis-de-la-arquitectura-actual)
3. [Arquitectura Propuesta v3.0](#3-arquitectura-propuesta-v30)
4. [Plan de Migración Detallado](#4-plan-de-migración-detallado)
5. [Especificación de Componentes Nuevos](#5-especificación-de-componentes-nuevos)
6. [Mapeo de Datos y Modelos](#6-mapeo-de-datos-y-modelos)
7. [Checklist de Implementación](#7-checklist-de-implementación)
8. [Gestión de Riesgos](#8-gestión-de-riesgos)
9. [Métricas de Éxito](#9-métricas-de-éxito)

---

## 1. Resumen Ejecutivo

### 1.1 Motivación

La arquitectura actual (v2.0 - Híbrida) implementa una separación entre:
- **Tier 1** (Conversacional): Claude con 13 herramientas
- **Tier 2** (Transaccional): 11 nodos LangGraph explícitos

Sin embargo, **ambos tiers ya usan Claude internamente**:
- Tier 1: Claude decide qué herramientas llamar
- Tier 2: Los nodos como `handle_slot_selection` y `collect_customer_data` usan Claude para clasificar respuestas

**Problema identificado:** La separación es artificial y genera:
- ❌ 663 líneas de lógica de routing que Claude podría manejar
- ❌ 50 campos de estado con flags de transición (`awaiting_X`, `booking_phase`)
- ❌ Duplicación de lógica (Claude razona + nodos validan)
- ❌ Dificultad para añadir nuevas operaciones (modificar/cancelar)

### 1.2 Propuesta

**Arquitectura Tool-Based Simplificada:**
```
1 Agente Conversacional (Claude Sonnet 4)
  └─ Llama 7 herramientas cuando las necesita
      ├─ 4 herramientas informativas (stateless)
      ├─ 2 herramientas transaccionales ATÓMICAS (book, modify/cancel)
      └─ 1 herramienta de escalación
```

**Beneficios cuantificados:**
- ✅ De 12 nodos → **1 nodo** (-92%)
- ✅ De 663 líneas routing → **10 líneas** (-98%)
- ✅ De 50 campos estado → **15 campos** (-70%)
- ✅ De 13 herramientas → **7 herramientas** (-46% más consolidadas)
- ✅ Costo: ~15-18 llamadas Claude/booking (vs 12-20 actual)
- ✅ Latencia: 8-12 segundos (vs 10-15 actual)

### 1.3 Alcance de la Migración

**QUÉ SE MANTIENE (Reutilizable 100%):**
- ✅ Infraestructura Docker Compose (4 servicios + 3 workers)
- ✅ PostgreSQL completo (8 tablas, todos los modelos, migraciones)
- ✅ Redis Stack 7.4.0 con checkpointing
- ✅ FastAPI webhook receiver (Chatwoot + Stripe)
- ✅ Integraciones externas (Google Calendar, Stripe, Anthropic)
- ✅ Prompts de Maite (31KB system prompt)
- ✅ Tests existentes (350 tests, estructura completa)
- ✅ .env, configuración, logging JSON

**QUÉ SE REFACTORIZA:**
- 🔄 12 nodos LangGraph → 1 nodo `conversational_agent`
- 🔄 13 herramientas dispersas → 7 herramientas consolidadas
- 🔄 Lógica transaccional de nodos → `BookingTransaction` class
- 🔄 Estado de 50 campos → Estado de 15 campos

**QUÉ SE ELIMINA:**
- ❌ `agent/graphs/conversation_flow.py` routing (663 líneas)
- ❌ 11 nodos transaccionales (validate_booking, check_availability, handle_slot_selection, etc.)
- ❌ 35 campos de estado obsoletos (`awaiting_X`, `booking_phase`, etc.)

---

## 2. Análisis de la Arquitectura Actual

### 2.1 Componentes Existentes

#### 2.1.1 Infraestructura (Docker Compose)

```yaml
# docker-compose.yml (MANTENER 100%)
services:
  postgres:        # PostgreSQL 15 - Base de datos principal
  redis:           # Redis Stack - Checkpointing + pub/sub
  api:             # FastAPI - Webhook receiver (Chatwoot + Stripe)
  agent:           # LangGraph - Orquestador conversacional
  archiver:        # Worker - Archiva conversaciones Redis → PostgreSQL
  payment_processor:  # Worker - Procesa webhooks de pago
  booking_expiration: # Worker - Expira reservas provisionales
```

**Decisión:** MANTENER sin cambios. La arquitectura de servicios está bien diseñada.

#### 2.1.2 Modelos de Base de Datos

```python
# database/models.py (MANTENER 100%)

# Tablas principales (8):
- Customer          # Clientes (phone E.164, nombres, historial)
  ├─ first_name: str
  ├─ last_name: str | None
  ├─ phone: str (unique, indexed)
  ├─ total_spent: Decimal
  ├─ preferred_stylist_id: UUID | None
  └─ metadata: JSONB

- Stylist           # Profesionales (categoría, Google Calendar)
  ├─ name: str
  ├─ category: ServiceCategory (Peluquería | Estética)
  ├─ google_calendar_id: str
  └─ is_active: bool

- Service           # Servicios individuales (92 servicios)
  ├─ name: str
  ├─ category: ServiceCategory
  ├─ duration_minutes: int        # ← CRÍTICO para cálculos
  ├─ price_euros: Decimal          # ← CRÍTICO para cálculos
  ├─ requires_advance_payment: bool
  └─ description: text

- Appointment       # Citas (provisional → confirmed)
  ├─ customer_id: UUID
  ├─ stylist_id: UUID
  ├─ service_ids: UUID[]           # Array de servicios
  ├─ start_time: datetime (Europe/Madrid)
  ├─ duration_minutes: int         # Suma de servicios
  ├─ total_price: Decimal          # Suma de precios
  ├─ advance_payment_amount: Decimal  # 20% del total
  ├─ payment_status: enum (pending | confirmed | refunded)
  ├─ status: enum (provisional | confirmed | completed | cancelled | expired)
  ├─ google_calendar_event_id: str | None
  ├─ stripe_payment_id: str | None
  └─ stripe_payment_link_id: str | None

- Payment           # Registro de pagos Stripe
  ├─ appointment_id: UUID
  ├─ stripe_payment_intent_id: str
  ├─ amount: Decimal
  └─ status: PaymentStatus

- Policy            # Reglas de negocio + FAQs (JSONB)
- ConversationHistory  # Archivo de mensajes
- BusinessHours     # Horarios del salón
```

**Decisión:** MANTENER 100%. Todos los modelos están bien diseñados y serán utilizados por las nuevas herramientas.

#### 2.1.3 Estado Conversacional Actual

```python
# agent/state/schemas.py (REFACTORIZAR)

class ConversationState(TypedDict, total=False):
    # === CAMPOS A MANTENER (15 campos) ===
    conversation_id: str
    customer_phone: str
    customer_id: UUID | None
    customer_name: str | None
    messages: list[dict]  # Últimos 10
    conversation_summary: str | None
    total_message_count: int
    metadata: dict
    created_at: datetime
    updated_at: datetime
    last_node: str | None
    error_count: int
    escalation_triggered: bool
    escalation_reason: str | None

    # === CAMPOS A ELIMINAR (35 campos) ===
    # Booking context (Tier 2 state)
    booking_intent_confirmed: bool  # ← ELIMINAR (Claude decide)
    requested_services: list[UUID]  # ← ELIMINAR (parámetro de tool)
    requested_date: str | None      # ← ELIMINAR (parámetro de tool)
    requested_time: str | None      # ← ELIMINAR (parámetro de tool)
    available_slots: list[dict]     # ← ELIMINAR (resultado de tool)
    prioritized_slots: list[dict]   # ← ELIMINAR (Claude presenta)
    selected_slot: dict | None      # ← ELIMINAR (parámetro de tool)
    booking_phase: str | None       # ← ELIMINAR (no hay fases)
    booking_validation_passed: bool # ← ELIMINAR (validación interna)
    mixed_category_detected: bool   # ← ELIMINAR (validación interna)
    provisional_appointment_id: UUID | None  # ← ELIMINAR (resultado de tool)
    payment_link_url: str | None    # ← ELIMINAR (resultado de tool)
    # ... 23 campos más de tracking transaccional
```

**Decisión:** REDUCIR de 50 → 15 campos. La mayoría de campos transaccionales se convierten en parámetros/resultados de herramientas.

#### 2.1.4 Nodos LangGraph Actuales

```python
# agent/graphs/conversation_flow.py (REFACTORIZAR COMPLETO)

# NODOS ACTUALES (12 nodos):
1. process_incoming_message        # ← ELIMINAR (logic integrada en agent)
2. conversational_agent            # ← MANTENER (único nodo)
3. summarize_conversation          # ← INTEGRAR en conversational_agent
4. booking_handler                 # ← ELIMINAR (book() tool)
5. validate_booking_request        # ← ELIMINAR (validación en BookingTransaction)
6. handle_category_choice          # ← ELIMINAR (Claude maneja diálogo)
7. check_availability              # ← ELIMINAR (check_availability() tool)
8. handle_slot_selection           # ← ELIMINAR (Claude maneja selección)
9. collect_customer_data           # ← ELIMINAR (Claude pregunta directamente)
10. create_provisional_booking     # ← ELIMINAR (parte de book() tool)
11. generate_payment_link          # ← ELIMINAR (parte de book() tool)
12. modification/cancellation handlers  # ← ELIMINAR (modify/cancel tools)
```

**Decisión:** CONSOLIDAR todo en `conversational_agent` + herramientas atómicas.

#### 2.1.5 Herramientas Actuales

```python
# agent/tools/* (CONSOLIDAR 13 → 7)

# INFORMATIVAS (Mantener con consolidación):
- get_customer_by_phone()         # ← MANTENER
- create_customer()                # ← CONSOLIDAR en manage_customer()
- get_services()                   # ← CONSOLIDAR en query_info()
- get_faqs()                       # ← CONSOLIDAR en query_info()
- get_business_hours()             # ← CONSOLIDAR en query_info()
- get_payment_policies()           # ← CONSOLIDAR en query_info()
- get_cancellation_policy()        # ← CONSOLIDAR en query_info()

# DISPONIBILIDAD:
- check_availability_tool()        # ← MANTENER (simplificar)
- validate_booking_date()          # ← ELIMINAR (lógica en check_availability)

# BOOKING:
- start_booking_flow()             # ← ELIMINAR (reemplazar con book())
- set_preferred_date()             # ← ELIMINAR (Claude extrae fecha)

# OTROS:
- offer_consultation_tool()        # ← MANTENER
- escalate_to_human()              # ← MANTENER
```

**Decisión:** CONSOLIDAR en 7 herramientas semánticas.

### 2.2 Problemas de la Arquitectura Actual

#### Problema 1: Routing Complejo

```python
# agent/graphs/conversation_flow.py (663 líneas)

def route_after_conversational_agent(state):
    booking_intent = state.get("booking_intent_confirmed", False)
    requested_services = state.get("requested_services", [])
    pending_clarification = state.get("pending_service_clarification", None)
    requested_date = state.get("requested_date", None)
    booking_validation_passed = state.get("booking_validation_passed", False)

    # 40+ líneas de lógica de decisión que Claude podría hacer
    if pending_clarification:
        return "end"
    if booking_intent and requested_services and requested_date:
        return "booking_handler"
    if booking_intent and requested_services:
        return "booking_handler"
    # ...más lógica
```

**Problema:** Claude ya sabe qué hacer, pero el routing fuerza un camino predefinido.

#### Problema 2: Estado Inflado

```python
# 50 campos de estado cuando solo 15 son necesarios

# Campos como estos no deberían estar en estado:
booking_phase: "availability"  # ← Claude no necesita esto
awaiting_slot_selection: True  # ← Claude sabe qué preguntó
prioritized_slots: [...]        # ← Solo Claude necesita verlo temporalmente
```

**Problema:** El estado persiste datos que solo son relevantes durante una conversación activa.

#### Problema 3: Validación Duplicada

```python
# Claude valida en Tier 1:
if service_name in ["mechas", "corte"]:  # Claude razona
    start_booking_flow(services=["mechas", "corte"])

# Tier 2 vuelve a validar:
def validate_booking_request(state):
    services = resolve_services(state["requested_services"])  # Re-valida
    if mixed_categories(services):
        return {"mixed_category_detected": True}
```

**Problema:** Validación doble, lógica duplicada.

---

## 3. Arquitectura Propuesta v3.0

### 3.1 Diagrama de Arquitectura

```
┌────────────────────────────────────────────────────────────┐
│         Maite (Conversational Agent - Claude Sonnet 4)     │
│                                                            │
│  • Conversación completamente libre                        │
│  • Razona sobre intenciones dinámicamente                  │
│  • Decide cuándo llamar qué herramienta                   │
│  • Maneja ambigüedad, cambios de tema, errores           │
└────────────────────────────────────────────────────────────┘
                            │
                            │ Llama herramientas según contexto
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    7 Herramientas Core                     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  1️⃣ query_info(type, filters)                              │
│     └─ Unifica: services, faqs, hours, policies           │
│                                                            │
│  2️⃣ manage_customer(action, phone, data)                   │
│     └─ CRUD: get, create, update customer                 │
│                                                            │
│  3️⃣ check_availability(date, services, preferences)        │
│     └─ Consulta Google Calendar, valida 3 días, retorna slots │
│                                                            │
│  4️⃣ book(services, slot, customer, notes)  ← TRANSACCIÓN  │
│     └─ BookingTransaction handler (ATÓMICO):              │
│        • Resuelve nombres de servicios → UUIDs            │
│        • Valida categoría única                           │
│        • Valida regla 3 días                              │
│        • Valida buffer 10 minutos                         │
│        • Crea appointment provisional (DB)                │
│        • Crea evento amarillo Google Calendar             │
│        • Genera payment link Stripe (si > 0€)             │
│        • Auto-confirma si gratuito                        │
│        • Rollback completo si falla cualquier paso        │
│                                                            │
│  5️⃣ modify(appointment_id, changes)  ← TRANSACCIÓN        │
│     └─ ModificationTransaction (futuro, similar a book)   │
│                                                            │
│  6️⃣ cancel(appointment_id, reason)  ← TRANSACCIÓN         │
│     └─ CancellationTransaction (futuro, similar a book)   │
│                                                            │
│  7️⃣ escalate(reason)                                       │
│     └─ Notifica equipo humano vía Chatwoot                │
└────────────────────────────────────────────────────────────┘
                            │
                            │ Operaciones CRUD atómicas
                            ▼
┌────────────────────────────────────────────────────────────┐
│              PostgreSQL (8 tablas) + Redis Stack           │
│                                                            │
│  • Customer, Stylist, Service, Appointment, Payment       │
│  • Redis: Checkpointing conversacional (15 min TTL)       │
└────────────────────────────────────────────────────────────┘
```

### 3.2 Herramientas Detalladas

#### 3.2.1 query_info() - Información Unificada

```python
@tool
async def query_info(
    type: Literal["services", "faqs", "hours", "policies"],
    filters: dict | None = None
) -> dict:
    """
    Consulta información del negocio de forma unificada.

    Ejemplos:
        query_info("services", {"category": "Peluquería"})
        query_info("services", {"keyword": "corte"})  # Fuzzy search
        query_info("faqs", {"keywords": ["parking", "ubicación"]})
        query_info("hours", {"date": "2025-11-08"})  # Detecta festivos
        query_info("policies", {"type": "cancellation"})

    Returns:
        Para "services":
            {
                "services": [
                    {
                        "id": "uuid",
                        "name": "Corte de Caballero",
                        "category": "Peluquería",
                        "duration_minutes": 30,
                        "price_euros": 15.0,
                        "description": "..."
                    },
                    ...
                ],
                "count": 7
            }

        Para "faqs":
            {
                "faqs": [
                    {
                        "question": "¿Dónde hay parking?",
                        "answer": "Hay parking gratuito en calle X...",
                        "keywords": ["parking", "aparcamiento"]
                    }
                ],
                "count": 3
            }

        Para "hours":
            {
                "date": "2025-11-08",
                "is_holiday": False,
                "open": True,
                "hours": "09:00-20:00",
                "day_name": "viernes"
            }

    Implementación:
        - Queries PostgreSQL (Service, Policy, BusinessHours tables)
        - Fuzzy search con pg_trgm para servicios
        - Cache de 1 hora en Redis para policies
    """
    pass
```

**Mapeo desde arquitectura actual:**
- `get_services()` → `query_info("services")`
- `get_faqs()` → `query_info("faqs")`
- `get_business_hours()` → `query_info("hours")`
- `get_payment_policies()` → `query_info("policies", {"type": "payment"})`
- `get_cancellation_policy()` → `query_info("policies", {"type": "cancellation"})`

#### 3.2.2 manage_customer() - CRUD de Clientes

```python
@tool
async def manage_customer(
    action: Literal["get", "create", "update"],
    phone: str,
    data: dict | None = None
) -> dict:
    """
    Gestión CRUD de clientes.

    Ejemplos:
        manage_customer("get", "+34612345678")
        manage_customer("create", "+34612345678", {
            "first_name": "Pedro",
            "last_name": "Gómez"
        })
        manage_customer("update", "+34612345678", {
            "preferred_stylist_id": "uuid-stylist"
        })

    Returns:
        {
            "id": "uuid",
            "phone": "+34612345678",
            "first_name": "Pedro",
            "last_name": "Gómez",
            "total_spent": 150.0,
            "preferred_stylist_id": "uuid" | None,
            "last_service_date": "2025-10-15T10:00:00+02:00" | None,
            "metadata": {}
        }

    Implementación:
        - Normaliza teléfono a E.164 con phonenumbers library
        - INSERT/UPDATE en Customer table
        - Para "get": retorna None si no existe
    """
    pass
```

**Mapeo desde arquitectura actual:**
- `get_customer_by_phone()` → `manage_customer("get")`
- `create_customer()` → `manage_customer("create")`

#### 3.2.3 check_availability() - Disponibilidad Google Calendar

```python
@tool
async def check_availability(
    date: str,  # Acepta "2025-11-08", "viernes", "mañana"
    services: list[str],  # ["Corte de Caballero"] o ["Mechas", "Corte"]
    stylist_preference: str | None = None,
    time_preference: Literal["morning", "afternoon", "anytime"] | None = None
) -> dict:
    """
    Consulta disponibilidad sin crear reservas.

    Parsea fechas naturales internamente usando date_parser helper.
    Valida regla de 3 días automáticamente.
    Consulta Google Calendar de estilistas que manejan la categoría del servicio.

    Args:
        date: Fecha en formato natural o ISO 8601
        services: Lista de nombres de servicios (resuelve a UUIDs internamente)
        stylist_preference: Nombre del estilista preferido (opcional)
        time_preference: "morning" (09:00-14:00), "afternoon" (14:00-20:00), "anytime"

    Returns:
        {
            "date_parsed": "2025-11-08",
            "date_formatted": "viernes 8 de noviembre",
            "meets_3_day_rule": True,
            "total_duration_minutes": 90,
            "total_price_euros": 50.0,
            "available": True,
            "slots": [
                {
                    "time": "10:00",
                    "end_time": "11:30",
                    "stylist_id": "uuid",
                    "stylist_name": "María",
                    "date": "2025-11-08"
                },
                {
                    "time": "15:00",
                    "end_time": "16:30",
                    "stylist_id": "uuid",
                    "stylist_name": "Carmen",
                    "date": "2025-11-08"
                }
            ],
            "alternative_dates": []  # Si no hay slots, sugiere fechas
        }

    Si fecha inválida (< 3 días):
        {
            "date_parsed": "2025-11-05",
            "meets_3_day_rule": False,
            "days_difference": 1,
            "earliest_valid_date": "2025-11-07",
            "earliest_valid_date_formatted": "jueves 7 de noviembre",
            "message": "La fecha no cumple la regla de 3 días de aviso"
        }

    IMPORTANTE: No crea ninguna reserva. Es puramente informativo.

    Implementación:
        1. Parse fecha natural → datetime (agent/utils/date_parser.py)
        2. Valida regla 3 días (agent/validators/booking_validators.py)
        3. Resuelve service names → Service UUIDs + calcula duración/precio
        4. Identifica categoría → filtra stylists por category
        5. Consulta Google Calendar de cada stylist (shared/clients/calendar_client.py)
        6. Calcula slots libres con buffer de 10 min
        7. Retorna top 3-5 slots ordenados por cercanía temporal
    """
    pass
```

**Mapeo desde arquitectura actual:**
- `check_availability_tool()` + `validate_booking_date()` → `check_availability()`
- Nodo `check_availability` → Lógica integrada en tool

#### 3.2.4 book() - Transacción de Reserva ATÓMICA

```python
@tool
async def book(
    services: list[str],  # ["Corte de Caballero"] - nombres, no UUIDs
    slot: dict,  # {"time": "10:00", "stylist_id": "uuid", "date": "2025-11-08"}
    customer_phone: str,
    customer_name: str | None = None,  # Requerido si cliente nuevo
    customer_notes: str | None = None
) -> dict:
    """
    Ejecuta transacción de reserva completa (ATÓMICA con rollback).

    Esta herramienta es el corazón de la arquitectura simplificada.
    Encapsula TODA la lógica de los siguientes nodos actuales:
    - validate_booking_request
    - create_provisional_booking
    - generate_payment_link

    Proceso interno (BookingTransaction class):
    ┌─────────────────────────────────────────────────────────┐
    │  1. Validación de precondiciones                        │
    │     • Resuelve service names → UUIDs (fuzzy matching)   │
    │     • Valida categoría única (no mix Peluquería+Estética) │
    │     • Valida regla 3 días                               │
    │     • Valida customer existe o puede crearse            │
    ├─────────────────────────────────────────────────────────┤
    │  2. BEGIN TRANSACTION (SERIALIZABLE)                    │
    │     • Verifica slot aún disponible (row lock)           │
    │     • Valida buffer 10 min con citas existentes         │
    ├─────────────────────────────────────────────────────────┤
    │  3. Crea appointment provisional                        │
    │     • INSERT Appointment (status=provisional)           │
    │     • Calcula duración/precio total                     │
    │     • Calcula anticipo 20% (o 0 si gratuito)           │
    ├─────────────────────────────────────────────────────────┤
    │  4. Crea evento Google Calendar                         │
    │     • Color amarillo (provisional)                      │
    │     • Título: "[PROVISIONAL] {customer} - {services}"   │
    │     • Duración: duration_minutes + 10 min buffer        │
    │     • Guarda event_id en appointment                    │
    ├─────────────────────────────────────────────────────────┤
    │  5. Genera payment link Stripe (si precio > 0)          │
    │     • Stripe Payment Link con metadata                  │
    │     • Timeout: 10 minutos (worker expira después)       │
    │     • Guarda stripe_payment_link_id                     │
    ├─────────────────────────────────────────────────────────┤
    │  6. Auto-confirma si gratuito (precio = 0)              │
    │     • UPDATE Appointment status=confirmed               │
    │     • Actualiza evento Calendar a verde                 │
    ├─────────────────────────────────────────────────────────┤
    │  7. COMMIT TRANSACTION                                  │
    │                                                         │
    │  8. Si cualquier paso falla → ROLLBACK + error         │
    └─────────────────────────────────────────────────────────┘

    Args:
        services: Lista de nombres de servicios (ej: ["Corte de Caballero"])
        slot: Slot seleccionado del output de check_availability()
        customer_phone: Teléfono E.164 del cliente
        customer_name: Nombre completo si es cliente nuevo
        customer_notes: Notas opcionales (alergias, preferencias)

    Returns (SUCCESS):
        {
            "success": True,
            "appointment_id": "uuid",
            "payment_required": True,
            "payment_link": "https://checkout.stripe.com/pay/cs_...",
            "payment_timeout_minutes": 10,
            "summary": {
                "date": "viernes 8 de noviembre",
                "time": "10:00",
                "end_time": "11:30",
                "stylist": "María",
                "services": ["Corte de Caballero"],
                "duration_minutes": 90,
                "total_price_euros": 50.0,
                "advance_payment_euros": 10.0  # 20%
            }
        }

    Returns (ERROR):
        {
            "success": False,
            "error_code": "BUFFER_CONFLICT" | "CATEGORY_MISMATCH" | "SLOT_TAKEN" | "DATE_TOO_SOON" | ...,
            "error_message": "El horario se ocupó hace un momento. Por favor selecciona otro slot.",
            "retry_possible": True,
            "suggested_action": "Llama check_availability de nuevo"
        }

    REGLAS CRÍTICAS:
    1. Solo llamar cuando tengas TODOS los datos requeridos
    2. NO llamar para "probar" - usa check_availability para eso
    3. Si retorna error, manejar conversacionalmente y reintentar si retry_possible=True
    4. Services pueden ser nombres naturales - la tool los resuelve

    Implementación:
        - agent/transactions/booking_transaction.py (nueva clase)
        - Usa SQLAlchemy async transactions con SERIALIZABLE isolation
        - Usa shared/clients/calendar_client.py para Google Calendar
        - Usa shared/clients/stripe_client.py para Stripe
        - Logging exhaustivo de cada paso con appointment_id
        - Idempotencia: si se llama dos veces con mismos datos, retorna el existente
    """
    pass
```

**Mapeo desde arquitectura actual:**

Consolida 5 nodos actuales:
1. `booking_handler` → Lógica inicial
2. `validate_booking_request` → Paso 1 (validaciones)
3. `create_provisional_booking` → Paso 3 (DB) + Paso 4 (Calendar)
4. `generate_payment_link` → Paso 5 (Stripe)
5. Confirmación automática → Paso 6

#### 3.2.5 modify() y cancel() - Transacciones Futuras

```python
@tool
async def modify(
    appointment_id: str,
    changes: dict,  # {"date": "...", "time": "...", "services_add": [...], "services_remove": [...]}
    reason: str | None = None
) -> dict:
    """
    Modifica cita existente (FUTURO - Epic 5).

    Similar a book() pero con lógica de:
    - Validación de política de modificación
    - Actualización de evento Calendar
    - Ajuste de pago si cambia precio
    - Notificaciones
    """
    pass

@tool
async def cancel(
    appointment_id: str,
    reason: str | None = None
) -> dict:
    """
    Cancela cita existente (FUTURO - Epic 5).

    Lógica:
    - Validación de política (>24h = refund, <=24h = forfeit)
    - Refund Stripe si aplica
    - Eliminación de evento Calendar
    - Notificaciones
    """
    pass
```

#### 3.2.6 escalate() - Escalación a Humanos

```python
@tool
async def escalate(reason: str, context: str | None = None) -> dict:
    """
    Escala conversación a equipo humano (MANTENER sin cambios).

    Razones:
    - "medical_consultation": Embarazo, alergias, condiciones médicas
    - "payment_failure": Fallos repetidos de pago
    - "ambiguity": Después de 3 intentos sin claridad
    - "delay_notice": Notificación de retraso <1h antes de cita
    - "manual_request": Cliente pide hablar con persona

    Acción:
    - Publica a Redis channel "escalations"
    - Notifica grupo WhatsApp del equipo vía Chatwoot
    - Establece flag en estado: escalation_triggered=True

    Returns:
        {
            "escalated": True,
            "message": "He notificado al equipo. Te atenderán pronto 🌸"
        }
    """
    pass
```

### 3.3 Estado Simplificado

```python
# agent/state/schemas.py (NUEVO - 15 campos)

class ConversationState(TypedDict, total=False):
    """
    Estado mínimo para conversación tool-based.

    Reducción: 50 campos → 15 campos (-70%)
    """

    # Core metadata (6 campos)
    conversation_id: str          # LangGraph thread_id
    customer_phone: str           # E.164 format
    customer_id: UUID | None      # Después de get/create
    customer_name: str | None     # Nombre identificado
    created_at: datetime
    updated_at: datetime

    # Messages (3 campos)
    messages: list[dict]          # Últimos 10 mensajes
    conversation_summary: str | None  # Si >15 mensajes
    total_message_count: int

    # Metadata flexible (1 campo)
    metadata: dict                # Para datos ad-hoc

    # Execution tracking (3 campos)
    last_node: str | None         # Siempre "conversational_agent"
    error_count: int

    # Escalation (2 campos)
    escalation_triggered: bool
    escalation_reason: str | None

    # === CAMPOS ELIMINADOS (35 campos) ===
    # No más:
    # - booking_intent_confirmed
    # - requested_services, requested_date, requested_time
    # - available_slots, prioritized_slots, selected_slot
    # - booking_phase, booking_validation_passed
    # - provisional_appointment_id, payment_link_url
    # - awaiting_X flags
    # - etc.
    #
    # Razón: Toda esa información fluye como parámetros/resultados
    # de herramientas, no necesita persistirse en estado conversacional.
```

### 3.4 Grafo LangGraph Simplificado

```python
# agent/graphs/conversation_flow.py (NUEVO - 10 líneas)

def create_conversation_graph(
    checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """
    Grafo ultra-simplificado: 1 nodo + END.

    Claude decide TODO el flujo usando herramientas.
    """
    graph = StateGraph(ConversationState)

    # Único nodo
    graph.add_node("conversational_agent", conversational_agent)

    # Routing trivial
    graph.set_entry_point("conversational_agent")
    graph.add_edge("conversational_agent", END)

    return graph.compile(checkpointer=checkpointer)
```

**Comparación:**
- Antes: 663 líneas con 12 nodos + routing complejo
- Después: 10 líneas con 1 nodo + routing trivial

---

## 4. Plan de Migración Detallado

### 4.1 Estrategia de Migración

**Enfoque:** Reemplazo directo con backup de seguridad.

**Estrategia simplificada:**
- Crear backup branch de v2 para rollback rápido
- Reemplazar archivos existentes directamente (no carpetas v3 temporales)
- Crear solo módulos nuevos necesarios (transactions/, utils si no existe)
- Testing continuo durante desarrollo

**Fases:**
1. **Fase 1** (2 días): Backup y preparar módulos nuevos (transactions, utils, validators)
2. **Fase 2** (1 día): Implementar y reemplazar herramientas consolidadas
3. **Fase 3** (1 día): Implementar BookingTransaction handler
4. **Fase 4** (2 días): Reemplazar grafo/estado, testing completo y deploy

**Total:** 6 días de trabajo

### 4.2 Fase 1: Backup y Preparar Módulos Nuevos (Días 1-2)

#### Día 1: Backup y Estructura de Módulos Nuevos

**Paso 1: Crear backup de v2**

```bash
# Crear branch de backup para rollback rápido
git checkout -b backup-v2-hybrid-architecture
git add -A
git commit -m "Backup: v2 Hybrid Architecture before v3 migration"
git push origin backup-v2-hybrid-architecture

# Volver a main
git checkout main
```

**Paso 2: Crear solo módulos nuevos necesarios**

```bash
# Crear directorios para componentes NUEVOS solamente
mkdir -p agent/transactions/
mkdir -p agent/utils/  # Solo si no existe
mkdir -p agent/validators/
```

**IMPORTANTE:** NO crear carpetas `tools_v3/`, `graphs_v3/`, `tests/v3/`, etc.
Vamos a reemplazar directamente los archivos existentes en `agent/tools/`, `agent/graphs/`, etc.

**Archivos a crear (módulos nuevos):**

1. `agent/transactions/__init__.py`
2. `agent/transactions/booking_transaction.py` (esqueleto)
```python
class BookingTransaction:
    """
    Handler para transacción atómica de reserva.

    Reemplaza 5 nodos de v2:
    - booking_handler
    - validate_booking_request
    - create_provisional_booking
    - generate_payment_link
    - Auto-confirmation logic
    """

    async def execute(
        self,
        services: list[str],
        slot: dict,
        customer_phone: str,
        customer_name: str | None,
        customer_notes: str | None
    ) -> dict:
        """Implementar lógica completa (ver sección 3.2.4)."""
        pass
```

3. `agent/utils/__init__.py` (si no existe)
4. `agent/utils/date_parser.py` (NUEVO módulo)
```python
def parse_natural_date(date_str: str, timezone=ZoneInfo("Europe/Madrid")) -> datetime:
    """
    Parsea fechas naturales en español a datetime.

    Acepta:
    - "2025-11-08" (ISO)
    - "mañana", "pasado mañana"
    - "viernes", "sábado"
    - "8 de noviembre"

    Returns:
        datetime with timezone
    """
    # Implementar lógica usando dateparser library
    pass
```

#### Día 2: Utilities y Validadores

**Archivos a crear:**

1. `agent/utils/service_resolver.py` (NUEVO)
```python
async def resolve_service_names(
    service_names: list[str]
) -> tuple[list[UUID], dict | None]:
    """
    Resuelve nombres de servicios a UUIDs con fuzzy matching.

    Reutiliza lógica de agent/nodes/conversational_agent.py:333-462

    Returns:
        (resolved_uuids, ambiguity_info)
    """
    pass
```

2. `agent/validators/__init__.py` (NUEVO módulo)
3. `agent/validators/transaction_validators.py` (NUEVO)
```python
async def validate_category_consistency(service_ids: list[UUID]) -> dict:
    """Valida que todos los servicios sean de la misma categoría."""
    pass

async def validate_slot_availability(
    stylist_id: UUID,
    start_time: datetime,
    duration_minutes: int
) -> bool:
    """Valida que el slot esté libre con buffer de 10 min."""
    pass

async def validate_3_day_rule(date: datetime) -> bool:
    """Valida regla de 3 días de aviso mínimo."""
    pass
```

### 4.3 Fase 2: Implementar y Reemplazar Herramientas (Día 3)

**Objetivo:** Reemplazar las 13 herramientas de v2 con las 7 herramientas consolidadas de v3.

**Estrategia:** Reescribir archivos en `agent/tools/` directamente.

**Paso 1: Backup de herramientas v2**

```bash
# Commit estado actual antes de modificar
git add agent/tools/
git commit -m "Checkpoint: v2 tools before consolidation"
```

**Paso 2: Eliminar herramientas antiguas dispersas**

```bash
# Eliminar archivos de herramientas v2 que serán consolidadas
rm agent/tools/faq_tools.py
rm agent/tools/business_hours_tools.py
rm agent/tools/policy_tools.py
# Otros archivos se reescriben (customer_tools.py, booking_tools.py, etc.)
```

**Paso 3: Crear/reescribir herramientas consolidadas**

1. **REEMPLAZAR** `agent/tools/__init__.py` (exportar solo 7 herramientas)
```python
from agent.tools.info_tools import query_info
from agent.tools.customer_tools import manage_customer
from agent.tools.availability_tools import check_availability
from agent.tools.booking_tools import book
from agent.tools.escalation_tools import escalate

__all__ = [
    "query_info",
    "manage_customer",
    "check_availability",
    "book",
    "escalate"
]
```

2. **CREAR** `agent/tools/info_tools.py` (NUEVO archivo)
```python
@tool
async def query_info(...):
    """
    Herramienta unificada de información.

    Consolida:
    - get_services() de booking_tools.py
    - get_faqs() de faq_tools.py
    - get_business_hours() de business_hours_tools.py
    - get_payment_policies() de policy_tools.py
    """
    pass
```

3. **REESCRIBIR** `agent/tools/customer_tools.py` (consolidar CRUD)
```python
@tool
async def manage_customer(...):
    """
    Consolida get_customer_by_phone() y create_customer()
    en una sola herramienta con parámetro action.
    """
    pass
```

4. **REESCRIBIR** `agent/tools/availability_tools.py` (añadir date parser)
```python
@tool
async def check_availability(...):
    """
    Integra parse_natural_date() de agent/utils/date_parser.py
    para aceptar "viernes", "mañana", etc.
    """
    pass
```

5. **REESCRIBIR** `agent/tools/booking_tools.py` (simplificar a solo book())
```python
@tool
async def book(...):
    """
    Herramienta de booking que delega a BookingTransaction.
    Reemplaza start_booking_flow() y toda la lógica de nodos.
    """
    transaction = BookingTransaction()
    result = await transaction.execute(...)
    return result
```

6. **MANTENER** `agent/tools/escalation_tools.py` (sin cambios)

**Métricas de progreso:**
- [ ] query_info() implementado y testeado
- [ ] manage_customer() consolidado y testeado
- [ ] check_availability() con date parser testeado
- [ ] book() delegando a BookingTransaction testeado
- [ ] escalate() mantenido sin cambios
- [ ] __init__.py actualizado con 7 exports

### 4.4 Fase 3: Implementar BookingTransaction (Día 4)

**Objetivo:** Completar la lógica atómica de reserva.

**Archivo:** `agent/transactions/booking_transaction.py`

**Pasos de implementación:**

```python
class BookingTransaction:
    def __init__(self):
        self.session: AsyncSession | None = None
        self.appointment_id: UUID | None = None
        self.calendar_event_id: str | None = None
        self.rollback_needed = False

    async def execute(self, services, slot, customer_phone, customer_name, customer_notes):
        """
        Pasos:
        1. Validar precondiciones (service resolution, category, 3-day rule)
        2. BEGIN TRANSACTION (SERIALIZABLE)
        3. Verificar slot disponible (con row lock)
        4. INSERT Appointment (provisional)
        5. Create Google Calendar event (amarillo)
        6. Generate Stripe payment link (si > 0€)
        7. Auto-confirm si gratuito
        8. COMMIT
        9. En caso de error: ROLLBACK + cleanup Calendar
        """

        try:
            # Paso 1: Validaciones pre-transaccionales
            service_uuids = await self._resolve_services(services)
            await self._validate_category_consistency(service_uuids)
            await self._validate_3_day_rule(slot["date"])
            customer = await self._get_or_create_customer(customer_phone, customer_name)

            # Paso 2-8: Transacción DB + Calendar + Stripe
            async with get_async_session() as session:
                async with session.begin():  # BEGIN TRANSACTION
                    self.session = session

                    # Paso 3: Validar slot con lock
                    slot_available = await self._check_slot_with_lock(
                        slot["stylist_id"],
                        slot["date"],
                        slot["time"]
                    )
                    if not slot_available:
                        return {
                            "success": False,
                            "error_code": "SLOT_TAKEN",
                            "error_message": "Ese horario se ocupó hace un momento.",
                            "retry_possible": True
                        }

                    # Paso 4: Crear appointment provisional
                    appointment = await self._create_provisional_appointment(
                        customer_id=customer.id,
                        stylist_id=slot["stylist_id"],
                        service_ids=service_uuids,
                        start_time=slot["datetime"],
                        duration_minutes=slot["duration_minutes"],
                        total_price=slot["total_price"]
                    )
                    self.appointment_id = appointment.id

                    # Paso 5: Crear evento Google Calendar (fuera de transaction)
                    # (Nota: Si falla Calendar, hacer rollback de DB)

                # COMMIT automático al salir del contexto

            # Paso 5: Google Calendar (después de commit DB exitoso)
            calendar_event = await self._create_calendar_event(appointment)
            self.calendar_event_id = calendar_event["id"]

            # Actualizar appointment con event_id
            async with get_async_session() as session:
                await session.execute(
                    update(Appointment)
                    .where(Appointment.id == appointment.id)
                    .values(google_calendar_event_id=calendar_event["id"])
                )
                await session.commit()

            # Paso 6: Stripe payment link (si > 0€)
            if appointment.total_price > 0:
                payment_link = await self._generate_payment_link(appointment)
                return {
                    "success": True,
                    "appointment_id": str(appointment.id),
                    "payment_required": True,
                    "payment_link": payment_link["url"],
                    "payment_timeout_minutes": 10,
                    "summary": self._build_summary(appointment)
                }
            else:
                # Paso 7: Auto-confirm si gratuito
                await self._auto_confirm_free_appointment(appointment)
                return {
                    "success": True,
                    "appointment_id": str(appointment.id),
                    "payment_required": False,
                    "summary": self._build_summary(appointment)
                }

        except Exception as e:
            # Paso 9: Rollback + cleanup
            logger.error(f"BookingTransaction failed: {e}", exc_info=True)
            await self._rollback_calendar_event()
            # DB rollback es automático (exception dentro de async with session.begin())

            return {
                "success": False,
                "error_code": "TRANSACTION_FAILED",
                "error_message": str(e),
                "retry_possible": False
            }

    # Métodos helpers internos
    async def _resolve_services(self, service_names: list[str]) -> list[UUID]:
        """Resuelve nombres → UUIDs usando service_resolver.py"""
        pass

    async def _validate_category_consistency(self, service_ids: list[UUID]):
        """Valida categoría única"""
        pass

    async def _validate_3_day_rule(self, date: str):
        """Valida aviso mínimo de 3 días"""
        pass

    async def _get_or_create_customer(self, phone: str, name: str | None) -> Customer:
        """Get existing o create new customer"""
        pass

    async def _check_slot_with_lock(self, stylist_id, date, time) -> bool:
        """
        SELECT FROM appointments
        WHERE stylist_id = X AND start_time OVERLAPS ...
        FOR UPDATE  -- Row lock
        """
        pass

    async def _create_provisional_appointment(self, ...) -> Appointment:
        """INSERT Appointment with status=provisional"""
        pass

    async def _create_calendar_event(self, appointment: Appointment) -> dict:
        """Google Calendar API: create event (yellow, provisional)"""
        pass

    async def _generate_payment_link(self, appointment: Appointment) -> dict:
        """Stripe API: create payment link with metadata"""
        pass

    async def _auto_confirm_free_appointment(self, appointment: Appointment):
        """UPDATE Appointment status=confirmed + Calendar event green"""
        pass

    async def _rollback_calendar_event(self):
        """Delete Calendar event si se creó"""
        if self.calendar_event_id:
            # calendar_client.delete_event(self.calendar_event_id)
            pass

    def _build_summary(self, appointment: Appointment) -> dict:
        """Construye diccionario de resumen para respuesta"""
        pass
```

**Reutilización de código existente:**
- Lógica de `validate_booking_request` → `_validate_category_consistency()`
- Lógica de `create_provisional_booking` → `_create_provisional_appointment()` + `_create_calendar_event()`
- Lógica de `generate_payment_link` → `_generate_payment_link()`

**Testing unitario:**
```python
# tests/v3/unit/test_booking_transaction.py

@pytest.mark.asyncio
async def test_booking_transaction_success():
    """Test transacción exitosa con pago"""
    transaction = BookingTransaction()
    result = await transaction.execute(
        services=["Corte de Caballero"],
        slot={
            "time": "10:00",
            "date": "2025-11-15",
            "stylist_id": "uuid-stylist",
            "duration_minutes": 30,
            "total_price": Decimal("15.00")
        },
        customer_phone="+34612345678",
        customer_name="Pedro Gómez",
        customer_notes=None
    )

    assert result["success"] == True
    assert result["payment_required"] == True
    assert result["summary"]["total_price_euros"] == 15.0

@pytest.mark.asyncio
async def test_booking_transaction_rollback_on_calendar_failure():
    """Test rollback si falla Google Calendar"""
    # Mock Google Calendar para que falle
    with patch("shared.clients.calendar_client.create_event", side_effect=Exception("Calendar API down")):
        transaction = BookingTransaction()
        result = await transaction.execute(...)

        assert result["success"] == False
        assert result["error_code"] == "TRANSACTION_FAILED"

        # Verificar que NO quedó appointment en DB
        async with get_async_session() as session:
            count = await session.execute(
                select(func.count()).select_from(Appointment)
            )
            assert count.scalar() == 0  # Rollback exitoso
```

### 4.5 Fase 4: Reemplazar Grafo/Estado y Testing (Días 5-6)

**Objetivo:** Reemplazar el grafo y estado de v2, testing completo y deploy.

#### Día 5: Reemplazar Grafo y Estado

**Paso 1: Checkpoint antes de reemplazar**

```bash
git add agent/graphs/ agent/state/ agent/nodes/
git commit -m "Checkpoint: v2 graph and state before replacement"
```

**Paso 2: Reemplazar `agent/state/schemas.py`**

```bash
# REESCRIBIR agent/state/schemas.py con el estado simplificado de 15 campos
# (copiar desde sección 3.3 del PRD)
```

```python
# agent/state/schemas.py (REEMPLAZAR contenido completo)

class ConversationState(TypedDict, total=False):
    """Estado simplificado v3.0: 15 campos (reducido desde 50)"""

    # Core metadata (6 campos)
    conversation_id: str
    customer_phone: str
    customer_id: UUID | None
    customer_name: str | None
    created_at: datetime
    updated_at: datetime

    # Messages (3 campos)
    messages: list[dict]
    conversation_summary: str | None
    total_message_count: int

    # Metadata (1 campo)
    metadata: dict

    # Execution tracking (2 campos)
    last_node: str | None
    error_count: int

    # Escalation (2 campos)
    escalation_triggered: bool
    escalation_reason: str | None
```

**Paso 3: Reemplazar `agent/graphs/conversation_flow.py`**

```python
# agent/graphs/conversation_flow.py (REEMPLAZAR contenido completo)

from langgraph.graph import StateGraph, END
from agent.state.schemas import ConversationState
from agent.nodes.conversational_agent import conversational_agent

def create_conversation_graph(checkpointer=None):
    """Grafo simplificado v3.0: 1 nodo + END (10 líneas vs 663)"""
    graph = StateGraph(ConversationState)

    graph.add_node("conversational_agent", conversational_agent)
    graph.set_entry_point("conversational_agent")
    graph.add_edge("conversational_agent", END)

    return graph.compile(checkpointer=checkpointer)
```

**Paso 4: Reemplazar `agent/nodes/conversational_agent.py`**

```python
# agent/nodes/conversational_agent.py (REEMPLAZAR contenido completo)

from langchain_anthropic import ChatAnthropic
from agent.tools import (
    query_info,
    manage_customer,
    check_availability,
    book,
    escalate
)

def get_llm_with_tools() -> ChatAnthropic:
    """Claude Sonnet 4 con 7 herramientas consolidadas"""
    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        temperature=0.3
    )

    tools = [query_info, manage_customer, check_availability, book, escalate]
    return llm.bind_tools(tools)

async def conversational_agent(state: ConversationState) -> dict:
    """
    Agente conversacional único que maneja TODO el flujo.

    Reutiliza lógica de v2 pero sin:
    - booking_intent_confirmed detection
    - requested_services extraction
    - Routing manual
    """
    # Implementar ReAct loop con las 7 herramientas
    pass
```

**Paso 5: Eliminar nodos transaccionales obsoletos**

```bash
# Eliminar nodos que fueron reemplazados por BookingTransaction
rm agent/nodes/booking_nodes.py
rm agent/nodes/availability_nodes.py
rm agent/nodes/appointment_nodes.py
```

**Paso 6: Actualizar `agent/prompts/maite_system_prompt.md`**

- Eliminar referencias a "Tier 1" y "Tier 2"
- Simplificar instrucciones de booking (ahora solo call book() tool)
- Añadir ejemplos de uso de las 7 herramientas consolidadas

#### Día 6: Testing Completo y Deploy

**Objetivo:** Ejecutar suite de tests completa y deploy a producción.

**Paso 1: Tests unitarios de componentes nuevos**

```bash
# Tests de utilities
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_date_parser.py -v
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_service_resolver.py -v
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_transaction_validators.py -v

# Tests de BookingTransaction
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_booking_transaction.py -v

# Tests de herramientas consolidadas
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_query_info_tool.py -v
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_manage_customer_tool.py -v
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_check_availability_tool.py -v
DATABASE_URL="..." ./venv/bin/pytest tests/unit/test_book_tool.py -v
```

**Paso 2: Tests de integración end-to-end**

```python
# tests/integration/test_booking_flow_v3.py

@pytest.mark.asyncio
async def test_booking_flow_standard():
    """Test flujo de booking estándar"""
    messages = [
        {"role": "user", "content": "Quiero corte de caballero el viernes a las 10"},
    ]

    result = await run_conversation(messages)

    assert result["appointment_created"] == True
    assert result["payment_link"] is not None
```

**Paso 3: Tests de carga (concurrencia)**

```python
# tests/integration/test_concurrent_bookings.py

@pytest.mark.asyncio
async def test_concurrent_bookings():
    """Test 10 bookings concurrentes - solo 1 debe succeed"""
    tasks = [book_appointment_task(slot_id="same-slot") for _ in range(10)]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1
    assert len(failures) == 9
    assert all(f["error_code"] == "SLOT_TAKEN" for f in failures)
```

**Paso 4: Ejecutar toda la suite de tests**

```bash
# Ejecutar todos los tests con coverage
DATABASE_URL="..." ./venv/bin/pytest --cov=agent --cov-report=term-missing

# Verificar coverage ≥85%
```

**Paso 5: Testing manual (5 conversaciones)**

Ejecutar manualmente 5 conversaciones completas cubriendo:
1. Booking simple exitoso
2. Servicio ambiguo (múltiples matches)
3. Fecha inválida (< 3 días)
4. Slot ocupado por otro booking
5. Escalación a humano

**Paso 6: Deploy a producción**

```bash
# 1. Commit final
git add -A
git commit -m "feat: Migrate to v3.0 Simplified Architecture

- Reduced 12 nodes → 1 node (-92%)
- Consolidated 13 tools → 7 tools (-46%)
- Simplified state 50 → 15 fields (-70%)
- Removed 663 lines of routing logic (-98%)
- Implemented atomic BookingTransaction handler

All tests passing (18/18 scenarios).
Coverage: 87%

Breaking changes: None (external API unchanged)
"

# 2. Tag release
git tag -a v3.0.0 -m "Release v3.0.0: Simplified Tool-Based Architecture"
git push origin main --tags

# 3. Deploy
docker-compose down
docker-compose up --build -d

# 4. Verificar health
curl http://localhost:8000/health
docker-compose logs -f agent | grep "Using SIMPLIFIED ARCHITECTURE"

# 5. Monitorear logs por 1 hora
docker-compose logs -f agent
```

**Paso 7: Plan de rollback (si falla)**

Si hay problemas críticos en producción:

```bash
# Rollback inmediato usando backup branch
git checkout backup-v2-hybrid-architecture
docker-compose down
docker-compose up --build -d

# Alternativa: revert commit
git revert v3.0.0
docker-compose down
docker-compose up --build -d
```

**Criterios Go/No-Go:**
- ✅ 100% tests passing
- ✅ Coverage ≥85%
- ✅ 5 conversaciones manuales exitosas
- ✅ 0 errores críticos en logs durante testing
- ✅ Aprobación de Product Owner

---

## 5. Especificación de Componentes Nuevos

### 5.1 BookingTransaction - Handler Atómico

**Archivo:** `agent/transactions/booking_transaction.py`

**Responsabilidades:**
1. Validar todas las precondiciones antes de comenzar transacción
2. Ejecutar operaciones DB, Calendar, Stripe de forma atómica
3. Hacer rollback completo si falla cualquier paso
4. Loggear exhaustivamente cada paso
5. Retornar errores descriptivos con códigos de error

**Dependencias reutilizables:**
- `database/models.py` → Appointment, Customer, Service, Payment models
- `database/connection.py` → get_async_session()
- `shared/clients/calendar_client.py` → Google Calendar operations
- `shared/clients/stripe_client.py` → Stripe payment links
- `agent/utils/service_resolver.py` → Resolve service names
- `agent/validators/` → Business rule validators

**Códigos de error:**

| Código | Descripción | Retry? | Acción sugerida |
|--------|-------------|--------|-----------------|
| `SERVICE_NOT_FOUND` | Servicio no existe en DB | No | Mostrar servicios disponibles |
| `SERVICE_AMBIGUOUS` | Múltiples servicios coinciden | No | Clarificar con cliente |
| `CATEGORY_MISMATCH` | Mix de Peluquería + Estética | No | Explicar restricción |
| `DATE_TOO_SOON` | < 3 días de aviso | No | Sugerir fecha alternativa |
| `SLOT_TAKEN` | Slot ocupado por otra reserva | Sí | Llamar check_availability de nuevo |
| `BUFFER_CONFLICT` | Conflicto con buffer 10 min | Sí | Llamar check_availability de nuevo |
| `CALENDAR_ERROR` | Fallo al crear evento Calendar | Sí | Reintentar 1 vez |
| `STRIPE_ERROR` | Fallo al generar payment link | No | Escalar a humano |
| `TRANSACTION_FAILED` | Error general | No | Escalar a humano |

**Logging:**

```python
logger.info(
    "BookingTransaction started",
    extra={
        "services": services,
        "slot": slot,
        "customer_phone": customer_phone,
        "trace_id": str(uuid4())
    }
)

logger.info(
    "Step 1: Service resolution",
    extra={"resolved_uuids": service_uuids, "trace_id": trace_id}
)

logger.info(
    "Step 4: Appointment created",
    extra={"appointment_id": str(appointment.id), "trace_id": trace_id}
)

logger.error(
    "BookingTransaction failed",
    extra={
        "error": str(e),
        "step": "calendar_creation",
        "trace_id": trace_id
    },
    exc_info=True
)
```

### 5.2 Service Resolver

**Archivo:** `agent/utils/service_resolver.py`

**Función:**

```python
async def resolve_service_names(
    service_names: list[str]
) -> tuple[list[UUID], dict | None]:
    """
    Resuelve nombres de servicios a UUIDs usando fuzzy matching.

    Algoritmo:
    1. Para cada nombre:
       a. Query PostgreSQL con pg_trgm similarity > 0.7
       b. Si 1 match → Agregar UUID
       c. Si >1 match sin exact match → Marcar como ambiguo
       d. Si exact match → Agregar UUID (ignorar otros matches)
       e. Si 0 matches → Agregar a lista de not_found

    2. Si hay ambigüedad:
       - Detener procesamiento
       - Retornar info de ambigüedad para que Claude clarifique

    3. Si todos resueltos:
       - Retornar lista de UUIDs

    Returns:
        (resolved_uuids, ambiguity_info)

    Ejemplos:
        resolve_service_names(["Corte de Caballero"])
        → ([UUID("...")], None)

        resolve_service_names(["corte"])
        → ([], {
            "query": "corte",
            "options": [
                {"id": "uuid", "name": "Corte Bebé", ...},
                {"id": "uuid", "name": "Corte Niño", ...},
                {"id": "uuid", "name": "Corte de Caballero", ...}
            ]
        })

        resolve_service_names(["Servicio Inexistente"])
        → ([], {
            "query": "Servicio Inexistente",
            "not_found": True
        })
    """
    pass
```

**Reutilización:**
- Copiar lógica de `agent/nodes/conversational_agent.py::extract_requested_services()`
- Ya implementado y testeado en v2

### 5.3 Date Parser Natural

**Archivo:** `agent/utils/date_parser.py`

**Función:**

```python
def parse_natural_date(
    date_str: str,
    timezone: ZoneInfo = ZoneInfo("Europe/Madrid")
) -> datetime:
    """
    Parsea fechas en formato natural a datetime.

    Formatos soportados:
    - ISO 8601: "2025-11-08"
    - Relativos: "mañana", "pasado mañana", "hoy"
    - Días de semana: "lunes", "martes", ..., "domingo"
    - Fechas escritas: "8 de noviembre", "15 de diciembre de 2025"
    - Abreviaciones: "vie", "sáb"

    Reglas:
    - Si menciona día de semana sin fecha específica:
      - Si ese día ya pasó esta semana → Siguiente semana
      - Si ese día aún no llegó esta semana → Esta semana

    Ejemplos (asumiendo hoy = 2025-11-04, martes):
        parse_natural_date("mañana")
        → datetime(2025, 11, 5, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        parse_natural_date("viernes")
        → datetime(2025, 11, 8, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        parse_natural_date("lunes")  # Lunes ya pasó esta semana
        → datetime(2025, 11, 11, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        parse_natural_date("8 de noviembre")
        → datetime(2025, 11, 8, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    Raises:
        ValueError: Si no puede parsear el formato
    """
    # Implementar usando dateparser library + lógica custom para español
    pass
```

**Dependencias:**
```bash
pip install dateparser
```

---

## 6. Mapeo de Datos y Modelos

### 6.1 Mapeo de Modelos Database (Sin cambios)

Todos los modelos de `database/models.py` se mantienen **100% sin cambios**:

| Modelo | Campos Críticos | Usado Por |
|--------|----------------|-----------|
| **Customer** | `phone` (unique), `first_name`, `last_name`, `customer_id`, `preferred_stylist_id` | `manage_customer()` |
| **Stylist** | `name`, `category`, `google_calendar_id`, `is_active` | `check_availability()`, `BookingTransaction` |
| **Service** | `name`, `category`, `duration_minutes`, `price_euros`, `requires_advance_payment` | `query_info()`, `service_resolver`, `BookingTransaction` |
| **Appointment** | `customer_id`, `stylist_id`, `service_ids[]`, `start_time`, `duration_minutes`, `total_price`, `advance_payment_amount`, `status`, `payment_status`, `google_calendar_event_id`, `stripe_payment_id` | `BookingTransaction`, `modify()`, `cancel()` |
| **Payment** | `appointment_id`, `stripe_payment_intent_id`, `amount`, `status` | Workers (payment_processor) |
| **Policy** | `key`, `value` (JSONB) | `query_info("policies")` |
| **ConversationHistory** | `customer_id`, `conversation_id`, `timestamp`, `message_role`, `message_content` | Workers (archiver) |
| **BusinessHours** | `day_of_week`, `is_closed`, `start_hour`, `end_hour` | `query_info("hours")` |

### 6.2 Mapeo de Estado v2 → v3

| Campo v2 | Mantener? | Campo v3 | Razón |
|----------|-----------|----------|-------|
| `conversation_id` | ✅ | `conversation_id` | Identificador de thread |
| `customer_phone` | ✅ | `customer_phone` | E.164 phone |
| `customer_id` | ✅ | `customer_id` | FK a Customer |
| `customer_name` | ✅ | `customer_name` | Display name |
| `messages` | ✅ | `messages` | Últimos 10 |
| `conversation_summary` | ✅ | `conversation_summary` | Para >15 mensajes |
| `total_message_count` | ✅ | `total_message_count` | Tracking total |
| `metadata` | ✅ | `metadata` | Flexible dict |
| `created_at` | ✅ | `created_at` | Timestamp inicio |
| `updated_at` | ✅ | `updated_at` | Timestamp última modificación |
| `last_node` | ✅ | `last_node` | Debugging (siempre "conversational_agent") |
| `error_count` | ✅ | `error_count` | Tracking errores |
| `escalation_triggered` | ✅ | `escalation_triggered` | Flag escalación |
| `escalation_reason` | ✅ | `escalation_reason` | Razón escalación |
| `booking_intent_confirmed` | ❌ | - | Claude decide cuándo llamar book() |
| `requested_services` | ❌ | - | Parámetro de book(), no estado |
| `requested_date` | ❌ | - | Parámetro de check_availability(), no estado |
| `requested_time` | ❌ | - | Parámetro de check_availability(), no estado |
| `available_slots` | ❌ | - | Resultado temporal de check_availability() |
| `prioritized_slots` | ❌ | - | Claude presenta top slots, no necesita estado |
| `selected_slot` | ❌ | - | Parámetro de book(), no estado |
| `booking_phase` | ❌ | - | No hay fases, Claude maneja flujo libremente |
| `booking_validation_passed` | ❌ | - | Validación interna de BookingTransaction |
| `mixed_category_detected` | ❌ | - | Validación interna de BookingTransaction |
| `provisional_appointment_id` | ❌ | - | Resultado de book(), no estado persistente |
| `payment_link_url` | ❌ | - | Resultado de book(), Claude lo envía al cliente |
| `payment_timeout_at` | ❌ | - | Worker de expiration maneja esto |
| `total_price` | ❌ | - | Calculado por check_availability() |
| `advance_payment_amount` | ❌ | - | Calculado por book() |
| ... | ❌ | - | 20+ campos transaccionales más eliminados |

**Total:**
- v2: 50 campos
- v3: 15 campos
- Reducción: 70%

### 6.3 Mapeo de Herramientas v2 → v3

| Herramienta v2 | Herramienta v3 | Cambios |
|----------------|----------------|---------|
| `get_customer_by_phone()` | `manage_customer("get", phone)` | Consolidado |
| `create_customer()` | `manage_customer("create", phone, data)` | Consolidado |
| `get_services()` | `query_info("services", filters)` | Consolidado |
| `get_faqs()` | `query_info("faqs", filters)` | Consolidado |
| `get_business_hours()` | `query_info("hours", filters)` | Consolidado |
| `get_payment_policies()` | `query_info("policies", {"type": "payment"})` | Consolidado |
| `get_cancellation_policy()` | `query_info("policies", {"type": "cancellation"})` | Consolidado |
| `check_availability_tool()` + `validate_booking_date()` | `check_availability()` | Fusionados + date parser natural |
| `start_booking_flow()` | `book()` | Reemplazado por transacción atómica |
| `set_preferred_date()` | - | Eliminado (Claude extrae fecha) |
| `offer_consultation_tool()` | `query_info("services", {"name": "consulta gratuita"})` + `book()` | Simplificado |
| `escalate_to_human()` | `escalate()` | Sin cambios |

---

## 7. Checklist de Implementación

### 7.1 Fase 1: Backup y Preparar Módulos Nuevos ☐

#### Día 1: Backup y Estructura
- [ ] **Crear backup branch:** `git checkout -b backup-v2-hybrid-architecture`
- [ ] **Commit backup:** `git commit -m "Backup v2 before migration"`
- [ ] **Push backup:** `git push origin backup-v2-hybrid-architecture`
- [ ] **Volver a main:** `git checkout main`
- [ ] **Crear directorios nuevos:**
  - [ ] `mkdir -p agent/transactions/`
  - [ ] `mkdir -p agent/utils/` (si no existe)
  - [ ] `mkdir -p agent/validators/`
- [ ] **Crear `agent/transactions/__init__.py`**
- [ ] **Crear `agent/transactions/booking_transaction.py`** (esqueleto)
- [ ] **Crear `agent/utils/__init__.py`** (si no existe)
- [ ] **Crear `agent/utils/date_parser.py`** (esqueleto)

#### Día 2: Utilities y Validadores
- [ ] **Implementar `agent/utils/date_parser.py`:**
  - [ ] `parse_natural_date()` con soporte español
  - [ ] `get_weekday_name()`
  - [ ] `format_date_spanish()`
  - [ ] Diccionarios: SPANISH_WEEKDAYS, SPANISH_MONTHS, RELATIVE_DATES
  - [ ] **Tests:** "mañana", "viernes", "8 de noviembre", ValueError
- [ ] **Crear `agent/utils/service_resolver.py`:**
  - [ ] `resolve_service_names()` con fuzzy matching (reutilizar de conversational_agent.py:333-462)
  - [ ] **Tests:** 1 match, >1 match (ambiguity), 0 matches
- [ ] **Crear `agent/validators/__init__.py`**
- [ ] **Crear `agent/validators/transaction_validators.py`:**
  - [ ] `validate_category_consistency()`
  - [ ] `validate_slot_availability()`
  - [ ] `validate_3_day_rule()`
  - [ ] **Tests** para cada validador

### 7.2 Fase 2: Reemplazar Herramientas ☐

#### Día 3: Consolidar Tools
- [ ] **Checkpoint:** `git commit -m "Checkpoint: v2 tools before consolidation"`
- [ ] **Eliminar archivos dispersos:**
  - [ ] `rm agent/tools/faq_tools.py`
  - [ ] `rm agent/tools/business_hours_tools.py`
  - [ ] `rm agent/tools/policy_tools.py`
- [ ] **CREAR `agent/tools/info_tools.py`** (NUEVO):
  - [ ] `query_info()` consolidando get_services, get_faqs, get_hours, get_policies
  - [ ] **Tests:** services, faqs, hours, policies
- [ ] **REESCRIBIR `agent/tools/customer_tools.py`:**
  - [ ] `manage_customer(action, phone, data)` consolidando get + create
  - [ ] **Tests:** get, create, update
- [ ] **REESCRIBIR `agent/tools/availability_tools.py`:**
  - [ ] `check_availability()` integrando date_parser natural
  - [ ] **Tests:** fechas naturales, regla 3 días, slots disponibles
- [ ] **REESCRIBIR `agent/tools/booking_tools.py`:**
  - [ ] Solo `book()` tool que delega a BookingTransaction
  - [ ] Eliminar start_booking_flow, set_preferred_date, etc.
  - [ ] **Test:** delegación a BookingTransaction (mocked)
- [ ] **MANTENER `agent/tools/escalation_tools.py`** (sin cambios)
- [ ] **REESCRIBIR `agent/tools/__init__.py`:**
  - [ ] Exportar solo 7 herramientas: query_info, manage_customer, check_availability, book, escalate

### 7.3 Fase 3: Implementar BookingTransaction ☐

#### Día 4: Handler Atómico
- [ ] **Completar `agent/transactions/booking_transaction.py`:**
  - [ ] `execute()` completo con 9 pasos
  - [ ] `_resolve_services()` usando service_resolver
  - [ ] `_validate_category_consistency()` usando validators
  - [ ] `_validate_3_day_rule()` usando validators
  - [ ] `_get_or_create_customer()` usando manage_customer logic
  - [ ] `_check_slot_with_lock()` con SELECT FOR UPDATE
  - [ ] `_create_provisional_appointment()` INSERT en DB
  - [ ] `_create_calendar_event()` usando calendar_client
  - [ ] `_generate_payment_link()` usando stripe_client
  - [ ] `_auto_confirm_free_appointment()` si price = 0
  - [ ] `_rollback_calendar_event()` cleanup
  - [ ] `_build_summary()` para respuesta
  - [ ] **Logging exhaustivo** con trace_id

#### Tests BookingTransaction
- [ ] **Test:** Booking exitoso con pago
- [ ] **Test:** Booking gratuito auto-confirm
- [ ] **Test:** Rollback si falla Calendar
- [ ] **Test:** Error SLOT_TAKEN
- [ ] **Test:** Error CATEGORY_MISMATCH
- [ ] **Test:** Error DATE_TOO_SOON
- [ ] **Test:** Error BUFFER_CONFLICT

### 7.4 Fase 4: Reemplazar Grafo/Estado y Deploy ☐

#### Día 5: Reemplazar Arquitectura Core
- [ ] **Checkpoint:** `git commit -m "Checkpoint: v2 graph/state before replacement"`
- [ ] **REESCRIBIR `agent/state/schemas.py`:**
  - [ ] Reemplazar con 15 campos (desde sección 3.3 PRD)
  - [ ] Eliminar 35 campos de v2
- [ ] **REESCRIBIR `agent/graphs/conversation_flow.py`:**
  - [ ] Grafo simplificado: 1 nodo + END (10 líneas vs 663)
- [ ] **REESCRIBIR `agent/nodes/conversational_agent.py`:**
  - [ ] `get_llm_with_tools()` con 7 herramientas
  - [ ] `conversational_agent()` sin booking_intent_confirmed detection
  - [ ] ReAct loop sin routing manual
- [ ] **Eliminar nodos transaccionales:**
  - [ ] `rm agent/nodes/booking_nodes.py`
  - [ ] `rm agent/nodes/availability_nodes.py`
  - [ ] `rm agent/nodes/appointment_nodes.py`
- [ ] **Actualizar `agent/prompts/maite_system_prompt.md`:**
  - [ ] Eliminar referencias "Tier 1" y "Tier 2"
  - [ ] Simplificar instrucciones booking
  - [ ] Añadir ejemplos 7 herramientas

#### Día 6: Testing y Deploy
- [ ] **Tests unitarios:** date_parser, service_resolver, validators
- [ ] **Tests unitarios:** BookingTransaction completo
- [ ] **Tests unitarios:** 7 herramientas consolidadas
- [ ] **Tests integración:** Flujos end-to-end (18 scenarios)
- [ ] **Tests carga:** 10 bookings concurrentes (solo 1 succeed)
- [ ] **Tests carga:** 50 conversaciones simultáneas
- [ ] **Tests manuales:** 5 conversaciones completas
- [ ] **Verificar coverage:** ≥85%
- [ ] **Commit final:**
  ```bash
  git commit -m "feat: Migrate to v3.0 Simplified Architecture

  - Reduced 12 nodes → 1 node (-92%)
  - Consolidated 13 tools → 7 tools (-46%)
  - Simplified state 50 → 15 fields (-70%)
  - Removed 663 lines routing (-98%)
  - Implemented atomic BookingTransaction

  All tests passing. Coverage: 87%"
  ```
- [ ] **Tag release:** `git tag -a v3.0.0 -m "Release v3.0.0"`
- [ ] **Push:** `git push origin main --tags`
- [ ] **Deploy:**
  ```bash
  docker-compose down
  docker-compose up --build -d
  ```
- [ ] **Verificar health:** `curl http://localhost:8000/health`
- [ ] **Monitorear logs:** 1 hora de observación
- [ ] **Actualizar docs:**
  - [ ] `docs/architecture.md`
  - [ ] `CLAUDE.md`
  - [ ] `README.md`

---

## 8. Gestión de Riesgos

### 8.1 Riesgos Técnicos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Claude no llama book() en el momento correcto** | Media | Alto | Prompting robusto con ejemplos explícitos. Monitoring de conversaciones stuck. |
| **BookingTransaction rollback incompleto** | Baja | Crítico | Tests exhaustivos de rollback. Idempotencia en Calendar API. |
| **Race condition en bookings concurrentes** | Media | Alto | SERIALIZABLE isolation + SELECT FOR UPDATE. Tests de carga. |
| **Costo de Claude aumenta** | Baja | Medio | Medición continua. Si aumenta >20%, optimizar prompts. |
| **Latencia aumenta** | Baja | Medio | Tests de carga. Si aumenta >50%, optimizar herramientas. |
| **Tests fallan durante migración** | Media | Alto | Testing exhaustivo en cada fase. Backup branch para rollback rápido. |
| **Pérdida de funcionalidad** | Baja | Crítico | Tests de regresión (18 scenarios). Validación manual. |

### 8.2 Plan de Rollback

**Si v3 falla en producción:**

**Opción 1: Rollback desde backup branch (< 5 minutos)**

```bash
# Checkout al backup de v2
git checkout backup-v2-hybrid-architecture
git push origin main --force  # PRECAUCIÓN: solo si es emergencia

# Redeploy
docker-compose down
docker-compose up --build -d

# Verificar funcionamiento
curl http://localhost:8000/health

# Monitorear logs
docker-compose logs -f agent | grep ERROR
```

**Opción 2: Git revert (< 10 minutos)**

```bash
# Revertir commit de migración
git revert v3.0.0

# Push revert
git push origin main

# Redeploy
docker-compose down
docker-compose up --build -d
```

**IMPORTANTE:** El backup branch `backup-v2-hybrid-architecture` se crea al inicio de Fase 1 y contiene v2 completo funcional para rollback rápido.

### 8.3 Criterios de Go/No-Go

**Criterios para proceder con deploy a producción:**

- ✅ 100% tests passing (unit + integration)
- ✅ Coverage ≥85%
- ✅ 5 conversaciones manuales exitosas
- ✅ Tests de carga passing (concurrencia)
- ✅ 0 errores críticos en logs durante testing local
- ✅ Backup branch creado y verificado
- ✅ Aprobación de Product Owner

**Si NO se cumplen criterios:**
- Investigar y fix issues
- Repetir testing
- Si después de 3 intentos no se cumple → **POSPONER migración**, revisar PRD

---

## 9. Métricas de Éxito

### 9.1 Métricas Cuantitativas

| Métrica | Baseline v2 | Target v3 | Cómo Medir |
|---------|-------------|-----------|------------|
| **Líneas de código** | 2,500 líneas (agent/) | <1,500 líneas (-40%) | `cloc agent/` |
| **Routing logic** | 663 líneas | <20 líneas (-97%) | Líneas en conversation_flow.py |
| **Nodos LangGraph** | 12 nodos | 1 nodo (-92%) | Count en create_conversation_graph() |
| **Campos de estado** | 50 campos | 15 campos (-70%) | Count en ConversationState |
| **Herramientas** | 13 tools | 7 tools (-46%) | Count en tools/ |
| **Latencia promedio** | 11.2s | <12.0s (+<7%) | Promedio de 18 scenarios |
| **Costo por booking** | $0.11 | <$0.12 (+<9%) | Claude API usage tracking |
| **Success rate** | 100% (18/18) | 100% (18/18) | Test scenarios passing |
| **Coverage** | 85% | ≥85% | pytest --cov |

### 9.2 Métricas Cualitativas

**Mantenibilidad:**
- [ ] Reducción de complejidad ciclomática
- [ ] Más fácil añadir nuevas operaciones (modify, cancel)
- [ ] Más fácil debugging (menos nodos, más logs)

**Escalabilidad:**
- [ ] Facilita añadir nuevos tipos de citas
- [ ] Facilita añadir nuevos servicios
- [ ] Facilita cambiar reglas de negocio (3 días → 2 días, etc.)

**Developer Experience:**
- [ ] Onboarding más rápido (arquitectura más simple)
- [ ] Menos bugs por routing incorrecto
- [ ] Más rápido implementar nuevas features

### 9.3 Monitoreo Post-Migración

**Durante primeras 2 semanas:**

```python
# Métricas a trackear en producción
{
    "architecture_version": "v3.0",
    "conversations_total": 450,
    "conversations_successful": 445,
    "conversations_escalated": 5,
    "success_rate": 98.9%,  # Target: ≥95%

    "avg_latency_seconds": 10.1,  # Target: <12s
    "p95_latency_seconds": 13.2,
    "p99_latency_seconds": 15.8,

    "avg_claude_calls_per_booking": 16,  # Target: <20
    "avg_cost_per_booking_usd": 0.10,  # Target: <$0.12

    "bookings_created": 234,
    "bookings_confirmed": 228,
    "bookings_expired": 6,  # Payment timeout
    "booking_confirmation_rate": 97.4%,  # Target: ≥95%

    "errors_total": 12,
    "errors_booking_transaction": 3,  # SLOT_TAKEN
    "errors_calendar_api": 2,
    "errors_stripe_api": 1,
    "errors_claude_api": 0,
    "errors_unknown": 6,

    "rollbacks_triggered": 0  # Target: 0
}
```

**Alertas automáticas:**
- Success rate < 95% → Notificar equipo
- Latencia p95 > 15s → Investigar
- Error rate > 5% → Rollback automático a v2
- Booking confirmation rate < 90% → Investigar payments

---

## 10. Apéndices

### 10.1 Glosario

| Término | Definición |
|---------|------------|
| **Tool-Based Architecture** | Arquitectura donde el agente LLM decide qué herramientas llamar basándose en contexto conversacional |
| **Atomic Transaction** | Operación que se completa enteramente o falla completamente (ACID) |
| **Feature Flag** | Variable de entorno que permite activar/desactivar features en runtime |
| **Rollback** | Revertir cambios a una versión anterior funcional |
| **BookingTransaction** | Handler que encapsula toda la lógica de crear una reserva de forma atómica |
| **Service Resolver** | Utilidad que resuelve nombres de servicios ambiguos a UUIDs únicos |
| **ReAct Loop** | Patrón donde LLM razona (Reason) y actúa (Act) iterativamente hasta completar la tarea |

### 10.2 Referencias

**Documentos del proyecto:**
- `/docs/prd.md` - PRD v2.0 (Arquitectura Híbrida actual)
- `/docs/architecture.md` - Arquitectura v1.1 (Post-Epic 1)
- `/CLAUDE.md` - Guía para Claude Code
- `/docs/specs/scenarios.md` - 18 escenarios conversacionales

**Código crítico actual:**
- `agent/graphs/conversation_flow.py` - Routing v2 (663 líneas)
- `agent/nodes/conversational_agent.py` - Agente conversacional v2
- `agent/nodes/appointment_nodes.py` - Nodos transaccionales v2
- `agent/transactions/booking_transaction.py` - **NUEVO en v3**

**Herramientas externas:**
- LangGraph docs: https://langchain-ai.github.io/langgraph/
- Claude API: https://docs.anthropic.com/
- Stripe Payment Links: https://stripe.com/docs/payment-links

### 10.3 Changelog

| Versión | Fecha | Cambios |
|---------|-------|---------|
| 3.0 | 2025-11-04 | Documento inicial - Arquitectura Simplificada propuesta |
| 3.0.1 | 2025-11-04 | Simplificada estrategia de migración: reemplazo directo sin carpetas v3, reducción de 7 a 6 días |

---

**Fin del Documento PRD v3.0.1**

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
