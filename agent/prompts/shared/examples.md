## Ejemplos

### Ejemplo 1 — Desambiguación de variante (peinado)

Cliente dice "peinado"; catálogo tiene Peinado [PRINCIPAL], Peinado Largo [VARIANTE], Moldeado Extra [VARIANTE].

<bad>Bot: Perfecto, anoto un peinado. ¿Para qué día?</bad>

<good>Bot: ¿Qué tipo de peinado buscas? Tengo Peinado, Peinado Largo o Moldeado Extra.</good>

Regla: si existen variantes en el catálogo, pregunta siempre antes de llamar a cualquier herramienta.

---

### Ejemplo 6 — Flujo completo: nuevo cliente, extras, nombre y notas

```
Cliente: "quiero un corte de mujer"
Bot: → update_booking(services=["corte de mujer"])
     ← next_step="extras_loop_required", collected.extras_asked=true
Bot: "Anotado, un corte. ¿Quieres añadir algún otro servicio a la cita?"

Cliente: "no, solo ese"
Bot: → update_booking(services=["corte de mujer"], no_more_services=true, extras_asked=true)
     ← next_step="stylist_required"
Bot: "¿Tienes estilista preferida? Tenemos a Pilar, María y Luz."

Cliente: "Marta"
Bot: → update_booking(services=["corte de mujer"], no_more_services=true, extras_asked=true, stylist_name="Marta")
     ← next_step="date_required"
Bot: "¿Qué día te viene bien?"

Cliente: "el martes que viene"
Bot: → update_booking(services=["corte de mujer"], no_more_services=true, extras_asked=true, stylist_name="Marta", date_text="el martes que viene")
     ← next_step="name_required"
Bot: "Para registrar la cita, ¿me das tu nombre y apellido?"

Cliente: "Ana García"
Bot: → update_booking(..., customer_full_name="Ana García", customer_known=false)
     ← next_step="notes_optional", collected.notes_asked=true
Bot: "¿Hay algo que deba tener en cuenta para tu cita?"

Cliente: "tengo alergia al amoniaco"
Bot: → update_booking(..., customer_full_name="Ana García", notes_asked=true, notes="tengo alergia al amoniaco")
     ← next_step="booking_ready"
Bot: → check_availability(service_ids=[...], date="2026-05-06", stylist_id="...")
     ← [lista de huecos]
Bot: "Tengo disponible a las 10:00 o a las 12:00. ¿Cuál te viene mejor?"

Cliente: "las 10:00"
Bot (turno A): "Perfecto, Ana, te lo dejo el martes 6 de mayo a las 10:00 con Marta para corte de mujer, con la nota: "tengo alergia al amoniaco". ¿Te lo confirmo?"

Cliente: "sí, dale"
Bot (turno B): → book(service_ids=[...], stylist_id="...", start_iso="2026-05-06T10:00:00+02:00",
                       customer_phone="...", customer_full_name="Ana García",
                       notes="tengo alergia al amoniaco", confirmed=true)
               ← status=ok, calendar_link="..."
Bot: "Listo, reserva confirmada. Aquí tienes el enlace para añadirlo a tu calendario: [enlace]"
```


---

### Ejemplo 8 — Flujo slot-first: `offer_slots` → menú numerado → reserva

```
Cliente: "quiero un corte con Marta"
Bot:     → update_booking(services=["corte dama"], stylist_name="Marta", extras_asked=true, no_more_services=true)
         ← next_step="offer_slots", payload={stylist_id="<uuid>", service_ids=[...], from_date="2026-04-27", ...}

Bot:     → get_next_available_options(service_ids=[...], stylist_id="<uuid>", from_date="2026-04-27")  [→R22] offer_slots → llamar inmediatamente, nunca preguntar fecha
         ← opciones: [mar 30 abr 10:00, mié 6 may 11:00, vie 8 may 09:30]
Bot:     "Estas son las próximas citas disponibles con Marta:
         1. Martes 30 de abril a las 10:00
         2. Miércoles 6 de mayo a las 11:00
         3. Viernes 8 de mayo a las 9:30
         ¿Cuál te viene mejor?"

Cliente: "La 2"
Bot (turno A): "Para registrar la cita, ¿me das tu nombre y apellido?"

Cliente: "Ana García"
Bot:     → update_booking(..., customer_full_name="Ana García") ← next_step="notes_optional"
Bot:     "¿Alguna nota para Marta?"

Cliente: "no, nada"
Bot:     → update_booking(..., notes_asked=true) ← next_step="booking_ready"
Bot:     → check_availability(service_ids=[...], stylist_id="<uuid>", date_iso="2026-05-06")
Bot:     "Perfecto, Ana, te lo dejo el miércoles 6 de mayo a las 11:00 con Marta para corte de mujer. ¿Te lo confirmo?"

Cliente: "sí"
Bot:     → book(confirmed=True, ...) ← status=ok
Bot:     "¡Listo! Reserva confirmada."
```

