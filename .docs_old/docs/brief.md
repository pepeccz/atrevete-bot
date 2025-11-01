# Project Brief: Atrévete Bot

**Sistema de IA Conversacional para Atrévete Peluquería**

---

## Executive Summary

**Atrévete Bot** es un sistema de IA conversacional diseñado para automatizar la atención al cliente de Atrévete Peluquería vía WhatsApp, gestionando reservas de citas, consultas de servicios y derivación inteligente al equipo humano cuando sea necesario.

**Problema Principal:** El salón de belleza necesita atender consultas y gestionar reservas 24/7, pero el equipo humano tiene capacidad limitada. Las reservas manuales generan fricción (ida y vuelta de mensajes, confirmaciones de pago, recordatorios) y consumen tiempo valioso que las asistentas podrían dedicar a servicios.

**Mercado Objetivo:** Atrévete Peluquería (salón único con 5 asistentas: Pilar, Marta, Rosa, Harol y Víctor) y sus clientes actuales y potenciales que prefieren comunicarse vía WhatsApp.

**Propuesta de Valor Clave:** Automatización inteligente que replica la experiencia cálida de "Maite" (asistenta virtual) para gestionar todo el ciclo de reserva (consulta → disponibilidad → pago → confirmación → recordatorios), liberando al equipo para enfocarse en servicios mientras mejora la experiencia del cliente con respuestas inmediatas y disponibilidad 24/7.

---

## Problem Statement

### Current State and Pain Points

Actualmente, Atrévete Peluquería gestiona reservas y consultas de manera manual a través de WhatsApp. Este proceso implica:

- **Múltiples intercambios de mensajes** para confirmar disponibilidad, servicios, precios y horarios
- **Gestión manual de pagos anticipados** (20% del total) enviando enlaces de Stripe y esperando confirmación
- **Coordinación manual de calendarios** de 5 asistentas con diferentes especialidades (Peluquería/Estética)
- **Envío manual de recordatorios** 48 horas antes de cada cita
- **Atención limitada a horario laboral**, perdiendo potenciales clientes que consultan fuera de ese horario
- **Cancelaciones y reprogramaciones** que requieren intervención humana constante

### Impact of the Problem

**Cuantificable:**
- Tiempo estimado: **15-20 minutos por reserva** (desde consulta inicial hasta confirmación de pago)
- **Carga operativa** en horarios pico cuando el equipo debería enfocarse en atender clientes presentes
- **Pérdida de conversión** por consultas fuera de horario (estimado 20-30% de mensajes entrantes no atendidos inmediatamente)

**Cualitativo:**
- Fricción en experiencia del cliente (esperas, múltiples mensajes)
- Estrés operativo del equipo manejando interrupciones constantes
- Falta de consistencia en información (diferentes asistentas pueden dar respuestas distintas)

### Why Existing Solutions Fall Short

- **Sistemas de reserva online tradicionales** requieren que clientes salgan de WhatsApp (su canal preferido)
- **Chatbots simples con reglas** no pueden manejar la complejidad conversacional (consultas médicas, indecisión sobre servicios, casos edge)
- **Gestión manual** no escala y tiene límite de horario

### Urgency and Importance

**Momento crítico:** El salón está funcionando a capacidad operativa. Cada hora invertida en gestión administrativa es una hora menos de servicios. La automatización inteligente es necesaria **ahora** para:
- Capturar la demanda fuera de horario laboral
- Liberar tiempo del equipo para enfocarse en calidad de servicio
- Escalar operaciones sin aumentar headcount administrativo

---

## Proposed Solution

### Core Concept and Approach

**Atrévete Bot** es un agente de IA conversacional basado en LangChain + Anthropic Claude que actúa como "Maite", la asistenta virtual del salón. El sistema utiliza una arquitectura de **1 Agente Principal + Herramientas especializadas** que permite:

- **Razonamiento conversacional inteligente** para manejar consultas complejas, ambigüedad y toma de decisiones contextuales
- **Herramientas deterministas** para operaciones técnicas (Google Calendar API, Stripe API, base de datos PostgreSQL)
- **Memoria conversacional híbrida** (Redis) que mantiene contexto de conversaciones para experiencia personalizada
- **Derivación inteligente** al equipo humano cuando detecta casos que requieren intervención (consultas médicas, problemas de pago, situaciones complejas)

El agente cubre **18 escenarios conversacionales** documentados que van desde reservas estándar hasta casos edge como cancelaciones fuera de plazo, retrasos, reservas grupales y consultas sobre servicios.

### Key Differentiators from Existing Solutions

1. **IA Conversacional vs Chatbot de Reglas:** Maite razona y adapta respuestas en lugar de seguir árboles de decisión rígidos
2. **Integración Nativa con WhatsApp:** El cliente nunca sale de su canal preferido (vía Chatwoot)
3. **Gestión Completa del Ciclo de Reserva:** Desde consulta inicial hasta recordatorio automático 48h antes, incluyendo pagos anticipados
4. **Personalización y Memoria:** Reconoce clientes recurrentes, recuerda "lo de siempre", detecta preferencias
5. **Derivación Inteligente:** No intenta resolver todo, sabe cuándo escalar al equipo humano
6. **Multi-calendario:** Gestiona disponibilidad de 5 asistentas con especialidades diferentes

### Why This Solution Will Succeed

**Factores de éxito:**

- **Principio de Simplicidad (KISS):** Arquitectura probada (PostgreSQL + Redis + Docker) sin sobre-ingeniería
- **Stack Maduro:** LangChain + Claude + Google Calendar + Stripe son tecnologías estables y documentadas
- **Testing Exhaustivo:** Cobertura completa de 18 escenarios (unitarios + integración + manuales) antes de producción
- **Scope Realista:** Enfocado en UN salón con necesidades bien definidas (no intenta resolver múltiples negocios)
- **Razonamiento sobre Reglas:** El agente puede manejar casos imprevistos que romperían un sistema de reglas rígidas

