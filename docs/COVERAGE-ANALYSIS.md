# Coverage Analysis - Tarea 4.4

**Fecha**: 2025-11-27
**Objetivo**: Identificar gaps y alcanzar 85%+ overall coverage
**Estado**: Análisis inicial

---

## Estructura del Proyecto

### Módulos a Cubrir (según pyproject.toml)

1. **agent/** - Core agent logic
2. **shared/** - Shared utilities
3. **database/** - Database models and connections

### Módulos Excluidos
- `admin/*` - Django admin (deferred)
- `*/tests/*` - Test code
- `*/migrations/*` - Alembic migrations

---

## Inventario de Archivos

### Agent Module (29 archivos Python)

#### FSM (6 archivos)
```
agent/fsm/
├── __init__.py                 ✅ Exports only
├── booking_fsm.py              🔄 Partial coverage (nuevos tests agregados)
├── intent_extractor.py         ⚠️  Needs review
├── models.py                   ✅ Data classes (low priority)
├── response_validator.py       ⚠️  Needs review
└── tool_validation.py          ⚠️  Needs review
```

**Tests existentes:**
- `tests/unit/test_booking_fsm.py` ✅
- `tests/unit/test_intent_extractor.py` ✅
- `tests/unit/test_response_validator.py` ✅
- `tests/unit/test_tool_validation.py` ✅
- `tests/integration/test_booking_flow_complete.py` ✅ (nuevo)
- `tests/integration/scenarios/test_duration_enrichment.py` ✅ (nuevo)

**Coverage estimada**: 70-80% (mejorada con nuevos tests)

#### Graphs (2 archivos)
```
agent/graphs/
├── __init__.py                 ✅ Exports only
└── conversation_flow.py        ⚠️  Integration tests only
```

**Tests existentes:**
- `tests/integration/test_agent_flow.py` ✅
- `tests/integration/test_fsm_llm_integration.py` ✅

**Coverage estimada**: 50-60% (integration tests only)

#### Nodes (3 archivos)
```
agent/nodes/
├── __init__.py                 ✅ Exports only
├── conversational_agent.py     🔄 Partial coverage (refactored)
└── summarization.py            ⚠️  Needs review
```

**Tests existentes:**
- `tests/unit/test_conversation_summarization.py` ✅
- `tests/unit/test_process_incoming_message.py` ✅
- `tests/integration/test_long_conversation_summarization.py` ✅

**Coverage estimada**: 60-70%

#### Validators (3 archivos) - ⭐ NEW
```
agent/validators/
├── __init__.py                 ✅ Exports only
├── slot_validator.py           ✅ 100% (nuevo, 7 tests)
└── transaction_validators.py   ⚠️  Needs unit tests
```

**Tests existentes:**
- `tests/unit/test_slot_validator.py` ✅ (nuevo)
- `tests/unit/test_category_validation.py` ✅

**Coverage estimada**: 80% (nuevo módulo bien testeado)
**Gap**: transaction_validators.py necesita tests directos

#### Tools (9 archivos)
```
agent/tools/
├── __init__.py                 ✅ Exports only
├── availability_tools.py       ⚠️  Integration tests only
├── booking_tools.py            ✅ Unit + integration
├── calendar_tools.py           ✅ Unit tests
├── customer_tools.py           ⚠️  Needs more coverage
├── escalation_tools.py         ❌ No tests found
├── info_tools.py               ⚠️  Needs review
├── notification_tools.py       ❌ No tests found
└── search_services.py          ⚠️  Needs review
```

**Tests existentes:**
- `tests/unit/test_booking_tools.py` ✅
- `tests/unit/test_calendar_tools.py` ✅

**Coverage estimada**: 40-50%
**Gaps críticos:**
- `escalation_tools.py` - Sin tests
- `notification_tools.py` - Sin tests
- `customer_tools.py` - Coverage parcial

#### Transactions (2 archivos)
```
agent/transactions/
├── __init__.py                 ✅ Exports only
└── booking_transaction.py      ⚠️  Integration tests only
```

**Tests existentes:**
- `tests/integration/test_transactional_models.py` ✅

**Coverage estimada**: 60-70%
**Gap**: Necesita unit tests para validators individuales

#### State (4 archivos)
```
agent/state/
├── __init__.py                 ✅ Exports only
├── checkpointer.py             ✅ Integration tests
├── helpers.py                  ⚠️  Needs unit tests
└── schemas.py                  ✅ Data classes (low priority)
```

**Tests existentes:**
- `tests/integration/test_checkpoint_persistence.py` ✅
- `tests/unit/test_message_windowing.py` ✅

**Coverage estimada**: 70%

#### Utils (2 archivos)
```
agent/utils/
├── date_parser.py              ❌ No tests found
└── monitoring.py               ❌ No tests found
```

**Coverage estimada**: 0%
**Gap crítico**: Utils sin tests

#### Prompts (1 archivo)
```
agent/prompts/
└── __init__.py                 ✅ Unit tests
```

**Tests existentes:**
- `tests/unit/test_prompt_loading.py` ✅
- `tests/unit/test_prompt_injection.py` ✅
- `tests/unit/test_prompt_optimization_v32.py` ✅

**Coverage estimada**: 90%+

---

### Shared Module (8 archivos activos)

```
shared/
├── __init__.py                       ✅ Exports only
├── archive_retrieval.py              ⚠️  Integration tests only
├── audio_conversion.py               ❌ No tests (low priority)
├── audio_transcription.py            ❌ No tests (low priority)
├── business_hours_validator.py       ✅ Unit tests
├── chatwoot_client.py                ⚠️  Integration tests only
├── config.py                         ✅ Used everywhere (implicit)
├── logging_config.py                 ✅ Implicit coverage
├── redis_client.py                   ✅ Unit tests
└── resilient_api.py                  ❌ No tests found
```

**Tests existentes:**
- `tests/unit/test_business_hours_validator.py` ✅
- `tests/unit/test_redis_client.py` ✅
- `tests/unit/test_archival_logic.py` ✅

**Coverage estimada**: 50-60%
**Gaps:**
- `resilient_api.py` - Sin tests
- `audio_*` - Baja prioridad (features secundarias)

---

### Database Module (3 archivos activos)

```
database/
├── __init__.py                 ✅ Exports only
├── connection.py               ✅ Integration tests (implicit)
├── models.py                   ✅ Unit + integration tests
└── seeds/                      ⚠️  Excluded from coverage
```

**Tests existentes:**
- `tests/unit/test_database_models.py` ✅
- `tests/integration/test_transactional_models.py` ✅

**Coverage estimada**: 80%+

---

## Coverage Gaps Identificados

### 🔴 Críticos (Sin tests)

1. **agent/utils/date_parser.py**
   - Parsing de fechas en español
   - Usado en multiple places
   - **Prioridad**: P0

2. **agent/utils/monitoring.py**
   - Logging y métricas
   - **Prioridad**: P2 (monitoring, not critical)

3. **agent/tools/escalation_tools.py**
   - Handoff a humanos
   - **Prioridad**: P1

4. **agent/tools/notification_tools.py**
   - Notificaciones
   - **Prioridad**: P1

5. **shared/resilient_api.py**
   - Retry logic para APIs
   - **Prioridad**: P1

### 🟡 Parciales (< 70% coverage estimado)

1. **agent/nodes/conversational_agent.py**
   - Nodo principal, muy complejo
   - Coverage parcial con integration tests
   - **Gap**: Edge cases sin cubrir

2. **agent/transactions/booking_transaction.py**
   - Lógica transaccional crítica
   - Coverage via integration tests
   - **Gap**: Unit tests para validators

3. **agent/validators/transaction_validators.py**
   - Validators de negocio
   - Coverage indirecto
   - **Gap**: Unit tests directos

4. **agent/tools/customer_tools.py**
   - CRUD de customers
   - **Gap**: Edge cases

5. **agent/graphs/conversation_flow.py**
   - Orquestación LangGraph
   - **Gap**: Solo integration tests

### 🟢 Buenos (> 70% coverage estimado)

1. ✅ **agent/validators/slot_validator.py** (100%)
2. ✅ **agent/prompts/__init__.py** (90%+)
3. ✅ **database/models.py** (80%+)
4. ✅ **shared/business_hours_validator.py** (90%+)
5. ✅ **agent/fsm/booking_fsm.py** (70-80%)

---

## Plan de Acción para Alcanzar 85%

### Fase A: Quick Wins (1-2 horas)

**Objetivo**: Agregar tests para utils críticos

1. **Test date_parser.py**
   - Casos: español, formatos múltiples, timezone
   - Estimado: 30 min
   - Impact: +2-3% coverage

2. **Test escalation_tools.py**
   - Casos: handoff creation, metadata
   - Estimado: 20 min
   - Impact: +1-2% coverage

3. **Test notification_tools.py**
   - Casos: envío de mensajes
   - Estimado: 20 min
   - Impact: +1-2% coverage

**Total Phase A**: +4-7% coverage

### Fase B: Validators y Transactions (2-3 horas)

**Objetivo**: Cubrir lógica crítica de negocio

1. **Unit tests para transaction_validators.py**
   - `validate_3_day_rule()` - edge cases
   - `validate_category_consistency()` - mix scenarios
   - `validate_slot_availability()` - race conditions
   - Estimado: 1 hora
   - Impact: +3-4% coverage

2. **Unit tests para booking_transaction.py**
   - Atomicity tests
   - Rollback scenarios
   - Error handling
   - Estimado: 1 hora
   - Impact: +2-3% coverage

3. **Test resilient_api.py**
   - Retry logic
   - Timeout handling
   - Estimado: 30 min
   - Impact: +1-2% coverage

**Total Phase B**: +6-9% coverage

### Fase C: Edge Cases (2-3 horas)

**Objetivo**: Cubrir edge cases en módulos parcialmente testeados

1. **customer_tools.py edge cases**
   - Duplicate detection
   - Invalid phone numbers
   - Estimado: 30 min
   - Impact: +1-2% coverage

2. **conversational_agent.py edge cases**
   - Error recovery
   - Invalid tool responses
   - Estimado: 1 hora
   - Impact: +2-3% coverage

3. **conversation_flow.py unit tests**
   - Graph construction
   - Edge routing
   - Estimado: 30 min
   - Impact: +1-2% coverage

**Total Phase C**: +4-7% coverage

---

## Estimación Final

### Coverage Actual (Estimado)
- **Agent**: ~65%
- **Shared**: ~55%
- **Database**: ~80%
- **Overall**: ~65-70%

### Coverage Objetivo
- **Target**: 85%+
- **Gap**: ~15-20%

### Plan Total
- **Phase A**: +4-7% (quick wins)
- **Phase B**: +6-9% (validators)
- **Phase C**: +4-7% (edge cases)
- **Total ganancia**: +14-23%
- **Coverage final proyectado**: 79-93%

### Tiempo Estimado
- **Phase A**: 1-2 horas
- **Phase B**: 2-3 horas
- **Phase C**: 2-3 horas
- **Total**: 5-8 horas (1 día de trabajo)

---

## Priorización Recomendada

### Must-Have (para alcanzar 85%)
1. ✅ Phase A completa
2. ✅ Phase B completa
3. ⚠️  Phase C parcial (2-3 items)

### Nice-to-Have (para exceder 85%)
1. Phase C completa
2. Integration tests adicionales
3. Performance tests

---

## Próximos Pasos

1. **Ejecutar coverage report real**
   ```bash
   ./scripts/run-tests-with-coverage.sh
   firefox htmlcov/index.html
   ```

2. **Validar estimaciones** contra report real

3. **Implementar Phase A** (quick wins)

4. **Re-evaluar** después de Phase A

5. **Implementar Phase B y C** según necesidad

---

**Última actualización**: 2025-11-27 23:55 CET
**Autor**: Claude Code
**Estado**: Análisis completo, listo para ejecución
