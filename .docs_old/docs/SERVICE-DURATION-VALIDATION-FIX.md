# Service Duration Validation Fix

## 📋 Resumen

Se ha implementado validación completa de duración de servicios en el flujo de disponibilidad, asegurando que los slots presentados al cliente consideren el tiempo total necesario para completar el servicio o pack, respetando los horarios de cierre del salón.

---

## ❌ Problema Identificado

### Comportamiento Anterior (INCORRECTO)

El sistema generaba slots sin considerar la duración completa del servicio:

**Ejemplo 1: Servicio Largo Entre Semana**
```
Horario: 10:00 - 20:00
Servicio: "Mechas + Corte" = 180 minutos (3 horas)
Último slot mostrado: 19:30 ❌

Problema:
- Cliente podría reservar a las 19:30
- Servicio terminaría a las 22:30 (2.5 horas DESPUÉS del cierre)
```

**Ejemplo 2: Servicio Largo en Sábado**
```
Horario sábado: 10:00 - 14:00 (4 horas)
Pack: 180 minutos (3 horas)
Último slot mostrado: 13:30 ❌

Problema:
- De 8 slots mostrados (10:00-13:30), solo 3 eran válidos
- Cliente podría reservar a las 13:00
- Servicio terminaría a las 16:00 (2 horas DESPUÉS del cierre)
```

### Validaciones que Faltaban

1. ❌ **Generación de slots**: No verificaba que el servicio completo cabía en horario comercial
2. ❌ **Disponibilidad**: Solo verificaba los primeros 30 minutos, no la duración completa del servicio

---

## ✅ Solución Implementada

### 1. Validación en Generación de Slots

**Archivo**: `agent/tools/calendar_tools.py`

**Función modificada**: `generate_time_slots()`

**Cambios**:
- Añadido parámetro `service_duration_minutes` (default: 30 para retro-compatibilidad)
- Validación: Solo genera slots donde el servicio COMPLETO cabe en horario comercial

```python
def generate_time_slots(
    date: datetime,
    day_of_week: int,
    service_duration_minutes: int = SLOT_DURATION_MINUTES  # ← NUEVO
) -> list[datetime]:
    """
    IMPORTANTE: Solo genera slots donde el servicio COMPLETO puede completarse
    dentro del horario comercial.
    """
    while current_time < end_time:
        # Calcular cuándo terminaría el servicio
        service_end_time = current_time + timedelta(minutes=service_duration_minutes)

        # Solo añadir slot si el servicio completo cabe
        if service_end_time <= end_time:  # ← VALIDACIÓN NUEVA
            slots.append(current_time)

        current_time += timedelta(minutes=SLOT_DURATION_MINUTES)

    return slots
```

**Ejemplo Corregido - Sábado**:
```
Horario: 10:00 - 14:00
Servicio: 180 min

Antes: 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30 (8 slots) ❌
Ahora:  10:00, 10:30, 11:00 (3 slots) ✅

Último slot: 11:00
Fin servicio: 14:00 ✓ (justo al cierre)
```

### 2. Validación en Disponibilidad contra Eventos

**Archivo**: `agent/tools/calendar_tools.py`

**Función modificada**: `is_slot_available()`

**Cambios**:
- Añadido parámetro `service_duration_minutes`
- Validación: Verifica que TODA la duración del servicio esté libre de conflictos

```python
def is_slot_available(
    slot_time: datetime,
    busy_events: list[dict[str, Any]],
    service_duration_minutes: int = SLOT_DURATION_MINUTES  # ← NUEVO
) -> bool:
    """
    IMPORTANTE: Valida que la duración COMPLETA del servicio esté disponible.
    """
    # Calcular cuándo termina el servicio completo
    service_end_time = slot_time + timedelta(minutes=service_duration_minutes)  # ← CAMBIO

    for event in busy_events:
        event_start = ...
        event_end = ...

        # Verificar overlap del SERVICIO COMPLETO con evento
        if slot_time < event_end and service_end_time > event_start:  # ← CAMBIO
            return False

    return True
```