**Donde otros fallan:**
- Chatbots simples no pueden manejar la **complejidad conversacional** (indecisión, consultas sobre diferencias entre servicios, casos edge)
- Sistemas de reserva online tradicionales **rompen el flujo de WhatsApp** y pierden clientes
- Soluciones manuales **no escalan** y tienen límite de horario

### High-Level Vision for the Product

**MVP (Sistema Básico Funcional):**
- Atención conversacional 24/7 vía WhatsApp
- Gestión completa de ciclo de reserva (18 escenarios)
- Integración con Google Calendar (5 asistentas)
- Pagos anticipados vía Stripe
- Recordatorios automáticos
- Derivación inteligente al equipo humano

**Post-MVP (Future Innovations):**
- Dashboard de métricas operativas
- Notificaciones push a asistentas
- Analytics de preferencias de clientes (ML)
- Sistema multi-centro (expansión a otros salones)

**Long-term Vision (Moonshots):**
- Agente de voz para atender llamadas telefónicas
- Marketplace de servicios (múltiples salones)
- Plataforma SaaS para industria de belleza

---

## Target Users

### Primary User Segment: Clientes de Atrévete Peluquería

**Demographic Profile:**
- **Edad:** 18-65 años (predominantemente 25-50)
- **Género:** Mayoritariamente femenino, también masculino (servicios de barbería)
- **Ubicación:** Local/regional (zona de influencia del salón)
- **Tecnología:** Usuarios activos de WhatsApp (canal de comunicación preferido)
- **Comportamiento:** Combinación de clientes recurrentes (70%) y nuevos clientes (30%)

**Current Behaviors and Workflows:**
- **Canal Principal:** WhatsApp para consultas y reservas
- **Patrón de Reserva:**
  - Clientes recurrentes: "Lo de siempre" (último servicio recibido)
  - Nuevos clientes: Consultan precios, disponibilidad, diferencias entre servicios
- **Planificación:** Reservan con 2-7 días de anticipación (algunos buscan slots del mismo día)
- **Horarios de Consulta:** Muchas consultas fuera de horario laboral (noches, fines de semana)
- **Expectativas:** Respuestas rápidas, trato personalizado, proceso simple

**Specific Needs and Pain Points:**
- **Inmediatez:** Quieren respuesta instantánea sobre disponibilidad y precios
- **Conveniencia:** No quieren salir de WhatsApp para completar reserva
- **Claridad:** Necesitan entender diferencias entre servicios (ej: óleo vs barro gold)
- **Flexibilidad:** Requieren cambios/cancelaciones con proceso simple
- **Confianza:** Necesitan confirmación clara de su reserva y recordatorios

**Goals They're Trying to Achieve:**
- Reservar cita de manera rápida y sin fricción
- Obtener el servicio deseado con la asistenta preferida (si tienen preferencia)
- Entender opciones y recibir asesoramiento sobre servicios
- Gestionar cambios en su agenda sin complicaciones

### Secondary User Segment: Equipo de Atrévete Peluquería (Asistentas)

**Profile:**
- **Roles:** 5 asistentas (Pilar, Marta, Rosa, Harol, Víctor)
- **Especialidades:** Peluquería (4) y Estética (1)
- **Ubicación:** Presencial en el salón

**Current Behaviors and Workflows:**
- **Gestión Manual:** Actualmente responden WhatsApp entre servicios
- **Interrupciones Constantes:** Consultas llegan mientras atienden clientes presentes
- **Coordinación de Agenda:** Cada asistenta gestiona su Google Calendar
- **Multitasking:** Divididas entre atención presencial y gestión de consultas remotas

**Specific Needs and Pain Points:**
- **Reducir Interrupciones:** Enfocarse en clientes presentes sin perder consultas entrantes
- **Eficiencia:** Eliminar tiempo en ida-y-vuelta de mensajes para reservas
- **Visibilidad:** Saber cuándo tienen citas próximas sin revisar WhatsApp constantemente
- **Intervención Solo Cuando Necesario:** Ser notificadas solo en casos que requieren atención humana

**Goals They're Trying to Achieve:**
- Maximizar tiempo dedicado a servicios (su core expertise)
- Mantener sus calendarios actualizados automáticamente
- Intervenir solo en casos complejos (consultas médicas, problemas especiales)
- Recibir notificaciones claras de nuevas citas y cambios

---

## Goals & Success Metrics

### Business Objectives

- **Reducir tiempo operativo en gestión de reservas en 80%** (de ~15-20 min a ~3-4 min por reserva que requiera intervención humana)
- **Aumentar tasa de conversión de consultas a citas en 25%** capturando demanda fuera de horario laboral
- **Liberar 10-15 horas semanales del equipo** actualmente dedicadas a gestión administrativa para enfocarse en servicios
- **Mantener o mejorar satisfacción del cliente** (medir pre/post implementación) con respuesta instantánea 24/7
- **Reducir no-shows en 30%** mediante recordatorios automáticos 48h antes de cada cita

### User Success Metrics

**Para Clientes:**
- **Tiempo de respuesta < 5 segundos** para consultas estándar
- **Tasa de completación de reserva > 85%** (de consulta inicial a pago confirmado sin abandonar)
- **NPS (Net Promoter Score) ≥ 8/10** para experiencia de reserva vía bot
- **Tasa de re-reserva de clientes recurrentes ≥ 70%** (indicador de satisfacción continua)

**Para Asistentas:**
- **Reducción de interrupciones durante servicios en 70%** (menos notificaciones de WhatsApp)
- **Satisfacción del equipo con el sistema ≥ 8/10** (encuesta interna trimestral)
- **Tasa de derivación al equipo < 15%** de conversaciones totales (indicador de efectividad del bot)

### Key Performance Indicators (KPIs)

