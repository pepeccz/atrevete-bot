# Admin-Panel Frontend UX/Functional Backlog — consolidated

**Date**: 2026-06-16
**Method**: 4 parallel read-only code audits (dashboard+layout+notifications · conversaciones inbox · citas+calendario · clientes+gestión), building on the live UX test (`frontend-ux-report-2026-06-15.md`).
**Total**: ~110 findings (24 P1 · ~47 P2 · ~39 P3). Organized below by **cross-cutting theme** (how we'd fix coherently), not by screen.

> Lens: a non-technical salon operator must run this confidently. Two rules from the owner: **castellano de Madrid (tú, never voseo)**; **touch by resolving — validate each item before fixing, don't break working flows.**

---

## Theme A — Dead / unwired controls (P1) — highest impact
Controls that render but do nothing. This is the single biggest cluster.
- Dashboard **"Nueva cita" button has no `onClick`** → dead. `dashboard/page.tsx:195-199` → wire to AppointmentWizard.
- Dashboard **agenda rows non-interactive** (`onClick` prop exists, never passed; `MoreHorizontal` is raw SVG). `agenda-row.tsx:62`, `dashboard/page.tsx:272-281`.
- Dashboard **"Necesitan atención" items: no click, no dismiss, no link** + raw reason. `escalation-item.tsx:10-42` → click→`/conversations?filter=escalated&conversation_id={id}` + **dismiss=resolve** (`resolveEscalation`). *(the owner's request; partially in PR #60)*
- **Notification clicks dead for urgent types** — only `appointment` navigates; escalation / `conversation_history` only mark-read. `notification-center.tsx:230-233`.

## Theme B — Raw technical values leaked to the operator (P1/P2)
Internal codes shown verbatim to a non-technical user.
- **`HAIRDRESSING` / `AESTHETICS` enum** in appointment-edit Estilista dropdown. `appointments/[id]/page.tsx:291-295`. (A `CATEGORY_LABELS` map already exists in `blocking-event-modal.tsx:91-96` → extract to `lib/category-labels.ts`, reuse everywhere.)
- **snake_case escalation reasons** (`manual_request`, `cancellation_window_exception`) on dashboard + PausedBanner. `escalation-item.tsx`, `PausedBanner.tsx:110-113`.
- **English appointment status** ("completed"/"confirmed") in CustomerCard. `CustomerCard.tsx:368-375`.
- **Raw editable UUID** "ID Estilista preferida" in customer Memoria del bot → should be a `<Select>` from /stylists. `customers/[id]/page.tsx:578-595`. *(owner flagged earlier)*
- Google Calendar settings: **OAuth scope URLs**, **`access_role` enums**, **hex colors** shown raw. `settings/google-calendar/page.tsx:675,793,805`.
- Settings/System: **raw LLM model id** `openai/gpt-5.4-mini` in dropdown. `settings/system/page.tsx:153-163`.
- Stylists list + customer Perfil: **raw GCal IDs / chatwoot_conversation_id** as opaque text. `stylists/page.tsx:537-541`, `customers/[id]/page.tsx:332-341`.
- Trend chart tooltip: **raw ISO date** `2026-06-14`. `appointments-trend-chart.tsx:65`.

## Theme C — Voseo → castellano de Madrid (P2) — ties to owner directive
The panel has voseo leaking in several user-facing strings; normalize to **tú** (castellano de Madrid). The agent prompt already mandates this; the UI must match.
- "Activá al menos un estilista…" `calendar-day-view.tsx:321`
- "Editalo si la cita es para otra persona" `create-appointment-modal.tsx:589`
- "Para reasignar, eliminá y creá un bloqueo nuevo" `blocking-event-modal.tsx:605`
- "Agendá la primera cita…" `appointments/page.tsx:139`
- Settings hub cards mix "Seleccioná" with "Conecta" `settings/page.tsx:12,19`
- (A scan for other voseo forms across copy should run as part of this batch.)

## Theme D — Missing Spanish accents (P3) — mechanical copy
Headers/labels/copy without tildes. Pure text, zero logic risk.
- Headers: "Telefono", "Ultima Visita", "Categoria" (×2), "Descripcion", "Pagina". `customers/page.tsx:295,325`, `services/page.tsx:409,426`, `stylists/page.tsx:523`.
- Business hours: "Miercoles", "Sabado". `business-hours/page.tsx:19,22`.
- Notifications: "leida"(×4), "Notificacion", "gestion", "estadisticas". `settings/notifications/page.tsx`.
- Google Calendar: 8 strings ("conexion","seleccion","codigo"×2,"parametro","deberas","eliminara","recibio"). `settings/google-calendar/page.tsx`.
- Citas/calendar: "No se encontro la cita" `[id]/page.tsx:209`; "dias disponibles", "+n mas" `availability-picker.tsx:238,306`; "Dia" `calendar-view.tsx:1347`.

## Theme E — Swallowed error states (P1/P2)
Failed fetches look identical to empty/no-data → operator misled.
- Inbox list / thread / customer-card / notes-mutation / search / templates: errors silent, no retry/toast. `ConversationList.tsx:189-191`, `ConversationThread.tsx:246-249`, `CustomerCard.tsx:243-253,487-490`, `TemplatePicker.tsx:44-55`.
- Dashboard KPI failure → silent "—". `dashboard/page.tsx:130-133`.
- Notifications loading skeleton is dead code (`setLoading` never called → blank popover). `notification-center.tsx:142,264`.

## Theme F — Silent result/pagination caps (P1)
Data silently truncated, no indicator.
- Customers `page_size:200` no pagination. `customers/page.tsx:248`.
- Citas `page_size:100` no pagination. `appointments/page.tsx:48-52`.
- Inbox tab counts derived from local 100-slice, not server `counts`. `ConversationList.tsx:184-194`.

## Theme G — Native input locale (P1/P2)
- Time `<input type="time">` renders AM/PM on en-US OS (appointment edit + create modal). `[id]/page.tsx:316-321`, `create-appointment-modal.tsx:563-569`. → controlled 24h Select or lock `hour12:false`.
- Date `<input type="date">` "Última visita" → OS locale (MM/DD). `customers/[id]/page.tsx:724-731`. → shared DatePicker.
- `formatTimeRange` single-digit hour "9:00" vs "09:00". `lib/calendar-time.ts:64-70`.

## Theme H — Search / filter gaps (P1/P2)
- Customers search filters only `first_name` (not surname/phone). `customers/page.tsx:416`.
- Users table: no search. `users/page.tsx:523-529`.
- Citas: no date-range filter ("Hoy" pill). `appointment-filters.tsx`.
- Services: no "Ambos/BOTH" filter option. `services/page.tsx:514-518`.

## Theme I — Inbox interaction/polling bugs (P1/P2)
- **Scroll-jacking**: thread auto-scrolls to bottom every poll tick (3 s) → can't read history. `ConversationThread.tsx:263-266`.
- **Double pause request**: BotToggle + Composer each instantiate TakeoverModal → 2 concurrent `pauseConversation`. `BotToggle.tsx:105-112`, `Composer.tsx:202-208`.
- Unread badge lags up to 60 s after open (no optimistic zero). `ConversationThread.tsx:257-260`.
- Polling not paused during send (`enabled:!sending`). Duplicated window-status loop. `ConversationThread.tsx:268-272,525-568`.
- Thread ⋯ menu only has destructive "Eliminar" (add "Abrir en Chatwoot"). `ConversationThread.tsx:359-367`.

## Theme J — Calendar bugs (P2)
- **Mes view weekday headers show bogus day numbers** ("LUN 5 … DOM 4") — `dayHeaderContent` calls `getDate()`. Fix: return undefined for `dayGridMonth`. `calendar-view.tsx:1380-1392`.
- Zoom/slot-duration control visible in Mes view (no effect, misleading). `calendar-toolbar.tsx:181-205`.
- **Two parallel creation forms** (Wizard via "Nueva cita" vs flat CreateAppointmentModal via slot-click) — unify. `calendar-view.tsx:1447-1463`.
- Toolbar prev/next aria-labels hardcoded "Semana" regardless of view. `calendar-toolbar.tsx:99,107`.
- Non-sortable Citas headers look clickable. `appointments-table.tsx:107-244`.
- GCal column always visible/blank; rename "Sincronización", hide when 0 failures. `appointments-table.tsx:204-208`.

## Theme K — Notifications/escalations actionability (P1) — owner's request
- Dismiss = **resolve** (not cosmetic hide), backed by `resolveEscalation` / per-notification dismiss endpoint, keeping the "X pendientes" counter honest. (Covered in A + B; called out as its own theme because it's the trigger for this audit.)
- No per-notification dismiss/delete in the bell center. `notification-center.tsx:300-305`.

## Theme L — Accessibility (P3)
Icon buttons missing `aria-label` (edit buttons across customers/stylists/services; bell; search input; settings "Configurar" ×9 identical); notes toggle missing `aria-expanded`; raw `<textarea>` instead of design-system `<Textarea>`; `<a>`-wrapping-`<button>` invalid HTML in notifications.

## Theme M — Misc consistency / data integrity (P2/P3)
- `no_show` status uses same color as `completed` (should be red/amber). `status-pill.tsx:32-37`.
- Editable `visit_count`/`last_visit_date` in Memoria contradict computed history (add "se calcula automáticamente" or read-only). `customers/[id]/page.tsx:699-731`.
- Appointment-edit "Cancelar" silently discards edits (no dirty-check). `[id]/page.tsx:412-417`.
- No GCal retry on the edit page (only in list). `[id]/page.tsx`.
- "Sync GCal" English button. `header.tsx:138`.
- Terminology drift: "Añadir"/"Agregar", "Nuevo"/"Crear". Settings subpages have no breadcrumb back to hub.
- Dead props: `KpiCard.delta`, stylist `"idle"` status never emitted.

---

## Already in-flight (PR #60, unmerged) — dedupe
- Dashboard escalation items → clickable deep-link (Theme A/K click part).
- Inbox stuck-loading in hidden tab (initial unconditional fetch).
- /escalations proxy-safe redirect.

## What's genuinely GOOD (don't touch)
Date formatting via `formatDate()` (dd/MM/yyyy HH:mm, es) on most surfaces; AlertDialog confirmation on ALL destructive actions; thorough skeletons; `Promise.allSettled` + AbortController on dashboard; toast feedback on mutations; pause/resume 409-vs-502 differentiation; adaptive focus-aware polling; attachment lightbox a11y; the 4-step booking wizard with overlap detection; GCal-retry flow in the citas list.

---

## Proposed remediation batches (coherent, low→high risk)

**Lote 1 — Copy & labels (zero logic risk, high polish ROI)**: Theme C (voseo→tú) + D (accents) + the raw-value→Spanish-label maps in B (extract `lib/category-labels.ts`, status/reason/access_role maps) + "Sync GCal"/English strings. Pure presentational; safe to ship fast.

**Lote 2 — Wire the dead controls + notifications/escalations actionability (the owner's ask)**: Theme A + K — "Nueva cita", agenda rows, escalation click+**dismiss=resolve**, notification navigation. Reuses existing endpoints; validate each wiring + permission gates.

**Lote 3 — Honesty of data (errors, caps, search)**: Theme E + F + H — error/retry states, pagination indicators, customers/users search. Touches data fetching; needs care + re-test.

**Lote 4 — Inbox & calendar behavior**: Theme I + J — scroll-jack, double-pause, month headers, unify creation forms. Highest behavioral risk; validate each finding live before fixing.

**Lote 5 — Accessibility & misc polish**: Theme L + M.

Each item must be **validated against current code before fixing** (a code-audit can have false positives) and **re-tested** so working flows aren't regressed.
