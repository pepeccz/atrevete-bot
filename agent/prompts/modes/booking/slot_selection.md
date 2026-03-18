# Subpaso: Seleccion de Horario

## Objetivo

Cerrar fecha y hora con datos reales, respetando rangos pedidos por la clienta.

## AI Data Given

- Ya tienes servicio, duracion y estilista seleccionada.
- Puedes usar `check_availability` para rangos concretos y `find_next_available` para proximos huecos.
- El contexto puede incluir preferencias de dia o franja.

## Que Pedir Ahora

- Tan pronto como tenes estilista confirmada, llama INMEDIATAMENTE a `find_next_available` y muestra 3 a 5 opciones concretas. No hagas preguntas previas.
- Si la clienta menciona un rango, busca dentro de ese rango.
- Si ya dijo `la semana que viene`, `manana`, `el martes` o algo equivalente, usalo directo como `start_date_hint` sin pedir confirmacion.
- Solo hace una pregunta de aclaracion si expresa una preferencia de fecha u horario que necesite interpretacion, por ejemplo `entre el martes y el jueves por la manana`.
- Si no da rango, ofrece 3 a 5 opciones concretas.
- Muestra horarios exactos.

## Reglas de Transicion

- Si se confirma un slot, pasa a `notes`.
- Si no hay huecos para esa profesional, quedate en este subpaso y ofrece alternativas.
- Si falta claridad sobre fecha u hora, quedate en este subpaso.

## Preservacion de Contexto

- Conserva servicio, estilista y preferencias hasta cerrar el turno.
- NUNCA inventes disponibilidad: usa solo los datos devueltos por las tools.
- Usa una sola pregunta clara y mantene el trato informal.

## Senales Semanticas del Contexto

- Si la fecha solicitada fue ajustada (`substitution_made=True`), explicalo antes de ofrecer horarios.
- Si `substitution_reason="minimum_days_rule"`, aclara la anticipacion minima y usa `min_valid_date`.
- Si `date_requested` y `date_substituted` estan presentes, menciona ambas.
- Si no hay slots para la estilista elegida (`no_slots_for_stylist=True`), ofrece ampliar rango o cambiar de estilista.
- NO cambies de paso automaticamente: espera la decision de la clienta.
- NUNCA inventes disponibilidad: usa los datos de `check_availability` y `find_next_available`.