**Ejemplo Corregido - Evento Existente**:
```
Slot propuesto: 15:00
Servicio: 180 min (termina 18:00)
Evento existente: 17:00-18:00

Antes: ✅ Disponible (solo validaba 15:00-15:30) ❌
Ahora:  ❌ No disponible (servicio solapa con evento) ✅
```

### 3. Cálculo de Duración Total

**Archivo**: `agent/nodes/availability_nodes.py`

**Función modificada**: `check_availability()`

**Cambios**:
- Calcula duración total considerando packs vs servicios individuales
- Pasa duración a `generate_time_slots()` y `query_all_stylists_parallel()`

```python
async def check_availability(state: ConversationState) -> dict[str, Any]:
    # ... (obtener servicios solicitados)

    # Calcular duración total
    pack_id = state.get("pack_id")
    if pack_id:
        # Pack seleccionado - usar duración pre-definida del pack
        pack = await get_pack_by_id(pack_id)
        total_duration_minutes = pack.duration_minutes
    else:
        # Servicios individuales - sumar duraciones
        total_duration_minutes = sum(s.duration_minutes for s in services)

    logger.info(f"Using service duration: {total_duration_minutes} min")

    # Generar slots CON validación de duración
    time_slots = generate_time_slots(
        requested_date,
        day_of_week,
        service_duration_minutes=total_duration_minutes  # ← NUEVO
    )

    # Query disponibilidad CON validación de duración
    available_slots = await query_all_stylists_parallel(
        stylists,
        requested_date,
        time_slots,
        total_duration_minutes,  # ← NUEVO
        conversation_id
    )
```

**Lógica de Duración**:
1. **Si hay pack_id**: Usa `pack.duration_minutes` (duración optimizada)
2. **Si no hay pack**: Suma `service.duration_minutes` de todos los servicios

### 4. Actualización en Búsqueda de Alternativas

**Archivo**: `agent/nodes/availability_nodes.py`

**Función modificada**: `suggest_alternative_dates()`

**Cambios**:
- Añadido parámetro `service_duration_minutes`
- Pasa duración a `generate_time_slots()` y `query_all_stylists_parallel()`

---

## 📊 Impacto de los Cambios

### Horario Entre Semana (L-V: 10:00-20:00)

| Duración Servicio | Slots Antes | Slots Ahora | Último Slot Válido |
|-------------------|-------------|-------------|-------------------|
| 30 min | 20 | 20 | 19:30 (termina 20:00) ✅ |
| 60 min (1h) | 20 | 19 | 19:00 (termina 20:00) ✅ |
| 120 min (2h) | 20 | 16 | 18:00 (termina 20:00) ✅ |
| 180 min (3h) | 20 | 14 | 17:00 (termina 20:00) ✅ |
| 240 min (4h) | 20 | 12 | 16:00 (termina 20:00) ✅ |

### Horario Sábado (10:00-14:00)

| Duración Servicio | Slots Antes | Slots Ahora | Último Slot Válido |
|-------------------|-------------|-------------|-------------------|
| 30 min | 8 | 8 | 13:30 (termina 14:00) ✅ |
| 60 min (1h) | 8 | 6 | 13:00 (termina 14:00) ✅ |
| 120 min (2h) | 8 | 4 | 12:00 (termina 14:00) ✅ |
| 180 min (3h) | 8 ❌ | 3 ✅ | 11:00 (termina 14:00) ✅ |
| 240 min (4h) | 8 ❌ | 1 ✅ | 10:00 (termina 14:00) ✅ |

---

## 🔍 Archivos Modificados

### 1. `agent/tools/calendar_tools.py`
- **Líneas 251-310**: `generate_time_slots()` - Añadido parámetro y validación
- **Líneas 443-497**: `is_slot_available()` - Añadido parámetro y validación de duración completa

