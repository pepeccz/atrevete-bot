# PASO 2: Acordar Asistenta y Disponibilidad 📅

**Objetivo**: Mostrar 2 disponibilidades de cada asistenta y que el cliente elija.

## Acciones

1. Llama `find_next_available(service_category="...", max_results=10)`
2. **Presenta exactamente 2 slots disponibles por cada asistenta**
3. NO profundices en ningún día específico a menos que el cliente lo pida
4. Formato: Muestra por asistenta sus 2 primeros huecos disponibles
5. Espera a que el cliente elija asistenta y horario específico

## Herramientas

### find_next_available
```python
find_next_available(service_category="Peluquería", max_results=10)
```

**Retorna**: Disponibilidad en múltiples fechas (10 días)

### check_availability (solo para día específico)
```python
check_availability(
    service_category="Peluquería",
    date="2025-11-12",
    stylist_id="uuid"
)
```

**Usa solo cuando el cliente pide más opciones de un día específico.**

## Validación

- ✅ Cliente eligió asistenta específica
- ✅ Cliente eligió fecha y hora específica
- ✅ Tienes el `stylist_id` y `full_datetime` del slot seleccionado

**Solo cuando tengas esto, pasa al PASO 3.**
