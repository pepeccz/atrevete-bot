from agent.modes.base import BaseModeNode


def test_sanitize_response_strips_tool_call_text() -> None:
    text = '[manage_customer(action="create", phone="+34623226544")] Hola, soy Maite.'

    result = BaseModeNode._sanitize_response(text)

    assert "manage_customer" not in result
    assert result == "Hola, soy Maite."


def test_sanitize_response_strips_multiple_tool_calls() -> None:
    text = "Hola [manage_customer(action='create')] mundo [escalate_to_human(reason='x')] ahora"

    result = BaseModeNode._sanitize_response(text)

    assert "manage_customer" not in result
    assert "escalate_to_human" not in result
    assert result == "Hola  mundo  ahora"


def test_sanitize_response_keeps_clean_text() -> None:
    text = "Hola, en que puedo ayudarte hoy?"

    assert BaseModeNode._sanitize_response(text) == text


def test_sanitize_response_strips_plain_bracketed_identifier() -> None:
    text = "[not_a_tool] Seguimos con la conversacion"

    result = BaseModeNode._sanitize_response(text)

    assert "[not_a_tool]" not in result
    assert result == "Seguimos con la conversacion"
