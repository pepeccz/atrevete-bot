"""Unit tests for shared/chatwoot_client.py — create_conversation_with_template.

Covers the public wrapper (TASK-03/04, sdd/context-coherence D3): finds/creates the
contact, delegates to the internal ``_create_conversation_with_template``, and returns
``(conversation_id, success)``. Also asserts ``send_template_message``'s no-id branch
delegates to the new method (behavior-preserving refactor — still returns bool).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from shared.chatwoot_client import ChatwootClient


@pytest.fixture
def client() -> ChatwootClient:
    return ChatwootClient()


@pytest.mark.asyncio
async def test_create_conversation_with_template_uses_existing_contact(client, monkeypatch):
    monkeypatch.setattr(client, "_find_contact_by_phone", AsyncMock(return_value={"id": 42}))
    create_contact = AsyncMock()
    monkeypatch.setattr(client, "_create_contact", create_contact)
    monkeypatch.setattr(
        client,
        "_create_conversation_with_template",
        AsyncMock(return_value=(555, True)),
    )

    conv_id, success = await client.create_conversation_with_template(
        customer_phone="+34611111111",
        template_name="appointment_confirmation_48h",
        body_params={"1": "Ana"},
        fallback_content="Hola Ana",
    )

    assert conv_id == 555
    assert success is True
    create_contact.assert_not_called()
    client._create_conversation_with_template.assert_awaited_once()
    kwargs = client._create_conversation_with_template.await_args.kwargs
    assert kwargs["contact_id"] == 42
    assert kwargs["phone"] == "+34611111111"
    assert kwargs["template_name"] == "appointment_confirmation_48h"


@pytest.mark.asyncio
async def test_create_conversation_with_template_creates_contact_when_missing(client, monkeypatch):
    monkeypatch.setattr(client, "_find_contact_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(client, "_create_contact", AsyncMock(return_value={"id": 99}))
    monkeypatch.setattr(
        client,
        "_create_conversation_with_template",
        AsyncMock(return_value=(777, True)),
    )

    conv_id, success = await client.create_conversation_with_template(
        customer_phone="+34622222222",
        template_name="appointment_reminder_2h",
        body_params={"1": "Luis"},
        fallback_content="Hola Luis",
    )

    assert conv_id == 777
    assert success is True


@pytest.mark.asyncio
async def test_create_conversation_with_template_no_contact_id_returns_failure(client, monkeypatch):
    monkeypatch.setattr(client, "_find_contact_by_phone", AsyncMock(return_value={}))
    monkeypatch.setattr(client, "_create_contact", AsyncMock(return_value={}))
    inner = AsyncMock()
    monkeypatch.setattr(client, "_create_conversation_with_template", inner)

    conv_id, success = await client.create_conversation_with_template(
        customer_phone="+34633333333",
        template_name="appointment_confirmation_48h",
        body_params={},
        fallback_content="",
    )

    assert conv_id is None
    assert success is False
    inner.assert_not_called()


@pytest.mark.asyncio
async def test_create_conversation_with_template_swallows_http_error(client, monkeypatch):
    import httpx

    monkeypatch.setattr(
        client,
        "_find_contact_by_phone",
        AsyncMock(side_effect=httpx.HTTPError("boom")),
    )

    conv_id, success = await client.create_conversation_with_template(
        customer_phone="+34644444444",
        template_name="appointment_confirmation_48h",
        body_params={},
        fallback_content="",
    )

    assert conv_id is None
    assert success is False


@pytest.mark.asyncio
async def test_send_template_message_no_id_delegates_to_public_method(client, monkeypatch):
    delegate = AsyncMock(return_value=(321, True))
    monkeypatch.setattr(client, "create_conversation_with_template", delegate)

    result = await client.send_template_message(
        customer_phone="+34655555555",
        template_name="appointment_confirmation_48h",
        body_params={"1": "Ana"},
        fallback_content="Hola Ana",
    )

    assert result is True
    delegate.assert_awaited_once()
    kwargs = delegate.await_args.kwargs
    assert kwargs["customer_phone"] == "+34655555555"
    assert kwargs["template_name"] == "appointment_confirmation_48h"


@pytest.mark.asyncio
async def test_send_template_message_with_id_does_not_delegate(client, monkeypatch):
    delegate = AsyncMock()
    monkeypatch.setattr(client, "create_conversation_with_template", delegate)
    monkeypatch.setattr(client, "_send_template_to_conversation", AsyncMock(return_value=True))

    result = await client.send_template_message(
        customer_phone="+34666666666",
        template_name="appointment_confirmation_48h",
        body_params={"1": "Ana"},
        conversation_id=999,
    )

    assert result is True
    delegate.assert_not_called()
