# Brainstorming Session Results

**Session Date:** 2025-10-22
**Facilitator:** Business Analyst Mary 📊
**Participant:** Pepe

---

## Executive Summary

**Topic:** Sistema de IA Conversacional para Atrévete Peluquería

**Session Goals:** Diseñar arquitectura integral de un sistema de atención al cliente automatizado con agentes de IA para gestión de reservas, consultas y derivación inteligente al equipo humano.

**Techniques Used:**
- First Principles Thinking (30 min)
- Morphological Analysis (25 min)
- Assumption Reversal (10 min)

**Total Ideas Generated:** 47 decisiones arquitectónicas y componentes identificados

### Key Themes Identified:

- **Simplicidad sobre complejidad:** Principio KISS aplicado consistentemente (1 agente vs multi-agente, admin básico vs complejo)
- **Escalabilidad pragmática:** PostgreSQL + Redis para crecer sin sobre-ingeniería inicial
- **Separación de responsabilidades:** Herramientas deterministas vs razonamiento de IA claramente delimitados
- **Testing exhaustivo:** Cobertura completa desde unitarios hasta manuales antes de producción
- **Flexibilidad en derivación:** El agente razona cuándo escalar (no reglas rígidas)

---

## Technique Sessions

### First Principles Thinking - 30 min

**Description:** Descomposición del sistema en sus elementos fundamentales para evitar complejidad innecesaria y asegurar que cada componente tiene una razón de existir.

#### Ideas Generated:

1. **3 Responsabilidades CORE identificadas:**
   - Atender mensajes y consultas de clientes/posibles clientes
   - Agendar citas con toda su lógica (disponibilidad, pagos, anticipos, confirmaciones)
   - Derivar inteligentemente al equipo humano cuando corresponda

2. **5 Entidades de datos fundamentales:**
   - Clientes (nombre, apellidos, teléfono, historial, preferencias)
   - Asistentas (nombre, categoría: Peluquería/Estética, calendario asociado)
   - Servicios (nombre, duración, precio, categoría, requiere_anticipo)
   - Packs (nombre, servicios incluidos, precio total, duración total)
   - Citas (cliente, asistenta, servicios/pack, fecha/hora, estado, anticipo)

3. **16 Operaciones críticas identificadas:**
   - Confirmar identidad del cliente
   - Consultar disponibilidad en calendarios
   - Generar enlaces de pago (si anticipo > 0€)
   - Enviar recordatorios y confirmaciones automáticas
   - Crear eventos en calendarios (respetando horarios)
   - Modificar eventos en calendarios (respetando horarios)
   - Delegar conversación a equipo humano
   - Validar webhooks de pago (Stripe)
   - Gestionar bloqueos provisionales con timeout (15-30 min)
   - Cancelar citas con lógica de devolución según plazo
   - Calcular duraciones y precios totales para servicios combinados
   - Sugerir packs rentables cuando corresponda
   - Buscar en historial del cliente ("lo de siempre", preferencias)
   - Consultar políticas del negocio (horarios, festivos, cancelación)
   - Registrar/actualizar clientes nuevos
   - Notificar a asistentas sobre citas asignadas

4. **División clara: Herramientas vs Razonamiento IA:**
   - **12 Herramientas deterministas:** Calendar API, Stripe API, cálculos matemáticos, CRUD BD, schedulers, notificaciones
   - **6 Operaciones con razonamiento:** Confirmación de identidad, sugerencia de packs, búsqueda en historial, cancelación con lógica, derivación humana, gestión conversacional completa

5. **Decisión arquitectónica fundamental:**
   - **1 Agente Principal (Orquestador) + Herramientas** vs arquitectura multi-agente
   - Elegido: **Agente único** por simplicidad y suficiencia para el caso de uso

#### Insights Discovered:

- La complejidad del dominio está en el **razonamiento conversacional**, no en las operaciones técnicas
- Separar claramente "qué requiere IA" vs "qué es determinista" simplifica enormemente la arquitectura
- Un solo negocio con múltiples asistentas NO requiere multi-agente (sería sobre-ingeniería)
- Las 16 operaciones cubren completamente los 18 escenarios sin necesidad de añadir más

