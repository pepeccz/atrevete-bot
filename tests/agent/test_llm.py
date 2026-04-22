"""Tests for agent.llm — ChatOpenAI via OpenRouter factory.

Config mapping (from shared/config.py):
  - api_key   ← settings.OPENROUTER_API_KEY
  - model     ← settings.LLM_MODEL   (not OPENAI_MODEL — that field doesn't exist)
  - base_url  ← hardcoded "https://openrouter.ai/api/v1" (no OPENROUTER_BASE_URL field)
  - temperature ← 0.0 default (no OPENAI_TEMPERATURE field in config)
"""

from unittest.mock import MagicMock, patch

from langchain_openai import ChatOpenAI

from agent.llm import get_llm

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_fake_settings(
    api_key: str = "sk-or-test",
    model: str = "openai/gpt-4.1-mini",
    site_url: str = "https://atrevetepeluqueria.com",
    site_name: str = "Atrévete Peluquería",
) -> MagicMock:
    s = MagicMock()
    s.OPENROUTER_API_KEY = api_key
    s.LLM_MODEL = model
    s.SITE_URL = site_url
    s.SITE_NAME = site_name
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_llm_returns_chatopenai_instance():
    """get_llm() returns a ChatOpenAI instance."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm()
    assert isinstance(llm, ChatOpenAI)


def test_get_llm_uses_openrouter_base_url():
    """base_url is set to OpenRouter endpoint."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm()
    assert "openrouter.ai" in str(llm.openai_api_base)


def test_get_llm_uses_openrouter_api_key():
    """api_key comes from settings.OPENROUTER_API_KEY."""
    fake = _make_fake_settings(api_key="sk-or-real-key")
    with patch("agent.llm.get_settings", return_value=fake):
        llm = get_llm()
    assert llm.openai_api_key.get_secret_value() == "sk-or-real-key"


def test_get_llm_default_model_from_settings():
    """model defaults to settings.LLM_MODEL."""
    fake = _make_fake_settings(model="openai/gpt-4.1-mini")
    with patch("agent.llm.get_settings", return_value=fake):
        llm = get_llm()
    assert llm.model_name == "openai/gpt-4.1-mini"


def test_get_llm_explicit_model_override():
    """Explicit model parameter overrides settings.LLM_MODEL."""
    fake = _make_fake_settings(model="openai/gpt-4.1-mini")
    with patch("agent.llm.get_settings", return_value=fake):
        llm = get_llm(model="openai/gpt-4o")
    assert llm.model_name == "openai/gpt-4o"


def test_get_llm_default_temperature_is_zero():
    """Default temperature is 0.0 (no OPENAI_TEMPERATURE field in config)."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm()
    assert llm.temperature == 0.0


def test_get_llm_explicit_temperature_override():
    """Explicit temperature parameter is used."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm(temperature=0.7)
    assert llm.temperature == 0.7


def test_get_llm_temperature_zero_not_overridden_by_none():
    """temperature=0 is distinct from temperature=None (don't use None as sentinel)."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm(temperature=0)
    assert llm.temperature == 0.0


def test_get_llm_has_openrouter_attribution_headers():
    """default_headers includes HTTP-Referer and X-Title for OpenRouter attribution."""
    with patch("agent.llm.get_settings", return_value=_make_fake_settings()):
        llm = get_llm()
    headers = llm.default_headers
    assert "HTTP-Referer" in headers
    assert "X-Title" in headers


def test_get_llm_http_referer_is_site_url():
    """HTTP-Referer header uses settings.SITE_URL."""
    fake = _make_fake_settings(site_url="https://atrevetepeluqueria.com")
    with patch("agent.llm.get_settings", return_value=fake):
        llm = get_llm()
    assert llm.default_headers["HTTP-Referer"] == "https://atrevetepeluqueria.com"


def test_get_llm_x_title_is_site_name():
    """X-Title header uses settings.SITE_NAME."""
    fake = _make_fake_settings(site_name="Atrévete Peluquería")
    with patch("agent.llm.get_settings", return_value=fake):
        llm = get_llm()
    assert llm.default_headers["X-Title"] == "Atrévete Peluquería"
