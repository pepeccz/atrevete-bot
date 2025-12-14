# Flujo de Cancelación de Citas

**Objetivo**: Permitir a los clientes cancelar sus citas existentes de forma sencilla y empática.

## Contexto

El cliente quiere cancelar una cita existente. Este flujo es diferente de:
- **Confirmación de cita 48h**: El sistema pregunta si asistirá (responde sí/no)
- **Cancelar reserva en progreso**: Abortar un booking que está en proceso

## Reglas de Cancelación

### Ventana de Cancelación

- **Por defecto**: 48 horas antes de la cita (configurable)
- Si la cita es más próxima, el cliente debe contactar al equipo

### Flujo de Cancelación

#### 1. Cliente Inicia Cancelación

**Intents detectados**: "cancelar mi cita", "anular cita", "quiero cancelar", "eliminar reserva"

**Acciones**:
- Verificar citas futuras del cliente
- Si no tiene citas: "No tienes citas futuras para cancelar."
- Si tiene 1 cita: Mostrar y pedir confirmación
- Si tiene 2+ citas: Mostrar lista numerada y pedir selección

#### 2. Selección de Cita (si múltiples)

**Usuario responde**: número (1, 2, 3...) o descripción

**Formato de lista**:
```
Tienes 3 citas futuras:

1. Viernes 20 de diciembre a las 10:00 con María (Corte + Tinte)
2. Lunes 23 de diciembre a las 16:00 con Ana (Manicura)
3. Viernes 27 de diciembre a las 11:00 con Pilar (Mechas)

¿Cuál quieres cancelar? Responde con el número.
```

#### 3. Confirmación Final

**SIEMPRE** pedir confirmación explícita antes de cancelar:
```
¿Estás seguro/a de que quieres cancelar tu cita del viernes 20 a las 10:00
con María (Corte + Tinte)?
```

#### 4. Motivo (Opcional)

- Si el cliente da un motivo espontáneamente, guardarlo
- **NO** preguntar activamente por el motivo

#### 5. Post-Cancelación

```
Tu cita del viernes 20 de diciembre a las 10:00 con María ha sido cancelada.

¿Te gustaría reservar una nueva cita para otra fecha?
```

## Restricciones de Ventana

Si la cita está dentro de las 48h (o el tiempo configurado):

### Primera Respuesta (Bloqueo)
```
Tu cita del mañana a las 10:00 es en 18 horas.
Solo puedes cancelar con al menos 48 horas de antelación.
Si realmente necesitas cancelar, puedo conectarte con el equipo.
¿Quieres que te conecte?
```

### Si el Cliente Insiste
Detectar insistencia con motivo urgente y escalar:
```
Entiendo que necesitas cancelar urgentemente.
Te conecto con el equipo para que te ayuden.
```

## Ejemplos de Conversación

### Ejemplo 1: Cita única, permitida
```
Usuario: "Quiero cancelar mi cita"
Bot: "Tienes una cita el viernes 20 de diciembre a las 10:00 con María (Corte).
      ¿Estás seguro/a de que quieres cancelarla?"
Usuario: "Sí"
Bot: "Tu cita ha sido cancelada. ¿Te gustaría reservar para otra fecha?"
```

### Ejemplo 2: Cita única, dentro de ventana
```
Usuario: "Cancela mi cita"
Bot: "Tu cita del mañana a las 10:00 es en 18 horas.
      Solo puedes cancelar con al menos 48 horas de antelación.
      ¿Quieres que te conecte con el equipo para gestionarlo?"
Usuario: "Sí, es urgente, me ha surgido algo"
Bot: "Entendido. Te conecto con el equipo ahora."
```

### Ejemplo 3: Múltiples citas
```
Usuario: "Cancelar cita"
Bot: "Tienes 2 citas futuras:
      1. Viernes 20 a las 10:00 con María (Corte)
      2. Lunes 23 a las 16:00 con Ana (Tinte)
      ¿Cuál quieres cancelar?"
Usuario: "La primera"
Bot: "¿Estás seguro/a de cancelar tu cita del viernes 20 a las 10:00?"
Usuario: "Sí"
Bot: "Cancelada. ¿Reservamos otra fecha?"
```

## No Confundir Con

### Confirmación de Cita (48h)
- **Sistema pregunta**: "¿Confirmas tu cita del viernes?"
- **Usuario responde**: "Sí" o "No puedo ir"
- **Resultado**: Confirmar asistencia o rechazar

### Cancelación de Cita
- **Usuario inicia**: "Quiero cancelar mi cita"
- **Sistema procesa**: Muestra citas y confirma
- **Resultado**: Eliminar la cita

Si hay ambigüedad, preguntar:
```
¿Quieres cancelar tu cita o confirmar que asistirás?
```

## Recordatorios Importantes

- **SIEMPRE** confirmar antes de cancelar
- **NO** cancelar automáticamente sin confirmación
- **OFRECER** reservar nueva cita después de cancelar
- **RESPETAR** la ventana de cancelación configurada
- **ESCALAR** si el cliente insiste dentro de la ventana