#### Notable Connections:

- La **consultoría gratuita de 10 min** emergió naturalmente como servicio especial (duración corta, precio 0€, sin anticipo) durante el análisis de operaciones de sugerencia
- El concepto de "bloqueos provisionales" conecta directamente las operaciones de Calendar + Payment + Timeout management

---

### Morphological Analysis - 25 min

**Description:** Exploración sistemática de opciones viables para cada parámetro arquitectónico clave del sistema, eligiendo la combinación óptima que balancea simplicidad y eficacia.

#### Ideas Generated:

1. **Base de Datos: PostgreSQL + Redis**
   - PostgreSQL para datos persistentes (relaciones complejas entre Clientes, Citas, Servicios, Packs)
   - Redis para caché de memoria conversacional y cola de mensajes asíncronos
   - Justificación: Escalable, robusto, Docker-friendly, balance perfecto

2. **Framework de Agente: LangChain + Anthropic Claude**
   - LangChain para abstracción de tools y gestión de memoria
   - Anthropic Claude como LLM (tool calling nativo)
   - Justificación: Ecosistema maduro, balance entre simplicidad y control, integración con Google Calendar/Stripe ya resuelta

3. **Gestión de Memoria: Sistema Híbrido**
   - Ventana deslizante de últimos N mensajes recientes (contexto inmediato)
   - Resumen de conversación histórica generado por IA (contexto amplio comprimido)
   - Justificación: Maneja tanto conversaciones cortas ("cita el viernes") como largas (indecisión sobre servicios)

4. **Arquitectura de Contenedores: Separación Básica (3 contenedores)**
   - Contenedor 1: API REST (recibe webhooks Chatwoot/Stripe)
   - Contenedor 2: Agente IA + Workers (orquestador + tareas async)
   - Contenedor 3: PostgreSQL + Redis
   - Justificación: Separación suficiente para escalabilidad sin caer en microservicios innecesarios

5. **Comunicación entre Componentes: Híbrida**
   - HTTP/REST para webhooks entrantes (Chatwoot → API, Stripe → API)
   - Redis Pub/Sub para tareas asíncronas (pagos confirmados, recordatorios, timeouts)
   - Comunicación directa API ↔ Agente cuando necesita respuesta inmediata
   - Justificación: Balance entre simplicidad síncrona y robustez asíncrona

6. **Organización de Herramientas: Clases por Dominio**
   - `CalendarTools`: Consultar disponibilidad, crear/modificar eventos, validar horarios
   - `PaymentTools`: Generar enlaces Stripe, validar webhooks, calcular anticipos
   - `CustomerTools`: CRUD clientes, buscar historial, detectar preferencias
   - `BookingTools`: Lógica de reservas, bloqueos provisionales, cálculo precios/duraciones
   - `NotificationTools`: WhatsApp (Chatwoot API), Email, SMS a asistentas
   - Justificación: Organización clara, fácil de testear, extensible

7. **Lógica de Derivación: Razonamiento con IA**
   - El agente evalúa contexto y decide autónomamente cuándo derivar
   - NO reglas hardcodeadas (permite adaptación a casos ambiguos)
   - Justificación: Flexibilidad, capacidad de manejar edge cases no previstos

8. **Gestión de Google Calendar: 1 Calendar por Asistenta**
   - Pilar → calendar_pilar@atrevete.com
   - Marta → calendar_marta@atrevete.com
   - Rosa → calendar_rosa@atrevete.com
   - Harol → calendar_harol@atrevete.com
   - Víctor → calendar_victor@atrevete.com
   - Justificación: Separación natural, cada asistenta gestiona su propio calendario, queries más simples

9. **Políticas y Configuración: PostgreSQL (tabla editable)**
   - Tabla `business_policies` con configuración: horarios, festivos, políticas cancelación, timeouts
   - Editable vía admin básico (sin requiere redeploy ni restart)
   - Justificación: Flexibilidad operativa para el equipo del salón sin dependencia técnica

