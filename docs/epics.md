# atrevete-bot - Epic Breakdown

**Autor:** Pepe
**Fecha:** 2025-11-19
**Tipo de Proyecto:** Brownfield (sistema existente v3.2)
**Complejidad:** Baja

---

## Resumen

Este documento proporciona el desglose completo de épicas e historias para atrevete-bot, descomponiendo los requisitos del [PRD](./prd.md) en historias implementables.

**Nota de Documento Vivo:** Esta es la versión inicial con contexto de PRD + Architecture. Listo para Fase 4 de Implementación.

### Resumen de Épicas

| Épica | Título | Valor para el Usuario | Stories |
|-------|--------|----------------------|---------|
| **1** | Corrección del Flujo de Agendamiento | Cliente puede completar reservas sin errores | 7 |
| **2** | Sistema de Confirmación y Recordatorios | Cliente recibe confirmaciones 48h y recordatorios 24h automáticos | 6 |
| **3** | Cancelación y Reagendamiento | Cliente puede cancelar y reagendar sus citas por WhatsApp | 5 |
| **4** | Mejoras de Consultas y Escalamiento | Cliente recibe respuestas personalizadas y escalamiento inteligente | 6 |

**Total: 4 Épicas, 24 Stories, 42 FRs**

---

## Inventario de Requisitos Funcionales

**Total: 42 Requisitos Funcionales**

### Gestión de Citas - Agendamiento (12 FRs)
- **FR1**: Sistema presenta servicios en lista numerada
- **FR2**: Cliente puede seleccionar múltiples servicios
- **FR3**: Sistema muestra confirmación con desglose y pregunta si agregar más
- **FR4**: Sistema presenta estilistas en lista numerada
- **FR5**: Sistema muestra disponibilidad del estilista en lista numerada
- **FR6**: Sistema recopila datos personales si es primera vez
- **FR7**: Sistema solicita confirmación de datos si cliente recurrente
- **FR8**: Sistema permite agregar notas a la cita
- **FR9**: Sistema crea cita en BD con estado PENDING
- **FR10**: Sistema crea evento en Google Calendar con emoji 🟡
- **FR11**: Sistema envía mensaje informando sobre confirmación 48h antes
- **FR12**: Sistema muestra error claro si falla y ofrece reintentar

### Gestión de Citas - Confirmación y Recordatorios (8 FRs)
- **FR13**: Sistema envía plantilla de confirmación 48h antes
- **FR14**: Sistema detecta respuestas afirmativas del cliente
- **FR15**: Sistema actualiza evento Calendar con emoji 🟢 al confirmar
- **FR16**: Sistema actualiza estado a CONFIRMED al recibir confirmación
- **FR17**: Sistema envía recordatorio 24h antes si confirmó
- **FR18**: Sistema cancela automáticamente citas no confirmadas después de 24h
- **FR19**: Sistema elimina evento Calendar al cancelar por falta de confirmación
- **FR20**: Sistema notifica al cliente cuando su cita fue cancelada

### Gestión de Citas - Cancelación y Reagendamiento (8 FRs)
- **FR21**: Cliente puede solicitar cancelación por WhatsApp
- **FR22**: Sistema muestra citas activas en lista numerada
- **FR23**: Sistema ofrece opción de reagendar al cancelar
- **FR24**: Reagendamiento mantiene servicio/estilista, cambia fecha/hora
- **FR25**: Sistema muestra disponibilidad para reagendar
- **FR26**: Sistema cancela original y crea nueva al reagendar
- **FR27**: Sistema elimina evento Calendar al cancelar manualmente
- **FR28**: Sistema informa si no hay disponibilidad y sugiere nueva cita

### Consultas e Información (4 FRs)
- **FR29**: Sistema responde FAQs desde BD de políticas
- **FR30**: Sistema proporciona info de servicios (descripción, duración)
- **FR31**: Sistema informa horarios de atención
- **FR32**: Sistema personaliza respuestas con nombre del cliente

