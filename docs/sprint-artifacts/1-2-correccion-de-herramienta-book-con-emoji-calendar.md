# Story 1.2: Corrección de Herramienta book() con Emoji Calendar

Status: drafted

## Story

As a **cliente**,
I want **que mi reserva se complete exitosamente**,
so that **pueda tener mi cita confirmada en el calendario del estilista**.

## Acceptance Criteria

1. **AC1**: El sistema crea registro en tabla `appointments` con estado PENDING
   - Given el cliente ha seleccionado servicio, estilista y horario
   - When el sistema ejecuta la herramienta `book()`
   - Then se crea registro en BD con status='PENDING'
   - And los campos obligatorios están poblados (customer_id, stylist_id, service_ids, start_time, end_time, first_name)

2. **AC2**: El sistema crea evento en Google Calendar con emoji 🟡 en título
   - Given el registro de cita se creó exitosamente en BD
   - When el sistema llama a Google Calendar API
   - Then se crea evento con título en formato `🟡 {first_name} - {service_name}`
   - And el evento tiene descripción con servicios y notas
   - And la zona horaria es 'Europe/Madrid'

3. **AC3**: El sistema guarda `google_calendar_event_id` en la cita
   - Given el evento de Calendar se creó exitosamente
   - When Calendar API retorna el event_id
   - Then se guarda en campo `google_calendar_event_id` de la cita

4. **AC4**: El sistema guarda `chatwoot_conversation_id` en el customer
   - Given el sistema recibe el conversation_id del contexto
   - When ejecuta book()
   - Then actualiza campo `chatwoot_conversation_id` en la tabla customers

5. **AC5**: El mensaje de confirmación informa sobre confirmación 48h antes
   - Given la cita se creó exitosamente
   - When el sistema retorna respuesta
   - Then el mensaje incluye información sobre confirmación 48h antes
   - And el tono es amigable y profesional en español

6. **AC6**: Se hace rollback de transacción si falla Calendar
   - Given el registro de cita se creó en BD
   - When la creación de evento en Calendar falla
   - Then se hace rollback de la transacción DB
   - And NO queda registro en tabla appointments
   - And se retorna mensaje de error claro con opción de reintentar

## Tasks / Subtasks

- [ ] **Task 1: Analizar error actual en book()** (AC: 1, 6)
  - [ ] 1.1 Leer código actual de `agent/tools/booking_tools.py`
  - [ ] 1.2 Identificar causa del error que impide completar reservas
  - [ ] 1.3 Revisar logs de errores existentes si están disponibles
  - [ ] 1.4 Documentar problema específico y solución propuesta

- [ ] **Task 2: Implementar transacción atómica DB + Calendar** (AC: 1, 2, 3, 6)
  - [ ] 2.1 Refactorizar book() para usar `async with session.begin()` como context manager
  - [ ] 2.2 Crear registro de appointment con status=PENDING
  - [ ] 2.3 Usar `session.flush()` para obtener ID antes de Calendar
  - [ ] 2.4 Llamar a Google Calendar API dentro del bloque transaccional
  - [ ] 2.5 Si Calendar falla, el rollback es automático (no commit)
  - [ ] 2.6 Si Calendar OK, guardar event_id y hacer commit

- [ ] **Task 3: Integrar creación de evento Calendar con emoji** (AC: 2, 3)
  - [ ] 3.1 Crear función helper `create_calendar_event()` en booking_tools.py
  - [ ] 3.2 Formatear título: `f"🟡 {first_name} - {service_names}"`
  - [ ] 3.3 Agregar descripción con lista de servicios y notas del cliente
  - [ ] 3.4 Configurar zona horaria 'Europe/Madrid'
  - [ ] 3.5 Implementar timeout de 3 segundos (NFR3)
  - [ ] 3.6 Implementar retry 1x para errores transitorios con tenacity

- [ ] **Task 4: Guardar chatwoot_conversation_id** (AC: 4)
  - [ ] 4.1 Recibir conversation_id como parámetro en book() (desde estado de conversación)
  - [ ] 4.2 Actualizar campo `chatwoot_conversation_id` en customer si no existe
  - [ ] 4.3 Verificar que el campo se creó en Story 1.1 (migración)

- [ ] **Task 5: Mejorar mensaje de confirmación** (AC: 5)
  - [ ] 5.1 Actualizar response message con información de confirmación 48h
  - [ ] 5.2 Formato sugerido: "¡Cita confirmada! 🎉 Te enviaremos un mensaje 48 horas antes para confirmar tu asistencia."
  - [ ] 5.3 Incluir detalles: fecha, hora, estilista, servicios
  - [ ] 5.4 Tono amigable y profesional en español

- [ ] **Task 6: Manejo de errores y mensajes claros** (AC: 6)
  - [ ] 6.1 Capturar GoogleCalendarError y otras excepciones
  - [ ] 6.2 Retornar dict con status="error", message claro, error_code
  - [ ] 6.3 Mensaje ejemplo: "No pudimos completar tu reserva. Por favor, intenta de nuevo o contacta con el salón."
  - [ ] 6.4 Loggear error con contexto completo para debugging

- [ ] **Task 7: Testing unitario** (AC: 1-6)
  - [ ] 7.1 Test: book() crea cita con status PENDING
  - [ ] 7.2 Test: book() crea evento Calendar con emoji 🟡 correcto
  - [ ] 7.3 Test: book() guarda google_calendar_event_id
  - [ ] 7.4 Test: book() guarda chatwoot_conversation_id en customer
  - [ ] 7.5 Test: book() hace rollback si Calendar falla (mock Calendar error)
  - [ ] 7.6 Test: mensaje de confirmación incluye info 48h
  - [ ] 7.7 Test: timeout de 3s configurado correctamente
  - [ ] 7.8 Verificar cobertura >85% para código nuevo

- [ ] **Task 8: Testing de integración** (AC: 1-6)
  - [ ] 8.1 Test end-to-end: flujo completo de booking con Calendar real (staging)
  - [ ] 8.2 Test: verificar evento aparece en Google Calendar con emoji
  - [ ] 8.3 Test: rollback funciona cuando Calendar API no disponible
  - [ ] 8.4 Test: múltiples servicios se reflejan correctamente en descripción