- **Tasa de Automatización:** % de conversaciones resueltas completamente por el bot sin intervención humana. **Target: ≥ 85%**
- **Tiempo Promedio de Reserva:** Desde primer mensaje hasta confirmación de pago. **Target: ≤ 5 minutos**
- **Conversión Fuera de Horario:** % de consultas fuera de horario que resultan en cita confirmada. **Target: ≥ 60%** (vs 0% actual)
- **Precisión de Derivación:** % de casos derivados que efectivamente requerían intervención humana. **Target: ≥ 90%** (evitar falsos positivos)
- **Disponibilidad del Sistema (Uptime):** **Target: ≥ 99.5%** (máximo 3.6 horas de downtime mensual)
- **Tasa de Cancelación Fuera de Plazo:** % de cancelaciones con <24h que el sistema gestiona correctamente ofreciendo reprogramación. **Target: ≥ 70% retención**

---

## MVP Scope

### Core Features (Must Have)

- **Atención Conversacional Inteligente:** Agente "Maite" con personalidad cálida que maneja los 18 escenarios conversacionales documentados, desde reservas estándar hasta casos edge (cancelaciones, retrasos, indecisión, consultas complejas). Razona cuándo derivar al equipo humano en lugar de seguir reglas rígidas.

- **Gestión Completa del Ciclo de Reserva:**
  - Confirmar identidad del cliente (nuevo vs recurrente)
  - Consultar disponibilidad en Google Calendar de 5 asistentas
  - Calcular precios y duraciones para servicios individuales o combinados
  - Sugerir packs rentables cuando el cliente menciona servicio incluido
  - Ofrecer consultoría gratuita (10 min, 0€) cuando cliente está indeciso
  - Gestionar bloqueos provisionales (15-30 min) durante proceso de pago
  - Generar enlaces de pago en Stripe (20% anticipo)
  - Confirmar reserva tras validación de pago vía webhook

- **Integración con Google Calendar (Multi-Asistenta):**
  - 1 calendario por asistenta (Pilar, Marta, Rosa, Harol, Víctor)
  - Crear, modificar y cancelar eventos respetando horarios laborales
  - Filtrar por categoría (Peluquería/Estética) según servicio solicitado
  - Detectar y prevenir overbooking

- **Gestión de Cancelaciones y Cambios:**
  - Cancelación con >24h: Devolución automática de anticipo
  - Cancelación con <24h: Ofrecer reprogramación sin perder anticipo
  - Modificación de citas manteniendo misma asistenta cuando sea posible
  - Gestión de retrasos del cliente (avisar a asistenta, evaluar viabilidad)

- **Sistema de Recordatorios Automáticos:**
  - Envío 48 horas antes de cada cita vía WhatsApp
  - Incluye: servicio, asistenta, hora, duración, monto de anticipo pagado
  - Recordatorio de política de cancelación (24h de anticipación)

- **Memoria Conversacional Híbrida:**
  - Ventana de últimos N mensajes recientes (contexto inmediato)
  - Resumen histórico de conversación comprimido (contexto amplio)
  - Historial de cliente: servicios previos, preferencias de asistenta, "lo de siempre"

- **Base de Datos Completa:**
  - PostgreSQL con tablas: Clientes, Asistentas, Servicios, Packs, Citas, Políticas, ConversationHistory
  - Admin básico Django/Flask para gestionar políticas, servicios, packs, horarios (sin interfaz fancy)

- **Herramientas Organizadas por Dominio:**
  - CalendarTools: Operaciones con Google Calendar
  - PaymentTools: Stripe (generar enlaces, validar webhooks, calcular anticipos)
  - CustomerTools: CRUD clientes, buscar historial, detectar preferencias
  - BookingTools: Lógica de reservas, bloqueos provisionales, cálculos
  - NotificationTools: WhatsApp (vía Chatwoot API), notificaciones a asistentas

- **Derivación Inteligente al Equipo Humano:**
  - El agente razona cuándo derivar (no reglas hardcodeadas)
  - Casos típicos: consultas médicas, problemas de pago tras 2 intentos, retrasos que impactan agenda, ambigüedad no resuelta
  - Incluye resumen de conversación para contexto del equipo
  - Notificación a grupo de WhatsApp del equipo vía Chatwoot

- **Infraestructura Docker con 3 Contenedores:**
  - API REST (recibe webhooks Chatwoot/Stripe)
  - Agente IA + Workers (orquestador + tareas asíncronas)
  - PostgreSQL + Redis (datos + memoria/cola)

### Out of Scope for MVP

- Dashboard de métricas operativas (post-MVP)
- Notificaciones push móviles a asistentas (post-MVP)
- Analytics avanzado con ML para detectar patrones de clientes (post-MVP)
- Interfaz gráfica mejorada para admin (post-MVP)
- Sistema multi-centro (moonshot)
- Agente de voz para llamadas telefónicas (moonshot)
- Marketplace de servicios (moonshot)
- Sincronización bidireccional avanzada de estados con Chatwoot (post-MVP)
- App móvil dedicada para asistentas (post-MVP)
- Integración con sistemas de contabilidad (fuera de scope)
- Gestión de inventario de productos (fuera de scope)

### MVP Success Criteria

El MVP será considerado exitoso si:

1. **Cobertura de Escenarios:** Maneja correctamente los 18 escenarios conversacionales documentados en tests de integración
2. **Tasa de Automatización:** ≥ 70% de conversaciones resueltas sin intervención humana (target MVP conservador, objetivo final 85%)
3. **Estabilidad:** Sistema corre sin crashes críticos durante 1 semana de testing en staging con Chatwoot real
4. **Precisión de Derivación:** ≥ 80% de casos derivados efectivamente requerían intervención humana
5. **Performance:** Tiempo de respuesta del bot < 10 segundos en el 95% de los casos
6. **Validación del Equipo:** Las 5 asistentas aprueban el sistema tras 2 semanas de uso en producción (satisfacción ≥ 7/10)
7. **Validación de Clientes:** Al menos 20 reservas completadas exitosamente end-to-end sin intervención humana

---

## Post-MVP Vision

### Phase 2 Features (Post-MVP - 2-6 semanas después del lanzamiento)

