## Descripción General

Sistema de agendamiento automatizado para el salón de belleza Atrévete, integrado con WhatsApp vía Chatwoot. Permite a los clientes agendar citas de manera conversacional y gestionar disponibilidad en tiempo real de 5 asistentas.

**Alcance:** Agendamiento inicial de citas. Las modificaciones, cancelaciones, confirmaciones y recordatorios se tratarán en funcionalidades posteriores.

---

## Integraciones Externas Necesarias

- **Google Calendar**: Para consultar y gestionar la disponibilidad de los 5 calendarios de asistentas
- **Chatwoot**: Para enviar mensajes de confirmación y escalar conversaciones a humanos

---

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

---

## Información Necesaria para Completar el Agendamiento

### Del Servicio

- **Servicios seleccionados**: Qué servicios individuales desea el cliente
- **Categoría del servicio**: Todos los servicios deben pertenecer a la misma categoría
- **Duración total**: Suma del tiempo de todos los servicios seleccionados (en minutos)

**Nota:** Si se seleccionan múltiples servicios, TODOS deben ser de la misma categoría (Peluquería O Estética, no ambos). El pago se realiza en el salón después del servicio.

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

---

## Flujo del Proceso de Agendamiento

El proceso de agendamiento se divide en 4 fases secuenciales que el sistema debe completar con el cliente:

### Fase 1: Selección de Servicios

**Qué debe lograr esta fase:**

Identificar qué servicio(s) desea el cliente y asegurar que todos pertenezcan a una sola categoría.

**Cómo debe funcionar:**

1. **Preguntar al cliente** qué servicio(s) desea agendar
2. **Presentar opciones con listas numeradas** para facilitar la selección
3. **Validar la selección:**
    - Si selecciona múltiples servicios, verificar que TODOS sean de la misma categoría
    - Si son de categorías diferentes: rechazar la combinación y pedir que elija una sola categoría
4. **Mostrar confirmación con desglose:**
    - Incluir descripción de cada servicio seleccionado
    - Mostrar duración total
    - Preguntar: "¿Solo quieres este/estos servicio/s o algo más?"
5. **Si el cliente quiere añadir más servicios:**
    - Volver a mostrar las opciones
    - Validar que sean de la misma categoría
    - Actualizar el desglose
6. **Una vez confirmado**, calcular información del servicio:
    - Duración total: sumar los minutos de todos los servicios
    - Guardar la categoría para la siguiente fase

**Ejemplos de conversación:**

*Caso exitoso:*

```
Sistema: "¿Qué servicios te gustaría agendar?

1. Corte de Pelo (30 min)
2. Tinte (90 min)
3. Mechas (120 min)
..."

Cliente: "El 1 y el 2"

Sistema: "Perfecto, has elegido:
• Corte de Pelo - 30 min
• Tinte - 90 min

Duración total: 2 horas

¿Solo quieres estos servicios o algo más?"
```

*Caso de rechazo por categorías diferentes:*

```
Cliente: "Quiero manicura y masaje facial"

Sistema: "Lo siento, no puedo agendar servicios de diferentes categorías en la misma cita.
         Por favor, elige solo servicios de Manicura O servicios de Masaje Facial."
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
4. **Presentar las opciones al cliente** con listas numeradas:

```
"Estas son las asistentas disponibles para [Categoría]:

1. [Nombre Asistenta 1]:
   A) [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   B) [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   C) [Día Semana], [DD/MM/YYYY] a las [HH:MM]

2. [Nombre Asistenta 2]:
   A) [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   B) [Día Semana], [DD/MM/YYYY] a las [HH:MM]
   C) [Día Semana], [DD/MM/YYYY] a las [HH:MM]

¿Con qué asistenta y en qué horario prefieres tu cita?
(Responde con el número y letra, ej: 1A)"
```

1. **Procesar la respuesta del cliente:**
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
    ¿Confirmas que esos datos son correctos para la cita?"
    ```
    
    - Si confirma: usar los datos existentes
    - Si quiere cambiar: solicitar los nuevos datos y actualizarlos
3. **Para clientes nuevos:**
    
    ```
    "Para poder continuar agendando la cita necesitaré que me facilites tu nombre y apellidos."
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

### Fase 4: Confirmación Final y Agendamiento

**Qué debe lograr esta fase:**

Mostrar un resumen completo de la cita para confirmación final y, si el cliente confirma, crear la cita definitivamente.

**Cómo debe funcionar:**

1. **Mostrar resumen completo para confirmación:**

```
"Perfecto, voy a confirmar los datos de tu cita:

📅 Fecha: [Día de la semana], [DD/MM/YYYY]
🕐 Hora: [HH:MM] - [HH:MM]
💇‍♀️ Asistenta: [Nombre de la asistenta]

📋 Servicios:
1. [Servicio 1] - [duración] min
2. [Servicio 2] - [duración] min

⏱️ Duración total: [X] horas [Y] minutos

👤 Datos del cliente:
• Nombre: [Nombre Apellido]
• Teléfono: [teléfono]
• Notas: [notas o 'Ninguna']

¿Confirmas que todos los datos son correctos?"
```

1. **Esperar confirmación del cliente:**
    - Si confirma (responde "sí", "confirmo", "correcto", etc.): continuar con el agendamiento
    - Si quiere cambiar algo: preguntar qué desea modificar y volver a la fase correspondiente
    - Si cancela: agradecer y ofrecer ayuda para cuando esté listo
2. **Si el cliente confirma, crear la cita:**
    - Crear el evento en el calendario de Google de la asistenta
    - Registrar la cita en la base de datos
    - Asociar al cliente con la cita
3. **Enviar mensaje de confirmación final:**

```
✅ ¡Tu cita ha sido confirmada!