### 2. `agent/nodes/availability_nodes.py`
- **Líneas 38**: Añadido import de `Pack`
- **Líneas 299-320**: `query_all_stylists_parallel()` - Añadido parámetro `service_duration_minutes`
- **Líneas 352**: Llamada a `is_slot_available()` con duración
- **Líneas 409-432**: `suggest_alternative_dates()` - Añadido parámetro `service_duration_minutes`
- **Líneas 478-482, 491-497**: Llamadas con duración en `suggest_alternative_dates`
- **Líneas 686-723**: Cálculo de duración total (pack vs servicios)
- **Líneas 741-746, 759-765, 794-799**: Llamadas a `suggest_alternative_dates` con duración

---

## 🧪 Casos de Prueba

### Test 1: Servicio Largo Sábado

**Input**:
```
Día: Sábado
Horario: 10:00-14:00
Servicio: "Mechas + Corte" (180 min)
```

**Expected**:
```
Slots válidos: 10:00, 10:30, 11:00
Último slot: 11:00 (termina 14:00)
```

### Test 2: Servicio con Evento Existente

**Input**:
```
Día: Lunes
Horario: 10:00-20:00
Servicio: 180 min
Slot propuesto: 15:00
Evento existente: 17:00-18:00
```

**Expected**:
```
Slot 15:00: NO disponible
Razón: Servicio (15:00-18:00) solapa con evento (17:00-18:00)
```

### Test 3: Pack vs Servicios Individuales

**Input Pack**:
```
Pack "Mechas + Corte":
- Duración: 150 min (optimizado)
- Horario cierre: 20:00
```

**Expected**:
```
Último slot: 17:30 (termina 20:00)
```

**Input Servicios Individuales**:
```
Servicios: Mechas (120 min) + Corte (60 min)
- Duración total: 180 min (suma)
- Horario cierre: 20:00
```

**Expected**:
```
Último slot: 17:00 (termina 20:00)
```

---

## 🚀 Despliegue

### Pasos para Aplicar el Fix

1. **Rebuild agent container**:
```bash
docker compose build agent
```

2. **Restart agent**:
```bash
docker compose restart agent
```

3. **Verificar logs**:
```bash
docker compose logs agent --tail 50 | grep "service duration"
```

Deberías ver logs como:
```
Using pack duration: 150 min | pack_id=...
Using individual service durations sum: 180 min
```

---

## ✅ Validación Post-Despliegue

### Pruebas Recomendadas

1. **Test Sábado + Servicio Largo**:
   - Solicitar "Mechas + Corte" para un sábado
   - Verificar que último slot es ~11:00

2. **Test Con Eventos Existentes**:
   - Crear evento de prueba en Google Calendar
   - Solicitar servicio largo que incluya ese horario
   - Verificar que el slot no se muestra como disponible

3. **Test Pack vs Individual**:
   - Probar mismo servicio como pack y como individual
   - Verificar diferencia en slots disponibles según duración

---

## 📝 Notas Adicionales

### Retrocompatibilidad

Todos los cambios mantienen retrocompatibilidad mediante valores por defecto:
- `service_duration_minutes` default = `SLOT_DURATION_MINUTES` (30 min)
- Si no se pasa duración, comportamiento es idéntico a versión anterior

### Performance

No hay impacto negativo en performance:
- Misma cantidad de queries a Google Calendar
- Validación adicional es O(1) por slot
- Cálculo de duración total es O(n) donde n = número de servicios (típicamente 1-3)

### Logs Añadidos

```python
logger.info(f"Using pack duration: {total_duration_minutes} min | pack_id={pack_id}")
logger.info(f"Using individual service durations sum: {total_duration_minutes} min")
```

Estos logs facilitan debugging y validación del comportamiento correcto.

---

**Fecha de Implementación**: 2025-10-30
**Versión**: 1.0
**Autor**: Claude Code
