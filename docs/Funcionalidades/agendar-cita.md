# Sistema de Agendamiento de Citas - MVP

## Descripción General
Sistema de agendamiento automatizado para el salón de belleza Atrévete, integrado con WhatsApp vía Chatwoot. Permite a los clientes agendar citas de manera conversacional, gestionar disponibilidad en tiempo real de 5 asistentas, y procesar pagos de anticipo del 20% vía Stripe.

**Alcance del MVP:** Agendamiento inicial de citas. Las modificaciones y cancelaciones se tratarán en una funcionalidad posterior.

## Integraciones Externas Necesarias
- **Google Calendar**: Para consultar y gestionar la disponibilidad de los 5 calendarios de asistentas
- **Stripe**: Para generar enlaces de pago y procesar los anticipos
- **Chatwoot**: Para enviar mensajes de confirmación y escalar conversaciones a humanos

## Reglas de Negocio

### Antelación Mínima
Las citas deben agendarse con **mínimo 3 días de antelación**. Si el cliente solicita una cita con menos de 3 días:
- Rechazar la solicitud educadamente
- Explicar la política de 3 días mínimos
- Escalar a humano para casos urgentes
- Mostrar disponibilidades desde el tercer día en adelante

### Restricción de Categorías
**NO se permite mezclar servicios de diferentes categorías** en una misma cita. Si el cliente intenta mezclar categorías:
- Rechazar la combinación
- Explicar que solo se pueden agendar servicios de una misma categoría
- Pedir que elija una sola categoría para continuar
- Si insiste, escalar a humano

### Pagos y Anticipos
- **Anticipo obligatorio:** 20% del coste total del servicio
- **Excepción:** Si el coste total es 0€, no se requiere anticipo
- **Tiempo límite:** El cliente tiene 5-10 minutos para completar el pago desde que recibe el enlace

**Si el cliente no paga en el tiempo establecido:**
- Cancelar la reserva automáticamente
- Liberar el horario en el calendario
- Informar que la cita no se confirmó por falta de pago
- Ofrecer reintentar el proceso

### Disponibilidad y Horarios
- Se debe considerar un **buffer de 10 minutos** entre citas consecutivas para preparación
- La disponibilidad se calcula considerando:
  - Duración del servicio o pack solicitado
  - Los 10 minutos adicionales de buffer
  - Horarios de operación del salón
  - Citas ya existentes en los calendarios
  - La antelación mínima de 3 días

### Clientes Recurrentes
Para clientes que ya tienen historial, el sistema debe:
- Sugerir la asistenta que los atendió en citas anteriores
- Pre-llenar automáticamente nombre y apellido registrados (permitiendo cambios)
- Recordar y mencionar servicios que el cliente suele solicitar

## Información Necesaria para Completar el Agendamiento

### Del Servicio
- **Servicios o pack seleccionados**: Qué servicios individuales o qué pack desea el cliente
- **Categoría del servicio**: Todos los servicios deben pertenecer a la misma categoría
- **Duración total**: Suma del tiempo de todos los servicios seleccionados (en minutos)
- **Costo total**: Suma del precio de todos los servicios (en euros)

**Nota:** Si se seleccionan múltiples servicios, TODOS deben ser de la misma categoría. Si es un pack, se usa la categoría del pack.

### De la Asistenta
- **Asistenta seleccionada**: Qué asistenta atenderá la cita
- **Validación de categoría**: La categoría de la asistenta debe coincidir con la categoría del servicio
- **Disponibilidad real**: La asistenta debe tener el horario libre en su calendario de Google

### Del Cliente
- **Teléfono móvil**: Se obtiene automáticamente del número de WhatsApp (NUNCA preguntar)
- **Nombre**: Nombre de la persona que acudirá a la cita
- **Apellido**: Apellido de la persona que acudirá a la cita
- **Notas opcionales**: Cualquier información adicional que el cliente quiera compartir (alergias, preferencias, etc.)

**Para clientes recurrentes:** Si ya tienen datos registrados, sugerirlos automáticamente pero permitir cambios.

### De Fecha y Horario
- **Fecha de la cita**: Debe ser al menos 3 días después de la fecha actual
- **Hora de inicio**: Debe estar dentro del horario de operación del salón
- **Hora de fin**: Se calcula automáticamente sumando la duración del servicio más 10 minutos de buffer

