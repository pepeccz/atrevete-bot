# Sistema de FAQs - Atrévete Bot

## Resumen

El sistema de FAQs de Atrévete Bot proporciona respuestas automáticas a preguntas frecuentes de los clientes mediante una arquitectura híbrida que combina respuestas estáticas rápidas con generación personalizada basada en IA.

**Fuente única de verdad:** Base de datos PostgreSQL (tabla `policies`)

## Arquitectura del Sistema

### Componentes Principales

```
┌─────────────────────────────────────────────────────────┐
│ BASE DE DATOS (PostgreSQL)                              │
│ Tabla: policies                                          │
│ ├─ key: "faq:hours"                                     │
│ ├─ key: "faq:parking"                                   │
│ ├─ key: "faq:address"                                   │
│ ├─ key: "faq:cancellation_policy"                       │
│ └─ key: "faq:payment_info"                              │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ FLUJO DE DETECCIÓN Y RESPUESTA                          │
│                                                          │
│ 1. detect_faq_intent (agent/nodes/faq.py)              │
│    └─ Claude clasifica el mensaje del cliente           │
│                                                          │
│ 2. route_after_faq_detection (conversation_flow.py)    │
│    ├─ Simple (1 FAQ) → answer_faq                       │
│    └─ Compuesta (2+ FAQs) → fetch_faq_context          │
│                                                          │
│ 3A. answer_faq (agent/nodes/faq.py)                    │
│     └─ Respuesta estática directa de BD                 │
│                                                          │
│ 3B. fetch_faq_context → generate_personalized_response  │
│     └─ Respuesta generada con IA usando datos de BD    │
└─────────────────────────────────────────────────────────┘
```

### Estrategia Híbrida

El sistema usa dos estrategias según la complejidad de la consulta:

#### 1. Consulta Simple (1 FAQ)
```
Cliente: "¿Qué horario tenéis?"
         ↓
detect_faq_intent → ["hours"]
         ↓
answer_faq (estático)
         ↓
Consulta BD: faq:hours
         ↓
Respuesta directa (rápida, sin coste IA)
```

**Ventajas:**
- Respuesta instantánea
- Sin consumo de tokens de IA
- Consistente

#### 2. Consulta Compuesta (2+ FAQs)
```
Cliente: "¿Dónde estáis y a qué hora abrís?"
         ↓
detect_faq_intent → ["address", "hours"]
         ↓
fetch_faq_context
         ↓
Consulta BD: faq:address, faq:hours
         ↓
generate_personalized_faq_response
         ↓
Claude genera respuesta cohesiva
         ↓
Respuesta personalizada y natural
```

**Ventajas:**
- Respuesta natural y fluida
- Combina múltiples FAQs coherentemente
- Adapta tono al cliente
- Incluye nombre del cliente

## Estructura de Datos en BD

### Tabla: `policies`

```sql
CREATE TABLE policies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Formato de FAQ en JSONB

```json
{
    "faq_id": "hours",
    "question_patterns": [
        "¿qué horario tenéis?",
        "¿abrís los sábados?",
        "¿cuándo abren?",
        "¿hasta qué hora?"
    ],
    "answer": "Estamos abiertos de lunes a viernes de 10:00 a 20:00, y los sábados de 10:00 a 14:00 🌸. Los domingos cerramos para descansar 😊.",
    "category": "general",
    "requires_location_link": false
}
```

### Campos Explicados

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `faq_id` | string | Identificador único de la FAQ |
| `question_patterns` | array | Variaciones de preguntas que activan esta FAQ |
| `answer` | string | Respuesta base que se mostrará al cliente |
| `category` | string | Categoría de la FAQ (general, policies, services) |
| `requires_location_link` | boolean | Si true, agrega automáticamente enlace Google Maps |

## FAQs Disponibles

### 1. Horarios (`faq:hours`)
- **Categoría:** general
- **Enlace de ubicación:** No
- **Ejemplo de pregunta:** "¿Qué horario tenéis?"

### 2. Aparcamiento (`faq:parking`)
- **Categoría:** general
- **Enlace de ubicación:** No
- **Ejemplo de pregunta:** "¿Hay parking?"

### 3. Ubicación (`faq:address`)
- **Categoría:** general
- **Enlace de ubicación:** Sí
- **Ejemplo de pregunta:** "¿Dónde estáis?"

### 4. Política de Cancelación (`faq:cancellation_policy`)
- **Categoría:** policies
- **Enlace de ubicación:** No
- **Ejemplo de pregunta:** "¿Puedo cancelar mi cita?"

### 5. Información de Pago (`faq:payment_info`)
- **Categoría:** policies
- **Enlace de ubicación:** No
- **Ejemplo de pregunta:** "¿Cómo se paga?"

## Cómo Actualizar Respuestas de FAQs

### Opción 1: Mediante SQL Directo

```sql
-- Actualizar respuesta de horarios
UPDATE policies
SET value = jsonb_set(
    value,
    '{answer}',
    '"Estamos abiertos de lunes a viernes de 9:00 a 21:00, y los sábados de 10:00 a 14:00 🌸. Los domingos cerramos para descansar 😊."'::jsonb
),
updated_at = NOW()
WHERE key = 'faq:hours';
```

```sql
-- Actualizar respuesta de parking
UPDATE policies
SET value = jsonb_set(
    value,
    '{answer}',
    '"Sí 😊, hay parking público gratuito muy cerca en Calle Nueva y también zona azul en la calle principal. Es fácil encontrar sitio 🚗."'::jsonb
),
updated_at = NOW()
WHERE key = 'faq:parking';
```

### Opción 2: Mediante Script Python

Crear un script de actualización:

```python
# scripts/update_faq.py
import asyncio
from sqlalchemy import select, update
from database.models import Policy
from database.session import get_session