### Escalamiento a Humanos (5 FRs)
- **FR33**: Sistema escala por errores repetidos
- **FR34**: Sistema escala por insistencia/frustración del cliente
- **FR35**: Sistema escala por consultas no respondibles
- **FR36**: Sistema notifica motivo del escalamiento
- **FR37**: Sistema desactiva respuestas automáticas tras escalar

### Experiencia de Usuario (5 FRs)
- **FR38**: Todas las selecciones usan listas numeradas
- **FR39**: Sistema acepta respuestas por número o texto
- **FR40**: Sistema mantiene contexto de conversación
- **FR41**: Sistema maneja mensajes de audio
- **FR42**: Sistema responde en español con tono amigable

---

## Mapa de Cobertura FR

| Épica | FRs Cubiertos | Total |
|-------|---------------|-------|
| **Épica 1: Agendamiento** | FR1-FR12, FR38-FR42 | 17 FRs |
| **Épica 2: Confirmación/Recordatorios** | FR13-FR20 | 8 FRs |
| **Épica 3: Cancelación/Reagendamiento** | FR21-FR28 | 8 FRs |
| **Épica 4: Consultas/Escalamiento** | FR29-FR37 | 9 FRs |

**✅ Cobertura Total: 42/42 FRs**

---

## Épica 1: Corrección del Flujo de Agendamiento

**Objetivo:** El cliente puede completar reservas de principio a fin sin errores, con experiencia fluida usando listas numeradas.

**FRs Cubiertos:** FR1-FR12, FR38-FR42 (17 FRs)

---

### Story 1.1: Migración de Estados y Campos de Tracking

**Como** desarrollador,
**Quiero** actualizar el modelo de datos con nuevos estados y campos de tracking,
**Para que** el sistema soporte el ciclo completo de confirmación de citas.

**Acceptance Criteria:**

**Given** el esquema actual de base de datos
**When** se ejecuta la migración de Alembic
**Then** el enum `AppointmentStatus` tiene valores: PENDING, CONFIRMED, COMPLETED, CANCELLED, NO_SHOW
**And** la tabla `appointments` tiene campos: `confirmation_sent_at`, `reminder_sent_at`, `cancelled_at`, `notification_failed`
**And** la tabla `customers` tiene campo `chatwoot_conversation_id`
**And** existen índices optimizados para queries del worker

**Prerequisites:** Ninguno

**Technical Notes:**
- Renombrar CONFIRMED→PENDING en enum (Architecture ADR-002)
- Campos timestamp nullable para tracking
- Índices: `idx_appointments_confirmation_pending`, `idx_appointments_customer_active`
- Migration reversible

---

### Story 1.2: Corrección de Herramienta book() con Emoji Calendar

**Como** cliente,
**Quiero** que mi reserva se complete exitosamente,
**Para que** pueda tener mi cita confirmada en el calendario del estilista.

**Acceptance Criteria:**

**Given** el cliente ha seleccionado servicio, estilista y horario
**When** el sistema ejecuta la herramienta `book()`
**Then** se crea registro en tabla `appointments` con estado PENDING
**And** se crea evento en Google Calendar con emoji 🟡 en título
**And** el `google_calendar_event_id` se guarda en la cita
**And** se guarda `chatwoot_conversation_id` en el customer
**And** el mensaje informa sobre confirmación 48h antes

**Given** ocurre un error durante el agendamiento
**When** falla la creación en DB o Calendar
**Then** se hace rollback de la transacción
**And** se muestra mensaje de error claro y opción de reintentar

**Prerequisites:** Story 1.1

**Technical Notes:**
- Archivo: `agent/tools/booking_tools.py`
- Transacción: DB primero, Calendar después (NFR5)
- Formato emoji: `f"🟡 {customer_name} - {service_name}"`
- Timeout Calendar: 3s (NFR3)

---