10. **Testing: Cobertura Completa (Unitarios + Integración + Manuales)**
    - Tests unitarios de cada tool (aislados)
    - Tests de integración simulando los 18 escenarios conversacionales completos
    - Tests manuales con Chatwoot en staging antes de producción
    - Justificación: Confiabilidad crítica (atención directa a clientes), cobertura exhaustiva necesaria

#### Insights Discovered:

- **PostgreSQL + Redis** es una dupla probada y escalable que cubre todas las necesidades sin añadir complejidad
- **3 contenedores** es el sweet spot entre monolito y microservicios para este caso
- Organizar tools por **dominio funcional** (no técnico) facilita razonamiento y mantenimiento
- Permitir que el **agente razone la derivación** (vs reglas rígidas) da mucha más flexibilidad para casos imprevistos

#### Notable Connections:

- La decisión de **1 calendar por asistenta** se conecta directamente con la estructura de la tabla `Asistentas` (campo `calendar_id`)
- El **sistema híbrido de comunicación** permite que el webhook de Chatwoot sea síncrono (respuesta inmediata) mientras pagos y recordatorios son asíncronos
- La **tabla de políticas en BD** se convierte en una tool más (`PolicyTools.get_business_hours()`, `PolicyTools.check_holiday()`)

---

### Assumption Reversal - 10 min

**Description:** Cuestionamiento de asunciones comunes para eliminar complejidad innecesaria y validar decisiones críticas.

#### Ideas Generated:

1. **Asunción revertida: "Necesitamos gestionar todos los casos edge desde día 1"**
   - Decisión: **Cubrir los 18 escenarios completos desde el inicio**
   - Razón: Presión de tiempo en el desarrollo, mejor entregar completo y funcional
   - Insight: A veces MVP iterativo NO es la mejor estrategia cuando hay plazos ajustados

2. **Asunción revertida: "El agente debe hacer upselling agresivo"**
   - Decisión: **Sugerencia inteligente y contextual de packs**
   - Solo ofrece pack si el cliente menciona un servicio que está incluido en un pack
   - Si cliente está indeciso → ofrecer consultoría gratuita (10 min, 0€)
   - Razón: Priorizar experiencia de cliente sobre conversión agresiva
   - Insight: La consultoría gratuita es una **herramienta de conversión más efectiva** que el upselling directo

3. **Asunción revertida: "Necesitamos un panel de administración complejo"**
   - Decisión: **Admin básico Django/Flask**
   - Sin complicaciones visuales innecesarias inicialmente
   - Interfaz bonita solo si realmente la necesitan después
   - Razón: Principio KISS, el equipo puede usar interfaz técnica básica
   - Insight: La funcionalidad > estética en fase inicial

4. **Asunción revertida: "Debemos usar Google Sheets API inicialmente"**
   - Decisión: **Migración manual de Sheets → PostgreSQL**
   - Pepe migrará los datos manualmente antes del despliegue
   - Razón: Evitar dependencia de Sheets, mayor control y rendimiento desde día 1
   - Insight: Migración manual one-time es más simple que integración continua con Sheets

#### Insights Discovered:

- **Simplicidad no significa MVP incompleto** en este caso: los 18 escenarios son "tabla stakes"
- La **consultoría gratuita** emergió como innovación durante el cuestionamiento del upselling
- Admin básico es suficiente: **el equipo del salón no necesita dashboard fancy**, necesita funcionalidad

#### Notable Connections:

- La decisión de **migración manual vs Sheets API** se conecta con la elección de PostgreSQL (datos centralizados y controlados)
- El enfoque de **sugerencia inteligente vs upselling agresivo** refuerza la decisión de que el agente razone (no siga reglas rígidas)

---

## Idea Categorization

### Immediate Opportunities
*Ideas ready to implement now*

