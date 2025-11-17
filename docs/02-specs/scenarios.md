s## Simulación 1
**Escenario:** Reserva estándar con pack sugerido.

**Contexto inicial:**  
Es la primera vez que Laura escribe por WhatsApp.  
En la metadata recibida aparece su número y el nombre “Laura” (coincide con su nombre real).  
En la hoja *Asistentas* aparecen: Pilar (Peluquería), Marta (Peluquería y Estética), Rosa (Estética), Harol (Peluquería) y Víctor (Peluquería).  
El cliente pide un servicio individual (“mechas”). En la hoja *Packs* existe el pack “Mechas + Corte” por 80€, duración 60 minutos, que resulta más rentable que el servicio suelto.  
En Google Calendar hay huecos libres el viernes por la mañana y por la tarde.

**Conversación:**  
- Cliente: Quiero hacerme mechas el viernes.  
- Bot: ¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es Laura?  
  _Acción interna: Como es la primera vez que escribe, Maite se presenta y confirma el nombre que aparece en WhatsApp antes de continuar._  
- Cliente: Sí, soy Laura.  
- Bot: Genial, Laura 💕. Las mechas tienen un precio de X€ y una duración de Y minutos, pero también contamos con un **pack de mechas + corte** por 80€, que dura 60 minutos aproximadamente y con el que además ahorras dinero. ¿Quieres que te reserve ese pack?  
  _Acción interna: El sistema consulta la hoja *Packs* y detecta el pack más rentable, dando prioridad a mostrarlo al cliente._  
- Cliente: Sí, el pack.  
- Bot: Perfecto. ¿Quieres que te atienda alguna de mis compañeras en especial o prefieres que busque la primera opción disponible? Mis compañeras de peluquería son Pilar, Marta, Harol y Víctor.  
  _Acción interna: El sistema filtra en la hoja *Asistentas* por la categoría “Peluquería” y descarta automáticamente a Rosa (Estética)._  
- Cliente: La primera disponible.  
- Bot: Muy bien. Este viernes tenemos libre a las 10:30 con mi compañera Pilar y a las 12:30 con mi compañera Marta. ¿Cuál prefieres?  
  _Acción interna: Consulta de agendas y selección de dos opciones próximas._  
- Cliente: 12:30.  
- Bot: Perfecto. Para dejar la reserva bien a tu nombre, ¿me confirmas tus apellidos, Laura?  
- Cliente: Torres.  
- Bot: Gracias, Laura **Torres**. Para confirmar la cita solo necesito un anticipo de **16€** (20% del total). Si cancelas con al menos 6 horas de antelación, se te devuelve íntegro. Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].   
  _Acción interna: Se registra el nombre completo asociado al número. El sistema calcula el anticipo y genera el enlace de pago. Se debe crear un bloqueo provisional de 30 minutos en el calendario con estado “pendiente de pago”._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Laura! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **viernes a las 12:30** con mi compañera Marta, para el pack mechas + corte. ¡Te esperamos con muchas ganas! 💇‍♀️  
  _Acción interna: El sistema valida el pago, convierte el bloqueo provisional en cita definitiva de 60 minutos y notifica a Marta._  

**Resultado esperado:**  
Cita creada para el pack “Mechas + Corte”, viernes a las 12:30 con Marta, duración 60 minutos, nombre Laura Torres. Anticipo confirmado y correctamente registrado.

---

## Simulación 2

**Escenario:**  
Cambio de cita con solicitud de especialista.

**Contexto inicial:**  
El cliente se llama Beatriz y ya ha reservado antes (es cliente recurrente).  
En la base de datos consta como atendida previamente por Lucas (Peluquería).  
Tiene una cita con Lucas el martes a las 10:00 y quiere moverla a la tarde.  

**Conversación:**  
- Cliente: Hola, quiero cambiar mi cita con Lucas del martes por la mañana a la tarde.  
- Bot: ¡Hola de nuevo, Beatriz! Soy Maite, tu asistenta virtual de Atrévete Peluquería 🌸. Veo que tienes cita con mi compañero Lucas el martes a las 10:00. Te busco alternativas por la tarde 😉.  
  _Acción interna: Se detecta que es cliente recurrente, se salta el protocolo de presentación y confirmación de nombre. El sistema consulta en Google Calendar la agenda de Lucas para ese día._  
- Bot: Ese día Lucas tiene libres a las 16:00 y a las 17:00. ¿Cuál prefieres?  
- Cliente: Mejor a las 17:00.  
- Bot: Perfecto, Beatriz. Actualizo tu cita con Lucas al martes a las 17:00.  
  _Acción interna: El sistema modifica la cita en Google Calendar manteniendo al mismo especialista._  
- Bot: ¡Listo! Tu cita con Lucas está confirmada para el martes a las 17:00.  

**Resultado esperado:**  
La cita de Beatriz se reprograma correctamente con Lucas para el martes a las 17:00.  

---

## Simulación 3

**Escenario:**  
Cancelación cercana a la hora de la cita.

**Contexto inicial:**  
El cliente se llama María. Es cliente recurrente.  
Tiene una cita hoy a las 17:00 con Marta. Son las 15:00 (menos de 6h de antelación).  

