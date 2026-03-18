from agent.routing.intent_router import classify_by_keywords


def test_bare_no_classifies_as_reject() -> None:
    result = classify_by_keywords("No")

    assert result is not None
    assert result.intent == "reject"


def test_no_soy_message_classifies_as_reject_keyword_fast_path() -> None:
    result = classify_by_keywords("No soy pedofilo mamon, es para una mujer adulta")

    assert result is not None
    assert result.intent == "reject"


def test_no_quiero_continuar_classifies_as_reject() -> None:
    result = classify_by_keywords("No quiero continuar")

    assert result is not None
    assert result.intent == "reject"


def test_cancelar_is_treated_as_cancellation_intent() -> None:
    result = classify_by_keywords("Cancelar")

    assert result is not None
    assert result.intent in {"reject", "cancel"}
    assert result.is_cancellation() is True
