# Glosario — Taxonomía de Audiencia y Servicios

## Taxonomía de Audiencia

Usa estos valores exactos cuando el cliente describe para quién es el servicio:

| Lo que dice el cliente | Valor en sistema |
|------------------------|------------------|
| señora / mujer / femenino / ella | `adult_female` |
| caballero / hombre / masculino / él | `adult_male` |
| niña / chica menor | `child_female` |
| niño / chico menor | `child_male` |
| bebé / bebe / nene / nena | `baby` |
| unisex / para todos / cualquiera | `unisex` |

Si el cliente dice "para mí" y su género no es conocido, pregunta con quién es el servicio.

## Categorías de Servicios

- **hair** — Servicios de peluquería (cortes, tintes, tratamientos capilares)
- **aesthetics** — Servicios de estética (manicura, pedicura, depilación, tratamientos faciales)

## Tipos de Servicio en Catálogo

- **PRINCIPAL** — Servicio base (ej: Corte de Mujer, Tinte)
- **VARIANTE** — Variante de un servicio principal (ej: Corte + Secado)
- **ADDON** — Servicio complementario (ej: Tratamiento hidratante)

## Campos del Catálogo

Cada línea del catálogo tiene el formato:
```
[TIPO · dimensión · audiencia] Nombre del servicio — Xmin — Descripción — id=UUID
```

El `id=UUID` al final de cada línea es el identificador que debes usar en las llamadas a herramientas.

---

## Ejes de Desambiguación

El catálogo discrimina servicios en CINCO ejes independientes. Cada eje tiene su propia puerta en `update_booking`; el LLM NUNCA debe colapsar dos ejes en una sola pregunta.

| Eje (`axis`) | Trigger condition | Pregunta natural ejemplo | Ejemplo de familia de servicios |
|--------------|-------------------|--------------------------|----------------------------------|
| `audience` | `next_step=audience_required` | "¿Para quién es: señora, caballero, niña, niño o bebé?" | Corte (Mujer / Hombre / Niño / Niña / Bebé) |
| `variant` (zona) | `next_step=variant_required`, dimensión `wax`/`cut` | "¿Qué zona quieres depilarte? Tengo {candidates}." | Depilación (Piernas Enteras / Cejas / Axilas / …) |
| `variant` (longitud) | `next_step=variant_required`, dimensión `hairstyle`/`updo` | "¿Cómo tienes el pelo: corto, largo o muy largo?" | Peinado (Largo / Moldeado Extra / …) |
| `variant` (formalidad) | `next_step=variant_required`, dimensión `updo` | "¿Es para evento o para el día a día?" | Recogido (Recogido / Semirecogido / Recogido de Novia) |
| `variant` (duración) | `next_step=variant_required`, dimensión `highlights`/`color`/`treatment` | "¿La sesión corta o la completa? Tengo {candidates}." | Mechas (Extras / Localizadas / …) |

**Regla de independencia**: cuando dos ejes están abiertos a la vez, `update_booking` los puerta secuencialmente — primero audience, luego variant. NUNCA preguntes ambos en el mismo turno. Usa los nombres de `payload.candidates` como sustantivos; la pregunta DEBE sonar natural en castellano de Madrid.

---

## Mapeo longitud → variante

Cuando el cliente describe la longitud de su pelo, usa esta tabla para seleccionar la variante correcta.
Si la longitud no está clara, pregunta antes de elegir variante.

| Lo que dice el cliente | Variante a usar |
|------------------------|-----------------|
| corto / normal / media melena | Peinado |
| largo / melena larga | Peinado Largo |
| muy largo / mucho pelo / extra largo | Moldeado Extra |

> Si dudas, pregunta antes de elegir variante.

Esta tabla es la fuente única de verdad. Los demás archivos deben referenciar esta sección por nombre, no repetir el mapeo.

---

## Frases de fecha vaga

Cuando el cliente usa alguna de estas frases sin indicar un día concreto, usa `get_next_available_options`
(ver `tools_contract.md` para detalles de uso):

- "lo antes posible"
- "esta semana"
- "cuando puedas"
- "lo primero que haya"
- "cuanto antes"
- "cualquier día"
- "pronto"

> Si aparece alguna de estas frases sin día concreto, usa `get_next_available_options`.

---

## Lista canónica de estilistas

Cuando presentes opciones de estilista al cliente, usa siempre el formato indicado en
`booking_flow.md § Elección de estilista`.

<example do-not-reproduce reason="placeholder_template">
> 1. {nombre estilista 1}
> 2. {nombre estilista 2}
> …
> N. La primera con disponibilidad (mín. 3 días de antelación)
</example>

Sustituye los `{placeholders}` con los nombres reales de `payload.stylists` y la `payload.first_available_label`. NUNCA reproduzcas el texto dentro de `<example do-not-reproduce>` tal cual.

La opción "primera con disponibilidad" va SIEMPRE al final de la lista, después de todos los nombres reales de estilistas. Esto refleja el flujo preferido: primero elegir una persona concreta; solo si ninguna conviene, el cliente opta por "la primera que haya".
