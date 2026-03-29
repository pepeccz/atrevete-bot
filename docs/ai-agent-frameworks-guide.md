# Guía de Frameworks de Agentes IA — Cuándo Usar Cada Uno

> **Documento de referencia técnica empresarial**  
> Versión: 1.0 — Marzo 2026  
> Audiencia: Arquitectos de software, Tech Leads, Ingenieros Senior  

---

## Introducción

El ecosistema de frameworks para agentes de IA creció de manera explosiva entre 2023 y 2025. Hoy existe más de una docena de opciones viables, cada una con filosofías de diseño radicalmente distintas: grafos de estado, equipos de roles, máquinas de estados finitos, pipelines de RAG, y más. Esta proliferación es simultáneamente una bendición y una trampa: hay una herramienta correcta para cada problema, pero elegir mal puede costar meses de reescritura.

Este documento no es marketing. Es un análisis técnico honesto pensado para que un arquitecto pueda tomar una decisión fundada en minutos, no en horas de lectura de documentación. Cada framework se evalúa en sus fortalezas reales, sus limitaciones reales (incluyendo las que la documentación oficial no menciona), y los contextos donde brilla versus donde falla.

**Cómo leer esta guía:**
- Si necesitás decidir rápido → saltá a la **Matriz de Decisión** y el **Árbol de Decisión**
- Si estás diseñando una arquitectura nueva → leé los frameworks relevantes en detalle
- Si tenés un caso de uso específico → buscá en **Casos de Uso Empresariales Prácticos**
- Si querés evitar errores comunes → leé **Anti-patterns comunes**

Una observación fundamental antes de empezar: **ningún framework es universalmente superior**. La pregunta no es "¿cuál es el mejor?" sino "¿cuál resuelve mi problema específico con el menor costo técnico?". El framework más potente no es siempre el mejor — a veces una FSM custom con llamadas LLM directas supera a LangGraph en simplicidad, costo y debuggabilidad.

---

## Mapa Mental: Dimensiones de Decisión

Antes de evaluar frameworks, es fundamental entender las dimensiones que determinan qué herramienta usar. Estas son las variables críticas:

### Dimensiones primarias (definen la arquitectura)

| Dimensión | Opciones | Impacto |
|-----------|----------|---------|
| **Tipo de interacción** | Conversacional multi-turn / Batch task / Pipeline / Automatización de código | Define si necesitás estado entre turnos |
| **Gestión de estado** | Sin estado / Estado de sesión (mensajes) / Estado rico tipado / Estado con scopes | Determina complejidad del checkpointing |
| **Routing** | Lineal / Condicional / LLM-driven / Híbrido | Qué tan predecible debe ser el flujo |
| **Número de agentes** | Single / Multi-agente colaborativo / Multi-agente jerárquico | Overhead de coordinación |
| **Output** | Texto libre / Estructurado (JSON/Pydantic) / Acciones / Código | Si necesitás garantías en la salida |

### Dimensiones secundarias (condicionan la elección)

| Dimensión | Opciones | Impacto |
|-----------|----------|---------|
| **Cloud/Stack** | GCP / Azure / AWS / On-premise / Agnóstico | Ventajas nativas por proveedor |
| **Lenguaje** | Python / TypeScript / C# / Java | Soporte del framework |
| **Presupuesto de tokens** | Bajo / Medio / Alto | Afecta la viabilidad de ciertos patrones |
| **Compliance / Control** | Alto / Medio / Bajo | Self-hosted vs cloud |
| **Madurez del equipo** | Junior / Mid / Senior | Curva de aprendizaje del framework |
| **Time-to-market** | Urgente / Normal / Sin urgencia | Simplicidad vs potencia |
| **Escalabilidad** | Prototipo / MVP / Producción enterprise | Overhead de infraestructura |

### Preguntas diagnóstico (responder antes de elegir)

1. ¿El agente necesita recordar cosas entre mensajes del mismo usuario?
2. ¿El flujo tiene branches complejos o es relativamente lineal?
3. ¿Necesito que múltiples agentes especializados colaboren?
4. ¿El output debe ser estructurado y validado?
5. ¿Cuánto control necesito sobre el routing de la conversación?
6. ¿Tengo constraintas de costo por token?
7. ¿Hay requisitos de compliance que requieran self-hosting?

---

## Frameworks

---

### 1. LangGraph

#### Qué es

LangGraph es un framework de grafos de estado construido sobre el ecosistema LangChain. Su abstracción central es el **StateGraph**: un grafo dirigido donde los nodos son funciones Python (síncronas o asíncronas) y los edges son transiciones condicionales entre ellos. El estado es un `TypedDict` tipado que fluye a través del grafo, y los reducers (`Annotated[T, reducer_fn]`) controlan cómo se fusionan las actualizaciones de estado cuando múltiples nodos producen salidas.

Lo que distingue a LangGraph de otros frameworks es su modelo de persistencia: mediante un **checkpointer** (Redis, SQLite, PostgreSQL, in-memory), el estado completo del grafo se serializa después de cada nodo. Esto permite conversaciones multi-turn donde el agente "recuerda" el contexto exacto de turnos anteriores sin que la aplicación maneje esa persistencia manualmente.

La versión 0.6+ introdujo el concepto de **modos de conversación** (GREETING, BOOKING, GENERAL, ESCALATION), que permite modelar chatbots con comportamientos distintos según el contexto, cada uno implementado como un subgrafo o nodo especializado con su propio sistema de routing.

#### Fortalezas clave

- **Estado tipado y auditeable**: El estado es un TypedDict explícito, visible, debuggeable. En cualquier punto sabés exactamente qué hay en el estado.
- **Routing determinístico**: Los conditional edges permiten routing explícito basado en el estado, no en la "voluntad" del LLM.
- **Persistencia nativa**: Redis checkpointer, PostgreSQL checkpointer, SQLite — el estado multi-turn se maneja sin código custom.
- **Subgrafos y modos**: Podés anidar grafos para modularidad. Un modo BOOKING puede ser un subgrafo completo con su propio estado y routing.
- **Soporte LangChain completo**: Integración nativa con el ecosistema LangChain (tools, retrievers, memory, callbacks).
- **LangSmith integration**: Trazabilidad, debugging y evaluación con LangSmith sin configuración extra.
- **Resiliente a fallas**: Si un nodo falla, el checkpointer permite retomar desde el último estado guardado.
- **Human-in-the-loop**: Soporte nativo para `interrupt_before` y `interrupt_after` para flujos con intervención humana.

#### Limitaciones reales

- **Curva de aprendizaje MUY alta**: Los reducers con `Annotated`, las reglas del no-spread (`{**state}` causa message doubling), los conditional edges, los subgrafos — todo requiere semanas de estudio para usarlo correctamente en producción.
- **Over-engineering para flujos simples**: Un chatbot de FAQ de 5 respuestas no necesita un StateGraph. LangGraph agrega complejidad accidental para flujos lineales simples.
- **Bugs silenciosos con el estado**: El error más común es actualizar el estado incorrectamente (con spread) y no detectarlo hasta producción. El framework no te protege de este error.
- **Lock-in al ecosistema LangChain**: Si en algún momento querés migrar, el acoplamiento con LangChain tools, callbacks y LCEL es significativo.
- **Overhead de tokens**: El sistema de reducers y el historial completo de mensajes se pasa al LLM en cada turno. Para conversaciones largas, el costo de tokens puede dispararse.
- **Documentación inconsistente**: La API cambió varias veces entre LangGraph 0.1 y 0.6. Mucha documentación online está desactualizada.
- **Difícil de testear unitariamente**: Los nodos del grafo son funciones que dependen del estado completo. Mockear ese estado correctamente requiere setup significativo.

#### Casos de uso ideales

**1. Chatbots conversacionales multi-turn con routing complejo**  
El caso canónico: un asistente que maneja múltiples temas (reservas, soporte, FAQ), recuerda el contexto de la conversación y necesita derivar a flujos especializados según el intent. LangGraph modela esto exactamente: modos como nodos del grafo, routing condicional entre ellos, estado persistente en Redis.

**2. Asistentes de atención al cliente con múltiples etapas**  
Flujos como "detectar problema → clasificar urgencia → proponer solución → escalar si no se resuelve" son naturales en un grafo. Cada etapa es un nodo, las transiciones son edges condicionales, el estado almacena el historial de intentos.

**3. Agentes con procesos de aprobación (human-in-the-loop)**  
Si el agente necesita pausar y esperar aprobación humana antes de ejecutar una acción (enviar un email, procesar un pago), LangGraph tiene soporte nativo con `interrupt_before`. El estado se serializa, el humano aprueba, el grafo continúa exactamente donde estaba.

**4. Workflows de investigación iterativa**  
Agentes que buscan información, evalúan si es suficiente, y deciden si seguir buscando o responder. El loop en el grafo ("si la confianza < 0.7 → buscar más") es expresable naturalmente con conditional edges.

**5. Sistemas de reservas / agendas (ejemplo: Atrévete Bot)**  
El booking flow de un salón de belleza requiere: capturar nombre → servicio → estilista → fecha → hora → confirmar. Cada paso es un nodo, el estado almacena los datos capturados, y si el usuario cambia de idea en el paso 4, el estado permite volver atrás sin perder lo capturado.

#### Casos donde NO usar

- Pipelines batch simples sin interacción conversacional
- Extracción de datos estructurados de documentos (usar Pydantic AI)
- Equipos de agentes con roles declarativos (usar CrewAI)
- Proyectos en stack .NET/Azure (usar Semantic Kernel)
- Chatbots simples de FAQ sin routing complejo (usar FSM custom o PydanticAI)
- Automatización de código y CI/CD (usar Anthropic Agent SDK)
- Equipos sin experiencia en LangChain que necesitan entregar rápido

#### Ejemplo de código mínimo

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.redis import RedisSaver
from langchain_openai import ChatOpenAI

# Estado tipado — los reducers son CRÍTICOS
class ConversationState(TypedDict):
    messages: Annotated[list, add_messages]  # reducer: acumula, no reemplaza
    mode: str
    booking_data: dict

# Nodos del grafo
def intent_router(state: ConversationState) -> ConversationState:
    last_message = state["messages"][-1].content
    # Clasificación simple — en producción: llamada al LLM
    if "reserva" in last_message.lower() or "turno" in last_message.lower():
        return {"mode": "BOOKING"}
    return {"mode": "GENERAL"}

def booking_node(state: ConversationState) -> ConversationState:
    llm = ChatOpenAI(model="gpt-4o-mini")
    response = llm.invoke(state["messages"])
    # NUNCA: return {**state, "messages": [response]}  ← message doubling bug
    return {"messages": [response]}  # el reducer add_messages lo fusiona correctamente

def general_node(state: ConversationState) -> ConversationState:
    llm = ChatOpenAI(model="gpt-4o-mini")
    response = llm.invoke(state["messages"])
    return {"messages": [response]}

# Routing condicional
def route_by_mode(state: ConversationState) -> str:
    return state["mode"]  # "BOOKING" o "GENERAL"

# Construcción del grafo
builder = StateGraph(ConversationState)
builder.add_node("router", intent_router)
builder.add_node("booking", booking_node)
builder.add_node("general", general_node)

builder.set_entry_point("router")
builder.add_conditional_edges(
    "router",
    route_by_mode,
    {"BOOKING": "booking", "GENERAL": "general"}
)
builder.add_edge("booking", END)
builder.add_edge("general", END)

# Compilar con checkpointer para persistencia multi-turn
checkpointer = RedisSaver.from_conn_string("redis://localhost:6379")
graph = builder.compile(checkpointer=checkpointer)

# Invocar con thread_id para sesión persistente
config = {"configurable": {"thread_id": "user-123"}}
result = graph.invoke(
    {"messages": [{"role": "user", "content": "Quiero reservar un turno"}]},
    config=config
)
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI, Anthropic Claude, Gemini vía LiteLLM
- **Persistencia**: Redis Stack (checkpointer), PostgreSQL (AsyncPostgresSaver)
- **Observabilidad**: LangSmith (nativo), OpenTelemetry
- **API**: FastAPI (async nativo), Starlette
- **Testing**: pytest-asyncio, langgraph test utilities

