"""
Unit tests for scripts/backfill_paused_at.py — two-phase cutover (ADR-4).

Tests cover:
- SEED idempotency: only seeds paused_at WHERE paused_at IS NULL AND resumed_at IS NULL
- SEED SQL guard: UPDATE includes WHERE paused_at IS NULL (not just WHERE atencion_automatica=false)
- SEED SQL guard: UPDATE includes WHERE resumed_at IS NULL (F2-safety: never re-pauses resumed conv)
- C1 regression: conversation_id bound as str, not int (asyncpg String(255) type requirement)
- SEED skips conversations without atencion_automatica=false (value normalization: "false" seeds)
- SEED list-payload-missing fallback: falls back to per-conversation GET when custom_attributes absent
- CLEAR merge: GET → drop atencion_automatica key → POST remainder
- CLEAR never POSTs atencion_automatica (not even as null) — ADR-4 F2
- --dry-run: no DB writes, no Chatwoot HTTP writes
- 429 / 5xx: exponential backoff + asyncio.sleep call (sleep patched) for all HTTP helpers
- --max-pages: bounds pagination loop before the guard fires
- Checkpoint/resume: checkpoint saved per page (spy); re-run starts from next page
- --no-resume: ignores existing checkpoint, scans from page 1

All HTTP and DB I/O is mocked — no live DB or Chatwoot required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from scripts.backfill_paused_at import (
    load_checkpoint,
    run_clear,
    run_seed,
    save_checkpoint,
    clear_checkpoint,
)


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


def _ok(data: dict) -> MagicMock:
    """200 OK GET response."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


def _ok_post() -> MagicMock:
    """200 OK POST response."""
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    return r


def _err(status: int) -> MagicMock:
    """Error response (429 or 5xx) — no raise_for_status side-effect needed
    since the retry loop checks status_code before calling raise_for_status."""
    r = MagicMock()
    r.status_code = status
    return r


def _page(conversations: list[dict]) -> dict:
    """Chatwoot conversations list page envelope."""
    return {"data": {"payload": conversations}}


def _empty_page() -> dict:
    return {"data": {"payload": []}}


def _conv_detail(conv_id: int, custom_attrs: dict) -> dict:
    """Chatwoot GET conversation detail response."""
    return {"id": conv_id, "custom_attributes": custom_attrs}


def _conv(conv_id: int, atencion_automatica: bool | None = None) -> dict:
    """Build a minimal conversation payload entry (always includes custom_attributes key)."""
    attrs: dict = {}
    if atencion_automatica is not None:
        attrs["atencion_automatica"] = atencion_automatica
    return {"id": conv_id, "custom_attributes": attrs}


def _conv_str_attr(conv_id: int, atencion_value) -> dict:
    """Build a conversation payload with an arbitrary atencion_automatica value (any type)."""
    return {"id": conv_id, "custom_attributes": {"atencion_automatica": atencion_value}}


def _conv_no_attrs(conv_id: int) -> dict:
    """Build a conversation payload with NO custom_attributes key (simulates stale list entry)."""
    return {"id": conv_id}


