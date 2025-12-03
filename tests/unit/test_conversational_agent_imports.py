"""
Test de regresión para conversational agent imports.

Este test previene la regresión del UnboundLocalError causado por imports locales
de IntentType dentro de la función conversational_agent.

Fecha del bug original: 2025-12-03
Error: UnboundLocalError: cannot access local variable 'IntentType' where it is not associated with a value
Línea: agent/nodes/conversational_agent.py:154
"""

import inspect

import pytest

from agent.fsm.models import Intent, IntentType
from agent.nodes.conversational_agent import conversational_agent


def test_intent_type_imported_at_module_level():
    """
    Verifica que IntentType está importado al nivel del módulo,
    no dentro de la función conversational_agent.

    Este test previene que alguien mueva accidentalmente el import
    de IntentType dentro de la función (causando UnboundLocalError).
    """
    # Get source code of the conversational_agent module
    import agent.nodes.conversational_agent as module

    source = inspect.getsource(module)
    lines = source.split("\n")

    # Verify that IntentType is imported at module level (before any function definitions)
    found_module_level_import = False
    found_function_def = False

    for line in lines:
        # Check if we've reached a function definition
        if line.startswith("def ") or line.startswith("async def "):
            found_function_def = True

        # Check for IntentType import at module level (before functions)
        if "from agent.fsm.models import" in line and "IntentType" in line:
            if not found_function_def:
                found_module_level_import = True
                break

    assert found_module_level_import, (
        "IntentType debe estar importado al nivel del módulo, "
        "no dentro de funciones. Esto previene UnboundLocalError."
    )


def test_no_local_imports_in_conversational_agent():
    """
    Verifica que NO hay imports locales de IntentType dentro de
    la función conversational_agent.

    Imports locales dentro de funciones causan confusión de scoping
    y pueden resultar en UnboundLocalError.
    """
    # Get source code of conversational_agent function only
    source = inspect.getsource(conversational_agent)
    lines = source.split("\n")

    # Look for local imports of IntentType within the function
    for i, line in enumerate(lines, start=1):
        # Skip the function definition line
        if i == 1:
            continue

        # Check for local imports (indented import statements)
        if "    from agent.fsm.models import" in line and "IntentType" in line:
            pytest.fail(
                f"Import local de IntentType detectado en línea {i} de conversational_agent:\n"
                f"{line.strip()}\n\n"
                "IntentType debe importarse al nivel del módulo, no dentro de funciones.\n"
                "Imports locales causan UnboundLocalError cuando se accede a la variable\n"
                "antes de que se ejecute la línea del import."
            )


@pytest.mark.asyncio
async def test_conversational_agent_handles_simple_greeting():
    """
    Test end-to-end que verifica que conversational_agent puede procesar
    un mensaje simple sin UnboundLocalError.

    Este es el caso de prueba que falló originalmente:
    - Usuario: "Holaa"
    - FSM state: service_selection
    - Intent extraído: faq
    - Error: UnboundLocalError en línea 154
    """
    # Setup: Estado inicial con mensaje del usuario
    state = {
        "conversation_id": "test-unbound-error-regression",
        "customer_id": "test-customer-123",
        "customer_phone": "+34612345678",
        "whatsapp_name": "Test User",
        "messages": [
            {
                "role": "user",
                "content": "Holaa",
                "timestamp": "2025-12-03T19:15:00+01:00",
            }
        ],
        "fsm_state": {
            "conversation_id": "test-unbound-error-regression",
            "state": "service_selection",
            "collected_data": {},
            "context": {},
        },
        "escalated": False,
        "escalation_reason": None,
    }

    # Act: Procesar mensaje (debería ejecutar línea 154 sin UnboundLocalError)
    try:
        result = await conversational_agent(state)

        # Assert: Verificar que no hubo error y se generó una respuesta
        assert "messages" in result, "El resultado debe contener 'messages'"
        assert len(result["messages"]) == 2, "Debe haber 2 mensajes (user + assistant)"
        assert result["messages"][-1]["role"] == "assistant", "Último mensaje debe ser del assistant"
        assert len(result["messages"][-1]["content"]) > 0, "La respuesta no debe estar vacía"

        # Verificar que el FSM state fue persistido
        assert "fsm_state" in result, "El resultado debe contener 'fsm_state'"

    except UnboundLocalError as e:
        pytest.fail(
            f"UnboundLocalError detectado en conversational_agent:\n"
            f"{str(e)}\n\n"
            "Esto indica que hay un problema de scoping con imports locales.\n"
            "Verifica que todos los imports estén al nivel del módulo."
        )


@pytest.mark.asyncio
async def test_intent_type_validation_executes_without_error():
    """
    Test específico para la línea 154 que causó el error original:
    `if not isinstance(intent.type, IntentType):`

    Esta línea debe poder ejecutarse sin UnboundLocalError.
    """
    # Setup: Estado que forzará la ejecución de la línea 154
    state = {
        "conversation_id": "test-line-154",
        "customer_id": "test-customer",
        "customer_phone": "+34612345678",
        "whatsapp_name": "Test User",
        "messages": [
            {
                "role": "user",
                "content": "Test message",
                "timestamp": "2025-12-03T19:15:00+01:00",
            }
        ],
        "fsm_state": None,  # Primera interacción
        "escalated": False,
        "escalation_reason": None,
    }

    # Act & Assert: No debe lanzar UnboundLocalError
    try:
        result = await conversational_agent(state)
        assert "messages" in result
        assert result["messages"][-1]["role"] == "assistant"
    except UnboundLocalError as e:
        pytest.fail(
            f"UnboundLocalError en línea de validación de intent.type:\n{str(e)}\n"
            "IntentType debe estar accesible antes de cualquier bloque except."
        )


def test_intent_and_intenttype_both_imported():
    """
    Verifica que tanto Intent como IntentType están importados
    juntos al nivel del módulo (best practice).
    """
    import agent.nodes.conversational_agent as module

    source = inspect.getsource(module)

    # Check that both Intent and IntentType are imported in the same line
    import_line_found = False
    for line in source.split("\n"):
        if "from agent.fsm.models import" in line:
            if "Intent" in line and "IntentType" in line:
                import_line_found = True
                break

    assert import_line_found, (
        "Intent e IntentType deben importarse juntos al nivel del módulo:\n"
        "from agent.fsm.models import Intent, IntentType"
    )
