# state-first-booking — xfail tracking

## Introducción

Este archivo documenta los 17 tests marcados con `@pytest.mark.xfail(strict=True)` como parte del
change `state-first-booking` (Batch 4). Todos ellos referenciaban `_build_flow_hint`, un método
estático que fue eliminado en el Batch 4 de este change.

**Por qué existen**: `_build_flow_hint` era la implementación original que construía el estado del
booking como un bloque XML `<flow_hint>`. Los tests validaban esa API. Tras el delete del método, los
tests quedaron en xfail porque su behavior target (el bloque `[estado]` en el `HumanMessage` del
`StatusLineMiddleware`) no está activado aún — el feature flag `ENABLE_STATUS_LINE_MIDDLEWARE` sigue
en `False` (default). Estos tests necesitan ser reescritos para apuntar al nuevo contrato de
`StatusLineMiddleware._inject()` en lugar de `BookingModeNode._build_flow_hint()`.

**Cuándo cerrar esta lista**: ANTES de `sdd-archive`. Cada xfail debe tener una decisión tomada
(delete, rewrite, o mantener con justificación). Ver checklist al final.

**Para crear el issue master**: Copiar el contenido de este archivo como body de un nuevo GitHub
issue con título `state-first-booking: _build_flow_hint xfails cleanup`. Una vez creado, actualizar
el campo `reason` de cada `@pytest.mark.xfail` con `issue #NNN` (reemplazar `#TBD` con el número
real). Los 4 archivos a editar están listados en la columna "Archivo" de la tabla.

---

## Tabla de xfails

| # | Archivo | Función / Método | Scope del xfail | Recomendación |
|---|---------|-----------------|-----------------|---------------|
| 1 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_empty_ctx_all_pending` | Testa `_build_flow_hint({})` → keywords "pendiente", "servicio", "estilista", "nombre". API eliminada. | **rewrite** — reescribir contra `StatusLineMiddleware._inject()` con ctx vacío |
| 2 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_services_collected_stylist_pending` | Testa `_build_flow_hint` con `last_services` set. API eliminada. | **rewrite** — misma lógica, nuevo contrato |
| 3 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_services_and_stylist_collected` | Testa `_build_flow_hint` con services + stylist. | **rewrite** |
| 4 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_slots_offered_not_selected` | Testa `_build_flow_hint` con `offered_slots` sin `selected_slot`. | **rewrite** |
| 5 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_name_pending` | Testa `_build_flow_hint` sin `customer_name`. | **rewrite** |
| 6 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_all_required_collected_no_notes_asked` | Testa que `notes` no aparece como pending cuando notas son opcionales (R8/C5). | **rewrite** — este es el test más valioso: verifica el bug del loop; reescribir contra `[estado]` |
| 7 | `tests/unit/test_booking_conversational_flow.py` | `TestBuildFlowHint::test_all_collected_with_stylist_preference` | Testa `_build_flow_hint` con stylist preference. | **rewrite** |
| 8 | `tests/unit/test_booking_confirmation_loop.py` | `test_flow_hint_notes_not_pending_when_not_asked` | Valida R8/C5: notes no aparece como pending cuando `notes_asked=False`. Core del bug fix. | **rewrite** — test crítico, reescribir contra `StatusLineMiddleware` con flag ON |
| 9 | `tests/unit/test_booking_confirmation_loop.py` | `test_flow_hint_all_collected_sets_confirmation_shown` | Valida que `_confirmation_shown` se setea cuando all required fields presentes. | **rewrite** — lógica ahora en `_evaluate_confirmation_gate()` (Batch 2), test existe en `test_confirmation_gate.py` |
| 10 | `tests/unit/test_booking_confirmation_loop.py` | `test_flow_hint_confirmation_shown_mentions_waiting` | Valida que hint dice "esperando confirmación" cuando `_confirmation_shown=True`. | **rewrite** — verificar que `[estado]` incluye este estado |
| 11 | `tests/unit/test_booking_confirmation_loop.py` | `test_confirmation_shown_set_when_required_fields_present_without_notes` | Valida gate sin notas. Duplica cobertura de `test_confirmation_gate.py`. | **delete** — cubierto por `tests/unit/test_confirmation_gate.py` (14 tests, GREEN) |
| 12 | `tests/unit/test_booking_suggested_name.py` | `test_flow_hint_name_pending_no_suggestion` | Testa `_build_flow_hint` sin `customer_name` ni suggestion. | **rewrite** — contra `StatusLineMiddleware` |
| 13 | `tests/unit/test_booking_suggested_name.py` | `test_flow_hint_name_pending_with_suggestion` | Testa que suggestion presente pero no confirmada → nombre sigue pending. | **rewrite** — behavior importante: suggestion ≠ nombre confirmado |
| 14 | `tests/unit/test_booking_suggested_name.py` | `test_flow_hint_name_collected` | Testa que nombre confirmado aparece en "recogido". | **rewrite** |
| 15 | `tests/integration/test_booking_notes_optional.py` | `TestFlowHintNotasLeak::test_flow_hint_no_notas_pending_when_complete_without_notes` | Core del W1/R8 bug: `<flow_hint>Pendiente: notas</flow_hint>` leak. | **rewrite** — test más crítico del grupo; reescribir contra output del `StatusLineMiddleware` |
| 16 | `tests/integration/test_booking_notes_optional.py` | `TestFlowHintNotasLeak::test_confirmation_shown_set_when_complete_without_notes` | Valida que `_confirmation_shown=True` tras fix del leak. Cobertura parcialmente solapada con Batch 2. | **delete o rewrite** — si `test_confirmation_gate.py` ya cubre el gate, este puede eliminarse; de lo contrario reescribir |
| 17 | `tests/integration/test_booking_notes_optional.py` | `TestFlowHintNotasLeak::test_flow_hint_notas_in_collected_when_notes_asked_true` | Testa que `notes_asked=True` → notas aparece en "recogido" (no regresión). | **rewrite** — verificar que `StatusLineMiddleware` muestra notas en collected cuando `notes_asked=True` |