📅 Resumen de tu cita:
• Fecha: [Día de la semana], [DD/MM/YYYY]
• Hora: [HH:MM] - [HH:MM]
• Asistenta: [Nombre de la asistenta]

📋 Servicios:
1. [Servicio 1] - [duración] min
2. [Servicio 2] - [duración] min

⏱️ Duración total: [X] horas [Y] minutos

💶 El pago se realiza en el salón después del servicio

📍 Ubicación:
[Dirección del salón]
[Enlace a Google Maps]

⚠️ Importante:
• Recibirás una confirmación 48 horas antes de tu cita
• Te enviaremos un recordatorio 24 horas antes
• Para modificar o cancelar, contacta con nosotros con antelación

¡Nos vemos pronto en Atrévete! 💇‍♀️
```

---

## Situaciones de Error y Escalación

### Mensajes de Error Comunes

El sistema debe responder apropiadamente a estas situaciones:

| Situación | Mensaje al Cliente | Qué Hacer |
| --- | --- | --- |
| **Mezcla de categorías** | "Lo siento, no puedo agendar servicios de diferentes categorías en la misma cita. Por favor, elige servicios de una sola categoría." | Rechazar y pedir nueva selección |
| **Menos de 3 días antelación** | "Por política del salón, las citas deben agendarse con al menos 3 días de antelación. Para casos urgentes, puedo conectarte con el equipo. ¿Deseas hablar con una persona?" | Rechazar y ofrecer escalación |
| **Sin disponibilidad** | "Lo siento, no hay disponibilidad en las fechas solicitadas. La próxima disponibilidad es [fecha]. ¿Te funciona esa fecha?" | Ofrecer siguiente fecha disponible |
| **Error técnico Google Calendar** | "Estoy teniendo problemas para consultar la disponibilidad. Permíteme un momento mientras lo resuelvo." | Reintentar, escalar si falla 3 veces |
| **Cliente no confirma datos** | "Necesito que confirmes los datos antes de agendar la cita. ¿Los datos mostrados son correctos?" | Solicitar confirmación explícita |

### Cuándo Escalar a un Humano

El sistema debe transferir la conversación a un miembro del equipo en estos casos:

1. **Solicitud urgente:** Cliente insiste en agendar con menos de 3 días de antelación
2. **Fallo técnico persistente:** Los servicios externos (Google Calendar) fallan repetidamente
3. **Caso especial:** Cliente tiene peticiones que no se pueden manejar con el flujo estándar
4. **Cliente frustrado:** Se detecta frustración o insatisfacción en el tono del cliente
5. **Confusión recurrente:** Cliente no entiende o no puede seguir el flujo después de varios intentos

**Mensaje de escalación:**

```
"Entiendo tu situación. Voy a conectarte con un miembro del equipo
que podrá ayudarte personalmente con tu solicitud."
```

---

## Información que se Guarda en el Sistema

### En Google Calendar

Cada cita confirmada debe guardarse en el calendario de Google de la asistenta con:

- Título: "[Nombre Cliente] - [Servicios]"
- Descripción: Datos del cliente, teléfono, servicios, notas
- Fecha y hora de inicio y fin (incluyendo buffer de 10 minutos)
- Zona horaria: Europe/Madrid
- Metadatos privados: IDs del cliente y cita

### En la Base de Datos

**Información del cliente:**

- Teléfono, nombre, apellido, historial de citas

**Información de la cita:**

- Cliente, asistenta, fecha, hora, servicios, duración, notas, estado

---

## Consideraciones Importantes

### Zona Horaria

Todas las fechas y horas deben manejarse en **zona horaria de Madrid (Europe/Madrid)**.

### Idioma

Toda la comunicación debe ser en **español**, con tono amigable y profesional.

### Presentación de Opciones

**Todas las opciones deben presentarse con listas numeradas** para facilitar la selección del cliente y mejorar la experiencia de usuario.

### Datos que NUNCA se Preguntan

- **Teléfono móvil:** Se obtiene automáticamente del WhatsApp del cliente

### Funcionalidades Fuera del Alcance de este MVP

Las siguientes funcionalidades se desarrollarán en fases posteriores:

- Modificación de citas existentes
- Cancelación de citas
- Confirmaciones automáticas 48 horas antes
- Recordatorios automáticos 24 horas antes
- Sistema de lista de espera
- Historial detallado y estadísticas del cliente
- Programa de fidelización y descuentos

---

## Resumen del Flujo Completo

1. **Cliente inicia conversación** → Sistema identifica intención de agendar cita
2. **Fase 1:** Cliente selecciona servicio(s) → Sistema valida categorías, muestra desglose y pregunta si quiere algo más → Calcula duración total
3. **Fase 2:** Sistema muestra disponibilidad de asistentas con listas numeradas → Cliente elige asistenta y horario
4. **Fase 3:** Sistema solicita/confirma datos del cliente → Guarda nombre, apellido y notas
5. **Fase 4:** Sistema muestra resumen completo → Cliente confirma → Sistema crea la cita
6. **Confirmación:** Cliente recibe mensaje completo con todos los detalles de su cita confirmada, ubicación del salón, y la información sobre las confirmaciones y recordatorios futuros