class _FakeSession:
    """Async DB session double — records SQL text and returns configurable rowcount."""

    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        result = MagicMock()
        result.rowcount = self.rowcount
        return result

    async def commit(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


class _FakeSessionFactory:
    """Callable factory returning the same _FakeSession on every call."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


def _seed_kw(
    http_client,
    session_factory,
    *,
    tmp_path,
    dry_run: bool = False,
    max_pages: int | None = None,
    inbox_id: str | None = None,
    no_resume: bool = False,
) -> dict:
    return dict(
        session_factory=session_factory,
        http_client=http_client,
        account_id="999",
        base_url="https://chatwoot.test",
        api_headers={"api_access_token": "tok"},
        dry_run=dry_run,
        max_pages=max_pages,
        inbox_id=inbox_id,
        no_resume=no_resume,
        checkpoint_path=str(tmp_path / "cp.json"),
    )


def _clear_kw(
    http_client,
    *,
    tmp_path,
    dry_run: bool = False,
    max_pages: int | None = None,
    inbox_id: str | None = None,
    no_resume: bool = False,
) -> dict:
    return dict(
        http_client=http_client,
        account_id="999",
        base_url="https://chatwoot.test",
        api_headers={"api_access_token": "tok"},
        dry_run=dry_run,
        max_pages=max_pages,
        inbox_id=inbox_id,
        no_resume=no_resume,
        checkpoint_path=str(tmp_path / "cp.json"),
    )


# ---------------------------------------------------------------------------
# T-10 tests
# ---------------------------------------------------------------------------


class TestSeedIdempotency:
    """SEED only writes paused_at WHERE paused_at IS NULL — re-run is a no-op."""

    async def test_seed_sets_paused_at_for_atencion_false(self, tmp_path) -> None:
        """First run seeds a conversation with atencion_automatica=false."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(101, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1
        assert stats["skipped_already_set"] == 0
        assert stats["pages_processed"] == 1

    async def test_seed_idempotent_second_run_no_changes(self, tmp_path) -> None:
        """Second run against already-seeded rows: rowcount=0 → skipped_already_set."""
        session = _FakeSession(rowcount=0)  # paused_at already set
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(101, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 0
        assert stats["skipped_already_set"] == 1

    async def test_seed_sql_includes_where_paused_at_is_null(self, tmp_path) -> None:
        """UPDATE SQL must include the idempotency guard WHERE paused_at IS NULL."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(101, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        # At least one SQL executed
        assert session.executed, "Expected at least one SQL execute call"
        sql_text, params = session.executed[0]
        # Must contain the idempotency guard (direct check — no dead .replace("_"," ") form)
        assert "paused_at IS NULL" in sql_text
        # And it must reference conversation_id
        assert "conversation_id" in sql_text.lower() or "conversation_id" in params

    async def test_seed_sql_includes_resumed_at_is_null(self, tmp_path) -> None:
        """UPDATE SQL must include resumed_at IS NULL to avoid re-pausing resumed conversations."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(102, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert session.executed, "Expected at least one SQL execute call"
        sql_text, _ = session.executed[0]
        assert "resumed_at IS NULL" in sql_text, (
            "F2-safety: SQL must exclude conversations where resumed_at IS NOT NULL"
        )

    async def test_seed_binds_conversation_id_as_str(self, tmp_path) -> None:
        """C1 regression: conversation_id must be bound as str, not int.

        asyncpg raises DataError for int values bound to String(255) columns.
        Chatwoot API returns ids as int; every DB call must cast via str(conv_id).
        """
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)
        conv_id_int = 101  # integer from Chatwoot JSON

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(conv_id_int, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert session.executed, "Expected at least one SQL execute call"
        _, params = session.executed[0]
        cid = params.get("cid")
        assert isinstance(cid, str), (
            f"C1: cid must be str, got {type(cid).__name__!r} — "
            "asyncpg requires str for String(255) conversation_id column"
        )
        assert cid == str(conv_id_int), (
            f"C1: cid value mismatch: expected {str(conv_id_int)!r}, got {cid!r}"
        )

    async def test_seed_skips_conversations_without_atencion_false(self, tmp_path) -> None:
        """Conversations with atencion_automatica=true or absent are not seeded."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(
                    _page(
                        [
                            _conv(201, atencion_automatica=True),   # bot ON → skip
                            _conv(202),                              # no attr → skip
                            _conv(203, atencion_automatica=False),  # bot OFF → seed
                        ]
                    )
                ),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1
        assert stats["skipped_no_attr"] == 2
        assert len(session.executed) == 1  # only conv 203

    async def test_seed_value_normalization_string_false_seeds(self, tmp_path) -> None:
        """atencion_automatica='false' (string) must be treated as disabled → seed.

        Chatwoot's JSON encoding may return a string instead of a bool boolean.
        """
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv_str_attr(204, "false")])),   # string "false" → seed
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1, "string 'false' must be treated as disabled and seeded"
        assert stats["skipped_no_attr"] == 0

    async def test_seed_value_normalization_true_does_not_seed(self, tmp_path) -> None:
        """atencion_automatica=True, 'true', or absent must not seed."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(
                    _page(
                        [
                            _conv(205, atencion_automatica=True),   # bool True → skip
                            _conv_str_attr(206, "true"),            # string "true" → skip
                            _conv(207),                             # absent → skip
                        ]
                    )
                ),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 0
        assert stats["skipped_no_attr"] == 3
        assert session.executed == [], "must not execute any SQL for non-disabled conversations"

    async def test_seed_list_payload_missing_custom_attributes_fallback(
        self, tmp_path
    ) -> None:
        """When the list payload has no custom_attributes key, fall back to per-conv GET.

        The fallback GET is counted in stats['fallbacks_to_get']. If the GET returns
        atencion_automatica=false, the row is seeded.
        """
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        conv_detail = _conv_detail(208, {"atencion_automatica": False})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv_no_attrs(208)])),  # list entry — no custom_attributes key
                _ok(conv_detail),                   # fallback GET returns real attrs
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1
        assert stats["fallbacks_to_get"] == 1
        assert len(session.executed) == 1


