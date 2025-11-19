# atrevete-bot - Product Requirements Document

**Autor:** Pepe
**Fecha:** 2025-11-19
**Versión:** 1.0

---

## Resumen Ejecutivo

Atrévete Bot es un asistente de reservas por WhatsApp para una peluquería que gestiona citas de 5 estilistas. El sistema actual (v3.2) tiene la arquitectura base funcional pero requiere completar y mejorar funcionalidades críticas: el flujo de agendamiento tiene errores que impiden completar reservas, y falta implementar el sistema de confirmación/recordatorio automatizado que es esencial para reducir no-shows.

Este PRD define las mejoras necesarias para tener un sistema de reservas completamente funcional y automatizado, incluyendo: corrección del flujo de agendamiento, sistema de confirmación 48h antes con cancelación automática por no respuesta, recordatorios 24h antes, y capacidad de cancelación/reagendamiento por parte del cliente.

### Lo Que Hace Especial a Este Producto

- **Conversación natural en español**: No usa menús rígidos ni comandos - el cliente habla naturalmente y el bot entiende
- **Integración completa WhatsApp ↔ Google Calendar**: Sincronización bidireccional real con los calendarios de cada estilista
- **Sistema de estados visuales**: Emojis en eventos de calendario (🟡 pendiente, 🟢 confirmada) para que estilistas vean estado de un vistazo
- **Escalamiento inteligente**: Detecta cuándo escalar a humanos (errores, insistencia, consultas complejas)
- **Listas numeradas**: Facilita selección de opciones en WhatsApp donde no hay botones

---

## Clasificación del Proyecto

**Tipo Técnico:** API Backend
**Dominio:** General (Servicios/Peluquería)
**Complejidad:** Baja
**Campo:** Brownfield (sistema existente v3.2)

Este es un proyecto brownfield que requiere completar funcionalidades existentes y añadir nuevas capacidades sobre una arquitectura ya establecida (LangGraph + FastAPI + PostgreSQL + Redis). No hay requisitos regulatorios especiales.

---

## Criterios de Éxito

El sistema será exitoso cuando:

1. **Reservas completadas sin errores**: El flujo de agendamiento funciona de principio a fin sin fallos en la herramienta `book()`
2. **Reducción de no-shows**: El sistema de confirmación 48h + recordatorio 24h está operativo y cancela automáticamente citas no confirmadas
3. **Autonomía del cliente**: Los clientes pueden cancelar y reagendar sus citas sin intervención humana
4. **Experiencia fluida**: Todas las selecciones usan listas numeradas consistentes, reduciendo confusión
5. **Visibilidad para estilistas**: Los eventos en Google Calendar muestran estado visual (🟡/🟢) actualizado en tiempo real
6. **Escalamiento efectivo**: El bot escala a humanos solo cuando es necesario (errores repetidos, consultas complejas)

---

## Alcance del Producto

### MVP - Producto Mínimo Viable

**1. Corrección del Flujo de Agendamiento**
- Arreglar error en herramienta `book()` que impide completar reservas
- Implementar listas numeradas en todas las selecciones (servicios, estilistas, horarios)
- Flujo consistente: Servicio(s) → Confirmación servicios → Estilista + Disponibilidad → Datos personales → Agendamiento
- Crear evento en Google Calendar con emoji 🟡 (pendiente confirmación)
- Mensaje de confirmación informando sobre confirmación 48h antes

**2. Sistema de Confirmación y Recordatorios**
- Worker que ejecuta periódicamente para detectar citas próximas
- Envío de plantilla WhatsApp de confirmación 48h antes de la cita
- Si cliente confirma: Actualizar evento Google Calendar con emoji 🟢
- Si cliente no responde en 24h: Cancelar cita y eliminar evento de Google Calendar
- Envío de recordatorio 24h antes (si confirmó) o notificación de cancelación (si no confirmó)
- Crear plantillas de WhatsApp para recordatorio y cancelación (requieren aprobación de Meta)

**3. Cancelación y Reagendamiento**
- Cliente puede cancelar cita por WhatsApp en cualquier momento
- Al cancelar: Ofrecer opción de reagendar
- Reagendamiento mantiene servicio y estilista, solo cambia fecha/hora
- Si no hay disponibilidad para reagendar: Cancelar y que cliente agende nueva cita
- Eliminar evento de Google Calendar al cancelar

**4. Mejoras Generales**
- Respuestas personalizadas usando datos del cliente
- Consultas de FAQs desde base de datos
- Escalamiento a humano mejorado (error/insistencia/consulta compleja)

### Funcionalidades de Crecimiento (Post-MVP)

