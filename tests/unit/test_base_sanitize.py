from agent.modes.base import BaseModeNode


def test_sanitize_response_preserves_tool_call_text() -> None:
    # QF-4: _TOOL_CALL_PATTERN was removed — bracketed identifiers are no longer stripped.
    text = '[manage_customer(action="create", phone="+34623226544")] Hola, soy Maite.'

    result = BaseModeNode._sanitize_response(text)

    assert "manage_customer" in result
    assert result == text


def test_sanitize_response_preserves_multiple_bracketed_expressions() -> None:
    # QF-4: Multiple bracketed expressions are preserved as-is.
    text = "Hola [manage_customer(action='create')] mundo [escalate_to_human(reason='x')] ahora"

    result = BaseModeNode._sanitize_response(text)

    assert "manage_customer" in result
    assert "escalate_to_human" in result
    assert result == text


def test_sanitize_response_keeps_clean_text() -> None:
    text = "Hola, en que puedo ayudarte hoy?"

    assert BaseModeNode._sanitize_response(text) == text


def test_sanitize_response_preserves_plain_bracketed_identifier() -> None:
    # QF-4: Plain bracketed identifiers like [not_a_tool] are no longer stripped.
    text = "[not_a_tool] Seguimos con la conversacion"

    result = BaseModeNode._sanitize_response(text)

    assert "[not_a_tool]" in result
    assert result == text


def test_sanitize_response_preserves_numeric_references() -> None:
    # QF-4 bug fix: [3]-style numeric references must NOT be stripped.
    # The old _TOOL_CALL_PATTERN incorrectly removed these alongside tool call patterns.
    text = "Tenés [3] opciones disponibles"

    result = BaseModeNode._sanitize_response(text)

    assert result == "Tenés [3] opciones disponibles"
