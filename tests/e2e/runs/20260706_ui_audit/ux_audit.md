# Auditoría UX/Visual — Bandeja de Conversaciones (Atrévete Admin)

**Fecha:** 2026-07-06
**Alcance:** `/conversations` — bandeja de entrada de WhatsApp para el salón
**Usuario objetivo:** personal del salón, no técnico, a menudo revisando el móvil/tablet entre clientas
**Metodología:** revisión de capturas del pase funcional (`01_login.png`…`10_mobile_thread.png`) + exploración propia en vivo sobre `https://atrevete.zanovix.com` (capturas `ux_*.png` en este mismo directorio) + `functional_findings.md` como contexto (no se re-litigan los bugs funcionales, solo se audita la capa UX/visual).

No se envió ningún mensaje ni se pausó/reanudó ningún bot ni se borró nada — exploración de solo lectura.

---

## Resumen ejecutivo

La bandeja de conversaciones tiene una base de información sólida en el panel de cliente (ficha derecha) y un banner de pausa razonablemente claro, pero falla en tres frentes que van a doler mucho a una operadora no técnica el día 1:

1. **La carga inicial tarda ~20-22 segundos mostrando solo la palabra "Cargando…"** — sin esqueleto, sin animación, sin contador. Se percibe como una pantalla colgada, no como una app cargando.
2. **El layout de 3 columnas se rompe en tablet y en móvil de forma distinta pero igual de grave**: en tablet (768px) la columna central de mensajes **desaparece por completo** al abrir una conversación (ni mensajes ni cuadro de texto visibles); en móvil (375px) hay **desbordamiento horizontal confirmado** (scrollWidth 458px vs clientWidth 360px) y la lista completa sigue ocupando la pantalla en vez de dar paso al hilo.
3. **No hay forma de distinguir a simple vista una escalación urgente (cliente pidió hablar con una persona) de una pausa rutinaria** — ambas usan exactamente el mismo badge ámbar "Pausado", mismo icono, mismo color, en las pestañas "Bot OFF" y "Escaladas". Y en la lista "Todas"/"Bot ON" no hay ningún timestamp, así que tampoco se puede priorizar por recencia.

Ninguno de estos tres es un bug de datos (ese terreno ya lo cubre `functional_findings.md` con F1/F2) — son problemas de comunicación visual que van a hacer que Pilar y su equipo desconfíen de la herramienta o pierdan tiempo aunque los datos por debajo sean correctos.

**Patrón responsive recomendado:** navegación tipo "master-detail apilado" (lista → hilo → ficha cliente, cada uno a pantalla completa con botón "atrás") por debajo de ~1024px, en vez de intentar comprimir 3 columnas fijas. Detalle en la sección correspondiente más abajo.

**3 quick wins** (ver sección final): esqueleto de carga en la lista, timestamps relativos/legibles, y un badge distinto para "Escalada" vs "Pausado".

---

## Hallazgos P1 — Corregir antes del lanzamiento con Pilar

### P1-1. Estado de carga de la lista: 20-22s mostrando solo texto "Cargando…"
**Qué está mal:** Al entrar a `/conversations` la columna de lista muestra el texto plano "Cargando…" durante 20-22 segundos (tiempo confirmado también en `functional_findings.md` F2), sin skeleton, sin spinner animado, sin contador de progreso. Los contadores de las pestañas (Todas/Bot ON/etc.) tampoco aparecen hasta que termina la carga.
**Por qué importa para esta usuaria:** una empleada de salón entre clientas necesita respuestas casi instantáneas. 20 segundos de texto estático sin ningún indicio de actividad se lee como "se rompió la página", no como "está cargando". Es el tipo de fricción que hace que la gente cierre la pestaña y use Chatwoot directamente, saltándose el panel.
**Evidencia:** `ux_01_list_full.png` (t=0s, "Cargando…" sin contadores) → `ux_02_list_loaded.png` (t=~37s, ya cargado con contadores 325/312/13/11).
**Fix concreto:** Skeleton de filas (3-5 placeholders grises con el mismo alto/forma que una fila real) desde el primer render, más una nota de que la carga puede tardar. Esto es solo percepción — el fix real de los 20s está en el backend (`functional_findings.md` F2), pero mientras eso no esté resuelto, el skeleton evita que la app se sienta rota.