**Conversación:**  
- Cliente: No puedo ir, cancela mi cita de hoy.  
- Bot: Hola, María 🌸. Entiendo tu situación. Como falta menos de 6 horas para tu cita con mi compañera Marta, no puedo cancelarla automáticamente. Voy a pasar tu caso al equipo para que te atiendan directamente.  
  _Acción interna: El sistema detecta que la cancelación está fuera de plazo. Se debe notificar de inmediato al personal, incluyendo el nombre del cliente, hora de la cita y profesional asignado._  
- Bot: En breve una de mis compañeras se pondrá en contacto contigo para ayudarte con la cancelación.  

**Resultado esperado:**  
La cancelación fuera de plazo se deriva al personal con todos los datos relevantes. El cliente queda informado.  

---

## Simulación 4

**Escenario:**  
Consulta compleja sobre contraindicaciones.

**Contexto inicial:**  
El cliente se llama Ana. Es la primera vez que escribe.  
En la metadata aparece como “Ana”, se confirma nombre.  
Pregunta sobre la seguridad de un tinte estando embarazada.  

**Conversación:**  
- Cliente: ¿Puedo hacerme un tinte si estoy embarazada?  
- Bot: ¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de conocerte. ¿Me confirmas si tu nombre es Ana?  
  _Acción interna: Como es la primera vez que escribe, Maite se presenta y confirma el nombre que aparece en WhatsApp._  
- Cliente: Sí, soy Ana.  
- Bot: Gracias, Ana 💕. Tu consulta es muy importante y, por tu seguridad, este tipo de dudas debe resolverlas directamente una especialista.  
  _Acción interna: El sistema detecta que la consulta es médica y se debe derivar automáticamente._  
- Bot: Te paso ahora mismo con una de mis compañeras para que te atienda personalmente.  

**Resultado esperado:**  
La conversación se deriva al personal con resumen del motivo (“consulta sobre tinte y embarazo”). El cliente entiende el porqué de la derivación.  

---

## Simulación 5

**Escenario:**  
Problema de pago durante reserva.

**Contexto inicial:**  
El cliente se llama Carla. Es la primera vez que escribe.  
Quiere reservar un servicio de color el jueves a las 11:00.  

**Conversación:**  
- Cliente: Quiero reservar un color para el jueves por la mañana.  
- Bot: ¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es Carla?  
  _Acción interna: Es primera vez, por lo que se presenta y confirma nombre._  
- Cliente: Sí, soy Carla.  
- Bot: Encantada, Carla 💕. El jueves tengo libre a las 11:00 con una de mis compañeras. ¿Quieres que reserve esa hora para tu color?  
  _Acción interna: El sistema consulta Google Calendar y encuentra la franja disponible._  
- Cliente: Sí.  
- Bot: Perfecto. Para confirmar la cita necesito un anticipo de **X€** (20%). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: Se bloquea provisionalmente la franja durante 30 minutos en estado “pendiente de pago”._  
- Cliente: Lo intento pero me da error.  
- Bot: Vaya, parece que el pago no se completó 😕. No pasa nada, te envío otro enlace 👉 [Nuevo enlace].  
  _Acción interna: El sistema genera un nuevo enlace y mantiene el bloqueo._  
- Cliente: Tampoco funciona.  
- Bot: No te preocupes, Carla. Voy a pasar tu caso a una de mis compañeras para que te ayude a completar la reserva.  
  _Acción interna: Tras dos intentos fallidos, se libera el bloqueo y se deriva al equipo._  

**Resultado esperado:**  
La cita no queda confirmada. El caso se deriva a humano con nota del fallo en el pago.  

---

## Simulación 6

**Escenario:**  
Pregunta frecuente sobre horarios y aparcamiento.

**Contexto inicial:**  
El cliente es nuevo.  
En la metadata aparece un nombre extraño en WhatsApp (“✨✨”), por lo que se debe confirmar.  
Pregunta horarios de sábado y aparcamiento.  

**Conversación:**  
- Cliente: ¿Abrís los sábados? ¿Y hay parking cerca?  
- Bot: ¡Hola! Soy Maite, la asistenta virtual de Atrévete Peluquería 🌸. Encantada de saludarte. ¿Me confirmas tu nombre para dirigirme a ti correctamente?  
  _Acción interna: El nombre en la metadata no es fiable. Se debe pedir confirmación para registrar correctamente al cliente._  
- Cliente: Me llamo Sofía.  
- Bot: Gracias, Sofía 💕. Los sábados abrimos de 10:00 a 14:00 🕙. Y respecto al aparcamiento, tienes uno público en la calle Central, a dos minutos andando 🚶.  
  _Acción interna: El sistema busca en la base de datos la información de horarios y aparcamiento._  
- Cliente: Genial, gracias.  
- Bot: ¡A ti, Sofía! Estoy aquí para cualquier otra duda que tengas 😊.  

**Resultado esperado:**  
El cliente recibe respuesta clara y amable. El nombre queda confirmado como Sofía.  

---

## Simulación 7

**Escenario:**  
Reserva para grupo (dos personas).

**Contexto inicial:**  
El cliente se llama Julia. Es cliente recurrente (ya está en la base de datos).  
Quiere reservar un corte para ella y un peinado para su hija el viernes por la tarde.  

**Conversación:**  
- Cliente: Quiero reservar corte y peinado para mí y mi hija el viernes por la tarde.  
- Bot: ¡Hola, Julia! Soy Maite 🌸. Encantada de saludarte otra vez. Veamos qué huecos tenemos para ti y tu hija 😉.  
  _Acción interna: Al ser cliente recurrente, se omite la presentación inicial con confirmación de nombre._  