### Del Pago
- **Monto total**: Costo total de los servicios
- **Monto del anticipo**: 20% del monto total (solo si el costo es mayor a 0€)
- **Enlace de pago**: Generado por Stripe para que el cliente pague el anticipo
- **Estado del pago**: Si el anticipo fue pagado o no

## Flujo del Proceso de Agendamiento

El proceso de agendamiento se divide en 4 fases secuenciales que el sistema debe completar con el cliente:

### Fase 1: Selección del Servicio o Pack

**Qué debe lograr esta fase:**
Identificar qué servicio(s) o pack desea el cliente y asegurar que todos pertenezcan a una sola categoría.

**Cómo debe funcionar:**

1. **Preguntar al cliente** qué servicio(s) o pack desea agendar

2. **Validar la selección:**
   - Si selecciona múltiples servicios, verificar que TODOS sean de la misma categoría
   - Si son de categorías diferentes: rechazar la combinación y pedir que elija una sola categoría
   - Si selecciona un pack, validar que esté disponible y activo

3. **Calcular información del servicio:**
   - Duración total: sumar los minutos de todos los servicios
   - Costo total: sumar el precio de todos los servicios (o precio del pack)
   - Guardar la categoría para la siguiente fase

**Ejemplos de conversación:**

*Caso exitoso:*
```
Cliente: "Quiero un corte de pelo y un tinte"
Sistema: "Perfecto, has elegido Corte de Pelo (30 min, 25€) y Tinte (90 min, 60€).
         El tiempo total será de 2 horas y el costo de 85€."
```

*Caso de rechazo por categorías diferentes:*
```
Cliente: "Quiero manicura y masaje facial"
Sistema: "Lo siento, no puedo agendar servicios de diferentes categorías en la misma cita.
         Por favor, elige solo servicios de Nails O servicios de Skincare."
```

---

### Fase 2: Selección de Asistenta y Disponibilidad

**Qué debe lograr esta fase:**
Mostrar al cliente las asistentas disponibles con sus horarios y que el cliente elija una.

**Cómo debe funcionar:**

1. **Identificar asistentas elegibles:**
   - Buscar todas las asistentas que trabajen en la categoría del servicio seleccionado
   - Solo considerar asistentas activas

2. **Para clientes recurrentes:**
   - Verificar si el cliente tiene citas anteriores
   - Si las tiene, mencionar la asistenta que lo atendió: "Tu última cita fue con [Nombre]. ¿Te gustaría agendar con ella nuevamente?"

3. **Consultar disponibilidad real:**
   - Para cada asistenta elegible, buscar horarios disponibles en su calendario de Google
   - Buscar disponibilidades desde 3 días en adelante (hasta 30 días)
   - Considerar la duración del servicio + 10 minutos de buffer
   - Respetar los horarios de operación del salón
   - Identificar las 2-3 primeras disponibilidades de cada asistenta

4. **Presentar las opciones al cliente** en un formato claro:
```
"Estas son las asistentas disponibles para [Categoría]:

1. [Nombre Asistenta 1]:
   - Opción A: [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   - Opción B: [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   - Opción C: [Día Semana], [DD/MM/YYYY] a las [HH:MM]

2. [Nombre Asistenta 2]:
   - Opción A: [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   - Opción B: [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   - Opción C: [Día Semana], [DD/MM/YYYY] a las [HH:MM]

¿Con qué asistenta y en qué horario prefieres tu cita?"
```

5. **Procesar la respuesta del cliente:**
   - Si elige una asistenta y horario: continuar con la siguiente fase
   - Si pide más opciones de una asistenta específica: mostrar más horarios disponibles
   - Si ninguna opción le sirve: preguntar qué fecha/hora prefiere y verificar disponibilidad
   - Si no hay disponibilidad: escalar a humano

**Casos especiales:**

- **Sin disponibilidad para la fecha solicitada:**
  ```
  "Lo siento, no hay disponibilidad para [fecha].
  La próxima disponibilidad es [fecha más cercana]. ¿Te funciona?"
  ```

- **Cliente pide cita con menos de 3 días de antelación:**
  ```
  "Por política del salón, las citas deben agendarse con al menos 3 días de antelación.
  El primer día disponible es [D+3]. Para casos urgentes, puedo conectarte con el equipo.
  ¿Deseas que te transfiera?"
  ```

---

### Fase 3: Confirmación de Datos del Cliente