### Story 1.3: Presentación de Servicios en Lista Numerada

**Como** cliente,
**Quiero** ver los servicios disponibles en una lista numerada clara,
**Para que** pueda seleccionar fácilmente el servicio que deseo.

**Acceptance Criteria:**

**Given** el cliente indica intención de agendar cita
**When** el agente presenta servicios disponibles
**Then** se muestran en formato lista numerada con nombre y duración

**Given** el cliente responde con número o texto
**When** el sistema procesa la selección
**Then** identifica el servicio correctamente (número o nombre)

**Prerequisites:** Ninguno

**Technical Notes:**
- Modificar prompts: `step1_general.md`, `step2_availability.md`
- Max 5 resultados por búsqueda
- FR38, FR39

---

### Story 1.4: Selección Múltiple de Servicios con Confirmación

**Como** cliente,
**Quiero** poder seleccionar varios servicios para una misma cita,
**Para que** pueda hacerme corte y tinte en la misma visita.

**Acceptance Criteria:**

**Given** el cliente selecciona un servicio
**When** el sistema confirma la selección
**Then** muestra desglose y pregunta "¿Deseas agregar otro servicio?"

**Given** el cliente confirma que no quiere más
**When** el sistema procede
**Then** muestra resumen total con duración combinada

**Prerequisites:** Story 1.3

**Technical Notes:**
- Mantener lista en estado de conversación
- FR2, FR3

---

### Story 1.5: Presentación de Estilistas y Disponibilidad

**Como** cliente,
**Quiero** ver qué estilistas están disponibles,
**Para que** pueda elegir con quién quiero mi cita.

**Acceptance Criteria:**

**Given** el cliente ha confirmado servicios
**When** el agente presenta estilistas
**Then** muestra lista numerada de estilistas disponibles

**Given** el cliente selecciona estilista
**When** el sistema busca disponibilidad
**Then** presenta próximos 5 horarios en lista numerada

**Prerequisites:** Story 1.4

**Technical Notes:**
- Herramientas: `find_next_available`
- FR4, FR5

---

### Story 1.6: Recopilación de Datos del Cliente

**Como** sistema,
**Quiero** recopilar datos del cliente de forma inteligente,
**Para que** la cita tenga la información necesaria.

**Acceptance Criteria:**

**Given** el cliente es nuevo
**When** llega al paso de datos
**Then** solicita nombre, apellidos y notas opcionales

**Given** el cliente es recurrente
**When** llega al paso de datos
**Then** confirma datos existentes y permite modificar

**Prerequisites:** Story 1.5

**Technical Notes:**
- Datos en appointment (first_name, last_name, notes)
- FR6, FR7, FR8
- Prompts: `step3_customer.md`

---

### Story 1.7: Actualización de Prompts para Flujo Completo

**Como** cliente,
**Quiero** que el bot me guíe claramente en español,
**Para que** pueda completar mi reserva sin confusiones.

**Acceptance Criteria:**

**Given** el cliente está en cualquier paso
**When** el agente responde
**Then** mantiene contexto, usa listas numeradas, tono amigable

**Given** el cliente envía audio
**When** el sistema procesa
**Then** transcribe y procesa como texto

**Prerequisites:** Stories 1.3-1.6

**Technical Notes:**
- Actualizar prompts: core.md, step1-5
- FR40, FR41, FR42

---

## Épica 2: Sistema de Confirmación y Recordatorios

**Objetivo:** El cliente recibe confirmaciones 48h antes y recordatorios 24h antes. Las citas se cancelan automáticamente si no hay confirmación.

**FRs Cubiertos:** FR13-FR20 (8 FRs)

---

### Story 2.1: Worker de Recordatorios - Infraestructura Base

**Como** sistema,
**Quiero** tener un worker que ejecute periódicamente,
**Para que** pueda procesar confirmaciones y recordatorios automatizados.

**Acceptance Criteria:**