1. **Estructura de Docker Compose (3 contenedores)**
   - Description: Definir docker-compose.yml con API, Agente+Workers, PostgreSQL+Redis
   - Why immediate: Base de toda la infraestructura, sin esto no hay desarrollo
   - Resources needed: Docker, docker-compose, conocimiento básico de networking entre contenedores

2. **Esquema de Base de Datos PostgreSQL**
   - Description: Diseñar y crear tablas: Clientes, Asistentas, Servicios, Packs, Citas, Políticas, ConversationHistory
   - Why immediate: Fundamento de todos los datos del sistema, migración manual requiere esquema definido
   - Resources needed: PostgreSQL, SQL, diseño de relaciones (FKs entre tablas)

3. **Setup de Redis**
   - Description: Configurar Redis para memoria conversacional (keys por conversation_id) y cola Pub/Sub (canales: payments, reminders, timeouts)
   - Why immediate: Necesario para memoria del agente y comunicación asíncrona
   - Resources needed: Redis, conocimiento de estructuras de datos (hashes para memoria, pub/sub para colas)

4. **Webhook Receiver API REST básica**
   - Description: Endpoint `/webhook/chatwoot` que recibe POST con mensaje, extrae contenido y conversation_id, encola para procesamiento
   - Why immediate: Punto de entrada del sistema, sin esto no recibe mensajes
   - Resources needed: Flask/FastAPI, conocimiento de webhooks, parsing JSON

5. **Admin básico Django/Flask**
   - Description: CRUD simple para tablas Políticas, Servicios, Packs, Asistentas (sin CSS fancy)
   - Why immediate: Permite al equipo gestionar configuración sin tocar BD directamente
   - Resources needed: Django Admin o Flask-Admin, formularios básicos

### Future Innovations
*Ideas requiring development/research*

1. **Dashboard de Métricas Operativas**
   - Description: Panel con: tasa de conversación (consultas → citas), tasa de derivación humana, servicios más solicitados, horarios pico
   - Development needed: Sistema de analytics, agregación de datos, visualización (Chart.js, Plotly)
   - Timeline estimate: 2-3 semanas post-MVP

2. **Sistema de Notificaciones Push a Asistentas**
   - Description: App móvil o PWA para que asistentas reciban notificaciones en tiempo real de nuevas citas, cambios, cancelaciones
   - Development needed: Backend de notificaciones (Firebase Cloud Messaging), app móvil o PWA
   - Timeline estimate: 4-6 semanas post-MVP

3. **Mejoras en Gestión de Estados de Conversación**
   - Description: Sincronización bidireccional de estados Chatwoot (open/resolved) con estados del sistema, auto-cierre de conversaciones tras confirmación de cita
   - Development needed: Webhooks bidireccionales Chatwoot, lógica de estados, tests
   - Timeline estimate: 1-2 semanas post-MVP

4. **Analytics de Preferencias de Clientes**
   - Description: ML para detectar patrones (horarios preferidos, servicios frecuentes, profesional favorita) y usarlos en sugerencias
   - Development needed: Modelo ML simple (clustering, reglas de asociación), integración con agente
   - Timeline estimate: 3-4 semanas post-MVP

5. **Interfaz Gráfica Mejorada para Admin**
   - Description: Dashboard moderno con calendario visual, drag&drop para mover citas, vista de ocupación por asistenta
   - Development needed: Frontend React/Vue, integración con backend, UX/UI design
   - Timeline estimate: 4-5 semanas post-MVP

### Moonshots
*Ambitious, transformative concepts*

1. **Sistema Multi-Centro**
   - Description: Escalar arquitectura para soportar múltiples salones de belleza (Atrévete Madrid, Atrévete Barcelona, etc.) con gestión centralizada
   - Transformative potential: Convertir solución single-tenant en plataforma SaaS multi-tenant
   - Challenges to overcome: Multi-tenancy en BD, aislamiento de datos, configuración por centro, escalabilidad horizontal

2. **Agente de Voz (Voice AI)**
   - Description: Extensión del sistema para atender llamadas telefónicas con voz sintética, misma lógica conversacional
   - Transformative potential: Cobertura total de canales de comunicación (WhatsApp + voz)
   - Challenges to overcome: Integración con telefonía (Twilio), STT/TTS en español, latencia aceptable