async def update_faq_answer(faq_id: str, new_answer: str):
    """
    Actualiza la respuesta de una FAQ específica.

    Args:
        faq_id: ID de la FAQ (ej: "hours", "parking")
        new_answer: Nueva respuesta
    """
    async with get_session() as session:
        faq_key = f"faq:{faq_id}"

        result = await session.execute(
            select(Policy).where(Policy.key == faq_key)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            print(f"❌ FAQ '{faq_id}' no encontrada")
            return

        # Actualizar el campo 'answer' en el JSONB
        policy.value['answer'] = new_answer

        # Marcar como modificado
        from sqlalchemy.orm import attributes
        attributes.flag_modified(policy, 'value')

        await session.commit()
        print(f"✅ FAQ '{faq_id}' actualizada correctamente")

# Ejemplo de uso
if __name__ == "__main__":
    asyncio.run(update_faq_answer(
        faq_id="hours",
        new_answer="Estamos abiertos de lunes a viernes de 9:00 a 21:00, y los sábados de 10:00 a 14:00 🌸. Los domingos cerramos para descansar 😊."
    ))
```

### Opción 3: Mediante Consola Admin (Futuro)

Se puede crear un panel de administración que permita actualizar FAQs visualmente.

## Cómo Agregar una Nueva FAQ

### Paso 1: Crear el Seed

Agregar a `database/seeds/faqs.py`:

```python
{
    "key": "faq:new_service",
    "value": {
        "faq_id": "new_service",
        "question_patterns": [
            "¿hacéis extensiones?",
            "¿tenéis extensiones de pelo?",
            "extensiones",
        ],
        "answer": "Sí, ofrecemos servicio de extensiones de pelo 💇. Tenemos varios tipos: naturales, sintéticas y keratina. ¿Te gustaría agendar una consulta gratuita para asesorarte? 😊",
        "category": "services",
        "requires_location_link": False,
    },
    "description": "FAQ sobre servicio de extensiones de pelo",
}
```

### Paso 2: Ejecutar Seeds

```bash
# Desde el directorio raíz del proyecto
python -m database.seeds.faqs
```

O manualmente con SQL:

```sql
INSERT INTO policies (key, value, description)
VALUES (
    'faq:new_service',
    '{
        "faq_id": "new_service",
        "question_patterns": ["¿hacéis extensiones?", "extensiones"],
        "answer": "Sí, ofrecemos servicio de extensiones de pelo 💇...",
        "category": "services",
        "requires_location_link": false
    }'::jsonb,
    'FAQ sobre servicio de extensiones de pelo'
)
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    updated_at = NOW();
```

### Paso 3: Actualizar Prompt de Clasificación (Opcional)

Si quieres mejorar la detección, actualiza el prompt en `agent/nodes/faq.py:33-169` para incluir la nueva categoría:

```python
classification_prompt = f"""Analiza el siguiente mensaje del cliente...

Categorías de FAQ disponibles:
- hours: Horarios de apertura/cierre
- parking: Información sobre estacionamiento
- address: Ubicación o dirección del salón
- cancellation_policy: Política de cancelación y reembolsos
- payment_info: Información sobre pagos y anticipos
- new_service: Servicio de extensiones de pelo  # ← NUEVA
"""
```

**Nota:** Claude es lo suficientemente inteligente para detectar nuevas FAQs sin necesidad de actualizar el prompt si los `question_patterns` son descriptivos.

## Proceso de Generación con IA

### System Prompt

El system prompt para generación está en `agent/nodes/faq_generation.py:104-287`:

```python
system_prompt = """Eres Maite, la asistente virtual del salón de belleza Atrévete.

Tu personalidad:
- Cálida, cercana y profesional
- Usas "tú" (nunca "usted")
- Incluyes emojis de forma natural pero sin exceso (🌸 😊 ✨)
- Eres concisa pero completa

Tu tarea es responder a preguntas frecuentes (FAQs) de forma personalizada y natural."""
```

### User Prompt Dinámico

```python
user_prompt = f"""El cliente ha preguntado:
"{latest_user_message}"

Información disponible para responder:
{faq_knowledge_text}  # ← Datos de BD inyectados aquí

Instrucciones:
1. Responde a TODAS las preguntas del mensaje en una sola respuesta cohesionada
2. Usa un tono {customer_tone} pero siempre cálido
3. Si se requiere enlace de ubicación, incluye: https://maps.google.com/?q=Atrévete+Peluquería+La+Línea
4. Máximo 150 palabras
5. Termina con: "¿Hay algo más en lo que pueda ayudarte? 😊"
6. IMPORTANTE: Saluda al cliente por su nombre ({customer_name}) al inicio
"""
```

### Validaciones de Seguridad

El sistema incluye varias validaciones automáticas:

1. **Respuesta muy corta (<20 caracteres):**
   - Fallback a respuesta estática

2. **Respuesta muy larga (>200 palabras):**
   - Trunca a última oración completa dentro del límite

3. **Error en generación:**
   - Fallback automático a `answer_faq` (estático)

## Diagrama de Flujo Completo

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CLIENTE ENVÍA MENSAJE                                    │
│    "¿Dónde estáis ubicados y a qué hora abrís?"            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. detect_faq_intent (agent/nodes/faq.py:33-169)           │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ - Extrae último mensaje del usuario                 │ │
│    │ - Llama a Claude con prompt de clasificación        │ │
│    │ - Claude responde: ["address", "hours"]             │ │
│    │ - Clasifica complejidad: "compound"                 │ │
│    └─────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. route_after_faq_detection (conversation_flow.py:270)    │
│                                                              │
│    ¿FAQ detectada? NO → extract_intent                     │
│         │ SÍ                                                │
│         ▼                                                   │
│    ¿Complejidad?                                            │
│         ├─ SIMPLE (1 FAQ) → answer_faq (estático)          │
│         └─ COMPOUND (2+ FAQs) → fetch_faq_context          │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                  │
        ▼ (SIMPLE)                         ▼ (COMPOUND)
┌───────────────────────┐     ┌──────────────────────────────┐
│ 4A. answer_faq        │     │ 4B. fetch_faq_context        │
│ (faq.py:172-276)      │     │ (faq_generation.py:28-101)   │
│                       │     │                              │
│ - Consulta BD:        │     │ for faq_id in FAQs:          │
│   faq:hours           │     │   - Consulta: faq:address    │
│ - Obtiene respuesta   │     │   - Consulta: faq:hours      │
│ - Agrega Maps si      │     │ - Almacena en faq_context    │
│   corresponde         │     └───────────┬──────────────────┘
│ - Agrega "¿Algo más?" │                 │
└───────┬───────────────┘                 ▼
        │         ┌──────────────────────────────────────────┐
        │         │ 5. generate_personalized_faq_response    │
        │         │ (faq_generation.py:104-287)              │
        │         │                                          │
        │         │ - Detecta tono del cliente               │
        │         │ - Construye faq_knowledge desde BD       │
        │         │ - System prompt: Eres Maite...           │
        │         │ - User prompt: Responde a TODAS...       │
        │         │ - Claude genera respuesta cohesiva       │
        │         │ - Validaciones (longitud, etc.)          │
        │         │ - Fallback si error → answer_faq         │
        │         └───────────┬──────────────────────────────┘
        │                     │
        └─────────┬───────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. RESPUESTA FINAL AL CLIENTE                               │
│                                                              │
│ Simple:                                                      │
│ "Estamos abiertos de lunes a viernes de 10:00 a 20:00,     │
│  y los sábados de 10:00 a 14:00 🌸.                         │
│  ¿Hay algo más en lo que pueda ayudarte? 😊"               │
│                                                              │
│ Compuesta:                                                   │
│ "¡Hola Laura! 🌸 Estamos en La Línea de la Concepción:     │
│  📍 https://maps.google.com/...                             │
│  Nuestro horario es de lunes a viernes de 10:00 a 20:00,   │
│  y los sábados de 10:00 a 14:00. Los domingos descansamos  │
│  😊. ¿Hay algo más en lo que pueda ayudarte? 😊"           │
└─────────────────────────────────────────────────────────────┘
```