- Bot: ¿Me confirmas qué servicio quieres para ti y cuál para tu hija?  
- Cliente: Yo quiero corte y mi hija peinado.  
- Bot: Perfecto 💕. El viernes por la tarde tengo a las 16:00 libre para corte con mi compañera Marta y a la misma hora un peinado con mi compañera Sara. ¿Quieres que reserve esas horas para ambas?  
  _Acción interna: El sistema busca huecos simultáneos para los dos servicios en Google Calendar y ofrece la mejor opción._  
- Cliente: Sí, las dos a las 16:00.  
- Bot: Genial. Para confirmar necesito un anticipo del 20% sobre el total de los dos servicios. Aquí tienes el enlace 👉 [Enlace de Stripe].  
  _Acción interna: Se crea un bloqueo provisional en el calendario para ambos servicios durante 30 minutos en estado “pendiente de pago”._  
- **Trigger interno:** Pago recibido correctamente.  
- Bot: ¡Perfecto, Julia! 🎉 Hemos recibido tu anticipo. Tus citas quedan confirmadas para el viernes a las 16:00: corte contigo con mi compañera Marta y peinado para tu hija con mi compañera Sara. ¡Las esperamos con muchas ganas 🤗!  
  _Acción interna: El sistema valida el pago y convierte los bloqueos en citas definitivas._  

**Resultado esperado:**  
Se crean dos citas vinculadas: corte y peinado, viernes 16:00, ambas confirmadas tras el anticipo.

---

## Simulación 8

**Escenario:** Cliente indeciso que pide recomendación de color.

**Contexto inicial:**  
Es la primera vez que Laura escribe por WhatsApp.  
En la metadata recibida aparece su número y el nombre "Laura" (coincide con su nombre real).  
En la hoja *Servicios* aparecen: OLEO PIGMENTO (30 min, 34€), BARRO (40 min, 36.5€), BARRO GOLD (40 min, 48€).  
En la hoja *Asistentas* aparecen: Pilar, Marta, Harol, Víctor y Ana (todas categoría Peluquería).  
El cliente pregunta sobre diferencias entre servicios de coloración sin especificar cuál quiere reservar.

**Conversación:**  
- Cliente: Hola, quiero un cambio de color pero no sé si elegir óleos o barro gol, ¿cuál me recomiendas?  
- Bot: ¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es Laura?  
  _Acción interna: Como es la primera vez que escribe, Maite se presenta y confirma el nombre que aparece en WhatsApp antes de continuar._  
- Cliente: Sí, soy Laura.  
- Bot: Genial, Laura 💕. El **óleo pigmento** (34€, 30 min) es una coloración semi-permanente con aceites nutritivos que protege y da brillo intenso, ideal para refrescar el color sin dañar la fibra capilar. El **barro gold** (48€, 40 min) es una mascarilla purificante con minerales que elimina impurezas y aporta nutrición profunda, perfecto para cabellos más exigentes que buscan un tratamiento intensivo.  
  _Acción interna: El sistema consulta la hoja *Servicios* y recupera las descripciones completas de OLEO PIGMENTO (ID:1) y BARRO GOLD (ID:15) con sus precios y duraciones exactas._  
- Bot: ¿Quieres que reserve una **consulta gratuita de 15 minutos** antes del servicio para que mi compañera te asesore en persona sobre cuál se adapta mejor a tu cabello?  
  _Acción interna: El sistema identifica que es una consulta técnica de producto y ofrece automáticamente la consulta gratuita sin anticipo._  
- Cliente: Sí, prefiero la consulta primero.  
- Bot: Perfecto, Laura. ¿Qué día te viene mejor esta semana para la consulta?  
  _Acción interna: El sistema espera que el cliente indique preferencia de día antes de consultar Google Calendar._  
- Cliente: El jueves por la mañana.  
- Bot: El jueves por la mañana tenemos libre a las 10:00 con mi compañera Marta y a las 11:30 con mi compañera Ana. ¿Cuál prefieres?  
  _Acción interna: Consulta de agendas de profesionales de categoría "Peluquería" y selección de dos opciones próximas en el rango horario solicitado._  
- Cliente: 10:00.  
- Bot: Genial. Para dejar la consulta registrada a tu nombre, ¿me confirmas tus apellidos, Laura?  
  _Acción interna: El sistema necesita completar el registro del cliente nuevo con apellidos._  
- Cliente: Martínez.  
- Bot: Perfecto, Laura **Martínez**. Tu consulta gratuita queda confirmada para el **jueves a las 10:00** con mi compañera Marta (15 minutos). ¡Te esperamos! 🌸  
  _Acción interna: Se crea un evento en Google Calendar de 15 minutos con estado "confirmado" sin anticipo, ya que las consultas gratuitas tienen el campo `requiere_anticipo=False` en la base de datos. Se registra el cliente con nombre completo, teléfono y se inicia su historial._  

**Resultado esperado:**  
Consulta gratuita creada para el jueves a las 10:00 con Marta, duración 15 minutos, cliente Laura Martínez registrado. Sin anticipo requerido.

---

## Simulación 9

**Escenario:** Cliente recurrente recibe recordatorio automático de cita.