- **Lista de espera**: Clientes que quieren agendar sin disponibilidad entran en cola y se notifican cuando hay cancelaciones
- **Notificaciones a estilistas**: Alertas cuando se cancelan citas por falta de confirmación
- **Métricas y analytics**: Dashboard con tasas de confirmación, cancelación, no-shows
- **Políticas de cancelación**: Restricciones de tiempo mínimo para cancelar/reagendar

### Visión (Futuro)

- **Multi-canal**: Integración con Instagram DM, Telegram
- **Pagos online**: Cobro de seña o pago completo al reservar
- **Sistema de fidelización**: Puntos, descuentos por visitas frecuentes
- **Recomendaciones inteligentes**: Sugerir servicios basado en historial del cliente
- **Gestión de inventario**: Control de productos usados en servicios

---

## Requisitos Específicos de API Backend

### Plantillas de WhatsApp Business API

El sistema requiere plantillas aprobadas por Meta para mensajes proactivos (fuera de ventana de 24h):

| Plantilla | Estado | Propósito |
|-----------|--------|-----------|
| `confirmacion_cita` | ✅ Existente | Confirmación 48h antes |
| `recordatorio_cita` | ❌ Por crear | Recordatorio 24h antes |
| `cancelacion_no_confirmada` | ❌ Por crear | Notificar cancelación automática |

**Contenido sugerido para plantillas nuevas:**

```
# recordatorio_cita
Hola {{1}}! 👋
Te recordamos tu cita mañana {{2}} a las {{3}} con {{4}}.
¡Te esperamos en Atrévete Peluquería!

# cancelacion_no_confirmada
Hola {{1}},
Tu cita del {{2}} a las {{3}} ha sido cancelada por falta de confirmación.
Si deseas agendar una nueva cita, escríbenos. ¡Estaremos encantados de atenderte!
```

### Worker de Confirmaciones/Recordatorios

Utilizar la infraestructura existente del archiver worker para ejecutar tareas programadas:

- **Frecuencia**: Cada 15-30 minutos
- **Tareas**:
  1. Detectar citas en ventana de 48h sin confirmación enviada → Enviar plantilla confirmación
  2. Detectar citas confirmadas en ventana de 24h sin recordatorio → Enviar plantilla recordatorio
  3. Detectar citas con confirmación enviada hace >24h sin respuesta → Cancelar y notificar

### Estados de Cita

Ampliar el enum `AppointmentStatus` existente:

| Estado | Descripción | Emoji Calendar |
|--------|-------------|----------------|
| `CONFIRMED` | Cita agendada, pendiente confirmación | 🟡 |
| `VERIFIED` | Cliente confirmó asistencia | 🟢 |
| `CANCELLED` | Cancelada (manual o automática) | (eliminado) |
| `COMPLETED` | Cita realizada | - |
| `NO_SHOW` | Cliente no se presentó | - |

### Herramientas del Agente

Herramientas existentes que requieren modificación:

| Herramienta | Modificación Requerida |
|-------------|------------------------|
| `book` | Arreglar error actual, agregar emoji 🟡 al crear evento |
| `query_info` | Ya funciona para FAQs |
| `manage_customer` | Ya funciona |

Herramientas nuevas a implementar:

| Herramienta | Propósito |
|-------------|-----------|
| `cancel_appointment` | Cancelar cita del cliente, eliminar evento Calendar |
| `reschedule_appointment` | Reagendar manteniendo servicio/estilista |
| `get_my_appointments` | Obtener citas activas del cliente (para cancelar/reagendar) |

---

## Requisitos Funcionales

### Gestión de Citas - Agendamiento

- **FR1**: El sistema presenta servicios disponibles en lista numerada para facilitar selección
- **FR2**: El cliente puede seleccionar múltiples servicios en una misma cita
- **FR3**: El sistema muestra confirmación con desglose de servicios seleccionados y pregunta si desea agregar más
- **FR4**: El sistema presenta estilistas disponibles en lista numerada
- **FR5**: El sistema muestra disponibilidad del estilista seleccionado en lista numerada de horarios
- **FR6**: El sistema recopila datos personales del cliente (nombre, apellidos) si es primera vez
- **FR7**: El sistema solicita confirmación de datos si el cliente es recurrente
- **FR8**: El sistema permite agregar notas a la cita durante el agendamiento
- **FR9**: El sistema crea la cita en base de datos con estado CONFIRMED
- **FR10**: El sistema crea evento en Google Calendar con emoji 🟡 en el título
- **FR11**: El sistema envía mensaje de confirmación informando sobre el proceso de confirmación 48h antes
- **FR12**: El sistema muestra mensaje de error claro si el agendamiento falla y ofrece reintentar

### Gestión de Citas - Confirmación y Recordatorios

