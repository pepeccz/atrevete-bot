# Atrévete Admin — Conversations Inbox UI Audit

Date: 2026-07-06
Target: https://atrevete.zanovix.com
Tester: playwright-mcp automated QA agent

Ground truth: 6 seeded conversations (phones +34999000041..46, conversation_ids 900041-900046):
Ana Test (bot ON), Bea Test (bot ON), Carla Test (paused), Diana Test (paused),
Eva Test (escalated + auto-paused), Fabiola Test (bot ON).

---

## Item-by-item results

### 1. Login flow — PASS
Logged out via user menu, landed on `/login`, filled `admin` / `AtrevetePeluqueria#1`,
submitted, redirected to `/dashboard`. No console errors (only benign CSS-preload
warnings, present on both `/login` and `/dashboard`).
Evidence: `01_login.png`, `02_dashboard.png`

### 2. Navigate to /conversations (desktop 1440x900) — PARTIAL FAIL
3-column layout renders (list | thread placeholder | customer card). Tab counters
render correctly (Todas 325, Bot ON 312, Bot OFF 13, Escaladas 11, Sin leer —).
**However**: none of the 6 seeded Test conversations (Ana/Bea/Carla/Diana/Eva/Fabiola)
appear anywhere in the default "Todas" list, even though ground truth says they are
the most recently started conversations and should be at the top. Root cause
identified below (#F1). No orphaned/no-customer rows are visible on this default tab
either — see #F1 for why.
Evidence: `03_conversations_desktop.png`

### 3. Filter tabs — PASS for Bot OFF / Escaladas, FAIL for Todas / Bot ON
- **Escaladas**: correctly shows Eva Test (Pausado badge) at top of 11 items, backed
  by the DB (`source:"db"`), correctly ordered by `started_at` DESC.
- **Bot OFF**: correctly shows Carla Test, Diana Test, Eva Test at the top (in that
  order — Carla 13:45 > Diana 13:35 > Eva 13:25 UTC), backed by DB, correct ordering.
- **Todas** and **Bot ON**: return an entirely different dataset sourced from Redis
  (see #F1) — Ana Test, Bea Test, Fabiola Test never appear under either tab despite
  being "bot ON" per ground truth.
- Tab counters (325/312/13/11) matched the `counts` object in every API response and
  matched the actual `total` returned per filter — no counter/list mismatch once
  requests fully resolved. (An initial "No hay conversaciones" observed on Escaladas
  was a snapshot-timing race, not a bug — confirmed by re-checking after the ~20s API
  call completed; see #F3.)
Evidence: `04_filter_escaladas.png`

### 4. Open Ana Test's thread — FAIL
Deep-linked to `/conversations?conversation_id=900041` (Ana Test, bot ON, DB-seeded,
no live Redis checkpoint). The thread panel renders:
> "Esta conversación ya no está disponible. Puede haber expirado o ya fue resuelta.
> Puedes resolver la escalación desde el panel."
This is an **escalation-specific error message shown for a conversation that is not
escalated at all** — Ana Test is plain bot-ON, never escalated. The underlying cause
is #F1: the conversation detail endpoint apparently cannot resolve a DB-only
conversation that has no matching Redis-backed thread, and the frontend falls back
to a generic/misleading "escalation expired" copy regardless of context.
Evidence: `05_thread_ana.png`

### 5. Open Eva Test's thread — PASS
Deep-linked via the same URL pattern the dashboard "Necesitan atención" widget uses
(`/conversations?conversation_id=900045&filter=escalated`). Thread loads correctly:
4 messages in chronological order, "Bot pausado desde 06 jul, 15:30 · Atención
manual" banner, "Reanudar bot" button, window-status "Ventana abierta · quedan 23h".
Customer card populated (phone +34999000045, policy accepted 03/07/2026, no notes,
0,00 € total spent). No mutating actions were taken.
Evidence: `06_thread_eva.png`

### 6. Unread badge check — PASS (matches known code fact)
Every conversation item and every API response shows `unread_message_count: 0`, and
no unread badges render anywhere in the UI (including on Eva Test's thread, which per
ground truth has a DB-level unread message). Confirms the hardcoded-0 finding from
code reading — the discrepancy between DB truth (1 unread on Ana) could not be
directly observed since Ana's thread cannot be opened at all (#4), but the
hardcoded-0 behavior is confirmed on every other visible conversation.

### 7. Ordering probe — PASS for DB-backed filters, N/A for Redis-backed
Bot OFF and Escaladas results are correctly ordered by `started_at` DESC (verified
via raw API payload timestamps). Todas/Bot ON items all have `started_at: null`
(Redis-sourced) so no ordering guarantee applies there at all — see #F1. As expected
per ground truth, no live message can float a conversation on the DB-backed tabs
without changing `started_at`; this was not further tested since it requires sending
real messages (explicitly out of scope).

### 8. Deep-link — PASS
- `/conversations?conversation_id=900045&filter=escalated` correctly resolves to Eva
  Test's thread (the app internally rewrites the URL param to the DB row's UUID
  `id`, e.g. `b0000000-0000-4000-8000-000000000045`).
- `/escalations` correctly issues a redirect to `/conversations?filter=escalated`
  with no `localhost` leak in the target URL.
Evidence: `07_deeplink_escalations_redirect.png`

### 9. Responsive (768x1024, 375x812) — FAIL
- **Tablet (768x1024)**: sidebar does NOT collapse; the 3-column layout does not
  reflow — the middle "thread" panel renders as a large blank area, and the
  right-hand customer panel is pushed far right with excess empty space between
  panels. Layout is functional but visually broken (unused blank space, disjointed
  proportions).
- **Mobile (375x812)**: sidebar correctly collapses to a hamburger menu (small win),
  but the list/thread/customer 3-column layout does **not** stack into a
  single-column or tabbed view. Selecting a conversation (Eva Test) leaves the full
  conversation list visible, squeezes the customer panel into an unreadable sliver,
  and the actual message thread + composer are **not visible at all** without
  horizontal scrolling. Confirmed programmatically:
  `document.documentElement.scrollWidth = 458px` vs `clientWidth = 360px` — genuine
  horizontal overflow (~98px), which the test plan explicitly calls a FAIL condition.
Evidence: `08_tablet.png`, `09_mobile.png`, `10_mobile_thread.png`

### 10. Console + network sweep — PASS (no errors) / PERFORMANCE FAIL
- **Console**: 0 errors across the entire session (login, dashboard, all filters,
  both threads, all viewport sizes). Only 5-7 recurring benign warnings, all the
  same "CSS preloaded but not used" Next.js warning on multiple routes — cosmetic,
  not a functional issue.
- **Network**: no 400s, no 404s, no CORS errors, no 500s observed on any request
  during this run, including `mark-read` (200) and repeated `window-status` polls
  (all 200). The previously-known B5 pattern (mark-read 400s / window-status 404
  spam) was **not reproduced** in this session.
- **New finding — severe performance issue (#F2)**: every
  `GET /api/admin/conversations?...` call took **~20-22 seconds** to resolve
  (confirmed durations: 20611ms, 21630ms, and a further ~22s wait needed after
  navigating to `/conversations` directly). This affects every tab switch, since
  each filter click triggers a fresh full page_size=100 fetch. This is a severe
  latency problem that will read as "broken/hung" to real operators, independent of
  the data-source bug in #F1.

---

## Cross-cutting findings (ranked by severity)

### F1 — CRITICAL: "Todas" and "Bot ON" tabs read from Redis, not the DB; DB-only conversations are invisible and unopenable there
`GET /api/admin/conversations?filter=all` and `?filter=bot_on` both return items
with `"source":"redis"`, `"started_at":null`, `"created_at":null` — this is clearly
a live/in-flight LangGraph checkpoint cache, not the persisted `conversation_history`
table. `?filter=bot_off` and `?filter=escalated` return `"source":"db"` items with
real timestamps, correctly ordered by `started_at` DESC.

Consequence: any bot-ON conversation that exists only in the DB (no active Redis
checkpoint — e.g., seeded via script rather than a live WhatsApp session) is
**invisible** on the two most commonly used tabs ("Todas" and "Bot ON"), cannot be
found via search (`q=Test` returns `{"items":[],"total":0}` even though "Eva Test"
literally exists), and its thread **cannot be opened** — the detail view falls back
to a generic, contextually wrong "escalation expired" message (item #4).

This means real customers whose conversations are bot-ON but whose Redis checkpoint
has expired/been flushed (a documented, deliberate operational step in this repo's
own deploy runbooks — "flush old Redis checkpoints") would also disappear from the
default admin view after any checkpoint flush, which is a serious operational risk
beyond just QA-seeded data.

Recommended fix direction: "Todas" and "Bot ON" should query the same
`conversation_history` DB source used by "Bot OFF"/"Escaladas" (optionally merged
with live Redis state for real-time enrichment), not substitute Redis as the primary
source of truth for the list.

### F2 — CRITICAL (performance): `/api/admin/conversations` takes ~20-22 seconds per call
Every single list fetch (any filter, page_size=100) took 20-22 seconds end-to-end in
this session, consistently. This alone makes the inbox feel broken/unresponsive on
every tab switch and page load, independent of F1.

### F3 — Minor / non-issue: transient "No hay conversaciones" on fast snapshot right after filter click
Taking a snapshot immediately after clicking a filter tab can catch the loading
gap before the (slow, per F2) API response lands, rendering the empty state
momentarily. Not a real bug — confirmed the data arrives correctly once the request
resolves. Worth noting only because it makes F2's latency very visible/jarring to a
real user clicking through tabs quickly.

### F4 — Minor: tablet (768px) layout has poor space utilization
Not a hard functional break like mobile, but panels don't reflow proportionally,
leaving large unused blank areas. Low priority relative to F1/F2/mobile stacking.

---

## Screenshots saved (in this directory)
- `01_login.png` — login page
- `02_dashboard.png` — dashboard after login
- `03_conversations_desktop.png` — /conversations default "Todas" view, 1440x900
- `04_filter_escaladas.png` — Escaladas filter, Eva Test visible with Pausado badge
- `05_thread_ana.png` — Ana Test deep-link FAIL ("conversación ya no disponible")
- `06_thread_eva.png` — Eva Test thread PASS (messages, pause banner, window status)
- `07_deeplink_escalations_redirect.png` — /escalations → /conversations?filter=escalated
- `08_tablet.png` — 768x1024 layout
- `09_mobile.png` — 375x812 list view
- `10_mobile_thread.png` — 375x812 thread view showing horizontal overflow/clipping