## Archivos Clave

| Archivo | Propósito |
|---------|-----------|
| `database/models.py:501-538` | Modelo SQLAlchemy de la tabla `policies` |
| `database/seeds/faqs.py` | Seeds con las 5 FAQs iniciales |
| `agent/nodes/faq.py:33-169` | Detección de FAQs con Claude |
| `agent/nodes/faq.py:172-276` | Respuesta estática (FAQ simple) |
| `agent/nodes/faq_generation.py:28-101` | Fetch de contexto de múltiples FAQs |
| `agent/nodes/faq_generation.py:104-287` | Generación personalizada con IA |
| `agent/graphs/conversation_flow.py:270-319` | Routing híbrido (simple vs compuesto) |
| `agent/prompts/maite_system_prompt.md:303-349` | Instrucciones generales sobre FAQs |

## Ventajas de Este Sistema

### 1. Fuente Única de Verdad
- ✅ Todas las respuestas vienen de BD
- ✅ Sin duplicación de contenido
- ✅ Sin inconsistencias

### 2. Actualización Fácil
- ✅ Actualizar BD = actualizar todas las respuestas
- ✅ No requiere cambios de código
- ✅ No requiere redeploy

### 3. Escalabilidad
- ✅ Agregar nuevas FAQs = insertar en BD
- ✅ Claude detecta automáticamente nuevas categorías
- ✅ Sistema se adapta sin modificaciones