**Dashboard de Métricas Operativas** (2-3 semanas):
- Visualización de tasa de conversión (consultas → citas confirmadas)
- Tasa de derivación humana y razones principales
- Servicios más solicitados y horarios pico de consultas
- Gráficos de ocupación por asistenta
- Ingresos generados vía bot vs manual

**Mejoras en Gestión de Estados de Conversación** (1-2 semanas):
- Sincronización bidireccional con estados Chatwoot (open/resolved)
- Auto-cierre de conversaciones tras confirmación de cita
- Re-apertura automática si cliente responde después

**Sistema de Notificaciones Push a Asistentas** (4-6 semanas):
- App móvil PWA o integración con Telegram/Signal
- Notificaciones en tiempo real de nuevas citas, cambios, cancelaciones
- Badge de "requiere atención" para casos derivados

**Analytics de Preferencias de Clientes** (3-4 semanas):
- Modelo ML simple (clustering, reglas de asociación) para detectar:
  - Horarios preferidos por cliente
  - Servicios frecuentes
  - Profesional favorita
- Uso de insights para sugerencias proactivas ("Veo que sueles reservar los martes a las 10:00, ¿quieres ese horario?")

**Interfaz Gráfica Mejorada para Admin** (4-5 semanas):
- Dashboard moderno con calendario visual
- Drag & drop para mover citas manualmente
- Vista de ocupación por asistenta en tiempo real
- Edición de políticas, servicios y packs sin tocar BD directamente

### Long-Term Vision (6-12 meses)

**Expansión Multi-Centro:**
- Arquitectura multi-tenant para soportar múltiples salones (Atrévete Madrid, Barcelona, etc.)
- Gestión centralizada de datos con aislamiento por centro
- Configuración personalizada por salón (horarios, políticas, servicios)
- Panel de control para franquicia o cadena

**Inteligencia Aumentada:**
- Detección proactiva de oportunidades (cliente no ha visitado en 2 meses → mensaje automático)
- Sugerencias inteligentes basadas en historial ("Hace 6 semanas te hiciste mechas, ¿quieres reservar retoque?")
- Predicción de demanda para optimizar calendarios

**Mejoras en Experiencia de Usuario:**
- Galería de fotos de resultados (antes/después) compartibles desde el bot
- Sistema de reviews y testimonios integrado
- Programa de fidelización automatizado (descuentos tras X servicios)

### Expansion Opportunities

**Vertical: Industria de Belleza**
- Convertir solución single-tenant en plataforma SaaS multi-tenant
- Onboarding automatizado para nuevos salones
- Marketplace de templates de servicios/packs por especialidad
- Modelo de negocio B2B2C con comisiones o suscripción mensual

**Horizontal: Otros Servicios con Citas**
- Clínicas médicas/dentales
- Spas y centros de bienestar
- Estudios de yoga/fitness
- Servicios profesionales (abogados, contadores, consultores)

**Tecnológico: Multicanal**
- **Agente de Voz (Voice AI):** Extensión para atender llamadas telefónicas con misma lógica conversacional (STT/TTS, integración Twilio)
- **Integración con redes sociales:** Instagram DMs, Facebook Messenger
- **Web widget:** Chat embebido en sitio web del salón

**Geográfico:**
- Expansión a mercados LATAM con adaptaciones culturales/lingüísticas
- Integración con métodos de pago regionales (Mercado Pago, etc.)

---

## Technical Considerations

### Platform Requirements

- **Target Platforms:** Linux-based server environment (Docker-compatible)
- **Browser/OS Support:** N/A (backend service, interfaz vía WhatsApp en mobile/web del cliente)
- **Performance Requirements:**
  - Tiempo de respuesta del bot: < 5 segundos para consultas estándar
  - Tiempo de respuesta del bot: < 10 segundos para operaciones complejas (búsqueda en múltiples calendarios, cálculos)
  - Uptime objetivo: ≥ 99.5% (máximo 3.6 horas downtime mensual)
  - Capacidad de manejo: 100 conversaciones concurrentes sin degradación

### Technology Preferences

**Frontend:**
- Admin básico: Django Admin o Flask-Admin (HTML generado, sin framework JS moderno necesario para MVP)
- Post-MVP: React o Vue para dashboard mejorado

**Backend:**
- **Framework API:** FastAPI 0.116+ (Python) - async nativo, webhooks, type hints con Pydantic, Trust Score 9.9
- **Agente IA:** **LangGraph 0.6+ + LangChain** para orquestación stateful de 18 escenarios conversacionales
  - **LangGraph:** Gestión de flujos multi-paso, persistencia automática (checkpointing), human-in-the-loop, recuperación ante fallos
  - **LangChain:** Tools especializadas (Calendar, Payment, Customer, Booking, Notification) y abstracciones LLM
  - **Justificación arquitectural:** Los 18 escenarios requieren bifurcaciones condicionales complejas, memoria híbrida, derivación inteligente y timeouts — funcionalidad nativa en LangGraph vs ~1,500-2,000 líneas custom con LangChain puro
- **LLM:** Anthropic Claude (Sonnet 4 o Opus según presupuesto) vía SDK oficial Python 0.40+
- **Worker Async:** Redis Pub/Sub + Python asyncio para tareas background (pagos, recordatorios, timeouts)

**Database:**
- **PostgreSQL 15+** (datos persistentes: clientes, asistentas, servicios, packs, citas, políticas)
- **Redis 7+** (memoria conversacional híbrida + cola de mensajes asíncronos)

**Hosting/Infrastructure:**
- **Docker Compose** para desarrollo y staging
- **Docker Swarm o Kubernetes (opcional)** para producción si se requiere alta disponibilidad
- **VPS o Cloud:** DigitalOcean, AWS EC2, Google Cloud Compute Engine (preferencia por simplicidad de pricing vs serverless)
- **Backup:** Automated daily PostgreSQL backups con retención de 30 días

### Architecture Considerations