**Given** el sistema está en ejecución
**When** el worker `appointment_reminder` inicia
**Then** ejecuta cada 15 minutos, procesa max 100 citas por ciclo
**And** es idempotente y completa en menos de 2 minutos (NFR2)

**Prerequisites:** Story 1.1

**Technical Notes:**
- Archivo: `agent/workers/appointment_reminder.py`
- Dockerfile: `docker/Dockerfile.reminder`
- Variables: `REMINDER_WORKER_INTERVAL_MINUTES`

---

### Story 2.2: Método send_template en Chatwoot Client

**Como** worker,
**Quiero** poder enviar plantillas de WhatsApp,
**Para que** los clientes reciban mensajes proactivos.

**Acceptance Criteria:**

**Given** el worker necesita enviar plantilla
**When** llama a `send_template()`
**Then** envía POST con `message_type: "template"`
**And** reintenta 3x con backoff si falla

**Given** falla después de 3 intentos
**When** el envío no es exitoso
**Then** marca `notification_failed=True`, NO cancela cita

**Prerequisites:** Ninguno

**Technical Notes:**
- Archivo: `shared/chatwoot_client.py`
- Retry con tenacity

---

### Story 2.3: Envío de Confirmación 48h Antes

**Como** cliente,
**Quiero** recibir confirmación 48h antes,
**Para que** pueda confirmar o cancelar con tiempo.

**Acceptance Criteria:**

**Given** cita PENDING sin `confirmation_sent_at`
**When** faltan 47-49h
**Then** envía plantilla `confirmacion_cita`
**And** actualiza `confirmation_sent_at = NOW()`

**Prerequisites:** Stories 2.1, 2.2

**Technical Notes:**
- FR13
- Usar índice `idx_appointments_confirmation_pending`

---

### Story 2.4: Detección de Confirmación del Cliente

**Como** cliente,
**Quiero** que el bot entienda cuando confirmo,
**Para que** quede registrada mi asistencia.

**Acceptance Criteria:**

**Given** cita PENDING con confirmation enviada
**When** cliente dice "sí", "confirmo", "ok"
**Then** actualiza a CONFIRMED
**And** actualiza Calendar emoji 🟢

**Given** múltiples citas pendientes
**When** confirma
**Then** muestra lista para seleccionar

**Prerequisites:** Story 1.2

**Technical Notes:**
- FR14, FR15, FR16
- Keyword matching + contexto

---

### Story 2.5: Envío de Recordatorio 24h Antes

**Como** cliente,
**Quiero** recordatorio 24h antes,
**Para que** no olvide asistir.

**Acceptance Criteria:**

**Given** cita CONFIRMED sin `reminder_sent_at`
**When** faltan 23-25h
**Then** envía plantilla `recordatorio_cita`
**And** actualiza `reminder_sent_at = NOW()`

**Prerequisites:** Stories 2.3, 2.4

**Technical Notes:**
- FR17
- Solo para citas CONFIRMED

---

### Story 2.6: Cancelación Automática por No Confirmación

**Como** sistema,
**Quiero** cancelar citas no confirmadas después de 24h,
**Para que** estilistas no esperen clientes ausentes.

**Acceptance Criteria:**

**Given** cita PENDING con confirmation hace >24h
**When** worker detecta timeout
**Then** usa `SELECT FOR UPDATE` (lock)
**And** cancela, elimina Calendar, notifica cliente

**Given** race condition
**When** cliente confirma mientras worker cancela
**Then** double-check status antes de cancelar

**Prerequisites:** Stories 2.3, 2.5

**Technical Notes:**
- FR18, FR19, FR20
- Plantilla: `cancelacion_no_confirmada`

---

## Épica 3: Cancelación y Reagendamiento

**Objetivo:** El cliente puede cancelar y reagendar sus citas por WhatsApp sin intervención humana.

**FRs Cubiertos:** FR21-FR28 (8 FRs)

---

### Story 3.1: Herramienta get_my_appointments