**Contexto inicial:**  
El cliente se llama Carmen. Ya está registrado en la base de datos como cliente recurrente.  
Tiene una cita confirmada de MANICURA PERMANENTE+BIOTERAPIA (90 min, 40.7€) el jueves a las 16:00 con Rosa (Estética).  
En la base de datos consta que pagó anticipo de 8.14€ (20% de 40.7€) hace 5 días.  
El sistema ejecuta recordatorio automático 48 horas antes de la cita.

**Conversación (mensaje automático):**  
- Bot: ¡Hola, Carmen! 🌸 Te recordamos tu cita de **manicura permanente + bioterapia** este **jueves a las 16:00** con mi compañera Rosa (duración: 90 minutos). Recuerda que si necesitas cancelar debe ser con al menos **24 horas de antelación** para no perder tu anticipo de 8.14€ 💕.  
  _Acción interna: El sistema ejecuta un cron job que revisa en Google Calendar todas las citas confirmadas que ocurren en exactamente 48 horas. Para cada cita, recupera de la base de datos: nombre del cliente, teléfono, servicio, profesional asignado, hora, duración y monto del anticipo pagado. Envía mensaje automático por WhatsApp._  
- Cliente: ¡Perfecto, gracias por recordarlo!  
- Bot: ¡A ti, Carmen! Nos vemos el jueves 😊.  
  _Acción interna: El sistema registra la confirmación del cliente en la base de datos, actualizando el campo `recordatorio_confirmado=True` en la tabla de citas._  

**Resultado esperado:**  
El cliente recibe recordatorio automatizado 48h antes con todos los datos de su cita. Sistema registra la confirmación del cliente para métricas internas.

---

## Simulación 10

**Escenario:** Cliente que quiere encadenar servicios largos.

**Contexto inicial:**  
El cliente se llama Patricia. Es cliente recurrente (ya está en la base de datos).  
Pide: BARRO GOLD (40 min, 48€) + AGUA LLUVIA (25 min, 20€) + PEINADO LARGO (45 min, 22.5€).  
Duración total calculada: 110 minutos (1h 50min).  
En la hoja *Asistentas*, todas las profesionales de categoría "Peluquería" están disponibles.  
En Google Calendar hay un hueco el viernes de 9:30 a 11:30 con Marta.

**Conversación:**  
- Cliente: Quiero barro gol, más un tratamiento agua de lluvia y peinado largo, ¿puedo el viernes por la mañana?  
- Bot: ¡Hola de nuevo, Patricia! Soy Maite 🌸. Claro, reviso disponibilidad 💫. Ese conjunto de servicios dura aproximadamente **1 hora y 50 minutos** (barro gold 40 min + agua lluvia 25 min + peinado largo 45 min). El precio total es de **90.5€**.  
  _Acción interna: El sistema consulta la hoja *Servicios* y suma las duraciones individuales: BARRO GOLD (40 min, 48€) + AGUA LLUVIA (25 min, 20€) + PEINADO LARGO (45 min, 22.5€) = 110 min y 90.5€. Como Patricia es cliente recurrente, se omite el protocolo de confirmación de nombre._  
- Bot: El viernes tengo hueco de **9:30 a 11:30** con mi compañera Marta. ¿Quieres que reserve todo junto?  
  _Acción interna: El sistema consulta Google Calendar buscando bloques continuos de al menos 110 minutos en el rango "mañana" (antes de 14:00) del viernes. Detecta disponibilidad de Marta de 9:30 a 12:00 (150 min disponibles), suficiente para los 110 min requeridos._  