**Repository Structure:**
```
atrevete-bot/
├── api/                 # FastAPI webhooks (Chatwoot, Stripe)
├── agent/               # LangGraph + LangChain + Claude
│   ├── graphs/          # StateGraph definitions (conversation_flow.py, escalation_flow.py)
│   ├── state/           # TypedDict state schemas (ConversationState, BookingContext)
│   ├── tools/           # CalendarTools, PaymentTools, CustomerTools, BookingTools, NotificationTools
│   ├── nodes/           # Graph node functions (identify_customer, check_availability, handle_payment)
│   └── prompts/         # System prompt de "Maite" + contexto del negocio
├── database/            # Modelos SQLAlchemy, migraciones Alembic
├── docker/              # Dockerfiles + docker-compose.yml
├── tests/               # Tests unitarios + integración (18 escenarios)
└── docs/                # Documentación, escenarios, brainstorming, tech-analysis.md
```

**Service Architecture:**
- **Contenedor 1 (API):** FastAPI recibiendo webhooks, encolando mensajes en Redis
- **Contenedor 2 (LangGraph Agent + Workers):**
  - **LangGraph StateGraph Orchestrator:** Gestiona flujo de 18 escenarios como grafo de nodos
    - Nodos: `identify_customer`, `load_memories`, `check_availability`, `suggest_packs`, `handle_payment`, `escalate_to_human`, etc.
    - Conditional edges para bifurcaciones dinámicas (indecisión, timeouts, errores)
    - Checkpointing automático en Redis (InMemoryStore) para persistencia conversacional
  - **Tools:** CalendarTools, PaymentTools, CustomerTools, BookingTools, NotificationTools (LangChain)
  - **Workers asyncio:** Recordatorios (cron 48h), timeouts de pago (25 min, 30 min), cleanup de bloqueos
- **Contenedor 3 (Data):** PostgreSQL + Redis (pueden separarse en producción)
  - **Redis:** Hot state (checkpoints conversacionales), pub/sub (colas mensajes)
  - **PostgreSQL:** Cold storage (historial clientes, preferencias, citas, políticas)

**Integration Requirements:**
- **Google Calendar API:** Service account con permisos sobre calendarios de 5 asistentas
- **Stripe API:** Webhooks para confirmación de pagos, generación de Payment Links
- **Chatwoot API:** Envío de mensajes a conversaciones, gestión de estados (open/resolved)
- **WhatsApp Business API (vía Chatwoot):** Canal de comunicación con clientes

**Security/Compliance:**
- **Secrets Management:** Variables de entorno (.env) o Docker secrets para API keys sensibles (Claude, Stripe, Google)
- **HTTPS:** Obligatorio para webhooks (Stripe requiere HTTPS)
- **GDPR Considerations:** Almacenamiento de datos personales (nombre, teléfono) - incluir política de privacidad y opción de eliminación de datos
- **PCI Compliance:** Stripe maneja datos de pago (no almacenamos tarjetas), solo guardamos confirmation tokens
- **Rate Limiting:** Protección contra spam de mensajes (max 10 mensajes/min por cliente)
- **Webhook Validation:** Verificación de signatures de Stripe y Chatwoot para prevenir ataques

---

## Constraints & Assumptions

### Constraints

**Budget:**
- **Infraestructura:** VPS/Cloud hosting estimado ~$50-100/mes (DigitalOcean Droplet 4GB RAM + almacenamiento)
- **APIs:**
  - Anthropic Claude API: ~$30-50/mes (volumen validado: 5-10 agendamientos/día ≈ 15-30 conversaciones/día)
  - Google Calendar API: Gratuito (límites generosos de 1M requests/día)
  - Stripe: 2.9% + $0.30 por transacción (costo transferido al negocio, no desarrollo)
  - Chatwoot: Self-hosted gratuito o Cloud ~$20/mes
- **Total estimado MVP:** $100-170/mes operativo + desarrollo one-time

**Timeline:**
- **Presión de tiempo:** Desarrollo ajustado, requiere entregar sistema funcional completo (18 escenarios)
- **Target:** 3-4 semanas para MVP funcional:
  - Semana 1: Infraestructura base + API webhooks
  - Semana 2-3: Agente + Tools + integración
  - Semana 4: Testing exhaustivo (18 escenarios) + fixes
- **Post-MVP:** Iteraciones posteriores tras validación en producción

**Resources:**
- **Equipo de desarrollo:** 1 desarrollador full-stack (tú)
- **Stakeholders:** 5 asistentas + gerente del salón para validación
- **Tiempo de validación:** 2 semanas en producción con asistentas antes de considerar MVP exitoso

**Technical:**
- **Dependencia de APIs externas:** Google Calendar, Stripe, Anthropic Claude (riesgo de outages o cambios de pricing)
- **Infraestructura inicial:** Docker Compose (no Kubernetes) para simplicidad
- **Single point of failure:** Si Redis cae, se pierde memoria conversacional activa (mitigable con persistencia RDB)
- **WhatsApp limitado a Chatwoot:** No acceso directo a WhatsApp Business API (depende de integración Chatwoot)

### Key Assumptions

