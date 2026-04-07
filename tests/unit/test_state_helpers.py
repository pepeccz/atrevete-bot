"""
Unit tests for agent/state/helpers.py — get_last_user_message()

Task 4.1: agent-state-architecture-fix
"""

from agent.state.helpers import get_last_user_message


def test_get_last_user_message_empty_messages():
    state = {"messages": []}
    assert get_last_user_message(state) == ""


def test_get_last_user_message_no_messages_key():
    state = {}
    assert get_last_user_message(state) == ""


def test_get_last_user_message_returns_last_user():
    state = {
        "messages": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola!"},
            {"role": "user", "content": "Quiero una cita"},
        ]
    }
    assert get_last_user_message(state) == "Quiero una cita"


def test_get_last_user_message_skips_assistant():
    state = {
        "messages": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "Respuesta"},
        ]
    }
    assert get_last_user_message(state) == "Hola"


def test_get_last_user_message_handles_none_content():
    state = {"messages": [{"role": "user", "content": None}]}
    assert get_last_user_message(state) == "None"


def test_get_last_user_message_only_assistant_messages():
    """No user messages → returns empty string."""
    state = {
        "messages": [
            {"role": "assistant", "content": "¡Hola! ¿En qué te puedo ayudar?"},
        ]
    }
    assert get_last_user_message(state) == ""


def test_get_last_user_message_multiple_user_messages_returns_last():
    """Returns the LAST user message, not the first."""
    state = {
        "messages": [
            {"role": "user", "content": "Primera"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "Segunda"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "Tercera"},
        ]
    }
    assert get_last_user_message(state) == "Tercera"


def test_get_last_user_message_ignores_missing_role():
    """Messages without role field are skipped."""
    state = {
        "messages": [
            {"content": "Sin rol"},
            {"role": "user", "content": "Con rol"},
        ]
    }
    assert get_last_user_message(state) == "Con rol"