- Cliente: Sí, perfecto.  
- Bot: Genial, Patricia. Para confirmar tu cita necesito un anticipo de **18.1€** (20% del total de 90.5€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: El sistema calcula el 20% de 90.5€ = 18.1€, genera el enlace de pago en Stripe con metadatos (ID_cliente, servicios solicitados, profesional, fecha/hora). Se crea un bloqueo provisional en Google Calendar de 110 minutos (9:30 a 11:20) con estado "pendiente de pago" y timeout de 30 minutos._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Patricia! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **viernes de 9:30 a 11:20** con mi compañera Marta, para: barro gold + agua lluvia + peinado largo. ¡Te esperamos! 💇‍♀️  
  _Acción interna: El sistema valida el webhook de Stripe, convierte el bloqueo provisional en cita definitiva de 110 minutos (9:30-11:20), actualiza el historial del cliente sumando 90.5€ a su gasto total, y notifica a Marta por email/calendario._  

**Resultado esperado:**  
Cita creada para 3 servicios encadenados el viernes 9:30-11:20 con Marta, duración total 110 minutos, cliente Patricia, anticipo 18.1€ confirmado. Historial actualizado.

---

## Simulación 11

**Escenario:** Cliente que llega tarde a su cita.

**Contexto inicial:**  
El cliente se llama Andrés. Es cliente recurrente.  
Tiene una cita confirmada de CORTE CABALLERO (40 min, 17.5€) hoy a las 17:00 con Víctor (Peluquería).  
Son las 17:10 y avisa que llegará en 20 minutos (17:30 aprox.).  
En Google Calendar, Víctor tiene otra cita inmediatamente después a las 17:40.

**Conversación:**  
- Cliente: Voy tarde, llego en 20 min.  
- Bot: Hola, Andrés 🌸. Te esperamos, aunque al llegar con retraso de 30 minutos quizá tengamos que ajustar la duración de tu servicio para no retrasar a los siguientes clientes de mi compañero Víctor. ¿Quieres que lo confirme con él para ver si es posible?  
  _Acción interna: El sistema detecta que es cliente recurrente y omite presentación. Calcula el retraso: hora actual 17:10, llegada estimada 17:30, inicio programado 17:00 = 30 min de retraso. Consulta Google Calendar y detecta que Víctor tiene cita a las 17:40 (solo 10 min de margen tras el retraso). Marca la cita como "retraso notificado" y activa alerta para derivar a humano si el cliente confirma._  
- Cliente: Sí, por favor.  
- Bot: Perfecto, Andrés. Voy a comunicarlo ahora mismo con mi compañero Víctor para que pueda atenderte lo mejor posible. En breve te confirmo 💕.  
  _Acción interna: El sistema deriva la conversación al equipo con los datos: "Cliente: Andrés, Cita: 17:00 CORTE CABALLERO con Víctor, Retraso: 30 min, Siguiente cita Víctor: 17:40". Se notifica al profesional por mensaje interno._  

**Resultado esperado:**  
La cita no se cancela automáticamente. El caso se deriva al equipo/profesional con datos del retraso para que gestionen manualmente si ajustan el servicio o reprograman.

---

## Simulación 12

**Escenario:** Cliente que pide cita para alguien más.

**Contexto inicial:**  
El cliente se llama Roberto. Es cliente recurrente (ya está en la base de datos).  
Quiere reservar BIOTERAPIA FACIAL (60 min, 57.5€, Estética) para su madre el lunes.  
En la hoja *Asistentas*, solo Rosa tiene categoría "Estética".  
En Google Calendar, Rosa tiene disponibilidad el lunes a las 11:00 y 16:00.

**Conversación:**  
- Cliente: Quiero reservar un tratamiento de bioterapia facial para mi madre el lunes.  
- Bot: ¡Hola de nuevo, Roberto! Soy Maite 🌸. ¡Qué bonito detalle! 💕 ¿Me indicas el nombre completo de tu madre para registrar su cita correctamente en el calendario?  
  _Acción interna: Como Roberto es cliente recurrente, se omite presentación. El sistema identifica que la cita es para un tercero y solicita nombre completo para crear/actualizar el perfil del nuevo cliente._  
- Cliente: María González.  
- Bot: Gracias, Roberto. El lunes tenemos libre a las **11:00** y a las **16:00** con mi compañera Rosa para la bioterapia facial (60 minutos, 57.5€). ¿Cuál hora prefieres para tu madre?  
  _Acción interna: El sistema consulta Google Calendar filtrando por categoría "Estética" (solo Rosa disponible). Detecta huecos de al menos 60 minutos el lunes y ofrece dos opciones._  
- Cliente: A las 11:00.  
- Bot: Perfecto. Para confirmar la cita de **María González** necesito un anticipo de **11.5€** (20% de 57.5€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: El sistema busca en la base de datos si existe "María González". Como no existe, se crea un nuevo registro con: nombre "María González", teléfono vacío (se pedirá después si es necesario), relación con Roberto (campo `referido_por=Roberto_ID`). Se genera enlace de pago y bloqueo provisional de 60 minutos en calendario de Rosa a las 11:00 con estado "pendiente de pago"._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Roberto! 🎉 Hemos recibido el anticipo. La cita de **María González** queda confirmada para el **lunes a las 11:00** con mi compañera Rosa, para bioterapia facial (60 minutos). ¡La esperamos! 🌸  
  _Acción interna: El sistema valida el pago, convierte el bloqueo en cita definitiva, actualiza el historial de María (primera cita) y el de Roberto (agregando nota "reservó para tercero: María González")._  

**Resultado esperado:**  
Cita creada a nombre de María González el lunes 11:00 con Rosa, duración 60 minutos. Anticipo 11.5€ pagado por Roberto. Ambos perfiles actualizados en base de datos.

---

## Simulación 13

**Escenario:** Consulta sobre precios de estética.

**Contexto inicial:**  
Es la primera vez que Lucía escribe por WhatsApp.  
En la metadata aparece su número y el nombre "Lucía" (coincide con su nombre real).  
En la hoja *Servicios* aparecen: CEJAS (15 min, 7€, Estética) y MANICURA PERMANENTE+BIOTERAPIA (90 min, 40.7€, Estética).  
El cliente pregunta precios sin indicar intención de reserva inmediata.

**Conversación:**  
- Cliente: ¿Cuánto cuesta la depilación de cejas y la manicura?  
- Bot: ¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas si tu nombre es Lucía?  
  _Acción interna: Como es la primera vez que escribe, Maite se presenta y confirma el nombre que aparece en WhatsApp._  
- Cliente: Sí, soy Lucía.  
- Bot: Genial, Lucía 💕. La **depilación de cejas** cuesta **7€** (15 minutos), y la **manicura permanente con bioterapia** cuesta **40.7€** (90 minutos).  
  _Acción interna: El sistema consulta la hoja *Servicios* buscando por palabras clave: "cejas" encuentra CEJAS (ID:48), y "manicura" encuentra MANICURA PERMANENTE+BIOTERAPIA (ID:50). Recupera precios y duraciones exactas._  
- Bot: ¿Quieres que reserve una cita para hacer ambos servicios el mismo día?  
  _Acción interna: El sistema detecta que aún no hay intención explícita de reserva, pero hace una oferta proactiva de cierre para convertir la consulta en cita._  
- Cliente: Sí, ¿tienes para el jueves?  
- Bot: El jueves tenemos libre a las **10:00** y a las **15:30** con mi compañera Rosa para depilación de cejas + manicura permanente con bioterapia (duración total: 105 minutos, precio total: 47.7€). ¿Cuál hora prefieres?  
  _Acción interna: El sistema suma duraciones: 15 min + 90 min = 105 min. Suma precios: 7€ + 40.7€ = 47.7€. Consulta Google Calendar filtrando por categoría "Estética" (solo Rosa disponible) buscando bloques de al menos 105 minutos el jueves. Ofrece dos opciones._  
- Cliente: 10:00.  
- Bot: Perfecto. Para dejar la reserva bien a tu nombre, ¿me confirmas tus apellidos, Lucía?  
  _Acción interna: Como es cliente nuevo, se debe completar el registro con apellidos._  
- Cliente: Fernández.  
- Bot: Gracias, Lucía **Fernández**. Para confirmar tu cita necesito un anticipo de **9.54€** (20% del total de 47.7€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: Se registra el nombre completo. Se calcula anticipo 20% de 47.7€ = 9.54€, se genera enlace de pago y se crea bloqueo provisional de 105 minutos (10:00-11:45) en calendario de Rosa con estado "pendiente de pago"._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Lucía! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **jueves a las 10:00** con mi compañera Rosa, para depilación de cejas + manicura permanente con bioterapia (105 minutos). ¡Te esperamos! 🌸  
  _Acción interna: Se valida el pago, convierte el bloqueo en cita definitiva, registra el cliente nuevo con historial inicial (gasto total: 47.7€, primera cita)._  

**Resultado esperado:**  
Cita creada para 2 servicios combinados el jueves 10:00-11:45 con Rosa, cliente Lucía Fernández registrado, anticipo 9.54€ confirmado.

---

## Simulación 14

**Escenario:** Cliente que intenta cancelar fuera de plazo.

**Contexto inicial:**  
El cliente se llama Lucía. Es cliente recurrente.  
Tiene una cita confirmada mañana (viernes) a las 10:00 de CORTAR (40 min, 26.2€) con Ana (Peluquería).  
Pagó anticipo de 5.24€ (20% de 26.2€) hace 3 días.  
Son las 22:00 del jueves (menos de 24h antes de la cita, política de cancelación no permite devolución).

**Conversación:**  
- Cliente: No puedo ir mañana, cancélame.  
- Bot: Hola, Lucía 🌸. Entiendo tu situación. Como faltan menos de 24 horas para tu cita de mañana viernes a las 10:00 con mi compañera Ana, nuestra política indica que **no se puede devolver el anticipo de 5.24€** en cancelaciones con menos de 24h de antelación.  
  _Acción interna: El sistema detecta que es cliente recurrente (omite presentación). Calcula diferencia entre hora actual (jueves 22:00) y hora de cita (viernes 10:00) = 12 horas < 24h. Consulta en la base de datos la política de cancelación y el monto del anticipo pagado._  
- Bot: Si quieres, te ofrezco **reprogramar tu cita para otra fecha** y ese anticipo se mantendría para la nueva reserva 💕. ¿Te gustaría reprogramarla?  
  _Acción interna: El sistema ofrece alternativa de reprogramación sin perder el anticipo, incentivando retención del cliente._  
- Cliente: Sí, mejor reprogramar para la otra semana.  
- Bot: Perfecto, Lucía. ¿Qué día te viene mejor la próxima semana?  
  _Acción interna: El sistema mantiene el estado de la cita original como "pendiente de reprogramación" y no libera el bloqueo en calendario hasta confirmar nueva fecha._  
- Cliente: El miércoles por la mañana.  
- Bot: El miércoles por la mañana tenemos libre a las **10:30** con mi compañera Ana y a las **11:30** con mi compañera Marta. ¿Cuál prefieres?  
  _Acción interna: Consulta Google Calendar filtrando por categoría "Peluquería" buscando huecos de 40 minutos el miércoles en rango "mañana". Ofrece dos opciones, priorizando a Ana (misma profesional de la cita original)._  
- Cliente: 10:30 con Ana.  
- Bot: ¡Listo, Lucía! He reprogramado tu cita para el **miércoles a las 10:30** con mi compañera Ana, para corte (40 minutos). Tu anticipo de 5.24€ se mantiene para esta nueva reserva. ¡Nos vemos el miércoles! 😊  
  _Acción interna: El sistema cancela el bloqueo del viernes 10:00 liberando el calendario de Ana. Crea nueva cita definitiva el miércoles 10:30 con Ana por 40 minutos, vinculando el anticipo ya pagado (sin generar nuevo pago). Actualiza el historial del cliente registrando "reprogramación fuera de plazo"._  

**Resultado esperado:**  
Cita original cancelada, nueva cita creada para miércoles 10:30 con Ana. Anticipo transferido sin pérdida. Cliente retenido.

---

## Simulación 15

**Escenario:** Cliente que quiere varios servicios pero no sabe tiempos.

**Contexto inicial:**  
El cliente se llama Fernando. Es cliente recurrente.  
Pregunta por CORTAR (40 min, 26.2€) + CULTURA DE COLOR (50 min, 43€) + SECADO (5 min, 8.2€).  
Duración total: 95 minutos. Precio total: 77.4€.  
En Google Calendar hay disponibilidad el martes con Marta.

**Conversación:**  
- Cliente: ¿Cuánto dura corte + color óleo + secado?  
- Bot: ¡Hola de nuevo, Fernando! Soy Maite 🌸. Ese conjunto de servicios dura aproximadamente **1 hora y 35 minutos** (corte 40 min + cultura de color 50 min + secado 5 min). El precio total es de **77.4€**. ¿Quieres que busque un hueco con esa duración para esta semana?  
  _Acción interna: El sistema identifica que Fernando es cliente recurrente (omite presentación). Consulta la hoja *Servicios* y detecta: CORTAR (40 min, 26.2€), CULTURA DE COLOR (50 min, 43€), SECADO (5 min, 8.2€). Suma duraciones y precios automáticamente._  
- Cliente: Sí, ¿tienes el martes?  
- Bot: El martes tenemos libre de **10:00 a 11:40** con mi compañera Marta para tu corte + cultura de color + secado. ¿Quieres que lo reserve?  
  _Acción interna: Consulta Google Calendar filtrando por categoría "Peluquería" buscando bloques continuos de al menos 95 minutos el martes. Detecta disponibilidad de Marta de 10:00 a 12:00 (120 min disponibles), suficiente para los 95 min requeridos._  
- Cliente: Perfecto.  
- Bot: Genial, Fernando. Para confirmar tu cita necesito un anticipo de **15.48€** (20% del total de 77.4€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: Calcula anticipo 20% de 77.4€ = 15.48€, genera enlace de pago y crea bloqueo provisional de 95 minutos (10:00-11:35) en calendario de Marta con estado "pendiente de pago"._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Fernando! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **martes de 10:00 a 11:35** con mi compañera Marta, para corte + cultura de color + secado. ¡Te esperamos! 💇‍♂️  
  _Acción interna: Valida el pago, convierte el bloqueo en cita definitiva, actualiza el historial de Fernando sumando 77.4€ a su gasto total._  

**Resultado esperado:**  
Cita creada para 3 servicios combinados el martes 10:00-11:35 con Marta, cliente Fernando, anticipo 15.48€ confirmado. Historial actualizado.

---

## Simulación 16

**Escenario:** Cliente frecuente que pide "lo de siempre".

**Contexto inicial:**  
El cliente se llama Raquel. Es cliente recurrente con historial extenso en la base de datos.  
Su última cita fue hace 1 mes: CORTAR (40 min, 26.2€) + INFOACTIVO SENSITIVO (30 min, 20.9€) con Pilar.  
En la base de datos consta preferencia de profesional: Pilar (categoría Peluquería).  
En Google Calendar, Pilar tiene disponibilidad el jueves a las 11:00 y 16:00.

**Conversación:**  
- Cliente: Ponme lo de siempre para el jueves.  
- Bot: ¡Hola, Raquel! Soy Maite 🌸. Claro, la última vez te hiciste **corte + infoactivo sensitivo** con mi compañera Pilar (duración total: 70 minutos, precio: 47.1€). ¿Quieres que reserve lo mismo para el jueves?  
  _Acción interna: El sistema identifica que Raquel es cliente recurrente y consulta su historial en la base de datos. Recupera la última cita: servicios CORTAR + INFOACTIVO SENSITIVO, profesional Pilar, suma duración 40+30=70 min y precio 26.2+20.9=47.1€._  
- Cliente: Sí, perfecto.  
- Bot: Genial. El jueves tengo libre a las **11:00** y a las **16:00** con mi compañera Pilar para tu corte + infoactivo sensitivo (70 minutos). ¿Cuál hora prefieres?  
  _Acción interna: Consulta Google Calendar específicamente en la agenda de Pilar (preferencia detectada en base de datos) buscando bloques de 70 minutos el jueves. Ofrece dos opciones._  
- Cliente: 11:00.  
- Bot: Perfecto, Raquel. Para confirmar tu cita necesito un anticipo de **9.42€** (20% del total de 47.1€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: Calcula anticipo 20% de 47.1€ = 9.42€, genera enlace de pago y crea bloqueo provisional de 70 minutos (11:00-12:10) en calendario de Pilar con estado "pendiente de pago"._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Raquel! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **jueves de 11:00 a 12:10** con mi compañera Pilar, para corte + infoactivo sensitivo. ¡Te esperamos! 💕  
  _Acción interna: Valida el pago, convierte el bloqueo en cita definitiva, actualiza el historial de Raquel sumando 47.1€ a su gasto total y refuerza la preferencia por Pilar._  

**Resultado esperado:**  
Cita creada replicando última combinación de servicios el jueves 11:00-12:10 con Pilar (profesional preferida), cliente Raquel, anticipo 9.42€ confirmado. Preferencia reforzada en base de datos.

---

## Simulación 17

**Escenario:** Cliente que consulta horarios especiales (puentes o festivos).

**Contexto inicial:**  
Es la primera vez que Sofía escribe por WhatsApp.  
En la metadata aparece su número y un nombre extraño "✨Sof✨" (no es fiable).  
Pregunta sobre apertura el lunes 12 de octubre (festivo nacional en España, bloqueado en Google Calendar como evento).  
El martes 13 de octubre está abierto con horario normal.

**Conversación:**  
- Cliente: ¿Abrís el lunes festivo?  
- Bot: ¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. Encantada de saludarte. ¿Me confirmas tu nombre para dirigirme a ti correctamente?  
  _Acción interna: Como es la primera vez que escribe y el nombre en metadata no es fiable ("✨Sof✨"), se solicita confirmación de nombre real._  
- Cliente: Me llamo Sofía.  
- Bot: Gracias, Sofía 💕. Ese lunes estaremos **cerrados por ser festivo** 🕊. Pero el martes abrimos con horario normal desde las 10:00. ¿Quieres que te busque hueco ese día?  
  _Acción interna: El sistema consulta Google Calendar y detecta que el lunes 12 de octubre está bloqueado con evento "Festivo - Cerrado". Verifica disponibilidad del día siguiente (martes 13)._  
- Cliente: Sí, el martes por la mañana.  
- Bot: Perfecto. ¿Qué servicio te gustaría reservar, Sofía?  
  _Acción interna: El sistema espera que el cliente especifique el servicio antes de consultar disponibilidad específica._  
- Cliente: Un corte.  
- Bot: Genial. El martes por la mañana tenemos libre a las **10:30** con mi compañera Ana y a las **11:30** con mi compañero Harol para corte (40 minutos, 26.2€). ¿Cuál prefieres?  
  _Acción interna: Consulta Google Calendar filtrando por categoría "Peluquería" buscando huecos de 40 minutos (duración de CORTAR) el martes en rango "mañana". Ofrece dos opciones._  
- Cliente: 10:30 con Ana.  
- Bot: Perfecto. Para dejar la reserva bien a tu nombre, ¿me confirmas tus apellidos, Sofía?  
  _Acción interna: Como es cliente nuevo, se debe completar el registro con apellidos._  
- Cliente: Ruiz.  
- Bot: Gracias, Sofía **Ruiz**. Para confirmar tu cita necesito un anticipo de **5.24€** (20% de 26.2€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe].  
  _Acción interna: Se registra el nombre completo, calcula anticipo, genera enlace de pago y crea bloqueo provisional de 40 minutos (10:30-11:10) en calendario de Ana con estado "pendiente de pago"._  
- **Trigger Interno del pago:** Se recibe correctamente el pago.  
- Bot: ¡Perfecto, Sofía! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para el **martes a las 10:30** con mi compañera Ana, para corte (40 minutos). ¡Te esperamos! 🌸  
  _Acción interna: Valida el pago, convierte el bloqueo en cita definitiva, registra el cliente nuevo con historial inicial._  

**Resultado esperado:**  
Cliente informado sobre cierre festivo. Cita creada para martes 10:30 con Ana, cliente Sofía Ruiz registrado, anticipo 5.24€ confirmado.

---

## Simulación 18

**Escenario:** Cliente pide cita urgente para el mismo día.

**Contexto inicial:**  
El cliente se llama Marta. Es cliente recurrente.  
Son las 13:00 del jueves y pregunta si puede cortarse el pelo hoy mismo.  
En la hoja *Servicios*: CORTAR (40 min, 26.2€).  
En Google Calendar hay disponibilidad hoy jueves: Ana tiene libre a las 16:30 y Víctor a las 18:00.

**Conversación:**  
- Cliente: ¿Puedo cortarme el pelo hoy mismo?  
- Bot: ¡Hola, Marta! Soy Maite 🌸. Hoy mismo tengo un hueco a las **16:30** con mi compañera Ana y otro a las **18:00** con mi compañero Víctor para corte (40 minutos, 26.2€). ¿Quieres que reserve uno de esos para ti?  
  _Acción interna: El sistema detecta que Marta es cliente recurrente (omite presentación). Calcula hora actual (13:00) y busca en Google Calendar huecos disponibles de 40 minutos (duración de CORTAR) para hoy jueves con al menos 1 hora de anticipación (para dar tiempo al pago y traslado). Filtra por categoría "Peluquería" y ofrece las dos opciones más próximas._  
- Cliente: 16:30 con Ana.  
- Bot: Perfecto, Marta. Para confirmar tu cita necesito un anticipo de **5.24€** (20% de 26.2€). Aquí tienes tu enlace de pago 👉 [Enlace de Stripe]. **Importante:** Como es para hoy, necesito que completes el pago en los próximos **15 minutos** para asegurar tu reserva 🕐.  
  _Acción interna: Calcula anticipo, genera enlace de pago y crea bloqueo provisional de 40 minutos (16:30-17:10) en calendario de Ana con estado "pendiente de pago" y timeout reducido de 15 minutos (en lugar de los 30 minutos habituales) debido a la urgencia de la cita del mismo día._  
- **Trigger Interno del pago:** Se recibe correctamente el pago a las 13:08.  
- Bot: ¡Perfecto, Marta! 🎉 Hemos recibido tu anticipo. Tu cita queda confirmada para **hoy a las 16:30** con mi compañera Ana, para corte (40 minutos). ¡Te esperamos en 3 horas! 💇‍♀️  
  _Acción interna: Valida el pago, convierte el bloqueo en cita definitiva, actualiza el historial de Marta y notifica a Ana urgentemente por email/SMS sobre la cita de última hora._  

**Resultado esperado:**  
Cita urgente creada para hoy 16:30 con Ana, cliente Marta, anticipo 5.24€ confirmado. Timeout de pago reducido a 15 minutos. Profesional notificado.

---