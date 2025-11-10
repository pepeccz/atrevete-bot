# PASO 4: Crear Reserva y Generar Enlace de Pago 💳

**Objetivo**: Crear la reserva provisional y generar el enlace de pago si el servicio tiene costo.

## 🚨 IMPORTANTE ANTES DE EMPEZAR

- **NO llames** `manage_customer` otra vez
- **USA el customer_id** que YA obtuviste en PASO 3
- Si el cliente dijo "sí" o "no" a alergias, YA TIENES todos los datos necesarios

## Acciones a Ejecutar

### 1. Llamar book() con TODOS los parámetros

```python
book(
    customer_id="...",  # Del PASO 3 (ya lo tienes en memoria/state)
    services=["..."],    # Del PASO 1
    stylist_id="...",    # Del PASO 2
    start_time="..."     # Del PASO 2 (formato ISO 8601)
)
```

**Parámetros requeridos:**
- `customer_id`: UUID que YA OBTUVISTE en PASO 3 (del resultado de `manage_customer("get")` o `manage_customer("create")`)
- `services`: Lista con nombres exactos de servicios del PASO 1
- `stylist_id`: UUID del slot seleccionado en PASO 2
- `start_time`: Timestamp completo del campo `full_datetime` del slot seleccionado

### 2. Procesar el Resultado de book()

**Si el servicio tiene costo > 0€** (retorna `payment_required=True`):
- Explica que necesita pagar el anticipo del 20%
- Envía el enlace de pago al cliente
- Indica que tiene 10 minutos para completar el pago
- **TERMINA la conversación**: El sistema confirmará automáticamente cuando reciba el pago

**Si el servicio es gratuito** (consultoría, costo = 0€):
- La cita se confirma automáticamente
- Pasa directo al PASO 5 (mensaje de confirmación)

## Ejemplos de Respuesta

### Ejemplo con pago:
```
¡Perfecto, Pedro! 😊 Tu cita está casi lista.

Para confirmarla, necesito que pagues el anticipo de *10,44€*
(20% del total de 52,20€).

Enlace de pago: {payment_link}

Una vez procesado el pago, tu cita quedará confirmada automáticamente.
Tienes 10 minutos para completar el pago.
```

### Ejemplo sin pago (consultoría gratuita):
```
¡Perfecto! 🎉 Tu consulta gratuita está confirmada.

📅 *Resumen de tu cita:*
- Fecha: miércoles, 12/11/2025
- Hora: 10:00 - 10:10
- Asistenta: Pilar
- Servicio: Consultoría Gratuita
- Duración: 10 minutos
- Costo: 0€

¡Nos vemos pronto en Atrévete! 💇‍♀️
```

## ⚠️ VALIDACIÓN ANTES DE CONTINUAR

Verifica que tienes TODOS estos datos antes de llamar `book()`:

- ✅ `customer_id` del cliente (obtenido del `manage_customer` que YA ejecutaste en PASO 3)
- ✅ Lista de `services` (nombres exactos elegidos en PASO 1)
- ✅ `stylist_id` (UUID del slot seleccionado en PASO 2)
- ✅ `start_time` (ISO 8601 timestamp del campo `full_datetime`)

**Si falta alguno, NO puedes llamar book(). Debes pedirle al cliente que complete esa información primero.**

## 🛠️ Herramienta: book

**Parámetros:**
- `customer_id`: UUID (de manage_customer en PASO 3)
- `services`: ["Nombre Exacto del Servicio"]
- `stylist_id`: UUID (del slot seleccionado en PASO 2)
- `start_time`: ISO 8601 timestamp (ej: "2025-11-12T10:00:00+01:00")

**Retorna:**
```json
// Si precio > 0:
{
  "success": true,
  "payment_required": true,
  "payment_link": "https://...",
  "appointment_id": "uuid",
  "start_time": "...",
  "end_time": "...",
  "total_price": 52.20,
  "advance_payment": 10.44
}

// Si precio = 0:
{
  "success": true,
  "payment_required": false,
  "appointment_id": "uuid",
  "start_time": "...",
  "end_time": "...",
  "total_price": 0,
  "duration_minutes": 10
}

// Si hay error:
{
  "success": false,
  "error_code": "CATEGORY_MISMATCH" | "SLOT_TAKEN" | "DATE_TOO_SOON" | ...,
  "error_message": "...",
  "details": {...}
}
```

## 🚫 Errores Comunes a Evitar

1. **NO llames manage_customer() otra vez** - Ya tienes el customer_id del PASO 3
2. **NO uses placeholders** - Usa los valores reales de pasos anteriores
3. **NO inventes datos** - Si no tienes un parámetro, pídelo al cliente
4. **NO continúes después de enviar payment_link** - El sistema maneja la confirmación automáticamente

## ✅ Si hay pago, TERMINA aquí. Si no hay pago, pasa al PASO 5.
