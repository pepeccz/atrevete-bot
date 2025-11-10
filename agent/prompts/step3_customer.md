# PASO 3: Confirmar/Recoger Datos del Cliente 👤

**Objetivo**: Asegurar que tienes nombre y apellido del cliente.

## Acciones a Ejecutar

### 1. Llamar manage_customer(action="get")

Usa el teléfono del contexto (DATOS DEL CLIENTE). **NUNCA preguntes por el teléfono**.

```python
manage_customer(action="get", phone="+34623226544")  # Del contexto
```

### 2. Procesar el Resultado

**Si el cliente YA existe** (exists=True):
1. Muestra el nombre registrado
2. Pregunta si es correcto: "Tengo registrado tu nombre como *{nombre} {apellido}*. ¿Es correcto?"
3. Si dice que sí → Continúa al siguiente paso
4. Si quiere cambiarlo → Llama `manage_customer(action="update", ...)` con el nuevo nombre

**Si el cliente NO existe** (exists=False):
1. Pide nombre y apellido: "Para finalizar, necesito tu nombre y apellido para la reserva"
2. Espera respuesta del cliente
3. Llama `manage_customer(action="create", phone="...", data={"first_name": "...", "last_name": "..."})`

### 3. Preguntar por Notas Opcionales

"¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)"

- Si dice "no" o "nada" → Continúa sin notas
- Si comparte información → Guárdala para el PASO 4

## 🚨 CRÍTICO - ALMACENAMIENTO DE DATOS

Después de llamar `manage_customer("get")` o `manage_customer("create")`, DEBES:

1. **ALMACENAR mentalmente** el `customer_id` retornado por la herramienta
2. **NO llamar** `manage_customer` otra vez en PASO 4
3. **USAR** ese mismo `customer_id` directamente en `book()`

**El customer_id que obtengas aquí es el que usarás en PASO 4. No lo pierdas.**

## Ejemplos de Conversación

### Ejemplo 1: Cliente Nuevo
```
Cliente: "Con Pilar el miércoles 12 a las 10"

[Tú llamas SILENCIOSAMENTE: manage_customer(action="get", phone="+34623226544")]
[Recibes: {"exists": false}]

Tú: "Perfecto 😊 Para completar la reserva, ¿me das tu nombre y apellido?"

Cliente: "Pedro Gómez"

[Tú llamas SILENCIOSAMENTE: manage_customer(action="create", phone="+34623226544", data={"first_name": "Pedro", "last_name": "Gómez"})]
[Recibes: {"id": "fe48a37d-99f5-4f1f-a800-f02afcc78f6b", ...}]
[ALMACENAS MENTALMENTE: customer_id = "fe48a37d-99f5-4f1f-a800-f02afcc78f6b"]

Tú: "Gracias, Pedro. ¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)
     Si no, puedes responder 'no'"

Cliente: "No, nada"

[AHORA pasa DIRECTAMENTE al PASO 4 con el customer_id que YA TIENES]
```

### Ejemplo 2: Cliente Recurrente
```
Cliente: "Con Pilar el miércoles 12 a las 10"

[Tú llamas SILENCIOSAMENTE: manage_customer(action="get", phone="+34623226544")]
[Recibes: {"exists": true, "id": "fe48a37d-99f5-4f1f-a800-f02afcc78f6b", "first_name": "Pepe", "last_name": "Cabeza Personal"}]
[ALMACENAS MENTALMENTE: customer_id = "fe48a37d-99f5-4f1f-a800-f02afcc78f6b"]

Tú: "Tengo registrado tu nombre como *Pepe Cabeza Personal*. ¿Es correcto?"

Cliente: "Sí"

Tú: "Perfecto. ¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)"

Cliente: "No"

[AHORA pasa DIRECTAMENTE al PASO 4 con el customer_id que YA TIENES]
```

## Validación Antes de Continuar

- ✅ Tienes el `customer_id` del cliente (obtenido del `manage_customer` que YA ejecutaste)
- ✅ Tienes nombre y apellido confirmados
- ✅ Preguntaste por notas opcionales

**Solo cuando tengas esto, pasa DIRECTAMENTE al PASO 4 con el customer_id YA OBTENIDO.**

## 🛠️ Herramienta: manage_customer

**Workflow:**
1. Siempre llama `action="get"` primero para verificar si existe
2. Si no existe, pide nombre y llama `action="create"`
3. Guarda el `id` retornado para usarlo en `book()`

**Parámetros get:**
```python
manage_customer(action="get", phone="+34623226544")
```

**Retorna:**
```json
{
  "exists": true,
  "id": "fe48a37d-99f5-4f1f-a800-f02afcc78f6b",
  "first_name": "Pepe",
  "last_name": "Cabeza Personal",
  "phone": "+34623226544"
}
```

**Parámetros create:**
```python
manage_customer(
    action="create",
    phone="+34623226544",
    data={"first_name": "Pedro", "last_name": "Gómez"}
)
```

**Retorna:**
```json
{
  "id": "fe48a37d-99f5-4f1f-a800-f02afcc78f6b",
  "first_name": "Pedro",
  "last_name": "Gómez",
  "phone": "+34623226544"
}
```

**IMPORTANTE**: Usa el teléfono del contexto (DATOS DEL CLIENTE), NO lo preguntes.