**Como** cliente,
**Quiero** ver mis citas activas,
**Para que** pueda seleccionar cuál cancelar o reagendar.

**Acceptance Criteria:**

**Given** el cliente solicita ver sus citas
**When** el agente llama a `get_my_appointments()`
**Then** retorna lista con id, fecha, hora, servicio, estilista, estado

**Given** no tiene citas activas
**When** se consulta
**Then** retorna lista vacía

**Prerequisites:** Story 1.1

**Technical Notes:**
- Archivo: `agent/tools/appointment_management_tools.py`
- Query: `WHERE status IN ('pending', 'confirmed')`
- FR22

---

### Story 3.2: Herramienta cancel_appointment

**Como** cliente,
**Quiero** cancelar una cita,
**Para que** libere el horario.

**Acceptance Criteria:**

**Given** cliente selecciona cita
**When** llama `cancel_appointment()`
**Then** verifica pertenencia, cancela, elimina Calendar

**Given** cita no pertenece al cliente
**When** intenta cancelar
**Then** retorna error de permiso

**Prerequisites:** Story 3.1

**Technical Notes:**
- Validación: `appointment.customer.phone == customer_phone`
- FR21, FR27

---

### Story 3.3: Flujo Conversacional de Cancelación

**Como** cliente,
**Quiero** cancelar de forma natural,
**Para que** sea fácil y rápido.

**Acceptance Criteria:**

**Given** cliente dice "cancelar cita"
**When** agente procesa
**Then** muestra citas en lista, pide selección, confirma, ofrece reagendar

**Prerequisites:** Stories 3.1, 3.2

**Technical Notes:**
- FR21, FR22, FR23
- Siempre ofrecer reagendar después

---

### Story 3.4: Herramienta reschedule_appointment

**Como** cliente,
**Quiero** reagendar mi cita,
**Para que** cambie fecha sin perder reserva.

**Acceptance Criteria:**

**Given** cliente quiere reagendar
**When** llama `reschedule_appointment()`
**Then** verifica disponibilidad, cancela original, crea nueva

**Given** no hay disponibilidad
**When** intenta reagendar
**Then** retorna error y sugiere otros horarios

**Prerequisites:** Stories 3.2, 1.2

**Technical Notes:**
- FR24, FR26
- Transacción atómica: cancel + create

---

### Story 3.5: Flujo Conversacional de Reagendamiento

**Como** cliente,
**Quiero** reagendar conversacionalmente,
**Para que** sea fácil como hablar con persona.

**Acceptance Criteria:**

**Given** cliente acepta reagendar
**When** agente procesa
**Then** muestra disponibilidad del estilista, confirma, ejecuta

**Given** no hay disponibilidad
**When** informa
**Then** sugiere cancelar y agendar nueva cita

**Prerequisites:** Stories 3.3, 3.4

**Technical Notes:**
- FR23, FR24, FR25, FR28

---

## Épica 4: Mejoras de Consultas y Escalamiento

**Objetivo:** El cliente recibe respuestas personalizadas y el bot escala inteligentemente a humanos cuando es necesario.

**FRs Cubiertos:** FR29-FR37 (9 FRs)

---

### Story 4.1: Respuestas Personalizadas con Nombre del Cliente

**Como** cliente,
**Quiero** que el bot me llame por mi nombre,
**Para que** la experiencia sea más personal.

**Acceptance Criteria:**

**Given** cliente identificado
**When** agente responde
**Then** usa nombre naturalmente: "Hola María, ..."

**Given** cliente sin nombre
**When** agente responde
**Then** usa formas genéricas amables

**Prerequisites:** Ninguno

**Technical Notes:**
- FR32
- Obtener de `customer.first_name`
- No abusar: 1-2 veces por conversación

---

### Story 4.2: Consultas de FAQs desde Base de Datos

**Como** cliente,
**Quiero** respuestas a preguntas frecuentes,
**Para que** resuelva dudas sin esperar.