**Qué debe lograr esta fase:**
Recopilar o confirmar el nombre, apellido y notas opcionales del cliente.

**Cómo debe funcionar:**

1. **Verificar si el cliente ya existe en el sistema:**
   - Buscar al cliente por su número de teléfono de WhatsApp
   - Determinar si es cliente nuevo o recurrente

2. **Para clientes recurrentes:**
   ```
   "Tengo registrado tu nombre como [nombre] [apellido].
   ¿Confirmas que esos datos son correctos o prefieres cambiarlos?"
   ```
   - Si confirma: usar los datos existentes
   - Si quiere cambiar: solicitar los nuevos datos y actualizarlos

3. **Para clientes nuevos:**
   ```
   "Para finalizar, necesito tu nombre y apellido para la reserva."
   ```
   - Esperar que el cliente proporcione su nombre y apellido
   - Guardar los datos en el sistema

4. **Solicitar notas opcionales (para todos):**
   ```
   "¿Hay algo que debamos saber antes de tu cita? (alergias, preferencias, etc.)
   Si no, puedes responder 'no' o 'nada'."
   ```
   - Si comparte información: guardarla como notas
   - Si responde negativamente: continuar sin notas

**Recordar:** El teléfono NUNCA se pregunta, se obtiene automáticamente del WhatsApp.

---

### Fase 4: Generación de Enlace de Pago y Confirmación

**Qué debe lograr esta fase:**
Procesar el anticipo del 20% (si aplica) y confirmar la cita definitivamente.

**Cómo debe funcionar:**

**Si el costo total es 0€:**
- Omitir todo el proceso de pago
- Crear la cita directamente en Google Calendar
- Registrar la cita en la base de datos
- Enviar mensaje de confirmación final al cliente

**Si el costo total es mayor a 0€:**

1. **Calcular el anticipo:**
   - Anticipo = 20% del costo total

2. **Generar enlace de pago:**
   - Crear un enlace de pago con Stripe
   - El enlace debe incluir información de la cita en los metadatos

3. **Bloquear temporalmente el horario:**
   - Crear una "RESERVA TEMPORAL" en el calendario de Google de la asistenta
   - Esta reserva se mantendrá por 5-10 minutos

4. **Enviar el enlace al cliente:**
   ```
   "Perfecto, tu cita está casi lista.

   Para confirmarla, necesito que pagues el anticipo de [anticipo]€
   (20% del total de [costo_total]€).

   Enlace de pago: [enlace]

   Una vez procesado el pago, tu cita quedará confirmada automáticamente.
   Tienes 10 minutos para completar el pago."
   ```

5. **Esperar la confirmación de pago:**
   - El sistema debe monitorear si Stripe confirma que el pago fue exitoso
   - Si el pago es exitoso:
     - Convertir la "RESERVA TEMPORAL" en cita confirmada
     - Registrar la cita y el pago en la base de datos
     - Enviar mensaje de confirmación final

6. **Si el pago NO se completa en 5-10 minutos:**
   - Cancelar la reserva temporal
   - Liberar el horario en el calendario
   - Informar al cliente:
   ```
   "Lo siento, no recibí la confirmación de tu pago en el tiempo establecido.
   La reserva ha sido cancelada para liberar el horario.

   Si aún deseas agendar esta cita, puedo ayudarte a reintentar el proceso.
   ¿Deseas volver a intentarlo?"
   ```

**Mensaje de confirmación final** (para citas con o sin pago):
```
✅ ¡Tu cita ha sido confirmada!

📅 Resumen de tu cita:
- Fecha: [Día de la semana], [DD/MM/YYYY]
- Hora: [HH:MM] - [HH:MM]
- Asistenta: [Nombre de la asistenta]
- Servicios: [Lista de servicios/pack]
- Duración: [minutos] minutos
- Costo total: [costo]€

💶 Información de pago:
- Anticipo pagado: [anticipo]€ ✓
- Saldo pendiente: [saldo]€
  (a pagar en el salón)

⚠️ Política de cancelación:
Para modificar o cancelar tu cita, debes hacerlo con al menos 24 horas
de antelación. Contacta con nosotros si necesitas hacer cambios.

📍 Ubicación:
[Dirección del salón]
[Enlace a Google Maps]

¡Nos vemos pronto en Atrévete! 💇‍♀️
```

---