### P1-2. Tablet (768px): la columna de hilo desaparece por completo al abrir una conversación
**Qué está mal:** Al redimensionar a 768×1024 y abrir "Carla Test", la columna central (mensajes + cuadro de texto) queda con ancho efectivo ~0 — la lista y la ficha de cliente quedan pegadas una a la otra sin ningún espacio para leer ni responder mensajes.
**Por qué importa:** esto no es solo "feo" (como lo describe el hallazgo funcional #9/F4) — es un **bloqueo funcional real**: en una tablet, que es el dispositivo más probable para usar de pie en el mostrador, la operadora **no puede leer los mensajes del cliente ni escribir una respuesta**. No hay forma de rodear el problema desde la UI.
**Evidencia:** `ux_04_tablet_thread_open.png` (comparar con `08_tablet.png` del pase funcional, que ya mostraba el problema sin conversación abierta).
**Fix concreto:** dar al panel de hilo un `min-width` explícito (ej. 360px) en el layout flex/grid; si no cabe con los 3 paneles a la vez en ese breakpoint, colapsar la ficha de cliente a un drawer/overlay en vez de dejarla como tercera columna fija (ver recomendación de patrón responsive).

### P1-3. Móvil (375px): desbordamiento horizontal confirmado, hilo y composer no visibles sin scroll
**Qué está mal:** el sidebar colapsa correctamente a hamburguesa (punto a favor), pero el layout de 3 columnas no se apila a una sola columna. Al seleccionar "Eva Test" la lista completa de conversaciones sigue visible, la ficha de cliente queda reducida a una franja ilegible, y el hilo de mensajes + el cuadro de texto **no son visibles sin hacer scroll horizontal**. Confirmado programáticamente en el pase funcional: `scrollWidth = 458px` vs `clientWidth = 360px` (~98px de overflow real).
**Por qué importa:** en móvil es directamente imposible completar el trabajo más básico — leer y responder un mensaje — sin descubrir por accidente que hay que arrastrar la pantalla lateralmente. Ninguna operadora va a intuir eso.
**Evidencia:** `09_mobile.png`, `10_mobile_thread.png` (pase funcional).
**Fix concreto:** ver recomendación de patrón responsive — vista única por pantalla con navegación tipo push (lista → hilo → ficha), no 3 columnas comprimidas.

### P1-4. "Escalada" y "Pausado" comparten exactamente el mismo badge — imposible distinguir urgencia
**Qué está mal:** comparando `ux_03_bot_off_tab.png` (pestaña "Bot OFF", 13 conversaciones) contra `04_filter_escaladas.png` (pestaña "Escaladas", 11 conversaciones): **todas** las filas en ambas pestañas usan el mismo badge ámbar "Pausado" con el mismo ícono de campana tachada. No hay ningún indicador visual — ni color, ni ícono, ni etiqueta — que diga "esto es una escalación real donde el cliente pidió hablar con una persona" vs. "esto es una conversación en la que alguien pausó el bot por rutina".
**Por qué importa:** la pestaña "Escaladas" existe precisamente para priorizar por urgencia, pero si el mismo badge aparece en "Bot OFF", una operadora que solo mira esa pestaña (que es donde probablemente empiece, al ser la primera etiqueta con contador visible tras "Todas"/"Bot ON") no tiene ninguna pista de que ese chat necesita atención humana urgente vs. que ya lo está atendiendo otra persona del equipo.
**Evidencia:** `ux_03_bot_off_tab.png` vs `04_filter_escaladas.png` (mismo badge "Pausado" naranja en ambas).
**Fix concreto:** dos badges visualmente distintos — p. ej. `Pausado` (gris/neutro) para Bot OFF genérico, y `Escalada · <motivo>` (rojo/naranja fuerte, con el motivo tal como ya se muestra en el widget "Necesitan atención" del dashboard: "Solicitud manual", "urgent_same_day_request", etc.) reservado para conversaciones realmente escaladas.

### P1-5. Ninguna fecha/hora visible en la lista "Todas"/"Bot ON" — imposible priorizar por recencia
**Qué está mal:** en la pestaña por defecto ("Todas", la que ve el operador al entrar), cada fila muestra solo el nombre del cliente y "N mensajes" — **ningún timestamp**, ni siquiera uno relativo. Comparar con las pestañas "Bot OFF"/"Escaladas", que sí muestran fecha y hora absolutas ("06/07/2026 15:45"). Esto es consistente con F1 del pase funcional (esas dos pestañas leen de una fuente — Redis — que no tiene `started_at`), pero desde el punto de vista visual el resultado es el mismo: la pestaña que el operador ve primero no tiene ninguna señal de urgencia/recencia.
**Por qué importa:** la bandeja tiene decenas de conversaciones con nombres repetidos ("Pepe Ruiz" aparece más de 10 veces en la captura). Sin timestamp ni orden confiable, la operadora no puede saber cuál conversación es la más reciente o la más urgente — tiene que abrir una por una.
**Evidencia:** `ux_02_list_loaded.png`.
**Fix concreto:** aunque el fix de fondo es de datos (F1), a nivel visual: mostrar siempre un timestamp relativo ("hace 5 min", "ayer") consistente con el que ya usa el dashboard, incluso si por ahora hay que derivarlo de un campo distinto según la fuente (Redis vs DB).

---

## Hallazgos P2 — Corregir pronto

### P2-1. Conversaciones "Desconocido / 0 mensajes" (huérfanas) mezcladas sin distinción en la cola de escaladas
En la pestaña "Escaladas" (la cola más urgente), **8 de 11 filas son "Desconocido" con "0 mensajes"** — ruido de datos que se ve exactamente igual que una escalación real ("Eva Test", con 4 mensajes). Esto obliga a la operadora a escanear/descartar entradas vacías para llegar a las que sí importan. Recomendación: filtrarlas de la vista por defecto o marcarlas con una etiqueta explícita tipo "Sin datos de cliente — revisar" con estilo visualmente apagado (gris, no ámbar).
Evidencia: `04_filter_escaladas.png`, `ux_03_bot_off_tab.png`.

### P2-2. Formato de fecha inconsistente entre Dashboard y Bandeja
El widget "Necesitan atención" del Dashboard usa tiempo relativo humanizado ("hace alrededor de 1 hora", "hace 1 día"). La bandeja de conversaciones, en las pestañas que sí muestran fecha, usa formato absoluto completo ("06/07/2026 15:25"). Son dos convenciones de legibilidad temporal distintas dentro del mismo producto, para el mismo tipo de dato.
Evidencia: snapshot del Dashboard (widget "Necesitan atención") vs `04_filter_escaladas.png`.
Fix: unificar en tiempo relativo en la lista, con el absoluto disponible solo como tooltip al pasar el mouse (patrón estándar).

### P2-3. "Ventana abierta · quedan 23h" — jerga técnica sin explicación
En el hilo de conversación, sobre el cuadro de texto, aparece en gris pequeño "Ventana abierta · quedan 23h" sin ícono, sin color de estado, sin tooltip. Para el personal del salón esto es jerga de la API de WhatsApp Business (ventana de 24h de mensajería) sin ninguna pista de qué pasa si se cierra (deja de poder responder libremente, solo con plantillas).
Evidencia: `06_thread_eva.png`.
Fix: icono de reloj + color (verde/ámbar/rojo según horas restantes) + tooltip: "Puedes responder libremente durante 23h más. Después, solo se pueden enviar plantillas aprobadas."

### P2-4. Motivo de escalación no se traslada al hilo — hay que leer todo el historial para entenderlo
El Dashboard sí muestra el motivo ("Solicitud manual", "urgent_same_day_request") en el widget "Necesitan atención", pero al abrir el hilo de la conversación escalada ese motivo desaparece — solo queda el genérico "Bot pausado desde 06 jul, 15:30 · Atención manual". Para entender por qué escaló, la operadora tiene que leer todos los mensajes.
Evidencia: `06_thread_eva.png` (banner sin motivo) vs snapshot del Dashboard (widget con motivo "Solicitud manual").
Fix: repetir el motivo en el propio banner del hilo, ej. "Bot pausado desde 06 jul, 15:30 · Motivo: Solicitud manual".

### P2-5. Pestaña "Sin leer" sin contador — rompe el patrón de las otras 4 pestañas
Las pestañas Todas/Bot ON/Bot OFF/Escaladas muestran su número entre paréntesis junto al nombre. "Sin leer" no muestra ningún número. Confirma a nivel visual el hallazgo funcional de que `unread_message_count` está hardcodeado en 0 — pero además genera una inconsistencia de patrón: 4 pestañas con badge numérico y una sin él, sin explicación visual de por qué.
Evidencia: `ux_02_list_loaded.png` (fila de pestañas).

---

## Hallazgos P3 — Pulido

### P3-1. Mismo ícono en todas las filas de "Todas"/"Bot ON"
Cada fila de la lista por defecto usa el mismo ícono verde de burbuja de chat, sin variar según estado. No aporta información y ocupa espacio que podría comunicar algo (ej. iniciales del cliente, como sí se hace en la ficha derecha con "EV", "CA").

### P3-2. Contraste del badge "Pausado" a verificar
El texto ocre sobre fondo melocotón claro del badge "Pausado" se ve ajustado a simple vista. Recomiendo pasar los valores hex reales por un verificador de contraste WCAG AA antes del lanzamiento (no se pudo confirmar el hex exacto desde la captura).

### P3-3. Preview de último mensaje inconsistente
Solo algunas filas muestran una segunda línea con el resumen del último mensaje (ej. "Lucia Herrera reservó un corte de mujer con la estilista Mar…"); la mayoría no la muestra. No está claro si es por longitud de mensaje, tipo de conversación, o un bug de datos — visualmente es una inconsistencia de densidad de información fila a fila.
Evidencia: `ux_02_list_loaded.png`.

### P3-4. "Sincronizar Google Calendar" en el header de Conversaciones
El botón de sincronización de calendario aparece en el header de `/conversations`, una pantalla sin relación directa con el calendario. Es ruido visual en una pantalla ya cargada de información.

---

## Recomendación de patrón responsive

**Problema de fondo:** el layout actual es un grid de 3 columnas de ancho fijo/mínimo que simplemente se comprime cuando no hay espacio, en vez de reorganizarse. Por eso en tablet una columna llega a 0px y en móvil aparece overflow horizontal en lugar de un colapso limpio.

**Patrón recomendado — navegación apilada tipo "master-detail push" (el mismo patrón de WhatsApp Web/Gmail en móvil):**

| Breakpoint | Comportamiento |
|---|---|
| **Desktop (≥1280px)** | Mantener las 3 columnas actuales, pero con `min-width` explícito en el panel de hilo (evita que se comprima a 0 si el viewport es intermedio). |
| **Tablet (768-1279px)** | 2 columnas: Lista + Hilo. La ficha de cliente pasa a ser un panel deslizable (drawer) que se abre con un botón/ícono en el header del hilo, no una tercera columna fija. |
| **Móvil (<768px)** | 1 columna con navegación push: la Lista ocupa toda la pantalla; al tocar una conversación, el Hilo la reemplaza a pantalla completa con un botón "←" para volver; la ficha de cliente se abre como una pantalla adicional (o bottom sheet) desde un ícono en el header del hilo. Nunca se muestran dos columnas simultáneamente en este rango. |

Esto resuelve P1-2 y P1-3 de raíz (nunca se necesita comprimir 3 columnas en el mismo viewport) y es un patrón que el personal ya conoce de WhatsApp, lo que reduce la curva de aprendizaje.

---

## Quick wins (alto impacto / bajo esfuerzo)

1. **Skeleton de carga en la lista** en vez de texto "Cargando…" — placeholders grises con la forma de una fila real, visibles desde el primer render. Compra tiempo de percepción mientras se resuelve el problema de fondo de los 20s (F2).
2. **Timestamps relativos y legibles en toda la lista** ("hace 5 min", "ayer 15:30"), consistentes con el formato que ya usa el widget del Dashboard — hoy la pestaña por defecto no muestra ninguna fecha y las demás usan formato absoluto distinto al del Dashboard.
3. **Badge distinto para "Escalada" vs "Pausado"** — reutilizar el motivo que el Dashboard ya calcula ("Solicitud manual", etc.) como texto del badge o como tooltip, y usar un color de mayor alarma (rojo/naranja fuerte) solo para escalaciones reales, dejando "Pausado" gris/neutro para pausas manuales rutinarias.

---

## Índice de evidencia (capturas)

- `ux_01_list_full.png` — estado "Cargando…" sin skeleton, t=0s
- `ux_02_list_loaded.png` — lista cargada (~37s), sin timestamps, sin distinción de estado por fila
- `ux_03_bot_off_tab.png` — pestaña Bot OFF, badge "Pausado" idéntico al de Escaladas
- `ux_04_tablet_thread_open.png` — tablet 768px, columna de hilo con ancho ~0 al abrir una conversación
- (del pase funcional) `04_filter_escaladas.png`, `06_thread_eva.png`, `08_tablet.png`, `09_mobile.png`, `10_mobile_thread.png`