- **Clientes prefieren WhatsApp** como canal de comunicación sobre web/apps nativas - validar con datos históricos de consultas
- **Volumen validado:** **5-10 agendamientos/día** (≈ 15-30 conversaciones totales/día incluyendo consultas sin conversión)
- **18 escenarios cubren 90%+ de casos reales** - los escenarios documentados representan la mayoría de situaciones
- **Asistentas tienen Google Calendar** configurado y lo usan actualmente para gestionar citas
- **Sistema de anticipos (20%) es NUEVO** para clientes del salón - requiere monitoreo especial de adopción y posible fricción
- **Claude API mantiene pricing actual** o similar durante al menos 12 meses (riesgo: cambios drásticos en costo/token)
- **Chatwoot self-hosted es suficiente** para volumen del salón - no requiere plan enterprise
- **Internet estable en salón** para que asistentas reciban notificaciones y gestionen derivaciones
- **Datos de Servicios/Packs están actualizados** en Google Sheets u otro formato - migración manual a PostgreSQL será realizada antes del deploy
- **Todas las asistentas trabajan en horario del salón**, pero pueden tener **descansos individuales** (días off) configurados en sus calendarios
- **Festivos y días cerrados** se gestionan mediante eventos en Google Calendar con antelación
- **No existe historial previo de clientes** - se creará desde cero con el sistema
- **Stripe gestiona todos los métodos de pago** (tarjeta, Bizum, etc.) - no se requieren integraciones adicionales
- **No existen servicios "bajo consulta"** - todos tienen precio fijo. Ante confusión del cliente, se deriva
- **Regla crítica:** **No se pueden mezclar servicios de categorías Peluquería + Estética** en una misma cita
- **Razonamiento del agente con Claude es suficientemente preciso** para derivación inteligente - no requiere fine-tuning inicial

---

## Risks & Open Questions

### Key Risks

- **Dependencia de APIs de Terceros:** Si Google Calendar, Stripe o Anthropic Claude tienen outages o cambios de pricing significativos, el sistema se ve afectado. **Impacto: Alto. Probabilidad: Media.** Mitigación: Monitoreo de status pages, tener presupuesto buffer del 30% para cambios de pricing.

- **Precisión de Derivación del Agente:** Si el agente deriva demasiado (falsos positivos), satura al equipo humano. Si deriva muy poco (falsos negativos), clientes tienen mala experiencia. **Impacto: Alto. Probabilidad: Media.** Mitigación: Testing exhaustivo de 18 escenarios, ajuste iterativo del prompt de derivación basado en data real de primeras semanas.

- **Adopción del Sistema de Anticipos (NUEVO):** El sistema de anticipos del 20% es nuevo para los clientes. Puede generar fricción o resistencia inicial. **Impacto: Alto. Probabilidad: Media.** Mitigación: Comunicación clara sobre política de devolución (>24h), explicación del beneficio (asegura reserva), monitoreo de tasa de abandono en pago.

- **Rechazo de Clientes al Bot:** Algunos clientes pueden preferir interacción humana y rechazar hablar con "Maite". **Impacto: Medio. Probabilidad: Baja-Media.** Mitigación: Personalidad cálida del bot, opción siempre disponible de "hablar con el equipo", validación temprana con clientes beta.

- **Overbooking por Concurrencia:** Dos clientes intentan reservar la misma franja casi simultáneamente (race condition). **Impacto: Alto. Probabilidad: Baja.** Mitigación: Bloqueos provisionales con timeout, transacciones atómicas en BD, tests de concurrencia.

- **Migración de Datos Incompleta/Incorrecta:** Si la migración manual de Sheets → PostgreSQL tiene errores (precios incorrectos, duraciones mal calculadas), el bot da información errónea. **Impacto: Alto. Probabilidad: Media.** Mitigación: Script de validación de datos migrados, revisión manual por gerente antes de go-live.

- **Gestión de Descansos Individuales por Asistenta:** Aunque todas trabajan en horario del salón, los descansos pueden variar por asistenta (ej: Pilar descansa martes, Marta miércoles). Si no se configura correctamente en Google Calendar, se pueden agendar citas en días no disponibles. **Impacto: Medio. Probabilidad: Media.** Mitigación: Configuración clara de eventos "bloqueados" en Google Calendar individual de cada asistenta, validación de disponibilidad antes de ofrecer slots.

- **Spam o Abuso del Sistema:** Clientes maliciosos envían mensajes masivos o intentan reservar y cancelar repetidamente. **Impacto: Medio. Probabilidad: Baja.** Mitigación: Rate limiting (10 mensajes/min por cliente), detección de patrones abusivos en roadmap post-MVP.

- **Costo de Claude API Supera Presupuesto:** Si volumen de conversaciones es mayor al estimado o pricing cambia. **Impacto: Medio. Probabilidad: Baja** (volumen validado: 5-10 agendamientos/día = ~15-30 conversaciones/día). Mitigación: Monitoreo de costos diarios, cache de respuestas comunes, considerar modelos más económicos (Claude Haiku) para casos simples.

### Open Questions (RESUELTAS)

✅ **Volumen real de consultas/reservas:** **5-10 agendamientos/día** (estimado ~15-30 conversaciones totales/día incluyendo consultas sin conversión)

✅ **Anticipos:** Sistema de **20% anticipo es NUEVO** - requiere monitoreo especial de adopción y fricción

✅ **Horarios de asistentas:** **Todas trabajan horario del salón**, pero pueden tener **descansos individuales** configurados en sus calendarios

✅ **Servicios sin anticipo:** Servicios con **precio = 0€** no requieren anticipo (ej: consultoría gratuita)

✅ **Festivos:** Se gestionan mediante **eventos en Google Calendar** con antelación

✅ **Historial de clientes:** **No existe** - se creará desde cero con el sistema

✅ **Métodos de pago:** **Solo Stripe** (gestiona todos los métodos: tarjeta, Bizum, etc.)

✅ **Timeout de pago:** **Recordatorio a los 25 minutos** (5 min antes del timeout) + liberación automática a los 30 min con mensaje al cliente informando

✅ **Servicios "bajo consulta":** **No existen** - todos tienen precio fijo. Ante confusión del cliente, se delega

✅ **Capacitación admin:** **No requerida para MVP** - puede desarrollarse post-MVP si necesario

✅ **Exclusividad de servicios:** **No hay exclusividad granular** - solo categorías Peluquería/Estética. **Regla crítica:** No se pueden mezclar servicios de ambas categorías en una misma cita

✅ **Clientes que avisan retraso:** Si quedan **<24h, se delega al equipo humano** para gestión manual

✅ **Notificación de derivación:** A **grupo de WhatsApp del equipo** (a crear) vía Chatwoot con resumen de caso