---

## Análisis por archivo

### `tests/unit/test_booking_conversational_flow.py` — clase `TestBuildFlowHint` (7 tests)
- **Scope**: Todos testean la API `BookingModeNode._build_flow_hint()` directamente.
- **Nuevo contrato**: `StatusLineMiddleware._inject(request)` → `HumanMessage` con prefix `[estado]`.
- **Acción**: Reescribir la clase entera como `TestStatusLineInject` con el mismo coverage semántico.
- **Prioridad**: Alta — son los tests más completos del behavior de estado.

### `tests/unit/test_booking_confirmation_loop.py` (4 tests)
- **Scope**: 3 tests del bug R8/C5 (notes no-pending), 1 duplica cobertura de `test_confirmation_gate.py`.
- **Acción**: Reescribir 3, eliminar 1 (xfail #11).
- **Nota**: `test_flow_hint_confirmation_shown_mentions_waiting` (xfail #10) requiere que el `[estado]` del `StatusLineMiddleware` incluya mención de "esperando confirmación" — verificar contra `status_line.py`.

### `tests/unit/test_booking_suggested_name.py` (3 tests)
- **Scope**: Testean que `_suggested_customer_name` vs `customer_name` se renderiza correctamente.
- **Acción**: Reescribir los 3. El behavior de "suggestion presente pero nombre pending" es importante porque el `StatusLineMiddleware` debe mostrar la sugerencia pero no marcar el nombre como recogido.

### `tests/integration/test_booking_notes_optional.py` — clase `TestFlowHintNotasLeak` (3 tests)
- **Scope**: Tests de integración del bug W1/R8 — el leak de `notas` en el pending.
- **Acción**: Reescribir xfails #15 y #17; evaluar si #16 puede eliminarse (ya cubierto por Batch 2).

---

## Procedimiento para actualizar `reason` de xfails

Una vez creado el issue de GitHub:

1. Abrir los 4 archivos listados.
2. Reemplazar `— issue #TBD"` con `— issue #NNN"` (donde NNN es el número del issue creado).
3. Correr `pytest --co -q tests/unit/test_booking_conversational_flow.py tests/unit/test_booking_confirmation_loop.py tests/unit/test_booking_suggested_name.py tests/integration/test_booking_notes_optional.py` para confirmar que la colección no rompe.
4. Commitear: `chore(tests): link xfail reasons to issue #NNN`.

---

## Checklist de cierre (OBLIGATORIO antes de `sdd-archive`)

Cada xfail debe tener una decisión tomada antes de archivar el change:

- [ ] xfail #1 — `test_empty_ctx_all_pending` → rewrite completado
- [ ] xfail #2 — `test_services_collected_stylist_pending` → rewrite completado
- [ ] xfail #3 — `test_services_and_stylist_collected` → rewrite completado
- [ ] xfail #4 — `test_slots_offered_not_selected` → rewrite completado
- [ ] xfail #5 — `test_name_pending` → rewrite completado
- [ ] xfail #6 — `test_all_required_collected_no_notes_asked` → rewrite completado _(test más valioso)_
- [ ] xfail #7 — `test_all_collected_with_stylist_preference` → rewrite completado
- [ ] xfail #8 — `test_flow_hint_notes_not_pending_when_not_asked` → rewrite completado _(core R8/C5)_
- [ ] xfail #9 — `test_flow_hint_all_collected_sets_confirmation_shown` → rewrite completado
- [ ] xfail #10 — `test_flow_hint_confirmation_shown_mentions_waiting` → rewrite completado
- [ ] xfail #11 — `test_confirmation_shown_set_when_required_fields_present_without_notes` → **ELIMINAR** (cubierto por `test_confirmation_gate.py`)
- [ ] xfail #12 — `test_flow_hint_name_pending_no_suggestion` → rewrite completado
- [ ] xfail #13 — `test_flow_hint_name_pending_with_suggestion` → rewrite completado
- [ ] xfail #14 — `test_flow_hint_name_collected` → rewrite completado
- [ ] xfail #15 — `test_flow_hint_no_notas_pending_when_complete_without_notes` → rewrite completado _(core W1/R8)_
- [ ] xfail #16 — `test_confirmation_shown_set_when_complete_without_notes` → evaluar delete vs rewrite
- [ ] xfail #17 — `test_flow_hint_notas_in_collected_when_notes_asked_true` → rewrite completado
- [ ] Issue de GitHub creado con este contenido como body
- [ ] Todos los `reason` actualizados con `issue #NNN`
- [ ] Suite final: 0 xfail marcados como `state-first-booking`, 0 FAILED