## Situaciones de Error y Escalación

### Mensajes de Error Comunes

El sistema debe responder apropiadamente a estas situaciones:

| Situación | Mensaje al Cliente | Qué Hacer |
|-----------|-------------------|-----------|
| **Mezcla de categorías** | "Lo siento, no puedo agendar servicios de diferentes categorías en la misma cita. Por favor, elige servicios de una sola categoría." | Rechazar y pedir nueva selección |
| **Menos de 3 días antelación** | "Por política del salón, las citas deben agendarse con al menos 3 días de antelación. Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?" | Rechazar y ofrecer escalación |
| **Sin disponibilidad** | "Lo siento, no hay disponibilidad en las fechas solicitadas. La próxima disponibilidad es [fecha]. ¿Te funciona esa fecha?" | Ofrecer siguiente fecha disponible |
| **Pago no completado** | "No recibí la confirmación de tu pago. La reserva ha sido cancelada. ¿Deseas reintentar el proceso?" | Cancelar reserva, liberar horario |
| **Error técnico Google Calendar** | "Estoy teniendo problemas para consultar la disponibilidad. Permíteme un momento mientras lo resuelvo." | Reintentar, escalar si falla 3 veces |
| **Error técnico Stripe** | "Hay un problema con el sistema de pagos. Te voy a conectar con el equipo para que te ayuden personalmente." | Escalar inmediatamente |

### Cuándo Escalar a un Humano

El sistema debe transferir la conversación a un miembro del equipo en estos casos:

1. **Solicitud urgente:** Cliente insiste en agendar con menos de 3 días de antelación
2. **Fallo técnico persistente:** Los servicios externos (Google Calendar o Stripe) fallan repetidamente
3. **Caso especial:** Cliente tiene peticiones que no se pueden manejar con el flujo estándar
4. **Cliente frustrado:** Se detecta frustración o insatisfacción en el tono del cliente
5. **Problemas con el pago:** El cliente tiene dificultades recurrentes con el proceso de pago

**Mensaje de escalación:**
```
"Entiendo tu situación. Voy a conectarte con un miembro del equipo
que podrá ayudarte personalmente con tu solicitud."
```

---

## Información que se Guarda en el Sistema

### En Google Calendar
Cada cita confirmada debe guardarse en el calendario de Google de la asistenta con:
- Título: "Cita - [Nombre Cliente] - [Servicios]"
- Descripción: Datos del cliente, teléfono, servicios, notas
- Fecha y hora de inicio y fin (incluyendo buffer de 10 minutos)
- Zona horaria: Europe/Madrid
- Metadatos privados: IDs del cliente, cita y estado del pago

### En la Base de Datos

**Información del cliente:**
- Teléfono, nombre, apellido, historial de citas

**Información de la cita:**
- Cliente, asistenta, fecha, hora, servicios, duración, costo, notas, estado

**Información del pago:**
- Monto total, anticipo, saldo pendiente, método, estado, referencia de Stripe

---

## Consideraciones Importantes

### Zona Horaria
Todas las fechas y horas deben manejarse en **zona horaria de Madrid (Europe/Madrid)**.

### Idioma
Toda la comunicación debe ser en **español**, con tono amigable y profesional.

### Datos que NUNCA se Preguntan
- **Teléfono móvil:** Se obtiene automáticamente del WhatsApp del cliente

### Funcionalidades Fuera del Alcance de este MVP
Las siguientes funcionalidades se desarrollarán en fases posteriores:
- Modificación de citas existentes
- Cancelación de citas con gestión de reembolsos
- Recordatorios automáticos previos a la cita
- Sistema de lista de espera
- Historial detallado y estadísticas del cliente
- Programa de fidelización y descuentos

---

## Resumen del Flujo Completo

1. **Cliente inicia conversación** → Sistema identifica intención de agendar cita
2. **Fase 1:** Cliente selecciona servicio(s) o pack → Sistema valida categorías y calcula duración/costo
3. **Fase 2:** Sistema muestra disponibilidad de asistentas → Cliente elige asistenta y horario
4. **Fase 3:** Sistema solicita/confirma datos del cliente → Guarda nombre, apellido y notas
5. **Fase 4:** Si hay costo > 0€, genera enlace de pago → Cliente paga anticipo → Sistema confirma cita
6. **Confirmación:** Cliente recibe mensaje completo con todos los detalles de su cita confirmada