# Admin-panel — UX + Functional Test Report (stylist perspective)

**Date**: 2026-06-15
**Target**: testing deploy `https://atrevete.zonavix.com` (server `pepe@server`, docker compose)
**Session**: logged in as `pepecabeza` (Pepe Cabeza, Admin)
**Method**: live browser walkthrough (Chrome automation) of every operational surface, console + network inspection, source cross-reference.
**Lens**: "Can a non-technical beauty-salon stylist operate this confidently, day to day?"

---

## Environment notes (read first)

- **The admin-panel is running in DEVELOPMENT mode, not a production build.** Console shows `[HMR] connected` and `[Fast Refresh] rebuilding/done`; `docker-compose.override.yml` uses `Dockerfile.admin-dev`. This means `next dev` with React StrictMode (effects double-invoke), unminified bundles, and slower loads. This is the probable amplifier of the P0 inbox bug below. Recommend deploying the production build (`Dockerfile.admin-panel`, `next build && next start`) for the real testing/UAT.
- Data is sandbox (`+34999…` phones, `TEST_MODE_GCAL_SKIP` active → all appointments `gcal_sync_status='not_applicable'`).

---

## P0 — BLOCKER

### 1. Conversaciones inbox stuck forever on "Cargando…"
- **Surface**: `/conversations` (the flagship inbox).
- **Symptom**: the conversation list never renders; it stays on "Cargando…" indefinitely. Tab filters (Todas/Bot ON/Bot OFF/Escaladas/Sin leer) show no counters.
- **Evidence**: `GET https://api.zonavix.com/api/admin/conversations?page_size=100` returns **HTTP 200** with a valid body `{"items":[{conversation_id, customer_name:"Sara Bautista", message_count:6, source:"redis", atencion_automatica, paused_at, unread_message_count}, …]}`. Data arrives fine; the UI never consumes it. No console error thrown. Two duplicate requests fire (StrictMode double-invoke), both 200, loading state never clears.
- **Impact**: the entire messaging operation is unusable — takeover/pause/resume, templates, window-status, customer card enrichment, escalated filter — ALL blocked because no conversation can be selected. For a stylist this is the single most important screen and it does not work.
- **Files**:
  - `admin-panel/src/components/inbox/ConversationList.tsx` — owns the `loading` state; `fetchList` at lines ~184-194 with a **silent `catch {}`** (no logging) at ~188-190 and `finally { setLoading(false) }` at ~191-193; loading gate at ~372-394.
  - `admin-panel/src/hooks/useConversationPolling.ts` — polls `fetchFn`; `getInterval`/`getBaseInterval` depend on `unreadCount`, which is recomputed un-memoized in `ConversationList` (~198-200), making the polling effect re-run on every list change.
  - `admin-panel/src/hooks/use-api-query.ts:66` — **separate latent StrictMode bug**: `finally { if (!signal.aborted) setIsLoading(false) }` never clears loading when the first mount's request is aborted by StrictMode cleanup. Currently **dead code (unused)**, but fix it before anyone wires it up.
  - Page: `admin-panel/src/app/(authenticated)/conversations/page.tsx`.
- **Root cause (not 100% pinned by static analysis)**: live evidence rules out a network hang (the request returns 200, twice). On paper `finally{setLoading(false)}` should always fire, so the strongest hypothesis is a **dev/StrictMode double-mount race / remount** that resets `loading=true` on the surviving instance while the resolved fetch cleared it on the discarded one — amplified by the dev deploy. The silent catch hides any real error.
- **Concrete fixes / next step**:
  1. **Deploy the production build** and re-test — if it works there, it's StrictMode-only and this is the fix.
  2. **Add diagnostics** to surface the real cause: `catch (err) { console.error("[ConversationList] fetchList failed:", err); }`.
  3. `useMemo` the `unreadCount` computation in `ConversationList` to stop the polling effect from thrashing on every render.
  4. Drop the abort guard in `use-api-query.ts:66` (`finally { setIsLoading(false) }` unconditionally).

---

## P1 — High

### 2. `/escalations` redirects to `https://localhost:3000` → broken error page
- **File**: `admin-panel/src/app/(authenticated)/escalations/route.ts:13`
- **Code**: `const destination = new URL("/conversations?filter=escalated", request.url); return Response.redirect(destination, 308);`
- **Cause**: behind the reverse proxy, `request.url` is the container-internal host (`localhost:3000`), so the 308 emits `Location: https://localhost:3000/conversations?filter=escalated`, which the stylist's browser cannot resolve → Chrome error page. **Affects production too**, not just dev.
- **Fix**: move to `next.config.ts` `async redirects()` returning `{source:'/escalations', destination:'/conversations?filter=escalated', permanent:true}` (Next handles relative destinations proxy-safely), or build the absolute URL from `x-forwarded-host`/`x-forwarded-proto`.

### 3. Dashboard "Necesitan atención" items are not clickable
- **Surface**: `/dashboard`, "Necesitan atención" panel (5 pending). **Files**: `components/dashboard/escalation-item.tsx`, `app/(authenticated)/dashboard/page.tsx`.
- **Symptom**: the items are plain `<div>`s — no link/button. A stylist sees "5 need attention" but clicking does nothing; she has no path from the alert to the conversation. Dead-end.
- **Fix**: wrap each item in a link to the conversation (`/conversations?filter=escalated` or the specific conversation), once the inbox is fixed.

---

