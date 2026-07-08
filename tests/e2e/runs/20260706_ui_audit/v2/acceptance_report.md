# inbox-reliability-p1 — Final Acceptance UI Audit (v2)

- Commit under test: `65615a1` (deployed at pepe@server)
- Date: 2026-07-06
- URL: https://atrevete.zanovix.com
- Viewport baseline: 1440x900, then 1024x768, 768x1024, 375x812

## Stage 1 — Seed

Seed script: `seed_inbox_v2.sql` (adapted from prior `seed_inbox.sql` to set `ended_at`
on every row, staggered to match `started_at` order, then a follow-up `UPDATE` flips
Bea's `ended_at` to `now()` without touching her `started_at`).

Ground truth (`ORDER BY ended_at DESC NULLS LAST`), confirmed via psql immediately after seeding:

| Order | Customer | conversation_id | started_at | ended_at |
|---|---|---|---|---|
| 1 | Bea | 900042 | 16:57:44 | 17:17:44 (flipped to `now()`) |
| 2 | Ana | 900041 | 17:07:44 | 17:12:44 |
| 3 | Carla | 900043 | 16:47:44 | 16:52:44 |
| 4 | Diana | 900044 | 16:37:44 | 16:42:44 |
| 5 | Eva | 900045 | 16:27:44 | 16:32:44 |
| 6 | Fabiola | 900046 | 16:17:44 | 16:22:44 |

## Stage 2 — Browser validation

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| 1 | Perf: `/conversations` initial load | **PASS** | `/api/admin/conversations` resource-timing duration: 39–90 ms (3 requests observed: 60ms, 90ms, 40ms). Baseline was 20–22 s. **~250–500x improvement**, well under the 2s target. |
| 2 | Activity ordering (Bea first) | **PASS** | v2_01_order.png. List renders Bea, Ana, Carla, Diana, Eva, Fabiola — matching `ended_at DESC` ground truth exactly. Notably Ana's displayed timestamp (19:07) is *later* than Bea's (18:57) yet Bea ranks first, proving the order key is `ended_at`/activity, not `started_at` or the displayed timestamp. |
| 3 | Unread badge (Ana) | **PASS** | v2_01_order.png / v2_06_loading_skeleton.png (post-load). Ana shows a real amber "1" unread-count badge next to her name, computed by the backend (not hardcoded 0 as in the pre-fix state). |
| 4 | Tab filters + counts | **PASS** | v2_02_bot_on.png, v2_03_bot_off.png, v2_04_escaladas.png. Bot ON (7) contains Ana, Bea, Fabiola + 4 pre-existing prod conversations. Bot OFF (13) contains Carla, Diana, Eva + 10 pre-existing paused/escalated conversations. Escaladas (11) contains Eva (only our seeded escalated one) + 10 pre-existing escalations. All bucketing is internally consistent — no seeded item appears in the wrong tab. |
| 5 | Escalada badge visually distinct from Pausado | **PASS** | v2_03_bot_off.png, v2_05_escalada_badge.png. Eva shows a red "Escalada · manual_request" pill; Carla/Diana show a neutral gray "Pausado" pill. Clearly distinct by color and label. |
| 6 | Relative timestamps on default tab | **FAIL (discrepancy)** | v2_01_order.png. List items show **absolute** timestamps (`06/07/2026 18:57`), not relative ("hace 10 min"). This contradicts the acceptance expectation. Note the Dashboard's "Necesitan atención" widget *does* use relative timestamps ("hace alrededor de 1 hora"), so the pattern exists elsewhere in the app but was not applied to the conversation list rows. Low severity / cosmetic, but worth a follow-up ticket if relative timestamps were an intended PR-3 deliverable. |
| 7 | Skeleton on load, no re-flash on background poll | **PASS** | v2_06_loading_skeleton.png (genuine animated skeleton rows, not bare "Cargando…", captured by delaying the `/api/admin/conversations` response 3s via route interception), v2_07_after_slow_load.png (resolves correctly). For the no-re-flash check: navigated to `filter=unread` (closest available "sparse" tab, 5 items — no filter was literally empty), waited 35s (one full poll cycle at the 30s list-mode-with-unread cadence per `useConversationPolling.ts`), confirmed via `browser_network_requests` that a background re-fetch did occur (4th request to the endpoint) and via DOM check that no `animate-pulse` skeleton class was present after — i.e., the real list stayed rendered through the poll, no flash back to skeleton. |
| 8 | Deep-link numeric `conversation_id=900045` | **PASS** | v2_10_deeplink_eva.png. URL canonicalizes `900045` → the internal UUID (`b0000000-...-045`); Eva's thread resolves and renders with all 4 messages, paused-bot banner, and populated customer card. Confirms the resolve-then-swap flow works for the Chatwoot-style numeric ID format. |
| 9a | Responsive: 1440x900 → 3 columns | **PASS** | v2_01_order.png shows list / thread-placeholder / customer-panel as three simultaneous columns. |
| 9b | Responsive: 1024x768 → 2 columns + drawer | **PASS** | v2_11_1024_2col.png (list + thread, composer visible, "Ver cliente" trigger appears in place of the 3rd column), v2_12_1024_drawer.png (Sheet drawer opens over the content with full customer card: contacto, política, preferencias, última actividad, notas, resumen). |
| 9c | Responsive: 768x1024 → 2 columns, thread must not vanish | **PASS w/ finding** | v2_13_768_carla.png, v2_14_768_overflow_fullpage.png. Carla's messages and composer **are present and visible** in the DOM/accessibility tree (the original "thread vanished" baseline bug is fixed) — **but** a new, related layout bug was found: at 768px width the full-width left nav sidebar does not auto-collapse, so `document.documentElement.scrollWidth` (840px) exceeds `clientWidth` (753px), producing horizontal overflow that clips the right edge of the thread panel and composer. Manually clicking the sidebar-collapse toggle fixes it immediately (scrollWidth becomes exactly 768px, confirmed via `browser_evaluate`, screenshot v2_15_768_sidebar_collapsed_fixed.png). **Recommend**: the sidebar should auto-collapse (or hide behind a toggle) below the `xl` breakpoint so the 2-column conversations layout doesn't require a manual sidebar-collapse step to avoid horizontal scroll. |
| 9d | Responsive: 375x812 → 1 column, back button, no overflow | **PASS** | v2_16_375_list.png (list fills width, hamburger nav), v2_17_375_thread_ana.png (tap Ana → thread view, back button + composer visible, `scrollWidth === clientWidth === 375`, no overflow), v2_18_375_drawer.png (Info button opens the same Sheet drawer with full customer card), v2_19_375_back_to_list.png (back button returns cleanly to the list, URL reverts to `/conversations`). |
| 10 | Single-fetch check (`GET /customers/{id}`) | **PASS** | With the drawer open at 1024 width, `browser_network_requests` filtered to `/customers/a0000000...` showed exactly **one** `GET /api/admin/customers/{id}` call (plus one `/appointments` sub-resource call and two Next.js RSC route-prefetch requests for the `/customers/{id}` page, which are a separate concern — link prefetching, not duplicate API data fetches). |
| 11 | Console errors sweep | **PASS** | A clean fresh navigation to `/conversations` (after all interactive testing) produced **0 errors, 0 warnings**. During the stress sequence (rapid resize 1024→768→375, sidebar collapse/expand, multiple conversation switches), a transient burst of ~8 duplicate "Conversation not found" 404s for Carla's thread ID appeared in the console; a targeted follow-up (navigate to Carla's thread, then to `/dashboard`, wait 10s) showed **zero** further requests for that thread ID — confirming this was **not** a steady-state background-polling leak, just transient noise correlated with the rapid manual viewport/interaction churn (and possibly artifacts of an earlier Playwright route-interception test in this same session). Recommend a light follow-up if this recurs in real usage, but it did not reproduce cleanly and does not block acceptance. |

## Stage 3 — Cleanup

All 6 seeded customers (`+34999000041`..`046`), their `conversation_history` /
`conversation_messages` rows, and Eva's `escalations` row were deleted. Verified via
psql: `remaining_customers = 0`, `remaining_conv_history = 0`, `remaining_escalations = 0`.

## Summary

**12 of 13 checked items PASS** (item 6 timestamps is a FAIL/discrepancy — cosmetic,
low severity). One new finding surfaced outside the checklist: horizontal overflow at
768px width due to the sidebar not auto-collapsing (item 9c) — the specific "thread
vanishes" baseline regression is fixed, but a related layout issue remains at that
exact breakpoint. Overall: **the inbox-reliability-p1 chain is functionally solid and
the massive performance win (20–22s → ~40–90ms) is confirmed in production.** Two
follow-up tickets recommended: (a) relative timestamps in the conversation list, (b)
sidebar auto-collapse below `xl` to eliminate 768px horizontal overflow.