3. **Marketplace de Servicios**
   - Description: Plataforma donde clientes pueden descubrir y reservar servicios en múltiples salones, el sistema actúa como agregador
   - Transformative potential: Cambio de modelo de negocio (B2B2C), network effects
   - Challenges to overcome: Onboarding de salones, comisiones, gestión de múltiples calendarios/pagos

### Insights & Learnings
*Key realizations from the session*

- **Simplicidad es una decisión activa, no pasiva:** Requirió cuestionamiento constante (Assumption Reversal) para evitar sobre-ingeniería
- **La frontera Herramientas/IA es crítica:** Definir claramente qué requiere razonamiento vs qué es determinista simplifica enormemente la arquitectura y reduce costos de LLM
- **1 agente > multi-agente para este caso:** Un solo negocio con múltiples profesionales NO justifica complejidad de orquestación multi-agente
- **Testing exhaustivo es inversión, no costo:** Con 18 escenarios y atención directa a clientes, cobertura completa evita problemas en producción
- **PostgreSQL + Redis es dupla poderosa:** Cubre persistencia + velocidad + cola sin añadir más tecnologías
- **Consultoría gratuita emergió como innovación:** No estaba en escenarios originales, surgió del cuestionamiento del upselling
- **Razonamiento del agente > reglas rígidas:** Para derivación humana, la flexibilidad del LLM supera if/else hardcodeados
- **Migración manual > integración compleja:** Para datos iniciales, one-time manual migration es más simple que Sheets API
- **Admin básico suficiente inicialmente:** Funcionalidad > estética en fase temprana

---

## Action Planning

### Top 3 Priority Ideas

#### #1 Priority: Infraestructura Base (Docker + PostgreSQL + Redis + Esquema BD)

**Rationale:** Sin esta base no se puede desarrollar nada. Es el cimiento del sistema completo.

**Next steps:**
1. Crear estructura de proyecto con carpetas: `/api`, `/agent`, `/database`, `/docker`
2. Escribir `docker-compose.yml` con 3 servicios: api, agent-worker, postgres-redis
3. Diseñar esquema SQL completo con las 7 tablas principales
4. Crear scripts de migración (`init.sql`) con CREATE TABLE, FKs, índices
5. Configurar Redis con configuración para memoria (TTL keys) y pub/sub (canales)
6. Validar que los 3 contenedores levantan correctamente y se comunican

**Resources needed:**
- Docker & docker-compose instalados
- PostgreSQL client (psql o DBeaver) para validar esquema
- Redis client (redis-cli) para validar configuración
- Tiempo estimado: 1-2 días

**Timeline:** Semana 1

---

#### #2 Priority: API Webhook Receiver + Conexión Básica con Chatwoot

**Rationale:** Punto de entrada del sistema. Sin esto, no hay flujo de mensajes entrantes.

**Next steps:**
1. Elegir framework (FastAPI recomendado por velocidad y type hints)
2. Implementar endpoint POST `/webhook/chatwoot` que parsea JSON del ejemplo
3. Extraer: `conversation.id`, `sender.name`, `sender.phone_number`, `content` (mensaje)
4. Validar estructura del webhook (schema validation con Pydantic)
5. Encolar mensaje en Redis (Pub/Sub al canal `incoming_messages`)
6. Implementar endpoint POST `/webhook/stripe` para pagos (estructura similar)
7. Tests unitarios de parseo y encolado

**Resources needed:**
- FastAPI + Pydantic
- Redis client library (redis-py)
- Ejemplo de webhook real de Chatwoot (ya disponible en docs)
- Tiempo estimado: 2-3 días

**Timeline:** Semana 1-2

---

#### #3 Priority: Agente LangChain Básico con 2-3 Tools Esenciales

**Rationale:** Núcleo del sistema. Validar que el agente puede razonar y usar herramientas antes de añadir complejidad.

