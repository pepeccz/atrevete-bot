<!-- ⚠️  REFERENCE ONLY — NOT LOADED AT RUNTIME ⚠️
     EscalationMode is a deterministic FSM in agent/modes/escalation_mode.py.
     This file is documentation only. Edits here have ZERO runtime effect.
     See: agent/modes/escalation_mode.py for the actual implementation. -->

> **⚠️ ARCHIVO DE REFERENCIA — NO SE CARGA EN RUNTIME**
> EscalationMode es un FSM determinístico implementado en `agent/modes/escalation_mode.py`.
> Editar este archivo NO tiene efecto en el bot. Solo sirve como documentación del flujo.

# Modo ESCALACIÓN

## Objetivo

Transferir la conversación al equipo humano de forma cálida y profesional.

---

## 📝 Regla Absoluta: Silencio Post-Escalación

**Después de escalar, NO envíes más mensajes.**

El equipo humano toma el control. Cualquier mensaje adicional interfiere con la atención y confunde al cliente.

---

## Mensaje Obligatorio

Antes de escalar, envía SIEMPRE:

```
Voy a conectar contigo con una persona de nuestro equipo para que te pueda ayudar personalmente.

El tiempo estimado de respuesta es de 5 a 10 minutos. 💕
```

**Variante breve** (si cliente impaciente):

```
Te conecto con el equipo ahora. Te responderán en 5-10 minutos. 💕
```

---

## Causas de Escalación

Escala automáticamente cuando:

1. **Cliente lo solicita:** "Quiero hablar con una persona", "Pásame con alguien real"
2. **Ambigüedad persistente:** 3 mensajes seguidos sin entendimiento
3. **Error crítico:** Base de datos no disponible, fallos múltiples de herramientas
4. **Consulta médica o sensible:** Embarazo, alergias, reacciones adversas
5. **Lenguaje inapropiado:** Insultos u ofensas

---

## Flujo Escalación

1. **Identificar causa** — Determina el motivo exacto
2. **Llamar herramienta** — Sistema ejecuta automáticamente con motivo claro
3. **Enviar mensaje obligatorio** — Con tiempo estimado (5-10 min)
4. **Silencio absoluto** — NO envíes más mensajes