✅ **Gestión del admin:** **Gerente del salón** será responsable de actualizar políticas/servicios/packs

✅ **Grupo de WhatsApp del equipo:** **No existe actualmente** - se creará para notificaciones de derivación (incluir 5 asistentas + gerente)

### Areas Needing Further Research

- **Análisis de Logs de WhatsApp Históricos:** Revisar conversaciones de últimos 3 meses para identificar patrones, casos edge no contemplados en 18 escenarios.

- **Testing de Stripe en Mercado Español:** Validar que Payment Links funcionan correctamente con tarjetas españolas + Bizum, tiempos de confirmación de pago, tasas de abandono.

- **Benchmarking de Costos de Claude API:** Con volumen validado (15-30 conversaciones/día), estimar costo mensual real: ~450-900 conversaciones/mes × costo promedio por conversación.

- **UX de Derivación Humana:** Definir exactamente qué ve el equipo cuando el bot deriva (formato mensaje, resumen de conversación, acciones sugeridas).

- **Estrategia de Rollout:** ¿Go-live completo o soft launch con % de conversaciones? ¿Beta con clientes específicos primero?

- **Backup y Disaster Recovery:** Plan detallado de backups de PostgreSQL, estrategia de recuperación ante fallo catastrófico, RTO/RPO targets.

- **Monitoreo y Observabilidad:** ¿Qué métricas técnicas monitorear en tiempo real? (latencia, errores, rate de derivación) ¿Alertas? ¿Herramientas?
  - **Recomendación:** LangSmith (observabilidad nativa para LangGraph) + logs estructurados
  - Métricas clave: latencia por nodo, tasa de derivación, checkpoints fallidos, timeouts

- **Testing de Adopción de Anticipos:** Validar en primeras 2 semanas tasa de abandono en pago vs tasa de completación. Ajustar messaging si fricción es alta.

- **✅ RESUELTO - Decisión Arquitectural LangGraph:** Ver análisis completo en `docs/tech-analysis.md`
  - **Decisión:** Adoptar LangGraph 0.6+ para orquestación de 18 escenarios
  - **Razón:** Requisitos de estado complejo, bifurcaciones condicionales, human-in-the-loop y recuperación ante fallos hacen que LangGraph sea arquitecturalmente necesario vs ~1,500-2,000 líneas custom
  - **Curva aprendizaje:** ~2 días (compensado por reducción de bugs y time-to-market)

---

## Next Steps

### Immediate Actions

1. **Crear grupo de WhatsApp del equipo** para gestión de derivaciones (incluir las 5 asistentas + gerente). Conectar a Chatwoot para que el bot pueda enviar notificaciones al grupo cuando derive casos.

2. **Validar acceso a Google Calendars de asistentas** - Asegurar que cada una tiene su calendario configurado y que se puede crear service account con permisos de lectura/escritura sobre los 5 calendarios.

3. **Preparar migración de datos Servicios/Packs** - Exportar desde Google Sheets/sistema actual a formato CSV para validación antes de importar a PostgreSQL. Incluir: nombre, categoría (Peluquería/Estética), duración (min), precio (€), requiere_anticipo (bool).

4. **Configurar festivos en Google Calendar** - Asegurar que eventos de "cerrado por festivo" están creados con suficiente antelación (próximos 3-6 meses).

5. **Configurar descansos individuales en Google Calendar** - Cada asistenta debe tener eventos de "descanso" (bloqueados) en su calendario para días no disponibles.

6. **Semana 1 - Infraestructura Base (ACTUALIZADO CON LANGGRAPH):**
   - Instalar dependencias: `langgraph>=0.6.7 langchain>=0.3.0 langchain-anthropic>=0.3.0 anthropic>=0.40.0 fastapi[standard]==0.116.1 redis>=5.0.0 psycopg[binary]>=3.2.0`
   - Crear estructura de proyecto (`/api`, `/agent/graphs`, `/agent/state`, `/agent/nodes`, `/agent/tools`, `/database`, `/docker`)
   - Escribir `docker-compose.yml` con 3 servicios
   - Diseñar esquema SQL completo (7 tablas principales)
   - Crear scripts de migración (`init.sql`)
   - Configurar Redis (checkpointing LangGraph + pub/sub)
   - Validar que los 3 contenedores levantan y se comunican

7. **Semana 1-2 - API Webhook Receiver:**
   - Implementar endpoint POST `/webhook/chatwoot` (parseo JSON, validación Pydantic)
   - Implementar endpoint POST `/webhook/stripe` (validación de pagos)
   - Encolar mensajes en Redis (canal `incoming_messages`)
   - Tests unitarios de parseo y encolado

8. **Semana 2-3 - LangGraph StateGraph Básico (AJUSTADO):**
   - **Día 1-2:** Learning LangGraph (docs oficiales + ejemplos)
   - **Día 3-4:** Definir `ConversationState` TypedDict completo
   - **Día 5-6:** Implementar grafo básico con 3 escenarios:
     - Nodos: `identify_customer`, `load_memories`, `check_availability`, `create_booking`, `send_confirmation`
     - Conditional edges: decisión basada en cliente nuevo/recurrente
     - Checkpointing con MemorySaver (Redis)
   - **Día 7:** Crear 3 tools iniciales: CustomerTools (get/register), CalendarTools (check_availability)
   - **Día 8-10:** Tests de integración simulando Escenario 1 (reserva básica sin pago real)
   - **Validación crítica:** Simular crash mid-conversation → recuperación desde checkpoint

9. **Semana 3 - Completar Tools Restantes:**
   - PaymentTools (Stripe: generar enlaces, validar webhooks, calcular anticipos)
   - BookingTools (lógica de reservas, bloqueos provisionales, cálculos de duración/precio, validación no-mezcla de categorías)
   - NotificationTools (envío a WhatsApp vía Chatwoot, notificación a grupo del equipo)
   - Integrar Google Calendar API completa (crear/modificar/cancelar eventos)