#### Nivel de madurez / lock-in

- **Madurez**: Alta en producción (LangGraph 0.6+ es estable). Usado en producción por empresas grandes.
- **Lock-in**: **ALTO**. El acoplamiento con LangChain es profundo. Migrar a otro framework requiere reescribir la lógica del grafo y la gestión de estado.
- **Comunidad**: Muy activa. LangChain Inc. tiene financiamiento significativo.
- **Riesgo de abandono**: Bajo — es el framework dominante en el ecosistema Python para agentes.

---

### 2. OpenAI Agents SDK

#### Qué es

OpenAI Agents SDK es el sucesor oficial de Swarm, la librería experimental de OpenAI para multi-agente. A diferencia de LangGraph (que te da una máquina de estados), el SDK de OpenAI te da **primitivas de alto nivel**: `Agent`, `Runner`, `Session`, `Guardrail` y `Handoff`. La filosofía es "simple first": querés un agente que use tools y hable con usuarios → tres líneas de código. Querés múltiples agentes especializados que se pasan el control → cinco líneas más.

El estado en OpenAI Agents SDK es deliberadamente simple: **solo el historial de mensajes**. No hay TypedDict, no hay reducers, no hay state schemas complejos. Esto es una fortaleza para casos simples y una limitación real para casos donde necesitás estado rico (¿en qué paso del proceso de reserva estamos? ¿cuál es el nivel de urgencia del ticket?).

Los **Guardrails** son una primitiva particularmente valiosa: validaciones que corren en paralelo con el LLM (no en serie) para detectar inputs peligrosos o outputs inválidos antes de procesarlos. Los **Handoffs** permiten que un agente transfiera el control a otro especialista de manera declarativa.

#### Fortalezas clave

- **Curva de aprendizaje muy baja**: Un agente funcional en 10 líneas de código. La API es intuitiva y bien documentada.
- **Guardrails integrados**: Validación de inputs/outputs en paralelo, configurable con schemas Pydantic.
- **Handoffs declarativos**: Transferir control entre agentes (ej: "si el usuario pregunta sobre facturación → billing_agent") es una línea de código.
- **Sesiones nativas múltiples backends**: `RedisSession`, `SQLAlchemySession`, `SQLiteSession` — persistencia out-of-the-box.
- **Multi-provider**: Funciona con OpenRouter, LiteLLM, Azure OpenAI, no solo con la API de OpenAI.
- **Tracing integrado**: Logging de runs completo para debugging.
- **Buena documentación y ejemplos**: La documentación oficial tiene muchos casos de uso bien documentados.

#### Limitaciones reales

- **Estado solo = historial de mensajes**: No hay estado tipado. Si necesitás saber en qué step del booking está el usuario sin inferirlo del historial, tenés que manejarlo manualmente en tu aplicación o con herramientas auxiliares.
- **Lock-in suave hacia OpenAI**: Aunque soporta multi-provider, la API, los nombres de los conceptos y las optimizaciones están diseñadas para los modelos de OpenAI. GPT-4o funciona perfectamente. Otros modelos pueden tener fricciones sutiles.
- **Routing menos expresivo que LangGraph**: Los handoffs son potentes, pero no tenés la expressividad de un grafo dirigido con conditional edges. Flujos complejos con múltiples branches anidados se vuelven difíciles de modelar.
- **Sin soporte nativo para human-in-the-loop**: Pausar el agente y esperar aprobación humana requiere implementación custom.
- **Ecosistema más pequeño**: Menos integraciones, menos plugins, menos ejemplos de producción que LangChain/LangGraph.
- **Version churn**: El SDK es relativamente nuevo (2024-2025). La API puede cambiar más que LangGraph, que tiene más años.

#### Casos de uso ideales

**1. Chatbots con múltiples especialistas**  
Un asistente de e-commerce que tiene un agente de productos, uno de logística, uno de facturación, y uno de soporte técnico. El agente "recepcionista" clasifica la consulta y hace handoff al especialista. Simple de implementar, fácil de mantener.

**2. Pipelines de validación crítica**  
Flujos donde cada input y output debe pasar por guardrails: verificar que el usuario no esté enviando datos PII, que el output del LLM no contenga información de competidores, que la respuesta cumpla con políticas internas. Los guardrails paralelos son perfectos para esto.

**3. Prototipos rápidos que necesitan escalar**  
La baja curva de aprendizaje permite iterar rápido en la fase de prototipo. La arquitectura es lo suficientemente sólida para producción si los requerimientos de estado son simples.

**4. Sistemas de soporte técnico Nivel 1**  
Un agente que clasifica tickets, intenta resolver con FAQ/knowledge base, y escala a humano si no puede resolver. Los handoffs modelan perfectamente el escalado. Las sesiones mantienen el contexto del ticket.

**5. Asistentes de ventas con herramientas**  
Un agente que busca en catálogo de productos, verifica disponibilidad, calcula precios con descuentos, y genera cotizaciones. Cada capacidad es una tool. El Runner maneja el loop de function calling automáticamente.

#### Casos donde NO usar

- Flujos que requieren estado rico tipado y validado (usar LangGraph o Pydantic AI)
- Routing muy complejo con múltiples branches anidados (usar LangGraph)
- Stack .NET/Azure (usar Semantic Kernel)
- Automatización de código (usar Anthropic Agent SDK)
- Equipos que quieren evitar lock-in hacia OpenAI
- Casos donde el control determinístico es crítico (usar FSM custom)

#### Ejemplo de código mínimo

```python
from agents import Agent, Runner, Session, handoff
from agents.sessions import RedisSession
import asyncio

# Agentes especializados
billing_agent = Agent(
    name="Facturación",
    model="openai/gpt-4o-mini",
    instructions="Sos el especialista en facturación. Resolvés consultas sobre pagos, facturas y reembolsos.",
    tools=[get_invoice, process_refund],  # tools definidas como funciones Python
)

support_agent = Agent(
    name="Soporte",
    model="openai/gpt-4o-mini",
    instructions="Sos el agente de soporte técnico. Resolvés problemas técnicos.",
    tools=[get_ticket_status, search_knowledge_base],
)

# Agente principal con handoffs
main_agent = Agent(
    name="Recepcionista",
    model="openai/gpt-4o-mini",
    instructions="""
    Clasificás la consulta del usuario y derivás al especialista correcto.
    Para consultas de facturación → transfiere a Facturación.
    Para problemas técnicos → transfiere a Soporte.
    """,
    handoffs=[
        handoff(billing_agent, description="Consultas de facturación"),
        handoff(support_agent, description="Problemas técnicos"),
    ],
)

async def handle_message(user_id: str, message: str) -> str:
    # Sesión persistente en Redis — mantiene historial entre turnos
    session = RedisSession(
        session_id=f"user-{user_id}",
        redis_url="redis://localhost:6379"
    )
    
    result = await Runner.run(
        starting_agent=main_agent,
        input=message,
        session=session,
    )
    return result.final_output
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI GPT-4o, Azure OpenAI, OpenRouter (multi-provider)
- **Persistencia**: Redis (RedisSession), PostgreSQL (SQLAlchemySession), SQLite (desarrollo)
- **API**: FastAPI, Flask
- **Observabilidad**: OpenTelemetry, Datadog, built-in tracing
- **Testing**: pytest con mocks de sessions

#### Nivel de madurez / lock-in

- **Madurez**: Media-Alta. El SDK es relativamente nuevo (2024) pero desarrollado por el equipo de OpenAI, que tiene incentivos fuertes para mantenerlo.
- **Lock-in**: **MEDIO**. Técnicamente multi-provider, pero el diseño favorece GPT-4o. Migrar a otro framework requiere reescribir los Agents y Runners, aunque la lógica de negocio puede reutilizarse.
- **Comunidad**: Creciente, respaldada por OpenAI directamente.
- **Riesgo de abandono**: Bajo — OpenAI tiene incentivos económicos directos para que este SDK sea exitoso.

---

### 3. Google ADK (Agent Development Kit)

#### Qué es

Google ADK es el framework de agentes de Google, diseñado con la plataforma Vertex AI Agent Engine como deployment target nativo. Su característica más distintiva es el sistema de **state con scopes**: el estado no es un único diccionario plano, sino una jerarquía de contextos con ciclos de vida distintos: `session:` (dura lo que dura la sesión), `user:` (persiste entre sesiones del mismo usuario), `app:` (estado global de la aplicación), y `temp:` (efímero, solo dentro del turno actual).

Este sistema de scopes es más expresivo que el estado plano de OpenAI Agents SDK y más flexible que el TypedDict estático de LangGraph para ciertos patrones. La inyección automática de estado en prompts (`{booking_step}` en el system prompt se reemplaza automáticamente por el valor del estado) elimina código boilerplate.

ADK 2.0 Alpha introduce workflow agents: `SequentialAgent`, `ParallelAgent`, y `LoopAgent`, que permiten orquestar múltiples agentes sin escribir código de coordinación manual. El transfer entre agentes puede ser **LLM-driven** (el agente decide cuándo transferir) o **determinístico** (el orchestrator decide).

#### Fortalezas clave

- **State con scopes**: El manejo de estado con session/user/app/temp es más semántico que un TypedDict plano. Sabés exactamente qué datos viven cuánto tiempo.
- **Inyección automática de state en prompts**: Variables del estado disponibles directamente en el system prompt sin código extra.
- **Workflow agents declarativos**: Sequential, Parallel y Loop agents sin código de orquestación manual.
- **Model-agnostic real**: Gemini, Claude, GPT-4o, Ollama, vLLM — sin fricciones significativas con ninguno.
- **Deploy nativo en Vertex AI**: Si estás en GCP, el deploy a producción es trivial. Scaling, monitoring, seguridad — todo gestionado por Google.
- **Evaluación built-in**: Herramientas de evaluación de agentes integradas, útil para CI/CD de calidad.
- **Observabilidad en Vertex**: Cloud Trace, Cloud Monitoring integrados cuando se despliega en GCP.
- **ADK 2.0 Graph-based**: La versión alpha introduce workflows basados en grafos, compitiendo directamente con LangGraph.

#### Limitaciones reales

- **Ventaja nativa con Gemini/GCP**: El framework está optimizado para Gemini y el stack de Google. Funciona con otros modelos, pero las ventajas de optimización son menores.
- **Curva de aprendizaje media**: El sistema de scopes y la inyección de prompts son conceptos nuevos que requieren tiempo. No tan complejo como LangGraph, pero más que OpenAI Agents SDK.
- **ADK 2.0 Alpha inestable**: Las features más interesantes (graph-based workflows) están en alpha. No usar en producción sin evaluar estabilidad.
- **Ecosistema más pequeño**: Menos integraciones de terceros que LangChain/LangGraph. Más dependiente del ecosistema de Google.
- **Documentación en construcción**: Como framework relativamente nuevo, la documentación tiene gaps. Los examples son buenos pero no cubren todos los edge cases.
- **Lock-in en deploy**: Si usás Vertex AI Agent Engine, el lock-in con GCP es significativo. El costo de migrar a otro cloud aumenta.
- **Comunidad más chica**: Menos ejemplos de producción públicos que LangGraph.

#### Casos de uso ideales

**1. Empresas all-in en GCP**  
Si toda la infraestructura está en GCP (Cloud SQL, Cloud Storage, Vertex AI), el ADK ofrece integración nativa con cada servicio. El deploy en Vertex AI Agent Engine elimina la necesidad de gestionar infraestructura.

**2. Flujos multi-agente con estado rico por usuario**  
Un sistema CRM donde el agente conoce el historial del cliente (`user:` scope), el estado de la conversación actual (`session:` scope), y configuraciones globales (`app:` scope). El sistema de scopes de ADK modela esto perfectamente.

**3. Pipelines paralelos complejos**  
Análisis de documentos donde simultáneamente: un agente extrae entidades, otro analiza sentimiento, otro verifica compliance. `ParallelAgent` orquesta esto sin código manual de concurrencia.

**4. Asistentes con Gemini multimodal**  
Si el caso de uso incluye análisis de imágenes, videos o audio (propiedades de inmobiliarias, análisis de productos, etc.), la integración nativa con Gemini 2.0 Flash/Pro es una ventaja real.

**5. Proyectos que necesitan evaluación sistemática**  
Si el equipo necesita medir calidad del agente de manera continua (métricas de éxito, evaluación de respuestas), las herramientas de evaluación built-in de ADK son una ventaja sobre frameworks que no las incluyen.

#### Casos donde NO usar

- Stack Azure/Microsoft (usar Semantic Kernel)
- Equipos fuera del ecosistema GCP que no quieren lock-in
- Proyectos que necesitan estabilidad máxima (no usar ADK 2.0 Alpha en prod)
- Automatización de código (usar Anthropic Agent SDK)
- Equipos con experiencia en LangGraph que no tienen motivo para migrar

#### Ejemplo de código mínimo

```python
from google.adk.agents import Agent, LlmAgent, SequentialAgent
from google.adk.sessions import VertexAiSessionService
from google.adk.tools import Tool