**Next steps:**
1. Setup de LangChain + Anthropic SDK (API key de Claude)
2. Implementar memoria híbrida con Redis (ConversationBufferWindowMemory + resumen)
3. Crear 3 tools iniciales:
   - `CustomerTools.get_customer_by_phone()`: Busca cliente en BD
   - `CustomerTools.register_new_customer()`: Crea cliente nuevo
   - `CalendarTools.check_availability()`: Consulta Google Calendar de asistenta en fecha/hora
4. Crear prompt del agente con personalidad "Maite" y contexto del negocio
5. Implementar worker que consume cola `incoming_messages` y pasa mensaje al agente
6. El agente procesa, usa tools si necesita, genera respuesta
7. Response se encola en `outgoing_messages` para envío (conexión con Chatwoot en siguiente iteración)
8. Tests de integración simulando Escenario 1 (reserva básica) sin pago real

**Resources needed:**
- LangChain library
- Anthropic API key (Claude)
- Google Calendar API credentials (service account)
- redis-py para memoria
- Tiempo estimado: 4-5 días

**Timeline:** Semana 2-3

---

## Reflection & Follow-up

### What Worked Well

- **First Principles Thinking** fue perfecto para descomponer el problema y evitar asumir soluciones complejas desde el inicio
- **Morphological Analysis** permitió explorar sistemáticamente opciones sin sesgo, eligiendo la mejor combinación
- **Assumption Reversal** cuestionó decisiones y reveló la innovación de la consultoría gratuita
- **Enfoque híbrido** (técnicas múltiples) generó visión completa: fundamentos → opciones → validación
- **Ideación enfocada** mantuvo la sesión práctica y orientada a implementación real

### Areas for Further Exploration

- **Estrategia de despliegue:** Blue-green deployment, rollback strategy si algo falla en producción
- **Monitoreo y observabilidad:** Logging estructurado, métricas de latencia, alertas ante errores
- **Gestión de secretos:** Vault, AWS Secrets Manager o docker secrets para API keys sensibles
- **Estrategia de rate limiting:** Protección contra spam de mensajes o ataques
- **Backup y disaster recovery:** Estrategia de backups de PostgreSQL, plan de recuperación

### Recommended Follow-up Techniques

- **Failure Mode Analysis (FMEA):** Identificar puntos de fallo del sistema y estrategias de mitigación (¿qué pasa si Google Calendar cae? ¿Si Stripe no responde?)
- **User Journey Mapping:** Mapear experiencia completa del cliente desde WhatsApp hasta confirmación de cita, identificar fricciones
- **Five Whys:** Para decisiones de testing (¿por qué tests de integración? ¿por qué no solo unitarios?) y asegurar razonamiento sólido

### Questions That Emerged

- ¿Cómo manejar casos donde Google Calendar API está caído temporalmente? ¿Fallback o derivación automática?
- ¿Qué hacer si un cliente intenta reservar fuera de horario laboral (ej: mensaje a las 3am)? ¿Respuesta automática inmediata o esperar a horario de apertura?
- ¿Cómo gestionar overbooking si dos clientes intentan reservar la misma franja casi simultáneamente?
- ¿Debe el sistema detectar y bloquear clientes abusivos (múltiples cancelaciones, no-shows recurrentes)?
- ¿Cómo se manejan las actualizaciones del sistema sin downtime? (dado que es servicio de atención en tiempo real)

### Next Session Planning

**Suggested topics:**
- Diseño detallado del esquema de base de datos (normalización, índices, constraints)
- Especificación de cada Tool (inputs, outputs, error handling)
- Estrategia de testing (fixtures, mocks, escenarios de integración)

**Recommended timeframe:**
- 1 semana después de completar las 3 prioridades iniciales
- Revisar aprendizajes de implementación antes de continuar con resto de tools

**Preparation needed:**
- Tener esquema de BD implementado y validado
- Tener al menos 1 tool funcionando end-to-end
- Documentar cualquier decisión técnica que haya surgido durante implementación inicial

---

*Session facilitated using the BMAD-METHOD™ brainstorming framework*