## P2 — Medium (clarity / leaks for a non-technical user)

### 4. Dashboard "Necesitan atención" shows raw snake_case reason codes
- Shows `manual_request`, `medical_consultation`, `cancellation_window_exception` and the customer's phone instead of a human label/name.
- **The Spanish mapping already exists** — the notification center renders these correctly ("Escalación: Solicitud de usuario", "Escalación: Consulta médica"). The dashboard widget just doesn't apply it. **Fix**: reuse the notification label map in `escalation-item.tsx`.

### 5. Calendar "Mes" view: bogus day numbers in weekday headers
- **Surface**: `/calendar` → Mes. Headers render "LUN 5 · MAR 6 · MIÉ 7 · JUE 8 · VIE 9 · SÁB 10 · DOM 4" — stray date numbers (and the Sunday "4" breaks even the sequence). In a month grid the column headers should be weekday names only. Week-view header logic is leaking into month view. **File**: calendar view component under `components/` (`calendar/...`).

### 6. Appointment edit shows raw enum `Marta (HAIRDRESSING)`
- **Surface**: `/appointments/{id}` → Estilista dropdown. Shows the raw English enum `HAIRDRESSING` in the option label.
- The mapping exists in `components/shared/category-badge.tsx` (and stylist/service SelectItems use "Peluquería"/"Estética"); the appointment edit dropdown builds `${name} (${rawCategory})` instead of the localized label. **Fix**: use the category label map for the option text.

### 7. "Memoria del bot" exposes a raw editable UUID
- **Surface**: `/customers/{id}` → Memoria del bot → field **"ID Estilista preferida"** = `5f1745ba-d2b1-4d87-8d47-79821a99ae93` as an editable text input. Meaningless and risky for a stylist (she could corrupt the FK). **Fix**: hide it or make it internal/read-only; keep only the human "Estilista preferida" field.

---

## P3 / Polish

8. **Greeting uses raw username**: "Buenas tardes, **pepecabeza**" instead of the visible name "Pepe Cabeza". `components/dashboard/dashboard-greeting.tsx` — use `nombre visible`, not username.
9. **Locale not pinned to es-ES**: appointment edit shows time as `10:00 AM` (AM/PM) and the bot-memory "Última visita" as `06/16/2026` (MM/DD/YYYY), while the rest of the app uses 24h + DD/MM. Inconsistent for a Spanish salon.
10. **Stylists list**: Pilar's Google Calendar cell shows the raw calendar ID (`4df9392d761b0e0a80c5f62f921c07…`) instead of "Conectado ✓" / a calendar name.
11. **Missing Spanish accents** in several headers/labels: "Categoria", "Descripcion", "Telefono", "Pagina", "Miercoles", "Sabado", and in notifications "Escalacion / atencion / medica".
12. **Notification click** marks-as-read but does not navigate to the related conversation (missed affordance for an escalation alert).
13. **Data/display inconsistencies**: customer name renders "Pepe Cabeza" in Clientes but "Pepe cabeza" in Citas; customer Perfil shows "Última visita: Sin visitas" while Memoria del bot shows "1 visita el 16/06" (two different sources, contradictory to the operator).

---

## Could NOT be verified (tooling / data limits)

- **gcal-retry red badge + retry button** (`/appointments`): no failed-sync data exists in the sandbox (all `not_applicable` under `TEST_MODE_GCAL_SKIP`), so the red badge never appears. Needs a row with `gcal_sync_status='failed'` to test live.
- **Inbox interactions** (takeover/pause/resume, templates, window-status, customer card, delete conversation, escalated filter): blocked by the P0 inbox bug.
- **Authenticated responsive (tablet/mobile)**: the browser tooling did not honor viewport resize (innerWidth stayed fixed), and the separate CDP browser is not logged in. The **login page is confirmed responsive at 390px** (clean centered card). Code shows the sidebar has a mobile drawer ("Abrir menú"), but the inbox 3-column layout uses collapsible panels without a clear mobile-stacking breakpoint and may be cramped on a phone. **Recommend a manual pass on a real tablet/phone.**

---

## What works well (the panel is largely solid)

- **Calendar**: week view, color-coded stylist filters, status legend, slot-duration control, current-time line, rich appointment popover (cliente/servicios/hora/duración/estado/cancelar).
- **Citas**: clean list with filters, sortable columns, well-coloured status badges (Confirmada/Completada/No asistió); full edit form (Reagendar/Cancelar/Guardar/Eliminar) with good skeleton loading state.
- **Clientes**: rich detail with Perfil / Citas / Memoria del bot tabs, política-de-privacidad badge, actividad, editable notes.
- **Estilistas / Servicios / Usuarios / Configuración**: all load and function; Servicios paginates (78 rows); Config is a clean 9-card hub; Horarios works with per-day Abierto/Cerrado + 24h times.
- **Notification center**: human-readable, well-localized, mark-as-read works.
- **States & polish**: empty states, loading skeletons, and color-coding are consistently good.

---

## Priority recommendation

1. **Fix the P0 inbox loading** and **deploy the production build** — without these the stylist cannot do the core job (messaging) and `/escalations` is broken.
2. Fix the P1 redirect (`escalations/route.ts:13`) and make dashboard escalations clickable.
3. Sweep the P2 leaks (reason codes, HAIRDRESSING, month headers, UUID field) — they directly erode confidence for a non-technical operator.
4. P3 polish as a batch (greeting, locale, accents).