# Herramientas
@Tool()
def check_availability(date: str, stylist: str) -> dict:
    """Verifica disponibilidad de un estilista en una fecha."""
    # Lógica de negocio
    return {"available_slots": ["10:00", "14:00", "16:00"]}

@Tool()
def create_booking(data: dict) -> str:
    """Crea una reserva en el sistema."""
    return f"Reserva confirmada para {data['date']} a las {data['time']}"

# Agente de captura de datos
intake_agent = LlmAgent(
    name="intake",
    model="gemini-2.0-flash",
    instruction="""
    Capturás los datos de la reserva paso a paso.
    Estado actual del booking: {booking_step}
    Datos capturados: {booking_data}
    """,  # las variables del estado se inyectan automáticamente
    tools=[check_availability],
    output_key="booking_data",  # guarda el output en state["booking_data"]
)

# Agente de confirmación
confirmation_agent = LlmAgent(
    name="confirmation",
    model="gemini-2.0-flash",
    instruction="Confirmás la reserva con los datos: {booking_data}",
    tools=[create_booking],
)

# Pipeline secuencial
booking_pipeline = SequentialAgent(
    name="booking_pipeline",
    sub_agents=[intake_agent, confirmation_agent],
)

# Deploy con session service de Vertex AI
session_service = VertexAiSessionService(
    project="mi-proyecto-gcp",
    location="us-central1",
)
```

#### Stack tecnológico que combina bien

- **LLM**: Gemini 2.0 Flash/Pro (nativo), GPT-4o, Claude (multi-provider)
- **Deploy**: Vertex AI Agent Engine (nativo), Cloud Run
- **Persistencia**: Vertex AI Session Service, Firestore
- **Observabilidad**: Cloud Trace, Cloud Monitoring, Vertex AI Evaluation
- **API**: FastAPI en Cloud Run

#### Nivel de madurez / lock-in

- **Madurez**: Media. ADK 1.x es estable; ADK 2.0 está en alpha. Usar 1.x para producción.
- **Lock-in**: **ALTO si usás Vertex AI**. Medio si solo usás el framework sin Vertex.
- **Respaldo**: Google — credibilidad y recursos. Pero Google también tiene historial de discontinuar productos.
- **Riesgo de abandono**: Bajo-Medio. Es un producto estratégico para Google Cloud.

---

### 4. Anthropic Agent SDK (Claude Agent SDK)

#### Qué es

El Anthropic Agent SDK (también conocido como Claude Code SDK o Claude Agent SDK) es fundamentalmente **distinto** de los frameworks conversacionales anteriores. No está diseñado para chatbots de usuario final. Es un framework para **automatización de código y tareas de desarrollo**: agentes que leen, escriben y editan código; ejecutan comandos bash; buscan en el filesystem; hacen scraping web — y lo hacen con sub-agentes coordinados.

Sus primitivas incluyen tools built-in para operaciones de filesystem (`Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`), búsqueda web (`WebSearch`, `WebFetch`), soporte nativo para **Model Context Protocol (MCP)** para integrarse con herramientas externas, y **Hooks** (`PreToolUse`, `PostToolUse`) para interceptar y validar acciones del agente antes o después de ejecutarlas.

El estado en este SDK son **Sessions** — contexto que persiste entre runs del agente de código, permitiendo que un agente retome un task donde lo dejó. No es estado conversacional con un usuario humano; es estado de una tarea de automatización.

#### Fortalezas clave

- **Tools de filesystem y código built-in**: No necesitás implementar las tools más comunes para automatización de código — ya están.
- **Sub-agentes nativos**: Un agente puede spawnear sub-agentes especializados para tareas paralelas o especializadas.
- **MCP support**: Integración con el ecosistema Model Context Protocol — miles de herramientas disponibles sin implementación custom.
- **Hooks para control granular**: `PreToolUse` permite interceptar cualquier acción antes de ejecutarla (validar, logear, pedir confirmación). `PostToolUse` permite procesar el resultado antes de que el agente lo vea.
- **Claude como motor primario**: Optimizado para Claude 3.5/3.7 Sonnet, que son los mejores modelos disponibles para tareas de código.
- **Sessions para continuidad**: Un agente puede pausar y continuar un task complejo entre sesiones.

#### Limitaciones reales

- **NO es un framework conversacional**: Este punto merece énfasis. No tiene las primitivas necesarias para un chatbot de usuario final: no hay routing de intents, no hay manejo de turns de conversación casual, no hay sistema de sesiones orientado a diálogos.
- **Diseñado para un modelo específico**: Optimizado para Claude. Aunque técnicamente puede usarse con otros modelos, las capacidades de herramientas y el comportamiento están calibrados para Claude.
- **Costo elevado**: Las tareas de automatización de código requieren muchos tokens. Un agente de code review puede costar $0.50-$2 por run dependiendo del tamaño del codebase.
- **Seguridad crítica**: Un agente con acceso a `Bash` y `Write` puede causar daño real en un servidor. Los hooks de seguridad son responsabilidad del desarrollador, no del framework.
- **Ecosistema pequeño**: Mucho más nuevo que LangGraph. Menos recursos, menos ejemplos de producción.
- **Difícil de testear**: Las acciones en el filesystem y bash son intrínsecamente difíciles de testear de manera determinística.

#### Casos de uso ideales

**1. Agentes de code review en CI/CD**  
Un agente que, en cada PR, lee los archivos modificados, analiza el diff, verifica que sigue convenciones de código, y genera comentarios de review automáticos. Los hooks pueden requerir aprobación antes de comentar en el PR.

**2. Automatización de refactoring**  
Un agente que recibe la instrucción "refactoriza todos los componentes de class-based a functional en React" y ejecuta la tarea de manera autónoma, usando Read/Edit/Glob para encontrar y transformar los archivos.

**3. Generación de tests automática**  
Un agente que analiza el código fuente, identifica funciones sin tests, y genera tests unitarios para ellas usando los patrones del proyecto.

**4. Documentación automática**  
Un agente que lee el código fuente y genera o actualiza documentación técnica, asegurándose de que el código y la documentación estén sincronizados.

**5. Investigación y análisis de codebases**  
Un agente que analiza un repositorio desconocido y genera un informe de arquitectura: dependencias, patrones usados, problemas de seguridad, deuda técnica.

#### Casos donde NO usar

- Chatbots conversacionales con usuarios finales (usar LangGraph, OpenAI Agents SDK)
- Pipelines de datos sin componente de código (usar CrewAI, LlamaIndex)
- Extracción de datos estructurados (usar Pydantic AI)
- Cualquier caso donde el usuario final interactúa en tiempo real (no es para eso)

#### Ejemplo de código mínimo

```python
import anthropic
from anthropic.agents import Agent, Session
from anthropic.agents.hooks import PreToolUseHook

# Hook para seguridad: aprobar antes de ejecutar bash destructivo
class SafetyHook(PreToolUseHook):
    def __call__(self, tool_name: str, tool_input: dict) -> bool:
        if tool_name == "bash":
            command = tool_input.get("command", "")
            # Rechazar comandos destructivos sin confirmación
            dangerous_patterns = ["rm -rf", "DROP TABLE", "truncate"]
            if any(pattern in command for pattern in dangerous_patterns):
                print(f"⚠️ Comando peligroso detectado: {command}")
                confirm = input("¿Confirmar? (s/n): ")
                return confirm.lower() == "s"
        return True  # Aprobar por defecto

# Agente de code review
agent = Agent(
    model="claude-sonnet-4-5",
    system_prompt="""
    Sos un agente de code review experto. Analizás código Python
    y generás comentarios constructivos sobre:
    - Calidad del código y legibilidad
    - Posibles bugs o edge cases
    - Oportunidades de optimización
    - Adherencia a PEP 8 y buenas prácticas
    """,
    hooks=[SafetyHook()],
)

# Session para persistencia entre runs
session = Session(id="review-pr-123")

# El agente tiene acceso a tools de filesystem automáticamente
result = agent.run(
    task="""
    Lee todos los archivos Python en src/ que fueron modificados recientemente.
    Para cada archivo, genera un comentario de code review detallado.
    Guarda los comentarios en review_output.md
    """,
    session=session,
)

print(result.summary)
```

#### Stack tecnológico que combina bien

- **LLM**: Claude 3.5/3.7 Sonnet (optimizado), Claude Opus para análisis profundo
- **CI/CD**: GitHub Actions, GitLab CI, Jenkins
- **Version control**: GitHub, GitLab (vía Bash tools)
- **Containerización**: Docker (ejecución en containers aislados para seguridad)
- **Testing**: pytest para validar outputs del agente

#### Nivel de madurez / lock-in

- **Madurez**: Media. El SDK es relativamente nuevo. Las APIs pueden cambiar.
- **Lock-in**: **ALTO hacia Claude/Anthropic**. Las herramientas built-in y los hooks están diseñados para el modelo de Claude.
- **Comunidad**: Pequeña pero creciendo. Anthropic tiene credibilidad técnica alta.
- **Riesgo de abandono**: Bajo — Anthropic está invirtiendo fuertemente en este SDK como producto.

---

### 5. CrewAI

#### Qué es

CrewAI adopta una metáfora de **equipos de trabajo**: cada agente tiene un rol, un objetivo y un backstory, como si fuera un empleado con una especialización. Los agentes colaboran en una `Crew` para completar un conjunto de `Tasks`. El proceso puede ser `sequential` (agente A termina → pasa al B) o `hierarchical` (un manager agent descompone y delega tareas).

Esta abstracción de alto nivel es su mayor fortaleza y su mayor limitación. Es extremadamente fácil de modelar procesos de trabajo en equipo: "un investigador busca información, un escritor la sintetiza, un editor la refina". Pero CrewAI es **stateless por diseño** — no tiene estado conversacional multi-turn. Cada invocación de la Crew es un batch job que empieza de cero.

CrewAI es declarativo: definís los agentes y tareas con strings de texto natural (roles, goals, backstories). Esto lo hace accesible para no-técnicos que quieren configurar el comportamiento, pero puede dar la impresión de "jugar a los Sims con LLMs" — mucho prompting, poca ingeniería.

#### Fortalezas clave

- **API extremadamente simple**: La curva de aprendizaje más baja de todos los frameworks de multi-agente.
- **Metáfora intuitiva**: "Un equipo de agentes con roles" es comprensible para stakeholders no técnicos.
- **Proceso hierarchical**: El manager agent que descompone y delega es una abstracción potente para tareas complejas.
- **Integración nativa con herramientas comunes**: Serper (búsqueda web), DuckDuckGo, scraping, etc.
- **Fácil de probar conceptos**: Ideal para validar si un pipeline multi-agente tiene sentido antes de invertir en una arquitectura más compleja.
- **Output final estructurado**: El output de la Crew puede ser un Pydantic model, garantizando estructura.

#### Limitaciones reales

- **Stateless**: No hay estado conversacional multi-turn. Cada run es un batch job independiente. Si necesitás un chatbot que recuerde turnos anteriores, CrewAI no es la herramienta.
- **Routing condicional muy limitado**: El flujo es lineal (sequential) o jerárquico. No hay equivalente a los conditional edges de LangGraph.
- **Mucho prompt engineering disfrazado de código**: Los "agents" son esencialmente prompts con nombres. La calidad del resultado depende fuertemente de qué tan bien escribas los roles y backstories.
- **Difícil de debuggear**: Cuando la Crew produce resultados incorrectos, es difícil saber qué agente falló y por qué. El stack trace no siempre es claro.
- **Latencia alta**: En modo hierarchical, múltiples llamadas al LLM se encadenan. Para tareas simples, es overkill.
- **No apto para producción sin validación**: El output no es determinístico. En sistemas críticos, necesitás validación adicional sobre el output de la Crew.

#### Casos de uso ideales

**1. Pipelines editoriales de contenido**  
Researcher busca datos → Writer redacta el artículo → Editor revisa y mejora → SEO specialist optimiza. Este flujo secuencial con roles bien definidos es exactamente lo que CrewAI modela mejor.

**2. Research y síntesis de mercado**  
Data Collector busca información de múltiples fuentes → Analyst sintetiza findings → Report Writer genera el informe ejecutivo. El proceso hierarchical permite que el Manager decida cuánta investigación es necesaria.

**3. Generación de contenido escalado**  
Para generar cientos de descripciones de productos, post de blog, o emails de marketing, una Crew con researcher + writer + quality checker puede procesar lotes eficientemente.

**4. Análisis de documentos (no conversacional)**  
Un agente lee el documento, otro lo analiza, otro genera el resumen ejecutivo, otro extrae las acciones a tomar. Batch job sin estado conversacional.

**5. Prototipado rápido de pipelines complejos**  
Cuando querés validar si una arquitectura multi-agente tiene sentido antes de implementarla con LangGraph u otro framework más complejo.

#### Casos donde NO usar

- Chatbots conversacionales multi-turn con usuarios (no tiene estado)
- Flujos con routing condicional complejo (no es su fortaleza)
- Sistemas que requieren determinismo y control (demasiada "magia" de LLM)
- Producción sin validación exhaustiva del output
- Casos donde la latencia es crítica (múltiples llamadas LLM en serie)

#### Ejemplo de código mínimo

```python
from crewai import Crew, Agent, Task, Process
from crewai_tools import SerperDevTool, WebsiteSearchTool

