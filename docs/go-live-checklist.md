# Checklist de Go-Live — Atrévete Bot

> Estado: **PRE-PRODUCCIÓN**. Panel validado en QA (Fase C, 2026-07-01). El panel funciona;
> faltan pasos de infraestructura antes de abrir a producción. Documento para la reunión con Pilar.

---

## Resumen ejecutivo

El panel de administración está **funcionalmente listo y verificado** (agenda, reservas, gestión,
notificaciones). Hay **5 bloqueantes de infraestructura** que deben cerrarse antes de lanzar, más
un conjunto de tareas de coordinación con Pilar. El bloqueante más crítico es la **migración de
dominio incompleta (`zonavix.com` → `zanavix.com`)**: hoy el backend no puede hablar con Chatwoot
ni con Google Calendar en producción.

**Recomendación**: usar la reunión con Pilar para (1) demo del panel + OK de UX, y (2) alinear
este checklist y las decisiones de negocio. NO lanzar en la misma reunión.

---

## Estado actual (verificado en el server `pepe@server`, 2026-07-01)

| Área | Estado | OK para producción |
|------|--------|--------------------|
| Panel admin (UI/UX) | Funciona, verificado | ✅ |
| Login | Funciona (`admin`) | ✅ |
| Reservas / wizard / lead-time gate | Funciona | ✅ |
| Confirmar / cancelar / reagendar | Funciona | ✅ |
| Chatwoot (backend) | `CHATWOOT_API_URL=chats.zonavix.com` → **410 (muerto)** | ❌ P0 |
| Google Calendar | `TEST_MODE_GCAL_SKIP=true` (no sincroniza) + OAuth redirect en dominio viejo + 5 calendarios "Sin conectar" | ❌ P0 |
| OAuth / dominios | `GOOGLE_OAUTH_REDIRECT_URI` y `ADMIN_PANEL_URL` en `zonavix.com` | ❌ P0 |
| Código desplegado | ✅ Todo consolidado en `master` (confirm-lifecycle #93-95 + IDOR + Fase C, PR #96), CI verde. Falta rebuild del server desde código limpio (en el deploy) | ⚠️ deploy |
| Inbox de conversaciones | 271 threads de QA (Redis) + errores al abrir | ❌ P0 |
| Auto-cancelación | `AUTO_CANCEL_ENABLED=false`, template Meta sin aprobar | ⚠️ decisión de negocio |

---

## P0 — Bloqueantes (obligatorios antes de producción)

### P0-1 · Completar migración de dominio `zonavix.com` → `zanavix.com`
Hoy el backend apunta a dominios viejos que están muertos/incorrectos.

- [ ] `.env`: `CHATWOOT_API_URL` → `https://chats.zanavix.com/`
- [ ] Verificar que `CHATWOOT_API_TOKEN` y `CHATWOOT_ACCOUNT_ID` siguen siendo válidos en el dominio nuevo (probar 1 llamada a la API de Chatwoot).
- [ ] `.env`: `GOOGLE_OAUTH_REDIRECT_URI` → `https://apiatrevete.zanovix.com/api/admin/google/callback`
- [ ] `.env`: `ADMIN_PANEL_URL` → `https://atrevete.zanovix.com`
- [ ] **Google Cloud Console**: añadir el nuevo redirect URI a la app OAuth (si no, la reconexión de GCal falla).
- [ ] **Chatwoot**: confirmar que el webhook de Chatwoot apunta a `https://apiatrevete.zanovix.com/...` (no al dominio viejo).
- [ ] Rebuild + restart de `api`:
      ```bash
      docker compose -f docker-compose.yml up -d --build api
      ```

> Sin esto: el bot puede reservar, pero **el operador no puede intervenir por WhatsApp** y las
> ventanas de conversación no se calculan. Es el corazón de la visión IA + humano.

### P0-2 · Activar Google Calendar real
- [ ] `.env`: `TEST_MODE_GCAL_SKIP=false`
- [ ] Reconectar GCal por OAuth desde el panel (`/settings/google-calendar`) — requiere P0-1 hecho.
- [ ] Asignar los 5 calendarios a los estilistas (`/stylists` muestra hoy "Sin conectar").
- [ ] Verificar: crear una cita de prueba y confirmar que aparece en el Google Calendar del estilista.
- [ ] Borrar la cita de prueba.

### P0-3 · Consolidar el código en git (deploy reproducible) — ✅ HECHO (2026-07-02, código en `master` verde)
El server corría sobre `master` + 39 cambios **sin commitear** (los 3 fixes de Fase C y todo
el confirm-lifecycle). Ya está todo commiteado en `master` (CI verde).

- [x] Mergeados los PRs del confirm-lifecycle en orden **#93 → #94 → #95** (retargeteando cada uno a `master`; CI verde tras arreglar lint + un test stale de status PENDING).
- [x] Rescatados y commiteados en **PR #96** (mergeado): IDOR (P0-6), B4 (`recurrence_service`), B3 (`calendar-toolbar`), B2 (`docker-compose` — solo `NEXT_PUBLIC_CHATWOOT_URL`; el flip de `NEXT_PUBLIC_API_URL` queda para P0-1), y las correcciones de `scenarios.yaml` de Fase E.
- [x] Arreglada deuda de CI latente que había entrado a `master` porque la CI de #94/#95 nunca corrió: lint ruff, tests IDOR, y un off-by-one de `cwd` en el test de migración del slice-3 (4 `dirname` → alembic no encontraba `alembic.ini` → exit 255).
- [ ] **Pendiente en el deploy**: dejar el árbol del server limpio (`git checkout .` / stash) y **rebuild desde `master` commiteado** — hacerlo al desplegar (P0-1), no antes, para no tocar los contenedores en vuelo. Backups: `*.bak.faseC`, `.env.bak.*`, `docker-compose.yml.bak.*`.
- [ ] **Deuda futura (no bloqueante)**: `master` tiene 5 heads de migración (double-booking, catalog, inbox, stripe, slice-3). `alembic upgrade head` funciona hoy, pero conviene una migración de merge que unifique heads + regenerar `init_schema.sql` (hoy es un snapshot inconsistente).

### P0-4 · Limpiar el inbox (checkpoints de QA en Redis)
El inbox muestra 271 conversaciones que son threads de bot de QA (Redis), no clientes reales.
Al abrirlas dan `mark-read 400` + `window-status 404` en bucle.

- [ ] Confirmar que no hay conversaciones reales en vuelo.
- [ ] Flushear los checkpoints de QA:
      ```bash
      redis-cli --scan --pattern 'checkpoint:*' | xargs redis-cli del
      ```
- [ ] Verificar que el inbox queda limpio tras la limpieza.

### P0-5 · Limpiar datos de QA de la base
- [ ] Borrar clientes/citas sandbox (teléfonos `+34999*`) con el script de limpieza:
      ```bash
      python tests/e2e/harness/cleanup.py --dry-run   # revisar
      python tests/e2e/harness/cleanup.py
      ```
- [ ] Revisar/limpiar notificaciones de prueba viejas en el Centro de Notificaciones.

---

### P0-6 · [SEGURIDAD] IDOR en `manage_appointments` confirm/decline — ✅ FIXED + VERIFICADO (uncommitted)
Descubierto en Fase D (QA del agente en vivo, confirmado explotando en sandbox): un cliente podía **confirmar o cancelar (decline) la cita de OTRO cliente** enviando el UUID por WhatsApp. `cancel`/`reschedule` ya validaban propiedad; `confirm`/`decline` no.

- [x] Fix aplicado en `agent/tools/manage_appointments_tool.py` (`_confirm_or_decline` recibe `customer_id` inyectado, guard `CUSTOMER_ID_REQUIRED` + `validate_appointment_belongs_to_customer` antes de mutar; wrappers y dispatch threadean `_customer_id`). Backup: `manage_appointments_tool.py.bak.faseD`.
- [x] Rebuild del agente + verificación adversarial en vivo: B (identificado y sin identificar) NO puede tocar la cita de A (`appointment_not_owned` + `idor.appointment_ownership_mismatch`); control positivo: A sigue confirmando su propia cita. Cita de A intacta.
- [x] **HECHO (2026-07-02)**: commiteado en **PR #96** (`fix(security): enforce appointment ownership on confirm/decline (IDOR)`), mergeado a `master` con CI verde. Ver P0-3.
- Mitigante: el UUID es v4 (no enumerable), pero puede filtrarse (las notificaciones de auto-cancelación muestran UUIDs crudos — Fase C B1). Era un hueco de defensa en profundidad, ahora cerrado.

## P1 — Importantes (cerrar antes o justo al lanzar)

- [ ] **B1 (cosmético)**: notificaciones de auto-cancelación muestran el UUID de la cita en vez de
      nombre + fecha. Arreglar el armado del mensaje en el handler de `auto_cancel`.
- [ ] **B5 (definitivo)**: decidir el comportamiento del inbox para threads Redis tras la limpieza
      (que `window-status`/`mark-read` no rompan si vuelven a aparecer threads sin Chatwoot).
- [ ] **Rol estilista**: crear un usuario `stylist` de prueba y verificar los gates (no ve Usuarios,
      no ve Settings, no resuelve escalaciones). Solo se probó como `admin`.
- [ ] **Usuarios operadores**: crear en `/users` las cuentas reales de quienes van a atender
      (Pilar + estilistas), con roles correctos. Cambiar la contraseña de `admin` si hace falta.
- [ ] **Catálogo y horarios**: revisar con Pilar que servicios (77), precios/duraciones, horarios
      de apertura y festivos estén correctos para el salón real.

---

## Decisiones de negocio para la reunión con Pilar

- [ ] **Auto-cancelación de citas sin confirmar**: ¿se activa? Requiere:
      - aprobación del template Meta `whatsapp_template_final_warning`,
      - confirmar tiempos (por defecto: aviso a 12h, cancela a 6h, no toca citas a <24h),
      - luego `AUTO_CANCEL_ENABLED=true` + restart del agente.
      Hoy está **apagado** (seguro por defecto).
- [ ] **Política de privacidad** (`POLICY_VERSION`): NO cambiarla sin avisar — re-dispara la
      aceptación para todos los clientes que vuelven.
- [ ] **Horario de envío de confirmaciones** y recordatorios (configurable en `/settings/system`).
- [ ] ¿Quiénes son los operadores humanos y qué franja atienden?

---

## Runbook del día del lanzamiento (orden sugerido)

1. P0-3: mergear PRs + commitear fixes → árbol de git limpio.
2. P0-1: editar `.env` (dominios) + Google Console + webhook Chatwoot → rebuild `api`.
3. P0-2: `TEST_MODE_GCAL_SKIP=false` + reconectar GCal OAuth + asignar calendarios → verificar push real.
4. P0-4: flush de checkpoints Redis.
5. P0-5: limpieza de datos QA.
6. P1: crear usuarios reales, revisar catálogo/horarios con Pilar.
7. Smoke test end-to-end: un WhatsApp real → bot reserva → aparece en GCal → operador interviene desde el inbox.
8. Activar auto-cancelación (opcional, si el template Meta está aprobado).

## Verificación post-lanzamiento

- [ ] Reserva real por WhatsApp crea cita y la empuja a Google Calendar.
- [ ] El operador puede pausar el bot y responder por WhatsApp desde el inbox.
- [ ] El link de Chatwoot en el panel abre la instancia correcta.
- [ ] Las confirmaciones/recordatorios se envían a la hora configurada.
- [ ] Sin errores en consola del panel ni en logs de `api`/`agent`.

## Rollback

- Revertir imágenes: `git revert` de los commits + `docker compose -f docker-compose.yml up -d --build`.
- Backups de config en el server: `.env.bak.*`, `docker-compose.yml.bak.*`, `*.bak.faseC`.
- `TEST_MODE_GCAL_SKIP=true` y `AUTO_CANCEL_ENABLED=false` como interruptores de seguridad.

---

## Anexo A — Fixes de Fase C (aplicados en el server, pendientes de commit)

| Bug | Archivo | Cambio |
|-----|---------|--------|
| B4 (P1) crear bloqueo → 500 | `agent/services/recurrence_service.py` | `type_coerce(start_dt, DateTime(timezone=True))` en la query de solapamiento + import `DateTime, type_coerce`. Bug pre-existente de `master`. |
| B3 vista Mes mostraba mes anterior | `admin-panel/src/components/calendar/calendar-toolbar.tsx` | Anclar `date + 6 días` antes de formatear el nombre del mes. |
| B2 link Chatwoot roto | `docker-compose.yml` | `NEXT_PUBLIC_CHATWOOT_URL` → `https://chats.zanavix.com` (desacoplado del backend). |

**Nota**: B2 solo arregló el *link del panel*. El **backend** de Chatwoot (`CHATWOOT_API_URL`) sigue
en el dominio viejo — eso lo cierra **P0-1**.