class TestClearMerge:
    """CLEAR: GET → remove only atencion_automatica → POST remainder."""

    async def test_clear_preserves_sibling_attrs(self, tmp_path) -> None:
        """POST body keeps all other custom_attributes; atencion_automatica absent."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(
            301,
            {"atencion_automatica": False, "tag": "vip", "region": "es"},
        )
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(301)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        stats = await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert stats["cleared"] == 1
        assert mock_client.post.await_count == 1

        # Inspect POST body
        call = mock_client.post.call_args
        body = call.kwargs.get("json") or call.args[1] if call.args and len(call.args) > 1 else call.kwargs.get("json")
        posted_attrs = body["custom_attributes"]
        assert "atencion_automatica" not in posted_attrs, (
            "CLEAR must NOT post atencion_automatica (key-removal, not null override)"
        )
        assert posted_attrs.get("tag") == "vip"
        assert posted_attrs.get("region") == "es"

    async def test_clear_never_posts_atencion_automatica_null(self, tmp_path) -> None:
        """Posting atencion_automatica=null is FORBIDDEN — would wipe the slot.
        The key must be absent from the POST body entirely."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(302, {"atencion_automatica": False})
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(302)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        posted_bodies: list[dict] = []

        async def _capture_post(*args, **kwargs):
            posted_bodies.append(kwargs.get("json", {}))
            return _ok_post()

        mock_client.post = AsyncMock(side_effect=_capture_post)

        await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert posted_bodies, "Expected a POST call"
        for body in posted_bodies:
            assert "atencion_automatica" not in body.get("custom_attributes", {}), (
                "atencion_automatica must be absent (not null) in POST body"
            )

    async def test_clear_skips_conversations_without_atencion_attr(self, tmp_path) -> None:
        """Conversations whose custom_attributes lack atencion_automatica are skipped."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(303, {"other_key": "value"})  # no atencion_automatica
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(303)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        stats = await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert stats["skipped_no_attr"] == 1
        assert stats["cleared"] == 0
        mock_client.post.assert_not_awaited()


class TestDryRun:
    """--dry-run makes no DB writes and no HTTP POST writes."""

    async def test_seed_dry_run_no_db_writes(self, tmp_path) -> None:
        """--dry-run seed: logs intentions but executes no SQL."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(401, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(
            **_seed_kw(mock_client, factory, tmp_path=tmp_path, dry_run=True)
        )

        # Counted as "would seed"
        assert stats["seeded"] == 1
        # But NO SQL executed
        assert session.executed == [], "dry-run must not execute any SQL"

    async def test_clear_dry_run_no_http_posts(self, tmp_path) -> None:
        """--dry-run clear: logs intentions but sends no POST requests."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(402, {"atencion_automatica": False, "region": "es"})
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(402)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        stats = await run_clear(
            **_clear_kw(mock_client, tmp_path=tmp_path, dry_run=True)
        )

        assert stats["cleared"] == 1
        mock_client.post.assert_not_awaited()


class TestBackoffResilience:
    """429 and 5xx trigger exponential backoff via asyncio.sleep."""

    async def test_seed_429_triggers_retry(self, tmp_path) -> None:
        """A 429 on a page fetch triggers at least one asyncio.sleep call."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _err(429),                                           # first attempt → 429
                _ok(_page([_conv(501, atencion_automatica=False)])),  # retry → 200
                _ok(_empty_page()),
            ]
        )

        with patch("scripts.backfill_paused_at.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1
        mock_asyncio.sleep.assert_awaited()  # backoff sleep was called

    async def test_seed_5xx_triggers_retry(self, tmp_path) -> None:
        """A 503 on a page fetch triggers at least one asyncio.sleep call."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _err(503),
                _ok(_page([_conv(502, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        with patch("scripts.backfill_paused_at.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            stats = await run_seed(**_seed_kw(mock_client, factory, tmp_path=tmp_path))

        assert stats["seeded"] == 1
        mock_asyncio.sleep.assert_awaited()

    async def test_clear_429_triggers_retry_on_page_fetch(self, tmp_path) -> None:
        """CLEAR phase: 429 on page list fetch triggers backoff."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(503, {"atencion_automatica": False})
        mock_client.get = AsyncMock(
            side_effect=[
                _err(429),
                _ok(_page([_conv(503)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        with patch("scripts.backfill_paused_at.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            stats = await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert stats["cleared"] == 1
        mock_asyncio.sleep.assert_awaited()

    async def test_get_conversation_429_triggers_retry(self, tmp_path) -> None:
        """429 on GET single conversation (CLEAR per-conv GET) triggers exponential backoff."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(504, {"atencion_automatica": False})
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(504)])),  # list page → 200
                _err(429),                 # per-conv GET → 429
                _ok(conv_detail),          # retry → 200
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        with patch("scripts.backfill_paused_at.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            stats = await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert stats["cleared"] == 1
        mock_asyncio.sleep.assert_awaited()

    async def test_post_custom_attrs_429_triggers_retry(self, tmp_path) -> None:
        """429 on POST custom_attributes triggers exponential backoff."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(505, {"atencion_automatica": False})
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(505)])),
                _ok(conv_detail),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(
            side_effect=[
                _err(429),    # first POST → 429
                _ok_post(),   # retry → 200
            ]
        )

        with patch("scripts.backfill_paused_at.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            stats = await run_clear(**_clear_kw(mock_client, tmp_path=tmp_path))

        assert stats["cleared"] == 1
        mock_asyncio.sleep.assert_awaited()


class TestMaxPages:
    """--max-pages N stops pagination after N pages."""

    async def test_seed_max_pages_stops_loop(self, tmp_path) -> None:
        """With max_pages=1, only page 1 is processed even if page 2 has data."""
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        # Two pages of data; with max_pages=1 only page 1 should be fetched
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(601, atencion_automatica=False)])),
                # page 2 should NOT be fetched
                _ok(_page([_conv(602, atencion_automatica=False)])),
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(
            **_seed_kw(mock_client, factory, tmp_path=tmp_path, max_pages=1)
        )

        assert stats["pages_processed"] == 1
        assert stats["seeded"] == 1
        # Only page 1 GET was made (1 call)
        assert mock_client.get.await_count == 1

    async def test_clear_max_pages_stops_loop(self, tmp_path) -> None:
        """CLEAR: max_pages=1 stops after the first page."""
        mock_client = AsyncMock()
        conv_detail = _conv_detail(701, {"atencion_automatica": False})
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(701)])),
                _ok(conv_detail),
                # page 2 should NOT be fetched
                _ok(_page([_conv(702)])),
                _ok(_conv_detail(702, {"atencion_automatica": False})),
                _ok(_empty_page()),
            ]
        )
        mock_client.post = AsyncMock(return_value=_ok_post())

        stats = await run_clear(
            **_clear_kw(mock_client, tmp_path=tmp_path, max_pages=1)
        )

        assert stats["pages_processed"] == 1
        assert stats["cleared"] == 1