**Acceptance Criteria:**

**Given** pregunta cubierta por políticas
**When** agente consulta
**Then** usa `query_info("policies", ...)` y responde claramente

**Given** pregunta no está en FAQs
**When** no encuentra respuesta
**Then** ofrece escalar a humano

**Prerequisites:** Ninguno

**Technical Notes:**
- FR29
- Tabla: `policies` (JSONB)

---

### Story 4.3: Información de Servicios y Horarios

**Como** cliente,
**Quiero** conocer servicios y horarios,
**Para que** pueda planificar mi visita.

**Acceptance Criteria:**

**Given** pregunta por servicios
**When** agente responde
**Then** muestra nombre, descripción, duración

**Given** pregunta por horarios
**When** agente responde
**Then** muestra horario por día claramente

**Prerequisites:** Ninguno

**Technical Notes:**
- FR30, FR31
- Herramientas: `query_info`, `search_services`

---

### Story 4.4: Escalamiento por Errores Repetidos

**Como** sistema,
**Quiero** escalar cuando hay errores repetidos,
**Para que** cliente no se frustre.

**Acceptance Criteria:**

**Given** mismo error ocurre 3 veces
**When** se detecta patrón
**Then** escala con motivo "Errores técnicos repetidos"
**And** desactiva respuestas automáticas

**Prerequisites:** Ninguno

**Technical Notes:**
- FR33, FR36, FR37
- Umbral configurable
- Herramienta: `escalate_to_human`

---

### Story 4.5: Escalamiento por Frustración del Cliente

**Como** sistema,
**Quiero** detectar frustración del cliente,
**Para que** humano tome control a tiempo.

**Acceptance Criteria:**

**Given** cliente expresa frustración
**When** usa frases como "no entiendes", "quiero hablar con alguien"
**Then** ofrece escalar proactivamente

**Given** cliente acepta
**When** confirma
**Then** escala con motivo y desactiva automáticas

**Prerequisites:** Story 4.4

**Technical Notes:**
- FR34, FR36, FR37
- Keywords + patrón repetición

---

### Story 4.6: Escalamiento por Consultas Complejas

**Como** cliente,
**Quiero** hablar con persona para temas especiales,
**Para que** resuelva lo que bot no puede.

**Acceptance Criteria:**

**Given** consulta fuera de alcance (reclamos, precios especiales, grupos)
**When** agente detecta
**Then** ofrece escalar

**Given** cliente pide explícitamente humano
**When** dice "quiero hablar con persona"
**Then** escala inmediatamente sin preguntar

**Prerequisites:** Story 4.5

**Technical Notes:**
- FR35, FR36, FR37
- Lista de temas en prompts

---

## Matriz de Cobertura FR