10. **Semana 3-4 - Testing Exhaustivo:**
    - Tests unitarios de cada tool (aislados)
    - Tests de integración de los 18 escenarios conversacionales completos
    - Tests de concurrencia (overbooking, race conditions)
    - Tests de timeout de pago (25 min recordatorio, 30 min liberación)
    - Validación de regla crítica: no-mezcla de servicios Peluquería/Estética

11. **Semana 4 - Staging & Validación:**
    - Deploy en ambiente staging con Chatwoot real
    - Testing manual con asistentas (casos reales simulados)
    - Validación de notificaciones al grupo de WhatsApp del equipo
    - Validación de derivación inteligente (casos médicos, problemas pago, etc.)
    - Ajustes finales basados en feedback del equipo

12. **Semana 4-5 - Soft Launch:**
    - Go-live con monitoreo intensivo
    - Primeras 20 reservas reales (criterio de éxito MVP)
    - Monitoreo especial de tasa de adopción de anticipos (fricción en pago)
    - Ajustes iterativos del prompt de derivación según data real
    - Validación de satisfacción del equipo (≥7/10) tras 2 semanas en producción

### PM Handoff

Este **Project Brief** proporciona el contexto completo para el **Sistema de IA Conversacional - Atrévete Peluquería (Atrévete Bot)**.

**Próximos pasos con PM:**

1. **Revisión del Brief completo** - Validar que todas las secciones reflejan correctamente la visión y objetivos del proyecto
2. **Creación del PRD (Product Requirements Document)** - Expandir este brief en un PRD detallado con:
   - Especificación completa de los 18 escenarios conversacionales
   - User stories derivadas de MVP scope
   - Criterios de aceptación granulares
   - Wireframes/mockups (si aplica para admin básico)
   - Especificación de integrations (Google Calendar, Stripe, Chatwoot)
3. **Creación del Architecture Document** - Diseño técnico detallado incluyendo:
   - Diagrama de arquitectura de 3 contenedores
   - Esquema de base de datos (ER diagram)
   - Especificación de APIs y webhooks
   - Flujos de datos (message flow, payment flow, notification flow)
   - Especificación de cada Tool (inputs, outputs, error handling)
   - Estrategia de testing (fixtures, mocks, escenarios)

**Información Clave para el PM:**

- **Volumen validado:** 5-10 agendamientos/día (~15-30 conversaciones/día)
- **Restricción crítica:** Timeline ajustado (3-4 semanas para MVP funcional completo)
- **Innovación clave:** Consultoría gratuita (10 min, 0€) para clientes indecisos
- **Riesgo principal:** Adopción de sistema de anticipos (nuevo para clientes)
- **Regla técnica crítica:** No mezclar servicios de categorías Peluquería + Estética en misma cita
- **Derivación:** A grupo de WhatsApp del equipo vía Chatwoot cuando el agente detecta casos complejos
- **✅ Decisión arquitectural:** LangGraph 0.6+ adoptado para orquestación stateful (ver `docs/tech-analysis.md`)

**Documentos de Referencia:**
- `/docs/brainstorming-session-results.md` - 47 decisiones arquitectónicas y plan de acción detallado
- `/docs/specs/scenarios.md` - 18 escenarios conversacionales documentados
- `/docs/chatwoot_textmessage.json` - Ejemplo de webhook de Chatwoot
- **`/docs/tech-analysis.md`** - Análisis técnico completo (validación versiones + evaluación LangGraph vs LangChain)

---

## Apéndice: Stack Tecnológico Validado

### Dependencias Python (requirements.txt)

```txt
# Core Framework
fastapi[standard]==0.116.1
uvicorn[standard]>=0.30.0

# LLM & Orchestration (VALIDADO 2025-10-22)
langgraph>=0.6.7              # ← ARQUITECTURALMENTE NECESARIO
langchain>=0.3.0
langchain-anthropic>=0.3.0
anthropic>=0.40.0             # SDK oficial Anthropic

# Database & Cache
psycopg[binary]>=3.2.0        # PostgreSQL async driver
sqlalchemy>=2.0.0
alembic>=1.13.0               # Migraciones DB
redis>=5.0.0

# Integrations
google-api-python-client>=2.150.0  # Google Calendar
google-auth>=2.35.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
stripe>=10.0.0
httpx>=0.27.0                 # HTTP client async

# Utils
pydantic>=2.9.0
python-dotenv>=1.0.0
python-multipart>=0.0.9       # File uploads

# Background Tasks (evaluar vs asyncio puro)
celery>=5.4.0                 # Opcional - para tareas cron complejas

# Development & Testing
pytest>=8.3.0
pytest-asyncio>=0.24.0
pytest-cov>=6.0.0
black>=24.0.0
ruff>=0.7.0
mypy>=1.13.0

# Observability (recomendado)
langsmith>=0.1.0              # LangGraph tracing nativo
```

### Recursos de Aprendizaje LangGraph

**Documentación oficial:**
- Tutorial básico: https://langchain-ai.github.io/langgraph/tutorials/introduction/
- Conceptos clave: https://langchain-ai.github.io/langgraph/concepts/
- How-to guides: https://langchain-ai.github.io/langgraph/how-tos/

**Patrones recomendados para Atrévete Bot:**
- **Supervisor pattern:** Ideal para derivación inteligente al equipo humano
- **Reflexion pattern:** Para auto-corrección del agente (ej: validar disponibilidad antes de confirmar)
- **Human-in-the-loop:** Interrupción controlada para intervención del equipo

**Tiempo estimado de curva de aprendizaje:**
- Conceptos básicos (StateGraph, nodos, edges): 4-6 horas
- Patterns avanzados (conditional routing, checkpointing): 8-12 horas
- **Total: ~2 días** (compensado por reducción de bugs y time-to-market)

---

Por favor, inicia en **'PRD Generation Mode'**, revisa este brief completo y trabaja con el usuario para crear el PRD sección por sección según el template indica, pidiendo cualquier clarificación necesaria o sugiriendo mejoras.