class TestCheckpointResume:
    """Checkpoint/resume: re-run starts from the page after last checkpoint."""

    async def test_seed_resumes_from_checkpoint(self, tmp_path) -> None:
        """Simulate a prior partial run that completed page 1; re-run starts at page 2."""
        cp = str(tmp_path / "cp.json")
        # Pre-seed checkpoint: page 1 already done
        save_checkpoint("seed", 1, cp)

        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        # Only page 2 remains
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(801, atencion_automatica=False)])),  # page 2
                _ok(_empty_page()),
            ]
        )

        stats = await run_seed(
            session_factory=factory,
            http_client=mock_client,
            account_id="999",
            base_url="https://chatwoot.test",
            api_headers={"api_access_token": "tok"},
            dry_run=False,
            max_pages=None,
            inbox_id=None,
            checkpoint_path=cp,
        )

        # Fetched exactly 2 pages (page 2 + empty-stop)
        assert mock_client.get.await_count == 2
        # One row seeded (conv 801)
        assert stats["seeded"] == 1

    async def test_checkpoint_saved_per_page(self, tmp_path) -> None:
        """save_checkpoint is called exactly once per processed page.

        Patches save_checkpoint to verify it was invoked with the correct args
        after page 1 completes — not just that the file was eventually cleared.
        """
        cp = str(tmp_path / "cp.json")
        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(901, atencion_automatica=False)])),  # page 1
                _ok(_empty_page()),                                    # stop
            ]
        )

        with patch("scripts.backfill_paused_at.save_checkpoint") as mock_save:
            stats = await run_seed(
                session_factory=factory,
                http_client=mock_client,
                account_id="999",
                base_url="https://chatwoot.test",
                api_headers={"api_access_token": "tok"},
                dry_run=False,
                max_pages=None,
                inbox_id=None,
                checkpoint_path=cp,
            )

        assert stats["pages_processed"] == 1
        assert stats["seeded"] == 1
        # save_checkpoint must have been called once, for page 1
        mock_save.assert_called_once_with("seed", 1, cp)

    async def test_no_resume_ignores_checkpoint(self, tmp_path) -> None:
        """no_resume=True ignores an existing checkpoint and scans from page 1.

        Pre-saves a checkpoint claiming page 5 was done. With no_resume=True the
        function must start at page 1 (not page 6) and overwrite the checkpoint.
        """
        cp = str(tmp_path / "cp.json")
        # Simulate a previous partial run that finished page 5
        save_checkpoint("seed", 5, cp)

        session = _FakeSession(rowcount=1)
        factory = _FakeSessionFactory(session)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok(_page([_conv(1001, atencion_automatica=False)])),  # page 1 fetched
                _ok(_empty_page()),
            ]
        )

        with patch("scripts.backfill_paused_at.save_checkpoint") as mock_save:
            stats = await run_seed(
                session_factory=factory,
                http_client=mock_client,
                account_id="999",
                base_url="https://chatwoot.test",
                api_headers={"api_access_token": "tok"},
                dry_run=False,
                max_pages=None,
                inbox_id=None,
                checkpoint_path=cp,
                no_resume=True,
            )

        # Started from page 1 (not page 6); one page processed
        assert stats["pages_processed"] == 1
        assert stats["seeded"] == 1
        # save_checkpoint called for page 1 (not page 6)
        mock_save.assert_called_once_with("seed", 1, cp)
