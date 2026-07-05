"""Unit tests for shared/chatwoot_client.py — create_conversation_with_template.

Covers the public wrapper (TASK-03/04, sdd/context-coherence D3): finds/creates the
contact, delegates to the internal ``_create_conversation_with_template``, and returns
``(conversation_id, success)``. Also asserts ``send_template_message``'s no-id branch
delegates to the new method (behavior-preserving refactor — still returns bool).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from shared.chatwoot_client import ChatwootClient, ConversationSendOutcome


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


class TestSendTemplateToConversationChecked:
    """FIX 1/FIX 8 (sdd/context-coherence): typed outcome distinguishing a
    definitive Chatwoot rejection (fallback warranted) from a transient
    failure (worker backoff should retry the SAME conversation instead)."""

    @staticmethod
    def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", "https://chatwoot.example/api/v1/x")
        response = httpx.Response(status_code, request=request)
        return httpx.HTTPStatusError("boom", request=request, response=response)

    @pytest.mark.asyncio
    async def test_returns_sent_on_success(self, client, monkeypatch):
        monkeypatch.setattr(client, "_send_template_to_conversation", AsyncMock(return_value=True))

        outcome = await client.send_template_to_conversation_checked(
            conversation_id=125,
            customer_phone="+34611111111",
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            fallback_content="Hola Ana",
        )

        assert outcome is ConversationSendOutcome.SENT

    @pytest.mark.asyncio
    async def test_returns_rejected_on_realistic_400_response(self, client, monkeypatch):
        """FIX 8: a realistic httpx-level 400 response (not a generic exception)
        must map to REJECTED."""
        monkeypatch.setattr(
            client,
            "_send_template_to_conversation",
            AsyncMock(side_effect=self._make_http_status_error(400)),
        )

        outcome = await client.send_template_to_conversation_checked(
            conversation_id=99999999,
            customer_phone="+34611111111",
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            fallback_content="Hola Ana",
        )

        assert outcome is ConversationSendOutcome.REJECTED

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [404, 422])
    async def test_returns_rejected_on_other_rejection_status_codes(
        self, client, monkeypatch, status_code
    ):
        monkeypatch.setattr(
            client,
            "_send_template_to_conversation",
            AsyncMock(side_effect=self._make_http_status_error(status_code)),
        )

        outcome = await client.send_template_to_conversation_checked(
            conversation_id=125,
            customer_phone="+34611111111",
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            fallback_content="Hola Ana",
        )

        assert outcome is ConversationSendOutcome.REJECTED

    @pytest.mark.asyncio
    async def test_returns_transient_on_5xx_response(self, client, monkeypatch):
        """A transient 5xx must NOT be treated as a rejection — fragmenting the
        customer's history on a server hiccup is exactly what FIX 1 prevents."""
        monkeypatch.setattr(
            client,
            "_send_template_to_conversation",
            AsyncMock(side_effect=self._make_http_status_error(503)),
        )

        outcome = await client.send_template_to_conversation_checked(
            conversation_id=125,
            customer_phone="+34611111111",
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            fallback_content="Hola Ana",
        )

        assert outcome is ConversationSendOutcome.TRANSIENT

    @pytest.mark.asyncio
    async def test_returns_transient_on_network_error(self, client, monkeypatch):
        monkeypatch.setattr(
            client,
            "_send_template_to_conversation",
            AsyncMock(side_effect=httpx.ConnectTimeout("timed out")),
        )

        outcome = await client.send_template_to_conversation_checked(
            conversation_id=125,
            customer_phone="+34611111111",
            template_name="appointment_confirmation_48h",
            body_params={"1": "Ana"},
            fallback_content="Hola Ana",
        )

        assert outcome is ConversationSendOutcome.TRANSIENT