# Herramientas
search_tool = SerperDevTool()
web_tool = WebsiteSearchTool()

# Agentes con roles declarativos
researcher = Agent(
    role="Investigador Senior de Mercado",
    goal="Investigar tendencias actuales en el mercado de {topic}",
    backstory="""Tenés 10 años de experiencia en research de mercado.
    Sos metódico, verificás fuentes y siempre citás tus datos.""",
    tools=[search_tool, web_tool],
    verbose=True,
)

writer = Agent(
    role="Redactor de Contenido",
    goal="Crear un artículo bien estructurado y atractivo sobre {topic}",
    backstory="""Escritor especializado en contenido técnico y de negocios.
    Tu escritura es clara, concisa y tiene estructura lógica.""",
    verbose=True,
)

editor = Agent(
    role="Editor Senior",
    goal="Revisar y mejorar el artículo para máxima calidad",
    backstory="Editor con ojo crítico para claridad, precisión y estilo.",
    verbose=True,
)

# Tasks con dependencias
research_task = Task(
    description="Investigá las últimas tendencias en {topic}. Encontrá al menos 5 fuentes confiables.",
    expected_output="Informe de research con datos, fuentes y insights clave.",
    agent=researcher,
)

write_task = Task(
    description="Escribí un artículo de 800 palabras sobre {topic} basado en el research.",
    expected_output="Artículo completo con introducción, desarrollo y conclusión.",
    agent=writer,
    context=[research_task],  # depende del output del research
)

edit_task = Task(
    description="Revisá el artículo, corregí errores y mejorá la claridad.",
    expected_output="Artículo final pulido y listo para publicar.",
    agent=editor,
    context=[write_task],
)

# Crew con proceso secuencial
crew = Crew(
    agents=[researcher, writer, editor],
    tasks=[research_task, write_task, edit_task],
    process=Process.sequential,
    verbose=True,
)

# Ejecutar
result = crew.kickoff(inputs={"topic": "inteligencia artificial en salud"})
print(result.raw)
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI GPT-4o (óptimo), Claude, Gemini
- **Tools**: SerperDev, Browserbase, Firecrawl, Exa Search
- **Storage**: Para persistencia entre runs necesitás implementarla manualmente
- **Orquestación**: FastAPI + background tasks, Celery para lotes grandes

#### Nivel de madurez / lock-in

- **Madurez**: Alta para casos de uso batch. Comunidad muy activa, muchos ejemplos de producción.
- **Lock-in**: **BAJO**. Fácil de migrar los agents a otra arquitectura si es necesario.
- **Comunidad**: Muy grande, uno de los frameworks más populares en GitHub para multi-agente.
- **Riesgo de abandono**: Bajo — tiene una comunidad activa y backing de inversión.

---

### 6. Pydantic AI

#### Qué es

Pydantic AI resuelve un problema específico y crítico: **garantizar que el output del LLM tenga la estructura que el código espera**. Usa el mismo Pydantic V2 que ya usás para validar requests HTTP para definir el schema del output del agente. Si el LLM devuelve un JSON malformado o le falta un campo requerido, Pydantic AI detecta el error y **reintenta la llamada automáticamente** con feedback al modelo sobre qué estuvo mal.

La API de Pydantic AI es intencionalmente simple: un `Agent` con un modelo, un result type (schema Pydantic), system prompt, y tools. No hay grafos, no hay crews, no hay gestión de estado compleja. Es un wrapper potente sobre las APIs de LLM con foco en type safety.

La inyección de dependencias (`RunContext`) es elegante: podés inyectar sesiones de DB, clientes Redis, o cualquier objeto que las tools del agente necesiten, de manera type-safe y testeable.

#### Fortalezas clave

- **Output estructurado garantizado**: El resultado del agente es siempre un objeto Python tipado. No hay `json.loads(response.content)` frágiles.
- **Retry automático con feedback**: Si el LLM devuelve basura, Pydantic AI le explica el error y reintenta. Hasta 3 intentos por defecto, configurable.
- **Type safety end-to-end**: Desde la definición del agent hasta el consumo del resultado, todo está tipado. El IDE te dice si algo está mal.
- **Deps injection elegante**: `RunContext[MyDeps]` te da acceso type-safe a tus dependencias en las tools.
- **Multi-model**: Funciona con OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama — API unificada.
- **Más simple que LangGraph para flujos lineales**: Si tu flujo no necesita grafos ni routing complejo, Pydantic AI es menos overhead.
- **Excelente para testing**: La inyección de dependencias hace que mockear sea trivial.

#### Limitaciones reales

- **Estado conversacional multi-turn: manual**: No hay un sistema de checkpointing nativo como LangGraph. Si necesitás estado entre turnos, tenés que implementarlo vos.
- **No es un framework de orquestación**: No hay routing complejo, no hay multi-agente nativo (podés invocar agentes desde otros agentes, pero no es una primitiva del framework).
- **Flujos no lineales son verbosos**: Si el agente necesita tomar decisiones de routing basadas en el resultado de una tool, el código se complica porque no hay una abstracción para eso.
- **Relativamente nuevo**: Lanzado en 2024. Menos recursos, menos patterns de producción documentados.
- **Overkill para outputs simples**: Si el LLM solo necesita devolver texto libre sin estructura, el overhead de definir un schema Pydantic no vale la pena.

#### Casos de uso ideales

**1. Extracción de datos estructurados de documentos**  
Extraer datos de facturas, contratos, CVs, formularios — cualquier texto no estructurado que debe convertirse en datos tipados. El schema Pydantic define exactamente qué campos son requeridos y opcionales.

**2. Formularios conversacionales con validación**  
Un agente que captura datos de un usuario (nombre, email, fecha de nacimiento, dirección) y valida que cada campo sea válido. Si el usuario escribe una fecha en formato incorrecto, el schema la rechaza y el agente pide corrección.

**3. APIs de clasificación con output tipado**  
Un endpoint que clasifica tickets de soporte en `{category: str, priority: Literal["low", "medium", "high"], requires_escalation: bool}`. El schema garantiza que el LLM siempre devuelva exactamente esta estructura.

**4. Pipelines de enriquecimiento de datos**  
Enriquecer registros de CRM: dado un nombre y empresa, obtener información adicional (tamaño de empresa, industria, URL del website) con tipos definidos y validación.

**5. Generación de documentos estructurados**  
Generar reportes, proposals, o planes de proyecto con secciones bien definidas. El schema Pydantic asegura que cada sección requerida esté presente.

#### Casos donde NO usar

- Chatbots multi-turn sin output estructurado (innecesariamente complejo)
- Flujos con routing condicional complejo (no es su fortaleza)
- Pipelines multi-agente colaborativos (usar CrewAI o LangGraph)
- Casos donde el output es texto libre sin estructura (usar directamente la API del LLM)

#### Ejemplo de código mínimo