| FR | Descripción | Épica | Story |
|----|-------------|-------|-------|
| FR1 | Servicios en lista numerada | 1 | 1.3 |
| FR2 | Selección múltiple servicios | 1 | 1.4 |
| FR3 | Confirmación con desglose | 1 | 1.4 |
| FR4 | Estilistas en lista numerada | 1 | 1.5 |
| FR5 | Disponibilidad en lista numerada | 1 | 1.5 |
| FR6 | Datos si primera vez | 1 | 1.6 |
| FR7 | Confirmación datos recurrente | 1 | 1.6 |
| FR8 | Notas en cita | 1 | 1.6 |
| FR9 | Crear cita PENDING | 1 | 1.2 |
| FR10 | Evento Calendar emoji 🟡 | 1 | 1.2 |
| FR11 | Mensaje sobre confirmación 48h | 1 | 1.2 |
| FR12 | Error claro y reintentar | 1 | 1.2 |
| FR13 | Plantilla confirmación 48h | 2 | 2.3 |
| FR14 | Detectar respuesta afirmativa | 2 | 2.4 |
| FR15 | Actualizar Calendar emoji 🟢 | 2 | 2.4 |
| FR16 | Estado CONFIRMED | 2 | 2.4 |
| FR17 | Recordatorio 24h | 2 | 2.5 |
| FR18 | Cancelación automática 24h | 2 | 2.6 |
| FR19 | Eliminar Calendar si no confirma | 2 | 2.6 |
| FR20 | Notificar cancelación | 2 | 2.6 |
| FR21 | Solicitar cancelación | 3 | 3.2, 3.3 |
| FR22 | Citas en lista numerada | 3 | 3.1 |
| FR23 | Ofrecer reagendar | 3 | 3.3 |
| FR24 | Mantener servicio/estilista | 3 | 3.4 |
| FR25 | Disponibilidad para reagendar | 3 | 3.5 |
| FR26 | Cancelar original, crear nueva | 3 | 3.4 |
| FR27 | Eliminar Calendar al cancelar | 3 | 3.2 |
| FR28 | Informar sin disponibilidad | 3 | 3.5 |
| FR29 | FAQs desde BD | 4 | 4.2 |
| FR30 | Info servicios | 4 | 4.3 |
| FR31 | Horarios atención | 4 | 4.3 |
| FR32 | Personalizar con nombre | 4 | 4.1 |
| FR33 | Escalar por errores | 4 | 4.4 |
| FR34 | Escalar por frustración | 4 | 4.5 |
| FR35 | Escalar consultas complejas | 4 | 4.6 |
| FR36 | Notificar motivo escalamiento | 4 | 4.4, 4.5, 4.6 |
| FR37 | Desactivar automáticas tras escalar | 4 | 4.4, 4.5, 4.6 |
| FR38 | Listas numeradas | 1 | 1.3, 1.4, 1.5 |
| FR39 | Aceptar número o texto | 1 | 1.3, 1.7 |
| FR40 | Mantener contexto | 1 | 1.7 |
| FR41 | Manejar audio | 1 | 1.7 |
| FR42 | Español amigable | 1 | 1.7 |

**✅ Cobertura Completa: 42/42 FRs**

---

## Resumen

### Desglose Total

| Épica | Título | Stories | FRs |
|-------|--------|---------|-----|
| 1 | Corrección del Flujo de Agendamiento | 7 | 17 |
| 2 | Sistema de Confirmación y Recordatorios | 6 | 8 |
| 3 | Cancelación y Reagendamiento | 5 | 8 |
| 4 | Mejoras de Consultas y Escalamiento | 6 | 9 |
| **Total** | | **24 Stories** | **42 FRs** |

### Secuencia de Implementación

1. **Épica 1** - Base del sistema: migración, book(), flujo completo
2. **Épica 2** - Ciclo de confirmación: worker, templates, detección
3. **Épica 3** - Autonomía cliente: cancelar, reagendar
4. **Épica 4** - Mejoras UX: personalización, escalamiento

### Componentes Nuevos a Crear

- `agent/tools/appointment_management_tools.py` - 3 herramientas
- `agent/workers/appointment_reminder.py` - Worker confirmaciones
- `docker/Dockerfile.reminder` - Container para worker
- Migración Alembic - Estados y campos tracking
- Plantillas WhatsApp - `recordatorio_cita`, `cancelacion_no_confirmada`

### Archivos a Modificar

- `database/models.py` - Enum, campos timestamp
- `agent/tools/booking_tools.py` - Emoji Calendar
- `shared/chatwoot_client.py` - send_template()
- `agent/prompts/*.md` - Listas numeradas, flujos
- `docker-compose.yml` - Servicio reminder

### Contexto Incorporado

- ✅ PRD - 42 requisitos funcionales
- ✅ Architecture - Decisiones técnicas, patrones, contratos API

### Estado

**Listo para Fase 4: Sprint Planning e Implementación**

---

_Para implementación: Usar el workflow `create-story` para generar planes de implementación individuales desde este desglose de épicas._