### 4. Eficiencia
- ✅ FAQs simples: respuesta instantánea, sin coste IA
- ✅ FAQs compuestas: generación inteligente solo cuando es necesario
- ✅ Fallback robusto en caso de errores

### 5. Personalización
- ✅ Detecta tono del cliente (formal vs. informal)
- ✅ Incluye nombre del cliente en respuestas
- ✅ Adapta estilo según contexto
- ✅ Combina múltiples FAQs de forma natural

## Troubleshooting

### Problema: FAQ no se detecta

**Posibles causas:**
1. Los `question_patterns` no cubren la variación de la pregunta
2. El cliente usó terminología muy diferente

**Solución:**
```sql
-- Agregar más patrones a la FAQ
UPDATE policies
SET value = jsonb_set(
    value,
    '{question_patterns}',
    value->'question_patterns' || '["nueva variación", "otra forma"]'::jsonb
)
WHERE key = 'faq:hours';
```

### Problema: Respuesta generada es muy larga

**Causa:** Claude ignora el límite de 150 palabras

**Solución:** El sistema trunca automáticamente respuestas largas (líneas 241-274 de `faq_generation.py`)

### Problema: Respuesta no incluye enlace de Google Maps

**Causa:** El campo `requires_location_link` está en `false`

**Solución:**
```sql
UPDATE policies
SET value = jsonb_set(
    value,
    '{requires_location_link}',
    'true'::jsonb
)
WHERE key = 'faq:address';
```

### Problema: FAQ devuelve error

**Causa:** Registro no existe en BD o formato JSONB incorrecto

**Solución:** Verificar que el registro existe y tiene el formato correcto:
```sql
SELECT key, value FROM policies WHERE key LIKE 'faq:%';
```

## Mejoras Futuras

### 1. Panel de Administración
- Interfaz visual para gestionar FAQs
- CRUD completo sin necesidad de SQL
- Preview de respuestas

### 2. Analítica de FAQs
- Contador de veces que se usa cada FAQ
- Detección de preguntas no cubiertas
- Sugerencias de nuevas FAQs

### 3. A/B Testing
- Probar diferentes versiones de respuestas
- Medir satisfacción del cliente
- Optimizar redacción

### 4. Soporte Multiidioma
- FAQs en inglés, francés, etc.
- Detección automática de idioma
- Respuestas localizadas

### 5. FAQ Contextual
- Respuestas diferentes según historial del cliente
- Personalización basada en servicios previos
- Sugerencias proactivas

## Conclusión

El sistema de FAQs de Atrévete Bot es:
- **Dinámico:** Datos en BD, fácil actualización
- **Híbrido:** Estático para rapidez, IA para personalización
- **Escalable:** Agregar FAQs sin cambiar código
- **Robusto:** Fallbacks automáticos en caso de errores
- **Eficiente:** Solo usa IA cuando es necesario

Para cualquier duda o problema, consulta los archivos del código fuente listados en la sección "Archivos Clave".