```python
from pydantic import BaseModel, EmailStr, field_validator
from pydantic_ai import Agent, RunContext
from dataclasses import dataclass
from datetime import date

# Schema de output — lo que el LLM DEBE devolver
class ContactInfo(BaseModel):
    name: str
    email: EmailStr  # validado por Pydantic
    company: str
    phone: str | None = None
    
    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El nombre no puede estar vacío")
        return v.strip().title()

class MeetingRequest(BaseModel):
    contact: ContactInfo
    requested_date: date
    duration_minutes: int  # Pydantic valida el tipo
    topic: str
    urgency: str  # "low" | "medium" | "high"

# Dependencias inyectables
@dataclass
class AppDeps:
    db_session: AsyncSession  # sesión de DB
    available_dates: list[date]

# Agente con output tipado
agent = Agent(
    model="openai:gpt-4o-mini",
    result_type=MeetingRequest,  # output garantizado
    deps_type=AppDeps,
    system_prompt="""
    Sos un asistente que extrae información de solicitudes de reunión.
    Siempre devolvés la información estructurada según el schema.
    """,
)

@agent.tool
async def check_date_availability(ctx: RunContext[AppDeps], date_str: str) -> bool:
    """Verifica si una fecha está disponible en el calendario."""
    # ctx.deps.available_dates es type-safe
    try:
        requested = date.fromisoformat(date_str)
        return requested in ctx.deps.available_dates
    except ValueError:
        return False

async def process_meeting_request(text: str, db: AsyncSession) -> MeetingRequest:
    deps = AppDeps(
        db_session=db,
        available_dates=[date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    )
    
    result = await agent.run(text, deps=deps)
    # result.data es un MeetingRequest tipado — SIEMPRE
    return result.data
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI, Anthropic, Gemini, Groq, Ollama (API unificada)
- **Validación**: Pydantic V2 (ya lo estás usando en tu FastAPI seguramente)
- **DB**: SQLAlchemy (inyectable como dep), asyncpg
- **API**: FastAPI (integración natural con Pydantic)
- **Testing**: pytest con mocks de deps

#### Nivel de madurez / lock-in

- **Madurez**: Media. Nuevo (2024) pero del equipo de Pydantic, que tiene track record excelente.
- **Lock-in**: **BAJO**. La migración es relativamente sencilla porque el core es simplemente "LLM → Pydantic schema".
- **Comunidad**: Creciendo rápido gracias a la popularidad de Pydantic.
- **Riesgo de abandono**: Bajo — Samuel Colvin (creador de Pydantic) está activamente involucrado.

---

### 7. Rasa

#### Qué es

Rasa es el framework de chatbots más maduro de esta lista, con raíces en NLU (Natural Language Understanding) clásico anterior a los LLMs. Su arquitectura separa claramente dos responsabilidades: el **pipeline de NLU** (entender qué dijo el usuario: intents y entidades) y el **dialogue management** (decidir qué responder basado en el contexto).

El dialogue management usa **Stories** (ejemplos de conversaciones correctas), **Rules** (comportamiento determinístico para casos específicos), y **Forms** (flujos de captura de datos paso a paso). Esta arquitectura hace que Rasa sea extremadamente predecible y auditable — podés trazar exactamente por qué el bot respondió lo que respondió.

La relación de Rasa con los LLMs es complicada. En las versiones clásicas, Rasa usa su propio pipeline de NLU (basado en transformers fine-tuned). En versiones recientes, CALM (Conversational AI with Language Models) intenta integrar LLMs de manera más nativa, pero la sensación es de un LLM como "ciudadano de segunda clase" injertado en una arquitectura diseñada sin él.

#### Fortalezas clave

- **Máximo control y determinismo**: Si definís una Story o Rule, el bot SIEMPRE sigue ese camino. Cero alucinaciones en el flujo de conversación.
- **Self-hosted y open source**: Cero dependencia de APIs externas. Compliance completo, datos nunca salen de tu infraestructura.
- **NLU propio**: No necesitás pagar por un LLM para clasificar intents. Para dominios con vocabulario muy específico, el NLU propio fine-tuneado puede superar a un LLM genérico.
- **Tracker Store**: Sistema de estado de conversación maduro y battle-tested.
- **Forms para captura de datos**: El sistema de Forms maneja flujos multi-step de captura de datos de manera robusta.
- **Madurez probada**: Rasa existe desde 2016. Hay miles de deployments en producción.
- **Bajo costo operativo**: Sin llamadas a LLMs caros para clasificación básica de intents.

#### Limitaciones reales

- **LLM como ciudadano de segunda clase**: La arquitectura de Rasa no fue diseñada para LLMs. Aunque CALM lo intenta, la integración se siente forzada comparada con frameworks como LangGraph o OpenAI Agents SDK.
- **Mantenimiento intensivo**: Agregar un nuevo intent requiere: agregar stories de entrenamiento, agregar reglas, reentrenar el modelo NLU. Para dominios que evolucionan rápido, esto es mucho overhead.
- **Generación de lenguaje natural limitada**: Los templates de respuesta son... templates. El texto es rígido y poco natural comparado con outputs de LLMs.
- **Curva de aprendizaje media-alta**: El framework tiene muchos conceptos propios (stories, rules, forms, slots, tracker, actions) que hay que aprender.
- **Escalabilidad de Actions Server**: Las Custom Actions corren en un servidor Python separado. Bajo carga alta, necesitás escalar ese servidor independientemente.
- **Comunidad estancada**: Tras la adquisición por parte de una empresa de e-learning, la comunidad open source perdió momentum. Muchos proyectos migraron a otros frameworks.

#### Casos de uso ideales

**1. Chatbots con intents muy bien definidos en dominio cerrado**  
Un asistente bancario que maneja 20 intents específicos (consultar saldo, transferir dinero, bloquear tarjeta, etc.) con vocabulario controlado. El NLU de Rasa fine-tuneado supera a un LLM genérico en precisión para este dominio.

**2. Compliance estricto con datos sensibles**  
Healthcare, bancos, gobierno — sectores donde los datos del usuario no pueden salir de la infraestructura propia. Rasa self-hosted garantiza cero datos a terceros.

**3. Presupuesto muy limitado para LLMs**  
Si el costo de tokens es una limitante real, Rasa sin LLM (NLU propio) puede manejar flujos simples con costo casi cero en inferencia.

**4. Flujos de captura de datos muy estructurados**  
Forms para recopilar información paso a paso (nombre, DNI, número de cuenta, monto) con validación en cada paso. El sistema de Forms de Rasa es robusto para este caso.

**5. Migración gradual de chatbots legacy**  
Si ya tenés un bot en Rasa y necesitás agregar capacidades LLM sin reescribir todo, CALM permite incorporar LLMs de manera incremental.

#### Casos donde NO usar

- Proyectos nuevos que empiezan hoy con LLMs (usar LangGraph u OpenAI Agents SDK)
- Dominios donde el lenguaje natural es muy variado y no estructurado
- Equipos pequeños que no pueden mantener el overhead de entrenamiento NLU
- Casos donde la calidad de generación de texto es crítica
- Proyectos que necesitan evolucionar el scope conversacional rápidamente

#### Ejemplo de código mínimo

```yaml
# domain.yml — Definición del dominio
version: "3.1"
intents:
  - saludar
  - reservar_turno
  - cancelar_turno
  - consultar_disponibilidad

entities:
  - servicio
  - fecha
  - hora

slots:
  servicio:
    type: text
    mappings:
      - type: from_entity
        entity: servicio
  fecha:
    type: text
    mappings:
      - type: from_entity
        entity: fecha

responses:
  utter_saludo:
    - text: "¡Hola! ¿En qué puedo ayudarte hoy?"
  utter_ask_servicio:
    - text: "¿Qué servicio querés reservar? (corte, tinte, peinado)"
  utter_ask_fecha:
    - text: "¿Para qué fecha querés el turno?"

forms:
  booking_form:
    required_slots:
      - servicio
      - fecha
```

```python
# actions/actions.py — Custom Actions Python
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

class ActionConfirmBooking(Action):
    def name(self) -> str:
        return "action_confirm_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict):
        servicio = tracker.get_slot("servicio")
        fecha = tracker.get_slot("fecha")
        
        # Lógica de negocio: crear reserva en DB
        booking_id = create_booking(servicio, fecha)
        
        dispatcher.utter_message(
            text=f"✅ Reserva confirmada! Tu {servicio} está agendado para el {fecha}. ID: {booking_id}"
        )
        return []
```

#### Stack tecnológico que combina bien

- **Infraestructura**: Docker, Kubernetes, on-premise
- **DB**: PostgreSQL, MySQL (Tracker Store), Redis (Lock Store)
- **NLU Models**: spaCy, transformers (BERT, RoBERTa fine-tuned)
- **Integración**: REST API, Slack, Telegram, WhatsApp Business API
- **LLM (opcional)**: OpenAI, Anthropic vía CALM

#### Nivel de madurez / lock-in

- **Madurez**: Muy alta — 8+ años en producción. Pero estancamiento en innovación post-adquisición.
- **Lock-in**: **ALTO**. La arquitectura de Stories/Rules/Forms es muy específica de Rasa. Migrar requiere reescribir la lógica de diálogo.
- **Comunidad**: Declinando respecto a su pico. Soporte enterprise es de pago.
- **Riesgo de abandono**: Medio. La empresa pivoteó a modelo enterprise. El open source recibe menos atención.

---

### 8. Arquitectura Custom: FSM + LLM calls directas

#### Qué es

A veces el mejor framework es no usar un framework. Una **Máquina de Estados Finitos (FSM)** con llamadas directas a la API del LLM puede ser más simple, más predecible, más barata y más debuggeable que cualquier framework de alto nivel.

La arquitectura es conceptualmente simple: una FSM determinística controla el flujo de la conversación (en qué estado estoy: GREETING, COLLECTING_DATA, CONFIRMING, DONE). El LLM tiene dos roles bien separados: **NLU** (clasificar el input del usuario: ¿qué intent es esto?) y **NLG** (generar la respuesta en lenguaje natural dado el estado actual y el contexto). El estado de la conversación es tuyo — lo guardás donde quieras, con el schema que quieras.

Esta arquitectura no es "primitiva" ni "no escalable". Es una elección deliberada de **trading complejidad de framework por control y simplicidad**. Para flujos conversacionales bien definidos, una FSM bien implementada tiene propiedades que ningún framework puede igualar: **transiciones determinísticas** (cero sorpresas de routing LLM-driven), **costo de tokens mínimo** (prompts cortos y focalizados), **debugging trivial** (el estado es una variable, no una caja negra).

#### Fortalezas clave

- **Cero alucinaciones en el flujo**: Las transiciones de estado son determinísticas. El LLM puede alucinar el contenido de una respuesta, pero NUNCA el flujo del proceso.
- **Debugging trivial**: El estado es una variable Python visible. Podés hacer `print(current_state)` y saber exactamente dónde está el sistema.
- **Costo de tokens mínimo**: En lugar de pasar el historial completo de mensajes al LLM en cada turno, pasás solo el contexto relevante para el estado actual. 10x más barato que enfoques con historial completo.
- **Máximo control**: Cada transición, cada validación, cada regla de negocio está explícita en tu código. No hay comportamiento "emergente" que no puedas predecir.
- **Sin dependencias pesadas**: Sin LangChain, sin Redis obligatorio, sin TypedDict. Solo tu código y la API del LLM.
- **Fácil de testear**: Cada función del FSM es testeable independientemente. Las transiciones son determinísticas, por lo que los tests son confiables.
- **Evolución incremental**: Podés agregar estados nuevos sin afectar los existentes. No hay acoplamiento oculto de un framework.

#### Limitaciones reales

- **Más código inicial**: Tenés que implementar la FSM, la persistencia de estado, y la lógica de transiciones vos. Los frameworks te dan esto gratis.
- **Escala mal para flujos muy complejos**: Una FSM con 30+ estados y transiciones cruzadas se vuelve difícil de mantener. Ahí LangGraph tiene ventaja.
- **No hay magia de framework**: Sin multi-agente nativo, sin human-in-the-loop nativo, sin evaluación integrada. Todo custom.
- **Requiere más decisiones de diseño**: ¿Cómo persisto el estado? ¿Cómo manejo los errores de clasificación del LLM? ¿Cómo versiono los estados? Tenés que decidir todo.
- **Más difícil de escalar el equipo**: Los frameworks tienen documentación, convenciones y comunidad. Una FSM custom tiene tu documentación.

#### Casos de uso ideales

**1. Flujos conversacionales muy bien definidos con pocos estados**  
Un bot de reservas para un salón de belleza con 5-6 estados (GREETING → SERVICE_SELECTION → STYLIST_SELECTION → DATE_SELECTION → CONFIRMATION → DONE) es perfectamente manejable con una FSM. Más simple y más confiable que LangGraph para este caso.

**2. Presupuesto de tokens muy limitado**  
Si cada turno de conversación te cuesta $0.01 en tokens con LangGraph (historial completo + state) pero $0.001 con una FSM (prompt focalizado al estado actual), en 10,000 conversaciones diarias la diferencia es $90 vs $9 por día. En un año: ~$33,000 de diferencia.

**3. Máximo control y auditoría**  
Sistemas financieros, healthcare, o gobierno donde cada decisión del bot debe ser explicable y auditable. Con una FSM, podés generar un log perfectamente determinístico de por qué el bot tomó cada decisión.

**4. Migración gradual de sistemas legacy**  
Cuando tenés un sistema legacy con lógica de negocio compleja y querés agregar capacidad conversacional sin reescribir todo. La FSM se integra como una capa delgada sobre el sistema existente.

**5. Teams pequeños o proyectos con recursos limitados**  
Un equipo de 2 personas que necesita entregar un chatbot funcional en 2 semanas no tiene tiempo para aprender LangGraph. Una FSM con llamadas directas a GPT-4o mini puede estar en producción en días.

#### Casos donde NO usar

- Flujos muy complejos con 30+ estados y transiciones no lineales (usar LangGraph)
- Multi-agente con especialistas que colaboran (usar CrewAI o OpenAI Agents SDK)
- Cuando el equipo ya tiene experiencia en LangGraph (no hay razón para reinventar)
- Casos donde la velocidad de desarrollo importa más que el control (frameworks dan más productividad inicial)

#### Ejemplo de código mínimo

```python
from enum import Enum, auto
from dataclasses import dataclass, field
from openai import AsyncOpenAI
import json

class BookingState(Enum):
    GREETING = auto()
    SERVICE_SELECTION = auto()
    DATE_SELECTION = auto()
    CONFIRMATION = auto()
    DONE = auto()

@dataclass
class ConversationContext:
    state: BookingState = BookingState.GREETING
    service: str | None = None
    date: str | None = None
    messages: list[dict] = field(default_factory=list)

