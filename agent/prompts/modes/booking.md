# Modo RESERVA (Booking Mode)

## Objetivo

Guiar el FSM real de reserva usando `mode_context["booking_step"]` como fuente de verdad.
En este modo **no** se vuelve a pedir nombre: la clienta ya llega identificada desde GREETING
o se crea de forma lazy en el paso `customer_name`.

---

## Substeps Reales del FSM

### 1. `service_selection`

**Objetivo:** resolver el servicio exacto antes de hablar de estilista u horarios.

**Herramientas que usa el código:**
- `search_services(query, category)`
- `query_info(type="services")`

**Qué pasa acá:**
- Si hay coincidencia exacta, se guarda `service_id`, `service_name`, `service_category` y la
  duración.
- Si `search_services` devuelve `clarification_needed`, hay que transmitir el `question_hint`
  y esperar la respuesta del cliente.
- Si se resuelve el servicio, el flujo avanza a `stylist_selection`.

**Transiciones válidas:**
- `service_selection -> service_selection`
- `service_selection -> stylist_selection`

### 2. `stylist_selection`

**Objetivo:** elegir profesional o confirmar que cualquier estilista sirve.

**Herramientas que usa el código:**
- `list_stylists()`
- `get_customer_history(...)` se usa de forma auxiliar para detectar estilista recurrente

**Qué pasa acá:**
- Si hay historial consistente, el sistema puede precargar una estilista recurrente.
- Si la clienta elige una profesional concreta, se guardan `stylist_id` y `stylist_name`.
- Cuando ya hay estilista resuelta, el flujo avanza a `slot_selection`.

**Transiciones válidas:**
- `stylist_selection -> service_selection`
- `stylist_selection -> stylist_selection`
- `stylist_selection -> slot_selection`

### 3. `slot_selection`

**Objetivo:** encontrar una fecha y horario válidos con la estilista elegida.

**Herramientas que usa el código:**
- `check_availability(...)`
- `find_next_available(...)`

**Qué pasa acá:**
- `check_availability` se usa cuando la clienta pide una fecha o franja concreta.
- `find_next_available` se usa para proponer próximos huecos disponibles.
- El modo interpreta respuestas semánticas como `substitution_made`, `min_valid_date` y
  `no_slots_for_stylist`.
- Solo avanza cuando existe `selected_slot`; si no hay hueco para la estilista elegida, se queda
  en este mismo substep.

**Transiciones válidas:**
- `slot_selection -> slot_selection`
- `slot_selection -> notes`

### 4. `notes`

**Objetivo:** pedir una nota opcional para la cita.

**Herramientas que usa el código:**
- Ninguna

**Qué pasa acá:**
- La clienta ya está identificada; no se le pide nombre ni teléfono.
- Si responde con algo como "no" o "nada más", se guarda `notes = None`.
- Cualquier otra respuesta se guarda como nota libre.
- Con una respuesta de la clienta, el flujo avanza a `confirmation`.

**Transiciones válidas:**
- `notes -> notes`
- `notes -> confirmation`

### 5. `confirmation`

**Objetivo:** mostrar el resumen final y pedir confirmación explícita.

**Herramientas que usa el código:**
- Ninguna

**Qué pasa acá:**
- Se resume servicio, estilista, horario, nombre y notas si existen.
- Solo cuando el intent detectado es confirmación (`confirm`, `sí`, `si`, `yes`) el flujo avanza.
- Si la clienta cambia servicio, estilista u horario, el modo puede retroceder al substep
  correspondiente.

**Transiciones válidas:**
- `confirmation -> service_selection`
- `confirmation -> slot_selection`
- `confirmation -> confirmation`
- `confirmation -> completed`

### 6. `completed`

**Objetivo:** ejecutar la reserva y cerrar el flujo.

**Herramientas que usa el código:**
- `book(...)`

**Qué pasa acá:**
- `book()` se invoca de forma directa desde Python, no mediante el loop agentic.
- Si falla, el flujo vuelve a `confirmation`.
- Si sale bien, se responde con la confirmación final y el modo transiciona a `GENERAL`.

**Transiciones válidas:**
- `completed` es terminal dentro del FSM

---

## Resumen de Herramientas por Substep

| Substep | Herramientas |
| --- | --- |
| `service_selection` | `search_services`, `query_info` |
| `stylist_selection` | `list_stylists` (+ `get_customer_history` como ayuda interna) |
| `slot_selection` | `check_availability`, `find_next_available` |
| `notes` | ninguna |
| `confirmation` | ninguna |
| `completed` | `book` directo |

---

## Reglas Operativas

1. No vuelvas a pedir el nombre: ya existe `customer_name` en estado o contexto.
2. No inventes disponibilidad ni servicios; usá siempre los resultados reales de tools.
3. Si `search_services` pide aclaración, repetí el `question_hint` tal cual.
4. Si no hay huecos para la estilista elegida, quedate en `slot_selection` y ofrecé ampliar
   rango o cambiar de profesional.
5. La confirmación explícita sucede en `confirmation`; recién después se ejecuta `book()`.
6. La escalación se maneja por intención/ruteo del sistema, no por `manage_customer()` ni por un
   substep especial de booking.

---

## Relación con los prompts por substep

Cuando `USE_SUBSTEP_PROMPTS=True`, este archivo queda como referencia y el sistema carga los
overlays específicos desde `agent/prompts/modes/booking/`:

- `service_selection.md`
- `stylist_selection.md`
- `slot_selection.md`
- `notes.md`
- `confirmation.md`
- `completed.md`

Esos archivos se resuelven desde `load_mode_overlay()` usando el `booking_step` actual.

---

## Referencias de Código

- `agent/modes/booking_context.py` — enum `BookingSubstep`, transiciones y registro de tools
- `agent/modes/booking_mode.py` — handlers `_handle_*` y lógica real de avance
- `agent/prompts/modes/booking/*.md` — overlays específicos por substep
