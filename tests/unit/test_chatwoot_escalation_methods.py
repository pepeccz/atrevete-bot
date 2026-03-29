"""Unit tests for ChatwootClient escalation methods.

Tests: get_conversation_labels, add_conversation_labels,
       add_private_note, assign_to_team
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager


def _make_client():
    """Build a ChatwootClient with dummy settings (no network / env needed)."""
    from shared.chatwoot_client import ChatwootClient

    c = ChatwootClient.__new__(ChatwootClient)
    c.api_url = "https://chatwoot.test"
    c.api_token = "fake-token"
    c.account_id = 1
    c.inbox_id = 10
    c.headers = {
        "api_access_token": "fake-token",
        "Content-Type": "application/json",
    }
    return c


def _mock_http_client(get_response=None, post_response=None):
    """Return an async context manager that yields a mock httpx.AsyncClient."""
    mock_client = AsyncMock()

    if get_response is not None:
        mock_client.get = AsyncMock(return_value=get_response)
    if post_response is not None:
        mock_client.post = AsyncMock(return_value=post_response)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_client

    return _ctx, mock_client


def _mock_response(json_data=None, status_code=200):
    """Build a MagicMock response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data or {})
    return resp


# ---------------------------------------------------------------------------
# get_conversation_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conversation_labels_returns_list():
    """get_conversation_labels returns the payload list from the API."""
    client = _make_client()
    resp = _mock_response({"payload": ["vip", "escalado"]})
    ctx, mock_http = _mock_http_client(get_response=resp)

    with patch("shared.chatwoot_client.httpx.AsyncClient", ctx):
        labels = await client.get_conversation_labels(123)

    assert labels == ["vip", "escalado"]
    mock_http.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_labels_empty():
    """get_conversation_labels returns [] when payload is empty."""
    client = _make_client()
    resp = _mock_response({"payload": []})
    ctx, mock_http = _mock_http_client(get_response=resp)

    with patch("shared.chatwoot_client.httpx.AsyncClient", ctx):
        labels = await client.get_conversation_labels(99)

    assert labels == []


# ---------------------------------------------------------------------------
# add_conversation_labels — merge behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_conversation_labels_merges_without_duplicates():
    """add_conversation_labels merges new labels with existing ones (no dupes)."""
    client = _make_client()

    get_resp = _mock_response({"payload": ["vip"]})
    post_resp = _mock_response({"payload": ["vip", "escalado"]})

    # Two sequential HTTP calls: GET (existing) then POST (merge)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.post = AsyncMock(return_value=post_resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_client

    with patch("shared.chatwoot_client.httpx.AsyncClient", _ctx):
        result = await client.add_conversation_labels(123, ["escalado"])

    assert result is True
    # Verify the POST payload includes both existing and new label
    post_call = mock_client.post.call_args
    sent_labels = set(post_call.kwargs.get("json", {}).get("labels", []))
    assert "vip" in sent_labels
    assert "escalado" in sent_labels


@pytest.mark.asyncio
async def test_add_conversation_labels_no_duplicate_if_already_present():
    """add_conversation_labels does not duplicate a label already present."""
    client = _make_client()

    get_resp = _mock_response({"payload": ["escalado", "vip"]})
    post_resp = _mock_response({"payload": ["escalado", "vip"]})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.post = AsyncMock(return_value=post_resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_client

    with patch("shared.chatwoot_client.httpx.AsyncClient", _ctx):
        result = await client.add_conversation_labels(123, ["escalado"])

    assert result is True
    post_call = mock_client.post.call_args
    sent_labels = post_call.kwargs.get("json", {}).get("labels", [])
    # Must not duplicate
    assert sent_labels.count("escalado") == 1


# ---------------------------------------------------------------------------
# add_private_note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_private_note_sends_private_true():
    """add_private_note sends private=True in the POST payload."""
    client = _make_client()
    post_resp = _mock_response({})

    ctx, mock_http = _mock_http_client(post_response=post_resp)

    with patch("shared.chatwoot_client.httpx.AsyncClient", ctx):
        result = await client.add_private_note(123, "Test note")

    assert result is True
    post_call = mock_http.post.call_args
    sent_payload = post_call.kwargs.get("json", {})
    assert sent_payload.get("private") is True


@pytest.mark.asyncio
async def test_add_private_note_includes_content():
    """add_private_note sends the correct content string."""
    client = _make_client()
    post_resp = _mock_response({})
    ctx, mock_http = _mock_http_client(post_response=post_resp)

    with patch("shared.chatwoot_client.httpx.AsyncClient", ctx):
        await client.add_private_note(456, "Escalación manual por cliente")

    post_call = mock_http.post.call_args
    sent_payload = post_call.kwargs.get("json", {})
    assert sent_payload.get("content") == "Escalación manual por cliente"


@pytest.mark.asyncio
async def test_add_private_note_returns_false_on_error():
    """add_private_note returns False when an exception is raised."""
    client = _make_client()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        mock = AsyncMock()
        mock.post = AsyncMock(side_effect=Exception("network error"))
        yield mock

    with patch("shared.chatwoot_client.httpx.AsyncClient", _ctx):
        result = await client.add_private_note(123, "note")

    assert result is False


# ---------------------------------------------------------------------------
# assign_to_team
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_to_team_posts_correct_payload():
    """assign_to_team posts team_id correctly."""
    client = _make_client()
    post_resp = _mock_response({})
    ctx, mock_http = _mock_http_client(post_response=post_resp)

    with patch("shared.chatwoot_client.httpx.AsyncClient", ctx):
        result = await client.assign_to_team(123, 42)

    assert result is True
    post_call = mock_http.post.call_args
    sent_payload = post_call.kwargs.get("json", {})
    assert sent_payload.get("team_id") == 42


@pytest.mark.asyncio
async def test_assign_to_team_returns_false_on_error():
    """assign_to_team returns False when an exception is raised."""
    client = _make_client()

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        mock = AsyncMock()
        mock.post = AsyncMock(side_effect=Exception("timeout"))
        yield mock

    with patch("shared.chatwoot_client.httpx.AsyncClient", _ctx):
        result = await client.assign_to_team(123, 42)

    assert result is False