client = AsyncOpenAI()

# NLU: el LLM SOLO clasifica, no controla el flujo
async def classify_intent(message: str, current_state: BookingState) -> dict:
    prompt = f"""
    Estado actual: {current_state.name}
    Mensaje del usuario: "{message}"
    
    Clasificá el intent. Devolvé JSON con:
    - intent: "select_service" | "select_date" | "confirm" | "cancel" | "other"
    - entities: {{ "service": str | null, "date": str | null }}
    
    Solo JSON, sin texto adicional.
    """
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=100,  # clasificación es barata
    )
    return json.loads(response.choices[0].message.content)

# FSM: transiciones DETERMINÍSTICAS
async def process_message(ctx: ConversationContext, user_message: str) -> str:
    # Agregar mensaje al historial
    ctx.messages.append({"role": "user", "content": user_message})
    
    # Clasificar intent (LLM solo para NLU)
    classification = await classify_intent(user_message, ctx.state)
    intent = classification["intent"]
    entities = classification["entities"]
    
    # Transiciones determinísticas — el FSM decide el flujo
    if ctx.state == BookingState.GREETING:
        ctx.state = BookingState.SERVICE_SELECTION
        response = "¡Hola! ¿Qué servicio querés reservar? Tenemos corte, tinte y peinado."
    
    elif ctx.state == BookingState.SERVICE_SELECTION:
        if entities.get("service"):
            ctx.service = entities["service"]
            ctx.state = BookingState.DATE_SELECTION
            response = f"Perfecto, {ctx.service}. ¿Para qué fecha?"
        else:
            response = "No entendí el servicio. ¿Es corte, tinte o peinado?"
    
    elif ctx.state == BookingState.DATE_SELECTION:
        if entities.get("date"):
            ctx.date = entities["date"]
            ctx.state = BookingState.CONFIRMATION
            response = f"Reserva de {ctx.service} para el {ctx.date}. ¿Confirmamos?"
        else:
            response = "¿Para qué fecha? Por ejemplo: 'el viernes 5 de abril'"
    
    elif ctx.state == BookingState.CONFIRMATION:
        if intent == "confirm":
            ctx.state = BookingState.DONE
            # Aquí va la lógica de negocio real
            booking_id = await create_booking(ctx.service, ctx.date)
            response = f"✅ Reserva confirmada! ID: {booking_id}"
        elif intent == "cancel":
            ctx.state = BookingState.GREETING
            response = "Cancelado. ¿Necesitás algo más?"
        else:
            response = "¿Confirmamos la reserva? Decí 'sí' o 'no'."
    
    else:
        response = "¡Hasta pronto!"
    
    # NLG: el LLM genera texto natural (opcional, podés usar templates)
    # Para mayor naturalidad:
    # response = await generate_natural_response(response, ctx.messages)
    
    ctx.messages.append({"role": "assistant", "content": response})
    return response

async def create_booking(service: str, date: str) -> str:
    # Lógica de negocio — llamada a DB, Google Calendar, etc.
    return f"BK-{hash(service + date) % 10000:04d}"
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI directamente (sin wrapper), Anthropic client, o cualquier API REST
- **Persistencia**: Redis (para estado de sesión), PostgreSQL (para historial), o incluso un dict en memoria para demos
- **API**: FastAPI, Flask — sin overhead de framework de agentes
- **Testing**: pytest, coverage.py — tests unitarios normales

#### Nivel de madurez / lock-in

- **Madurez**: La tuya. Tan madura como tu implementación.
- **Lock-in**: **MÍNIMO**. Sin dependencias de framework. Podés cambiar el LLM, la DB, o la API sin refactorizar la lógica de la FSM.
- **Comunidad**: No aplica — es tu código.
- **Riesgo de abandono**: Cero — sos el dueño de cada línea.

---

### 9. Microsoft Semantic Kernel

#### Qué es

Semantic Kernel (SK) es el framework de agentes de Microsoft, diseñado con C# como lenguaje primario y con integración profunda con el ecosistema Azure. Python es soportado pero es un ciudadano de segunda clase en términos de madurez de la API y ejemplos disponibles.

La arquitectura de SK gira en torno a tres conceptos: **Plugins** (grupos de functions/tools que el agente puede usar), **Memory** (embeddings para búsqueda semántica sobre documentos y datos) y **Planners** (el componente que descompone un goal en pasos usando los plugins disponibles). El Planner es la gran diferencia respecto a otros frameworks: en lugar de definir el routing explícitamente, le decís al Planner cuál es el goal y él determina qué steps ejecutar usando qué plugins.

Esta arquitectura es potente pero introduce **no-determinismo en el planeamiento**: si el Planner decide que para responder una pregunta de facturación necesita ejecutar 5 steps, y en producción esos 5 steps tienen un bug sutil, debuggear el problema es significativamente más difícil que en un sistema con routing explícito.

#### Fortalezas clave

- **Mejor integración con Azure OpenAI**: Si usás Azure OpenAI Service, SK tiene la mejor integración disponible, incluyendo content filtering, compliance y deployment management.
- **Planners para decomposición de goals**: Para tareas tipo "dado este goal complejo, descomponer en pasos" el Planner es una abstracción potente.
- **C# first — excelente para .NET backends**: Si tu backend es C#/.NET, SK es el framework más maduro disponible. La experiencia de desarrollo en C# es significativamente mejor que en Python.
- **Memory integrada**: Búsqueda semántica sobre documentos sin necesidad de configurar un vector store por separado.
- **Plugins reutilizables**: Los plugins son portables entre proyectos. El ecosistema tiene plugins para Gmail, Jira, Confluence, etc.
- **Enterprise-ready**: Microsoft mantiene SK activamente para sus propios productos. La estabilidad de la API es alta.

#### Limitaciones reales

- **Python como ciudadano de segunda clase**: La API Python tiene gaps respecto a C#. Ejemplos, docs y community Q&A son más escasos en Python.
- **Verboso**: Comparado con OpenAI Agents SDK o Pydantic AI, SK requiere más boilerplate para tareas simples.
- **Ecosistema más pequeño que LangChain**: Menos integraciones de terceros, menos plugins disponibles, menos recursos online.
- **Planner no-determinístico**: Para flujos críticos donde el routing debe ser predecible, el Planner agrega riesgo. Hay que validar que el Planner toma decisiones correctas consistentemente.
- **Lock-in conceptual con Microsoft**: La filosofía y terminología de SK es específica de Microsoft. Skills se llaman "Plugins", el State es "Context", etc. Migrar implica aprender una nueva terminología además de nuevo código.
- **Curva de aprendizaje media-alta**: Los conceptos propios (Kernel, Plugins, Planners, Memory) requieren tiempo para entender correctamente.

#### Casos de uso ideales

**1. Backends .NET/C# que necesitan capacidades de agente**  
Si la empresa ya tiene un backend en C# con .NET 8, Semantic Kernel es la opción natural. La integración con ASP.NET, Entity Framework y Azure Services es nativa.

**2. Empresas all-in en Azure con Azure OpenAI Service**  
Si el contrato de Microsoft incluye Azure OpenAI, y los datos deben permanecer en Azure (compliance), SK + Azure OpenAI es el stack natural.

**3. Agentes que necesitan consultar múltiples fuentes de conocimiento**  
La Memory integrada con embeddings permite que el agente consulte documentación interna, emails, tickets de Jira — todo en una interfaz unificada.

**4. Automatización de procesos empresariales tipo RPA**  
Workflows que interactúan con sistemas internos (ERP, CRM, legacy APIs) y necesitan descomponer goals complejos en steps. El Planner es ideal para esto.

**5. Integración con productos Microsoft (M365, Teams, Outlook)**  
Los plugins para productos Microsoft hacen que las integraciones con el ecosistema M365 sean mucho más simples que con otros frameworks.

#### Casos donde NO usar

- Backends Python-first sin Azure (usar LangGraph o OpenAI Agents SDK)
- Proyectos que necesitan iterar rápido con menos boilerplate (usar OpenAI Agents SDK)
- Flujos simples que no justifican el overhead de SK
- Equipos sin experiencia en el ecosistema Microsoft

#### Ejemplo de código mínimo

```python
# Python SDK — menos idiomático que C# pero funcional
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.functions import kernel_function
from semantic_kernel.core_plugins import TextPlugin

kernel = Kernel()

# Configurar Azure OpenAI
kernel.add_service(
    AzureChatCompletion(
        deployment_name="gpt-4o",
        endpoint="https://mi-empresa.openai.azure.com",
        api_key="...",
    )
)

# Plugin de negocio — grupo de functions relacionadas
class BookingPlugin:
    @kernel_function(
        name="check_availability",
        description="Verifica disponibilidad de turnos para una fecha y servicio"
    )
    def check_availability(self, date: str, service: str) -> str:
        # Lógica de negocio
        return f"Slots disponibles para {service} el {date}: 10:00, 14:00, 16:00"
    
    @kernel_function(
        name="create_booking",
        description="Crea una reserva en el sistema"
    )
    def create_booking(self, date: str, time: str, service: str) -> str:
        return f"Reserva creada: {service} el {date} a las {time}. ID: BK-001"

# Registrar plugin
kernel.add_plugin(BookingPlugin(), plugin_name="Booking")
kernel.add_plugin(TextPlugin(), plugin_name="Text")

# Usar con Chat Completion y Function Calling
async def run_booking_agent(user_input: str) -> str:
    from semantic_kernel.contents import ChatHistory
    
    chat_history = ChatHistory()
    chat_history.add_system_message(
        "Sos un asistente de reservas de salón de belleza. "
        "Usás las tools disponibles para gestionar turnos."
    )
    chat_history.add_user_message(user_input)
    
    # El kernel maneja el function calling automáticamente
    chat_service = kernel.get_service(type=AzureChatCompletion)
    settings = kernel.get_prompt_execution_settings_from_service_id("default")
    settings.function_choice_behavior = "auto"
    
    response = await chat_service.get_chat_message_content(
        chat_history=chat_history,
        settings=settings,
        kernel=kernel,
    )
    return str(response)
```

#### Stack tecnológico que combina bien

