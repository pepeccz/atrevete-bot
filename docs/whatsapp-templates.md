# WhatsApp Templates — Atrévete Bot

Referencia operativa de plantillas Meta Business Suite usadas por el bot. Actualizado 2026-04-24.

---

## Estado actual

El código referencia **7 nombres de plantilla** repartidos en 3 grupos:

| Grupo | Estado | Descripción |
|---|---|---|
| **Activas** | En prod | Usadas por rutas/workers hoy |
| **Pendientes aprobación** | Nuevas (este SDD) | Variables `.env` vacías, worker `notifications` dormant hasta que existan |
| **Legacy definidas** | No usadas en código | Env vars con defaults pero sin callers — dead config |

---

## 1. Plantillas pendientes de crear en Meta (BLOQUEANTE)

Estas dos son las que el worker `notifications` necesita para operar. Hasta que Meta las apruebe y estén cargadas en `.env`, el worker permanece apagado (`NOTIFICATIONS_WORKER_ENABLED=false`).

> **⚠ Actualización 2026-07-05 (sdd/context-coherence FIX 6)**: las tablas de
> parámetros de esta sección quedaron desactualizadas respecto al código real
> (`reminder_24h.py` y `confirm_48h.py` evolucionaron a 4 y 6 variables
> respectivamente, con renderizado en español/hora de Madrid). El envío forzado
> del 2026-07-05 00:51 se entregó correctamente en WhatsApp con estilista,
> servicio y deadline renderizados (transcript del cliente como evidencia), lo
> que confirma que las plantillas reales en Meta ya aceptan estos conteos —
> **verificado por entrega en vivo 2026-07-05; pendiente de confirmación de
> Pepe en el portal de Meta, ver decisión Q4 (engram #7493)**. Las tablas de
> abajo reflejan el conteo real de variables enviadas por el código; un test
> (`tests/unit/test_whatsapp_template_param_counts.py`) fija estos conteos
> para que cualquier drift futuro falle de forma ruidosa.

### 1.1 Recordatorio 24h antes de la cita

| Campo | Valor |
|---|---|
| Nombre sugerido | `recordatorio_cita_24h` |
| Categoría | `UTILITY` |
| Idioma | `es` (Español) |
| Variables | **4 posicionales** (actualizado — antes documentaba 3) |
| Env var | `WHATSAPP_TEMPLATE_REMINDER_24H` |
| Handler | `agent/workers/notification_handlers/reminder_24h.py` |
| Disparo | 23–25h antes de `start_time` · `status ∈ (PENDING, CONFIRMED)` · `reminder_sent_at IS NULL` · `reminder_failed=false` |

**Parámetros enviados por el bot**:
- `{{1}}` → nombre del cliente (`appt.first_name`, puede ser string vacío)
- `{{2}}` → fecha en español, hora de Madrid (`_render_es.fecha_es`, ej. "miércoles 8 de julio")
- `{{3}}` → hora `HH:MM` en hora de Madrid (`_render_es.hora_es`)
- `{{4}}` → servicio(s) reservado(s), concatenados con ", "

**Body sugerido** (para presentar a Meta — ajustá tono según marca):

```
Hola {{1}} 👋 Te recordamos tu cita mañana {{2}} a las {{3}} para {{4}} en Atrévete. ¡Te esperamos! Si necesitás cancelar o reprogramar, respondé a este mensaje.
```

**Notas**:
- Meta exige que todas las variables estén rodeadas de texto — no empezar ni terminar con `{{n}}`.
- Sin header, footer ni buttons (cumple UTILITY básico).
- Si más adelante querés botones de respuesta rápida ("Confirmo" / "Cancelo"), hay que rediseñar el template y adaptar el inbound routing.

### 1.2 Petición de confirmación 48h antes

| Campo | Valor |
|---|---|
| Nombre sugerido | `confirmacion_cita_48h` |
| Categoría | `UTILITY` |
| Idioma | `es` |
| Variables | **6 posicionales** (actualizado — antes documentaba 3) |
| Env var | `WHATSAPP_TEMPLATE_CONFIRM_48H` |
| Handler | `agent/workers/notification_handlers/confirm_48h.py` |
| Disparo | 47–49h antes de `start_time` · `status = PENDING` · `confirmation_sent_at IS NULL` |

**Parámetros**:
- `{{1}}` → nombre cliente
- `{{2}}` → fecha en español, hora de Madrid (ej. "miércoles 8 de julio")
- `{{3}}` → hora `HH:MM` en hora de Madrid
- `{{4}}` → nombre del estilista asignado
- `{{5}}` → servicio(s) reservado(s), concatenados con ", "
- `{{6}}` → deadline de auto-cancelación en español/Madrid (ej. "martes 7 de julio a las 10:40") —
  anclado en el instante real más temprano en que el tail de auto-cancel podría disparar
  (`now + AUTO_CANCEL_GRACE_BEFORE_WARNING_HOURS + AUTO_CANCEL_GRACE_BEFORE_CANCEL_HOURS`),
  no un offset fijo de T-24h (ver sdd/context-coherence FIX 3)

**Body sugerido**:

```
Hola {{1}}, tenés cita en Atrévete el {{2}} a las {{3}} con {{4}} para {{5}}. ¿Nos confirmás que venís? Si no confirmás antes del {{6}}, la cita se cancelará automáticamente. Respondé "sí" para confirmar o "no" si no podés.
```

**Notas**:
- El agente reconoce respuestas "sí/confirmo/ok" o "no/cancelo/no puedo" gracias a la nueva sección de `appointment_management_flow.md` + las actions `confirm`/`decline` del tool `manage_appointments`.
- Para que el cliente pueda responder, el template debe tener body (no solo header), Meta exige contexto conversacional.

---

## 2. Plantilla activa en producción

### 2.1 Aviso de cita creada desde el panel admin

| Campo | Valor |
|---|---|
| Nombre | `appointment_booked_by_admin` |
| Env var | `ADMIN_APPOINTMENT_TEMPLATE_NAME` |
| Usada por | `api/routes/admin.py:146` (fire-and-forget al crear cita admin) |
| Categoría | `UTILITY` |
| Variables | 5 posicionales |

**Parámetros**:
- `{{1}}` → nombre cliente (display_name)
- `{{2}}` → fecha en español (`format_date_spanish`, ej. "viernes 25 de abril")
- `{{3}}` → hora `HH:MM` (Madrid TZ)
- `{{4}}` → nombre estilista
- `{{5}}` → servicios concatenados (ej. "Corte Dama + Tinte")

Si ya está aprobada en Meta, **no tocar**. Si hace falta recrearla:

```
Hola {{1}} 👋 Te reservamos cita en Atrévete el {{2}} a las {{3}} con {{4}} para {{5}}. ¡Te esperamos!
```

---

## 3. Plantillas legacy en config (sin callers)

Definidas en `shared/config.py` con defaults pero **nadie las importa en el código actual**. Son restos de un sistema previo de recordatorios/cancelaciones. NO hay que crearlas en Meta salvo que se quieran wiring de nuevo.

| Env var | Default | Estado |
|---|---|---|
| `CONFIRMATION_TEMPLATE_NAME` | `appointment_confirmation_48h` | Dead — superseded por `WHATSAPP_TEMPLATE_CONFIRM_48H` |
| `AUTO_CANCEL_TEMPLATE_NAME` | `appointment_auto_cancelled` | Dead — flujo auto-cancel no wired |
| `CUSTOMER_CANCEL_TEMPLATE_NAME` | `appointment_cancelled_by_customer` | Dead — cancel flow usa tool + service directo, sin template |
| `REMINDER_TEMPLATE_NAME` | `appointment_reminder_2h` | Dead — superseded por `WHATSAPP_TEMPLATE_REMINDER_24H` |

**Acción recomendada**: dejar como están. Borrar cuando se confirme que ninguna feature futura las pide. No crear plantillas nuevas en Meta para estos nombres.

---

## 4. Contrato técnico — `send_template_message`

Todas las plantillas se envían vía `shared/chatwoot_client.py:515` con esta firma:

```python
await chatwoot.send_template_message(
    customer_phone="+34612345678",        # E.164
    template_name="nombre_aprobado",      # Meta-approved
    body_params={"1": "...", "2": "..."}, # posicionales como strings
    category="UTILITY",
    language="es",
    fallback_content="Texto plano opcional",  # para canales no-WhatsApp
)
```

- `body_params` usa **keys string posicionales** (`"1"`, `"2"`, …), no nombres.
- Retry automático con backoff exponencial (3 intentos, 2–10s).
- Respeta 429 `Retry-After`.
- Rate limit configurable: `CHATWOOT_RATE_LIMIT_PER_MINUTE` (default 60).

Categorías Meta disponibles: `UTILITY` (transaccional, la que usamos), `MARKETING`, `AUTHENTICATION`. Todas las notificaciones de citas son `UTILITY`.

---

## 5. Procedimiento de alta en Meta Business Suite

1. **Meta Business Suite → WhatsApp → Plantillas → Crear plantilla**.
2. Categoría `UTILITY`, idioma `Español (es)`.
3. Nombre en minúsculas con guiones bajos, ej. `recordatorio_cita_24h`.
4. Body usando `{{1}} {{2}} {{3}}`, rodeadas de texto.
5. Sin header / footer / buttons en v1 (simplifica aprobación).
6. Submit → aprobación suele tardar 1–24h.
7. Una vez aprobada, Meta devuelve el nombre exacto — puede diferir ligeramente del propuesto.

---

## 6. Activación del worker tras aprobación

Cuando Meta apruebe las 2 plantillas nuevas:

### 6.1 Actualizar `.env` en el servidor

```bash
ssh pepe@server
nano /home/pepe/Proyectos/atrevete-bot/.env
```

Setear:

```env
WHATSAPP_TEMPLATE_REMINDER_24H=recordatorio_cita_24h
WHATSAPP_TEMPLATE_CONFIRM_48H=confirmacion_cita_48h
NOTIFICATIONS_WORKER_ENABLED=true
```

### 6.2 Recrear el contenedor

```bash
docker compose --project-directory /home/pepe/Proyectos/atrevete-bot \
  -f /home/pepe/Proyectos/atrevete-bot/docker-compose.yml \
  up -d --force-recreate notifications
```

### 6.3 Verificar

```bash
docker logs -f atrevete-notifications
```

Debe aparecer log `NotificationsWorker started | poll_interval=60s`. Si flag está `true` y templates vacíos, saldrá warnings "SKIPPING — template empty".

### 6.4 Monitor 48h

- `reminder_sent_at` + `confirmation_sent_at` deberían poblarse en `appointments` table.
- `reminder_failed` / `notification_failed` = `false` en happy path.
- Si `retry_count > 3` en alguna fila → revisar logs y Chatwoot rate limit.

---

## 7. Rollback

Si una plantilla aprobada envía mal o hay regresión:

```env
NOTIFICATIONS_WORKER_ENABLED=false
```

+ `docker compose up -d --force-recreate notifications` → worker sale 0, `restart: on-failure` lo deja parado. Flags `*_sent_at` en DB quedan intactos (no se rompe idempotencia).

---

## 8. Resumen ejecutivo — Lo que hay que hacer

1. [ ] Crear en Meta Business Suite: `recordatorio_cita_24h` (3 vars, UTILITY, es)
2. [ ] Crear en Meta Business Suite: `confirmacion_cita_48h` (3 vars, UTILITY, es)
3. [ ] Esperar aprobación Meta (1–24h habitual)
4. [ ] Setear 3 env vars en server: `WHATSAPP_TEMPLATE_REMINDER_24H`, `WHATSAPP_TEMPLATE_CONFIRM_48H`, `NOTIFICATIONS_WORKER_ENABLED=true`
5. [ ] `docker compose up -d --force-recreate notifications`
6. [ ] Monitor logs + DB flags 48h