- **FR13**: El sistema envía plantilla de confirmación 48 horas antes de la cita
- **FR14**: El sistema detecta respuestas afirmativas del cliente para confirmar (sí, confirmo, ok, etc.)
- **FR15**: El sistema actualiza evento de Google Calendar con emoji 🟢 al recibir confirmación
- **FR16**: El sistema actualiza estado de cita a VERIFIED al recibir confirmación
- **FR17**: El sistema envía recordatorio 24 horas antes si el cliente confirmó
- **FR18**: El sistema cancela automáticamente citas no confirmadas después de 24h desde envío de confirmación
- **FR19**: El sistema elimina evento de Google Calendar al cancelar por falta de confirmación
- **FR20**: El sistema notifica al cliente cuando su cita fue cancelada por falta de confirmación

### Gestión de Citas - Cancelación y Reagendamiento

- **FR21**: El cliente puede solicitar cancelación de cita por WhatsApp
- **FR22**: El sistema muestra citas activas del cliente en lista numerada para seleccionar cuál cancelar
- **FR23**: El sistema ofrece opción de reagendar al cancelar
- **FR24**: El reagendamiento mantiene servicio y estilista, permite cambiar fecha/hora
- **FR25**: El sistema muestra disponibilidad del estilista para reagendar
- **FR26**: El sistema cancela cita original y crea nueva al reagendar exitosamente
- **FR27**: El sistema elimina evento de Google Calendar al cancelar manualmente
- **FR28**: El sistema informa al cliente si no hay disponibilidad para reagendar y sugiere nueva cita

### Consultas e Información

- **FR29**: El sistema responde preguntas frecuentes consultando base de datos de políticas
- **FR30**: El sistema proporciona información de servicios (descripción, duración) desde base de datos
- **FR31**: El sistema informa horarios de atención del salón
- **FR32**: El sistema personaliza respuestas usando nombre del cliente cuando está disponible

### Escalamiento a Humanos

- **FR33**: El sistema escala a humano cuando detecta errores repetidos (umbral configurable)
- **FR34**: El sistema escala a humano cuando el cliente insiste o expresa frustración
- **FR35**: El sistema escala a humano para consultas que no puede responder
- **FR36**: El sistema notifica al equipo humano el motivo del escalamiento
- **FR37**: El sistema desactiva respuestas automáticas tras escalar

### Experiencia de Usuario

- **FR38**: Todas las selecciones de opciones usan listas numeradas
- **FR39**: El sistema acepta respuestas por número o por texto descriptivo
- **FR40**: El sistema mantiene contexto de conversación para flujos multi-paso
- **FR41**: El sistema maneja mensajes de audio transcribiéndolos a texto
- **FR42**: El sistema responde en español con tono amigable y profesional

---

## Requisitos No Funcionales

### Rendimiento

- **NFR1**: El bot debe responder en menos de 5 segundos para mensajes simples
- **NFR2**: El worker de confirmaciones debe procesar todas las citas pendientes en menos de 2 minutos por ejecución
- **NFR3**: Las operaciones de Google Calendar deben completarse en menos de 3 segundos

### Fiabilidad

- **NFR4**: El sistema debe manejar errores de APIs externas (Chatwoot, Google Calendar) sin perder datos
- **NFR5**: Las citas deben persistir en PostgreSQL antes de crear eventos en Calendar (transacción primero en DB)
- **NFR6**: El worker debe ser idempotente (re-ejecutar no duplica mensajes)

### Integración

- **NFR7**: Las plantillas de WhatsApp deben cumplir con las políticas de Meta Business
- **NFR8**: Los eventos de Google Calendar deben sincronizarse en tiempo real (crear, actualizar, eliminar)
- **NFR9**: El sistema debe manejar la ventana de 24h de WhatsApp Business API (mensajes proactivos solo con plantillas)

### Mantenibilidad

- **NFR10**: Cobertura de tests mínima de 85% para nuevo código
- **NFR11**: Logs estructurados para debugging de flujos de confirmación/cancelación
- **NFR12**: Configuración de umbrales (tiempo de confirmación, frecuencia de worker) externalizados en variables de entorno

---

## Resumen del PRD

**Total de Requisitos Funcionales:** 42
**Total de Requisitos No Funcionales:** 12

**Áreas de Capacidad:**
- Gestión de Citas - Agendamiento (12 FRs)
- Gestión de Citas - Confirmación y Recordatorios (8 FRs)
- Gestión de Citas - Cancelación y Reagendamiento (8 FRs)
- Consultas e Información (4 FRs)
- Escalamiento a Humanos (5 FRs)
- Experiencia de Usuario (5 FRs)

---

_Este PRD captura la esencia de Atrévete Bot - un asistente de reservas conversacional que automatiza completamente el ciclo de vida de citas (agendamiento, confirmación, recordatorio, cancelación) manteniendo la experiencia humana y natural que esperan los clientes de una peluquería._

_Creado a través de descubrimiento colaborativo entre Pepe y facilitador AI._