- **LLM**: Azure OpenAI Service (óptimo), OpenAI directo
- **Backend**: ASP.NET Core (C#, primera clase), FastAPI (Python, segunda clase)
- **Memory/Vector store**: Azure AI Search, Chroma, Qdrant
- **CI/CD**: Azure DevOps, GitHub Actions con Azure
- **Monitoring**: Azure Monitor, Application Insights

#### Nivel de madurez / lock-in

- **Madurez**: Alta en C#. Media en Python. Microsoft lo usa en sus propios productos.
- **Lock-in**: **ALTO con Azure**. Técnicamente multi-provider, pero optimizado para Azure OpenAI.
- **Comunidad**: Media-Grande. Respaldada por Microsoft con recursos significativos.
- **Riesgo de abandono**: Bajo — es estratégico para Microsoft AI.

---

### 10. LlamaIndex Workflows

#### Qué es

LlamaIndex nació como "la herramienta para hacer RAG sobre tus documentos". Con el tiempo, evolucionó para incluir Workflows: un sistema de steps basados en eventos que permite orquestar pipelines de procesamiento de información complejos. El concepto central es el **Event**: cada step del workflow emite eventos que disparan otros steps.

La fortaleza de LlamaIndex está en su ecosistema de conectores, loaders e indexers para fuentes de datos: PDFs, Notion, Confluence, Google Drive, bases de datos, APIs REST — hay conectores para prácticamente todo. El pipeline de RAG (ingest → chunk → embed → index → retrieve → synthesize) está optimizado y battle-tested.

Donde LlamaIndex es débil es en la dimensión conversacional multi-turn. El estado entre turnos de conversación no es una primitiva nativa — es posible implementarlo, pero es más verboso que en LangGraph o ADK.

#### Fortalezas clave

- **Ecosistema de data connectors sin rival**: 100+ loaders para fuentes de datos. Si necesitás indexar documentos de cualquier tipo, LlamaIndex lo tiene.
- **RAG optimizado**: El pipeline de retrieval y síntesis está optimizado para calidad. Múltiples estrategias: HyDE, reranking, sentence window retrieval.
- **Workflows reactivos**: El modelo de eventos permite pipelines donde los steps se disparan por eventos, no solo en secuencia.
- **Multi-modal**: Soporte para imágenes, PDFs con imágenes, tablas — no solo texto.
- **Evaluación de calidad RAG**: Métricas integradas (faithfulness, relevance, answer_similarity) para evaluar la calidad del pipeline.
- **Integración con vector stores populares**: Pinecone, Weaviate, Qdrant, pgvector, Chroma — todos soportados.

#### Limitaciones reales

- **Conversacional multi-turn débil**: El framework no está optimizado para diálogos. El estado entre turnos requiere implementación manual más verbosa que LangGraph.
- **Complejidad creciente**: LlamaIndex empezó simple y fue creciendo. La API tiene capas de abstracción que a veces confunden: Pipelines, Workflows, QueryEngines, ChatEngines — ¿cuál usar?
- **Overhead de embeddings**: Para casos donde no necesitás RAG (chatbots simples, pipelines de clasificación), el overhead de indexing y embedding es innecesario.
- **Latencia alta en retrieval**: El pipeline de RAG agrega latencia: embed query → search vector store → rerank → synthesize. Para respuestas en tiempo real, puede ser problemático.
- **Menor comunidad que LangChain**: Aunque es popular, LangChain tiene más integraciones, más ejemplos y más community support.

#### Casos de uso ideales

**1. Chatbot sobre documentos internos de empresa**  
Un asistente que responde preguntas sobre políticas de RRHH, manuales técnicos, o wikis internas. El usuario pregunta en lenguaje natural, el sistema busca en los documentos indexados y sintetiza la respuesta.

**2. Q&A sobre bases de conocimiento grandes**  
Un sistema de soporte que responde preguntas basándose en una base de conocimiento de 10,000 artículos. LlamaIndex maneja el indexing, la búsqueda semántica y la síntesis.

**3. Análisis de documentos legales o técnicos**  
Un agente que analiza contratos, especificaciones técnicas o informes financieros, responde preguntas específicas y extrae información clave.

**4. Pipelines de ingest y procesamiento de información**  
Un pipeline que ingesta artículos de noticias diariamente, los clasifica, los indexa y permite búsqueda semántica sobre el corpus.

**5. Sistemas de investigación asistida**  
Un asistente de investigación que puede consultar múltiples bases de datos (PDFs, web, APIs) en paralelo y sintetizar la información para responder preguntas complejas.

#### Casos donde NO usar

- Chatbots conversacionales sin base de conocimiento (usar LangGraph o OpenAI Agents SDK)
- Flujos de booking o CRM sin componente de RAG (usar FSM custom o LangGraph)
- Casos donde la latencia es crítica y no se puede pre-indexar (usar llamadas LLM directas)
- Multi-agente con roles y colaboración (usar CrewAI)

#### Ejemplo de código mínimo

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.core.workflow import Workflow, step, StartEvent, StopEvent
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.workflow import Event

# Configurar LLM y embeddings
Settings.llm = OpenAI(model="gpt-4o-mini")
Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")

# Indexar documentos
documents = SimpleDirectoryReader("./docs").load_data()
index = VectorStoreIndex.from_documents(documents)

# Workflow con eventos para pipeline complejo
class QueryEvent(Event):
    query: str

class RetrievalEvent(Event):
    query: str
    retrieved_nodes: list

class DocumentQAWorkflow(Workflow):
    
    def __init__(self, index: VectorStoreIndex):
        super().__init__(timeout=60)
        self.query_engine = index.as_query_engine(
            similarity_top_k=5,
            response_mode="tree_summarize",
        )
    
    @step
    async def process_query(self, event: StartEvent) -> QueryEvent:
        """Preprocesar y validar la query del usuario."""
        query = event.query
        # Podés hacer preprocessing: expand query, detect language, etc.
        return QueryEvent(query=query)
    
    @step
    async def retrieve_and_synthesize(self, event: QueryEvent) -> StopEvent:
        """Recuperar documentos relevantes y sintetizar respuesta."""
        response = await self.query_engine.aquery(event.query)
        
        # Metadata de los nodos usados para generar la respuesta
        sources = [
            {
                "file": node.metadata.get("file_name"),
                "score": node.score,
            }
            for node in response.source_nodes
        ]
        
        return StopEvent(result={
            "answer": str(response),
            "sources": sources,
            "query": event.query,
        })

# Usar el workflow
async def answer_question(question: str) -> dict:
    workflow = DocumentQAWorkflow(index=index)
    result = await workflow.run(query=question)
    return result

# Ejemplo de uso
import asyncio
result = asyncio.run(answer_question("¿Cuál es la política de vacaciones?"))
print(f"Respuesta: {result['answer']}")
print(f"Fuentes: {result['sources']}")
```

#### Stack tecnológico que combina bien

- **LLM**: OpenAI GPT-4o, Anthropic Claude, Gemini
- **Vector Stores**: Pinecone, Weaviate, Qdrant, pgvector (PostgreSQL)
- **Data Sources**: PDFs, Notion, Confluence, GitHub, Google Drive (100+ connectors)
- **Embeddings**: OpenAI, Cohere, sentence-transformers (local)
- **API**: FastAPI para exponer el workflow como endpoint

#### Nivel de madurez / lock-in

- **Madurez**: Alta para RAG. Media para Workflows.
- **Lock-in**: **BAJO**. Los documentos indexados y la lógica de negocio son portables.
- **Comunidad**: Grande y activa.
- **Riesgo de abandono**: Bajo — LlamaIndex Inc. tiene financiamiento sólido.

---

## Matriz de Decisión

Evaluación de cada framework en las dimensiones clave. Escala: ✅ Excelente | ⚠️ Aceptable | ❌ Débil/No aplica

| Framework | Multi-turn Conversacional | Estado Rico Tipado | Routing Complejo | Multi-agente | Output Estructurado | RAG/Documentos | Batch Tasks | Automatización Código | Self-hosted | Curva Aprendizaje | Costo Tokens |
|-----------|--------------------------|-------------------|-----------------|--------------|--------------------|--------------------|-------------|----------------------|-------------|-------------------|--------------|
| **LangGraph** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ❌ | ✅ | Alta (días) | Medio |
| **OpenAI Agents SDK** | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ⚠️ | Baja (horas) | Medio |
| **Google ADK** | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ⚠️ | Media (días) | Medio |
| **Anthropic Agent SDK** | ❌ | ❌ | ❌ | ✅ | ❌ | ⚠️ | ✅ | ✅ | ⚠️ | Media (días) | Alto |
| **CrewAI** | ❌ | ❌ | ❌ | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | Muy Baja (horas) | Alto |
| **Pydantic AI** | ⚠️ | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | Baja (horas) | Bajo |
| **Rasa** | ✅ | ⚠️ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | Alta (semanas) | Mínimo |
| **FSM Custom** | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ⚠️ | ❌ | ✅ | Baja | Mínimo |
| **Semantic Kernel** | ⚠️ | ⚠️ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ❌ | ⚠️ | Media-Alta (días) | Medio |
| **LlamaIndex Workflows** | ⚠️ | ❌ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ❌ | ✅ | Media (días) | Medio |

### Matriz de lock-in y madurez

| Framework | Lock-in | Madurez Producción | Riesgo Abandono | Comunidad |
|-----------|---------|-------------------|-----------------|-----------|
| **LangGraph** | Alto (LangChain) | Alta | Bajo | Muy Grande |
| **OpenAI Agents SDK** | Medio (OpenAI) | Media-Alta | Bajo | Grande |
| **Google ADK** | Alto (GCP) | Media (1.x) | Bajo-Medio | Mediana |
| **Anthropic Agent SDK** | Alto (Claude) | Media | Bajo | Pequeña |
| **CrewAI** | Bajo | Alta (batch) | Bajo | Muy Grande |
| **Pydantic AI** | Bajo | Media | Bajo | Grande |
| **Rasa** | Alto (Rasa) | Muy Alta | Medio | Mediana (declinando) |
| **FSM Custom** | Mínimo | Tu código | Cero | N/A |
| **Semantic Kernel** | Alto (Azure) | Alta (C#) | Bajo | Grande |
| **LlamaIndex Workflows** | Bajo | Media-Alta | Bajo | Grande |

---

## Árbol de Decisión

```
¿Para qué necesitás el agente?
│
├─── AUTOMATIZACIÓN DE CÓDIGO / CI-CD
│    └─── → Anthropic Agent SDK
│
├─── PROCESAMIENTO DE DOCUMENTOS / RAG
│    ├─── ¿Necesitás responder preguntas sobre documentos?
│    │    └─── → LlamaIndex Workflows
│    └─── ¿Necesitás extraer datos estructurados de documentos?
│         └─── → Pydantic AI
│
├─── TASKS EN LOTE (batch, sin interacción en tiempo real)
│    ├─── ¿Múltiples agentes con roles colaborando?
│    │    └─── → CrewAI
│    ├─── ¿El output debe ser estructurado y validado?
│    │    └─── → Pydantic AI
│    └─── ¿Stack Azure / .NET?
│         └─── → Semantic Kernel
│
└─── CHATBOT CONVERSACIONAL (multi-turn, tiempo real)
     │
     ├─── ¿Qué tan complejo es el flujo?
     │    │
     │    ├─── MUY SIMPLE (< 6 estados, flujo bien definido)
     │    │    ├─── ¿Presupuesto de tokens limitado?
     │    │    │    └─── → FSM Custom + LLM directo
     │    │    ├─── ¿Máximo control y auditoría?
     │    │    │    └─── → FSM Custom + LLM directo
     │    │    └─── ¿Entregar rápido sin complejidad técnica?
     │    │         └─── → OpenAI Agents SDK
     │    │
     │    └─── COMPLEJO (routing condicional, múltiples modos)
     │         ├─── ¿Stack GCP / Gemini nativo?
     │         │    └─── → Google ADK
     │         ├─── ¿Compliance + self-hosted + intents muy definidos?
     │         │    └─── → Rasa
     │         ├─── ¿Múltiples agentes especializados con handoffs?
     │         │    └─── → OpenAI Agents SDK
     │         └─── ¿Estado rico tipado + routing complejo + Python?
     │              └─── → LangGraph
     │
     ├─── ¿Stack .NET / Azure?
     │    └─── → Semantic Kernel
     │
     └─── ¿El output de cada turno debe ser estructurado?
          └─── → Pydantic AI (con estado manual)
```

---

## Casos de Uso Empresariales Prácticos

### 1. E-commerce: Asistente de Compras

**Escenario**: Un e-commerce de moda necesita un asistente en WhatsApp que ayude a encontrar productos, verificar tallas, consultar disponibilidad y guiar hasta el checkout.

**Recomendación: LangGraph**

El flujo tiene múltiples estados (navegación por catálogo → selección de producto → talla → disponibilidad → carrito → checkout) con estado rico que debe persistir entre turnos. El routing es condicional: si el producto no está en stock, redirigir a productos similares. LangGraph modela exactamente este flujo con sus modos y conditional edges. Redis checkpointer mantiene el carrito del usuario entre sesiones.

**Alternativa viable**: OpenAI Agents SDK con agentes especializados (búsqueda de productos, gestión de carrito, checkout).

---

### 2. Salón de Belleza: Sistema de Reservas

**Escenario**: Bot de WhatsApp para agendar turnos con 5 estilistas, manejar cancelaciones y enviar recordatorios.

**Recomendación: FSM Custom + LLM directo** (o LangGraph para mayor escala)

El flujo es simple y bien definido: 5-6 estados máximo. Las transiciones son determinísticas (no puede confirmar sin fecha, no puede dar fecha sin servicio). El presupuesto de tokens es relevante para un negocio pequeño. Una FSM custom es más simple de debuggear cuando algo falla a las 2am. Si el negocio escala a múltiples sucursales o necesita integrarse con Google Calendar y CRM, migrar a LangGraph.

---

### 3. Soporte Técnico Nivel 1

**Escenario**: Un SaaS necesita un agente que responda el 80% de los tickets de soporte comunes antes de escalar al equipo humano.

**Recomendación: OpenAI Agents SDK + LlamaIndex**

Usar OpenAI Agents SDK para la lógica conversacional (handoff al agente humano cuando el bot no puede resolver) combinado con LlamaIndex para RAG sobre la base de conocimiento de documentación técnica. El agente busca en la documentación, intenta resolver, y hace handoff si la confianza es baja o el issue es complejo.

---

### 4. Generación de Contenido Editorial

**Escenario**: Una agencia de contenidos necesita generar 100 artículos de blog por semana sobre diferentes temas, con research, redacción y revisión.

**Recomendación: CrewAI**

El flujo es batch (no conversacional), multi-agente con roles claros (researcher, writer, SEO specialist, editor), y la escala requiere procesar en paralelo. CrewAI modela perfectamente este caso. El proceso hierarchical permite que un manager agent coordine la profundidad de la investigación según el tema.

---

### 5. Análisis de Documentos Legales / Contratos

**Escenario**: Un estudio jurídico necesita un sistema que analice contratos, extraiga cláusulas clave, identifique riesgos y genere un resumen ejecutivo.

**Recomendación: LlamaIndex Workflows + Pydantic AI**

LlamaIndex para el ingesta y búsqueda semántica sobre el corpus de contratos. Pydantic AI para garantizar que la extracción de cláusulas y riesgos tenga la estructura requerida (`{clause_type: str, risk_level: Literal["low", "medium", "high"], recommendation: str}`). La combinación garantiza tanto la calidad del retrieval como la estructura del output.

---

### 6. Code Review Automatizado en CI/CD

**Escenario**: Un equipo de engineering necesita revisiones automáticas de código en cada PR — verificar convenciones, detectar bugs potenciales, generar sugerencias.

**Recomendación: Anthropic Agent SDK**

Este es exactamente el caso de uso para el que fue diseñado el Claude Agent SDK. Tools nativas de filesystem (Read, Glob, Edit), hooks para controlar qué acciones se ejecutan, sub-agentes para análisis paralelo de múltiples archivos. Claude 3.7 Sonnet tiene las mejores capacidades de análisis de código disponibles.

---

### 7. Onboarding de Empleados

**Escenario**: RRHH quiere un asistente que guíe a nuevos empleados a través del proceso de onboarding: documentación, beneficios, políticas, configuración de herramientas.

**Recomendación: LlamaIndex Workflows + OpenAI Agents SDK**

LlamaIndex para las preguntas sobre documentación interna (políticas, manuales, FAQs). OpenAI Agents SDK para el flujo conversacional guiado (handoffs entre agentes especializados en distintos aspectos del onboarding). Sesiones persistentes para retomar el onboarding si el empleado se desconecta.

**Alternativa simple**: Si el onboarding tiene un flujo muy guiado y la organización es pequeña, una FSM custom puede ser suficiente.

---

### 8. Análisis de Datos y Reportes

**Escenario**: Un equipo de datos quiere que analistas puedan hacer preguntas en lenguaje natural sobre datasets y obtener respuestas con visualizaciones.

**Recomendación: Pydantic AI + pandas/DuckDB**

El agente recibe una pregunta en lenguaje natural, genera una query SQL/pandas (output estructurado garantizado por Pydantic), la ejecuta contra la base de datos, y sintetiza los resultados en lenguaje natural. Pydantic AI garantiza que la query generada tenga la estructura correcta antes de ejecutarla.

---

### 9. CRM: Seguimiento de Leads

**Escenario**: Un equipo de ventas quiere un asistente que enriquezca leads automáticamente, sugiera próximos pasos y genere emails personalizados.

**Recomendación: OpenAI Agents SDK**

Los handoffs entre agentes especializados son perfectos: agente de enriquecimiento (busca info sobre el lead), agente de análisis (evalúa fit), agente de acción (sugiere siguiente paso o genera email). Las sesiones guardan el contexto del lead entre interacciones. La baja curva de aprendizaje es ideal para un equipo de ventas que quiere moverse rápido.

---

### 10. Healthcare: Triaje de Síntomas

**Escenario**: Un sistema de salud quiere un chatbot inicial que capture síntomas del paciente y determine si necesita atención urgente, programar cita, o puede auto-tratarse.

**Recomendación: FSM Custom + LLM directo** (con supervisión médica obligatoria)

**Advertencia importante**: Cualquier sistema de triaje médico requiere validación y supervisión clínica. Dicho esto, técnicamente: la FSM garantiza que el flujo de captura de síntomas sea determinístico y auditable. Los criterios de urgencia son reglas explícitas en el código, no decisiones del LLM. El LLM solo se usa para NLU (entender lo que dice el paciente en lenguaje natural) y NLG (formular las preguntas de manera empática). Cero alucinaciones en el flujo de decisión clínica. Rasa es otra opción válida aquí por su determinismo y la opción de self-hosting.

---

## Anti-patterns comunes

### 1. LangGraph para flujos simples

**El error**: Usar LangGraph con 3 nodos y 1 conditional edge para un chatbot de FAQ de 10 preguntas.

**El problema**: Semanas de setup, curva de aprendizaje alta, overhead de Redis checkpointer, bugs con reducers que aparecen en producción. Todo eso para un caso que se resuelve con un script de 50 líneas.

**La solución**: Evaluar honestamente la complejidad del flujo. Si tenés menos de 6 estados y el routing es simple, una FSM custom o Pydantic AI es suficiente.

---

### 2. CrewAI para chatbots multi-turn

**El error**: Usar CrewAI para un asistente conversacional de atención al cliente.

**El problema**: CrewAI no tiene estado conversacional. Cada mensaje del usuario inicia un nuevo run de la Crew desde cero. El "bot" no recuerda lo que el usuario dijo hace 2 turnos.

**La solución**: Usar LangGraph, OpenAI Agents SDK, o incluso una FSM custom para flujos conversacionales. CrewAI es para batch processing.

---

### 3. Anthropic Agent SDK para chatbots de usuario final

**El error**: Intentar construir un asistente de soporte al cliente con el Claude Agent SDK porque "Claude es el mejor modelo para esto".

**El problema**: El SDK no tiene las primitivas para diálogos conversacionales con usuarios. No hay sistema de turns, no hay manejo de intent routing, no hay sessions orientadas a conversación. El modelo puede ser excelente, pero el framework es incorrecto.

**La solución**: Usar Claude como modelo con OpenAI Agents SDK (multi-provider), LangGraph, o cualquier framework conversacional. El Anthropic SDK es para tareas de código, no para diálogos.

---

### 4. No evaluar costo de tokens antes de elegir arquitectura

**El error**: Elegir un framework que pasa el historial completo de la conversación al LLM en cada turno sin calcular el costo operativo.

**El problema**: Una conversación de 20 turnos con historial completo puede costar 10x más tokens que una arquitectura con estado que solo pasa el contexto relevante. En escala, la diferencia puede ser miles de dólares al mes.

**La solución**: Antes de elegir, estimar: tokens promedio por turno × turnos por conversación × conversaciones por día × costo por token. Una FSM custom con prompts focalizados puede ser 10x más barata que LangGraph con historial completo.

---

### 5. Framework multi-agente para un problema de un solo agente

**El error**: Usar CrewAI con 5 agentes para una tarea que un solo agente con 3 tools puede hacer mejor y más barato.

**El problema**: Cada agente en un crew es una llamada al LLM con su propio contexto. 5 agentes en serie = 5 llamadas al LLM en donde podría haber 1. La latencia se multiplica, el costo se multiplica, y los puntos de falla se multiplican.

**La solución**: Empezar siempre con el mínimo viable: un agente con tools. Solo agregar múltiples agentes cuando la especialización real lo justifica (los agentes necesitan contextos o capacidades genuinamente distintos, no solo roles distintos).

---

### 6. Rasa para proyectos nuevos en 2025

**El error**: Elegir Rasa para un proyecto nuevo porque "tiene mucha documentación y es enterprise".

**El problema**: Rasa tiene un overhead significativo de mantenimiento (entrenamiento de NLU, stories, reglas), la integración con LLMs se siente forzada, y la comunidad open source perdió momentum tras la adquisición. Los frameworks basados en LLMs ofrecen mejor experiencia con menos overhead.

**La solución**: Solo elegir Rasa si hay una razón específica: compliance extremo con self-hosting, equipo con experiencia previa en Rasa, o necesidad de NLU sin costos de LLM. Para proyectos nuevos, LangGraph u OpenAI Agents SDK son mejores puntos de partida.

---

### 7. Confiar en routing LLM-driven sin fallbacks

**El error**: Usar un Planner de Semantic Kernel o LLM-driven transfer de Google ADK para flujos críticos sin validación de las decisiones del LLM.

**El problema**: Los LLMs son estocásticos. En producción, eventualmente el Planner va a decidir un step incorrecto o el agente va a hacer un transfer inesperado. Sin fallbacks explícitos, el sistema falla de manera silenciosa y difícil de debuggear.

**La solución**: Para flujos críticos, preferir routing determinístico (LangGraph conditional edges, FSM). Si usás LLM-driven routing, agregar validación explícita sobre las decisiones del LLM y logging detallado de cada decisión de routing.

---

### 8. Ignorar la observabilidad desde el inicio

**El error**: Construir un agente en producción sin logging estructurado de los turnos de conversación, las decisiones de routing, y los errores.

**El problema**: Cuando el bot falla en producción a las 11pm del viernes, si no tenés logs estructurados no podés saber qué pasó. "El bot dijo algo raro" no es un bug report debuggeable.

**La solución**: Desde el inicio, loguear en cada turno: el estado entrante, el intent clasificado, las tools llamadas, el estado saliente, y el tiempo de respuesta. LangSmith (LangGraph), OpenTelemetry, o incluso logs JSON simples — cualquier cosa es mejor que nada.

---

## Conclusión

El ecosistema de frameworks de agentes IA es rico, diverso y en constante evolución. No existe un framework universalmente superior — cada uno es una respuesta a un conjunto específico de constraints y requerimientos.

### Las 3 preguntas para elegir en 5 minutos

**Pregunta 1: ¿Es conversacional multi-turn o batch?**
- Si es batch → CrewAI (multi-agente), Pydantic AI (output estructurado), LlamaIndex (documentos)
- Si es conversacional → seguir al punto 2

**Pregunta 2: ¿Qué tan complejo es el flujo?**
- Flujo simple (≤6 estados) + control máximo → FSM Custom
- Flujo simple + entregar rápido → OpenAI Agents SDK
- Flujo complejo + Python → LangGraph
- Flujo complejo + GCP → Google ADK
- Stack .NET/Azure → Semantic Kernel

**Pregunta 3: ¿Hay requerimientos especiales?**
- Automatización de código → Anthropic Agent SDK
- Compliance + self-hosted + sin LLM → Rasa
- Output estructurado garantizado → Pydantic AI
- RAG sobre documentos → LlamaIndex

### Principio de diseño final

> **Empieza simple. Escala cuando el problema lo justifica.**

La tentación de usar el framework más sofisticado desde el inicio es un anti-pattern común. LangGraph es poderoso, pero si tu flujo tiene 4 estados y 3 conditional edges, la FSM custom que escribís en un día te va a dar más control y menos problemas que LangGraph configurado en una semana.

La complejidad de un framework debe estar justificada por la complejidad del problema. Un chatbot de reservas para una peluquería no necesita la misma arquitectura que el asistente conversacional de un banco con 50 intents y 200,000 usuarios diarios. Elegir el framework correcto es elegir el nivel de abstracción apropiado para el problema que tenés hoy, con capacidad de evolución para el problema que podrías tener mañana.

---

*Documento generado en base a análisis técnico y experiencia práctica de producción.*  
*Los frameworks evolucionan rápidamente — verificar versiones y changelogs antes de decisiones arquitectónicas.*
