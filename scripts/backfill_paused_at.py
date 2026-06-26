"""
Two-phase backfill: seed paused_at (Phase A) and clear atencion_automatica (Phase B).

Deploy order (ADR-4 / pause-state-internal-ssot):

    # Phase A — SEED BEFORE deploying new images (old gate ignores DB; harmless)
    python scripts/backfill_paused_at.py --phase seed --dry-run   # review counts
    python scripts/backfill_paused_at.py --phase seed

    # Final pre-flip SEED — run idempotent seed IMMEDIATELY before image swap to
    # capture any conversation escalated under the old code during Phase A.
    python scripts/backfill_paused_at.py --phase seed

    # Deploy the new api/agent images (DB gate goes live, fail-closed).
    # Zero-leak alternative: hold settings.ai_agent_enabled=False across the entire
    # cutover, then flip it back on after deploy.

    # Phase B — CLEAR AFTER deploy (new gate ignores Chatwoot; cannot un-pause)
    python scripts/backfill_paused_at.py --phase clear --dry-run  # review counts
    python scripts/backfill_paused_at.py --phase clear

NOTE (apply-time): confirm against the live Chatwoot API whether the correct
"clear" semantic is key-removal (omit the key from the merged POST) vs explicit
null value.  This implementation uses key-removal (omit from POST body).  Never
POST {atencion_automatica: null} blindly — that wipes sibling custom attributes
because update_conversation_attributes replaces the whole custom_attributes object
(shared/chatwoot_client.py:359-361 / ADR-4 F2).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.config import get_settings

logger = logging.getLogger(__name__)

CHECKPOINT_FILE = ".backfill_paused_at_checkpoint.json"
_RETRY_BASE_DELAY: float = 1.0
_MAX_RETRIES: int = 5
# Values of atencion_automatica that mean "bot disabled" — tolerant check against
# Chatwoot's loose JSON encoding (may return bool False, string "false"/"False", or int 0).
_DISABLED_VALUES: tuple = (False, "false", "False", 0)


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def load_checkpoint(phase: str, path: str = CHECKPOINT_FILE) -> int:
    """Return the last successfully-processed page for *phase*, or 0 if none."""
    p = Path(path)
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text())
        if data.get("phase") == phase:
            return int(data.get("last_page", 0))
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return 0


def save_checkpoint(phase: str, last_page: int, path: str = CHECKPOINT_FILE) -> None:
    """Persist the last successfully-processed page for *phase*."""
    Path(path).write_text(
        json.dumps(
            {
                "phase": phase,
                "last_page": last_page,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    )


def clear_checkpoint(path: str = CHECKPOINT_FILE) -> None:
    """Remove the checkpoint file after a complete run."""
    p = Path(path)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# HTTP helpers (exponential backoff + jitter on 429/5xx)
# ---------------------------------------------------------------------------


async def _fetch_page(
    http_client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """GET a Chatwoot conversations list page with exponential backoff on 429/5xx."""
    for attempt in range(max_retries):
        response = await http_client.get(url, headers=headers, params=params, timeout=30.0)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429 or response.status_code >= 500:
            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0.0, 0.5)
            logger.warning(
                "HTTP %s on page fetch (attempt %d/%d), retrying in %.2fs",
                response.status_code,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
        else:
            response.raise_for_status()  # non-retryable 4xx
    response.raise_for_status()


async def _get_conversation(
    http_client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """GET a single Chatwoot conversation with exponential backoff on 429/5xx."""
    for attempt in range(max_retries):
        response = await http_client.get(url, headers=headers, timeout=30.0)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429 or response.status_code >= 500:
            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0.0, 0.5)
            logger.warning(
                "HTTP %s on GET conversation (attempt %d/%d), retrying in %.2fs",
                response.status_code,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
        else:
            response.raise_for_status()
    response.raise_for_status()


async def _post_custom_attrs(
    http_client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_retries: int = _MAX_RETRIES,
) -> None:
    """POST merged custom_attributes with exponential backoff on 429/5xx."""
    for attempt in range(max_retries):
        response = await http_client.post(url, headers=headers, json=payload, timeout=30.0)
        if response.status_code in (200, 201):
            return
        if response.status_code == 429 or response.status_code >= 500:
            delay = _RETRY_BASE_DELAY * (2**attempt) + random.uniform(0.0, 0.5)
            logger.warning(
                "HTTP %s on POST custom_attributes (attempt %d/%d), retrying in %.2fs",
                response.status_code,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
        else:
            response.raise_for_status()
    response.raise_for_status()


# ---------------------------------------------------------------------------
# Phase A — SEED
# ---------------------------------------------------------------------------


async def run_seed(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    account_id: str,
    base_url: str,
    api_headers: dict[str, str],
    dry_run: bool,
    max_pages: int | None,
    inbox_id: str | None,
    no_resume: bool = False,
    checkpoint_path: str = CHECKPOINT_FILE,
) -> dict[str, int]:
    """Phase A: set paused_at for conversations whose atencion_automatica=false.

    Idempotent guard: UPDATE ... WHERE paused_at IS NULL AND resumed_at IS NULL —
    never overwrites an operator-set paused_at, and never re-pauses a conversation
    that was already resumed (resumed_at set, paused_at NULL).

    If no_resume=True, any existing checkpoint is cleared and the scan starts from
    page 1 (full rescan).  Use this for the final pre-flip seed to avoid stale
    page-offset drift from Chatwoot's activity-ordered mutable list.

    Returns stats with keys: pages_processed, seeded, skipped_no_attr,
    skipped_already_set, fallbacks_to_get.
    """
    stats: dict[str, int] = {
        "pages_processed": 0,
        "seeded": 0,
        "skipped_no_attr": 0,
        "skipped_already_set": 0,
        "fallbacks_to_get": 0,
    }

    if no_resume:
        clear_checkpoint(checkpoint_path)
        start_page = 1
    else:
        start_page = load_checkpoint("seed", checkpoint_path) + 1
    conversations_url = f"{base_url}/api/v1/accounts/{account_id}/conversations"

    page = start_page
    while True:
        if max_pages is not None and page > max_pages:
            logger.info(
                "Reached --max-pages=%d guard; stopping after page %d.",
                max_pages,
                page - 1,
            )
            break

        params: dict[str, Any] = {"page": page}
        if inbox_id:
            params["inbox_id"] = inbox_id

        data = await _fetch_page(http_client, conversations_url, api_headers, params)
        payload: list[dict[str, Any]] = (data.get("data") or {}).get("payload") or []

        if not payload:
            logger.info("Empty page %d — finished paginating.", page)
            break

        for conv in payload:
            conv_id = conv.get("id")
            if conv_id is None:
                continue

            if "custom_attributes" not in conv:
                # Key absent from list payload — fall back to a fresh per-conversation GET.
                # Chatwoot's activity-ordered list may omit the field on stale entries.
                conv_url = (
                    f"{base_url}/api/v1/accounts/{account_id}/conversations/{conv_id}"
                )
                conv_data = await _get_conversation(http_client, conv_url, api_headers)
                custom_attrs: dict[str, Any] = conv_data.get("custom_attributes") or {}
                stats["fallbacks_to_get"] += 1
                logger.debug(
                    "List payload missing custom_attributes for conv=%s — fell back to GET",
                    conv_id,
                )
            else:
                custom_attrs = conv.get("custom_attributes") or {}

            atencion = custom_attrs.get("atencion_automatica")

            if atencion not in _DISABLED_VALUES:
                # Only seed conversations explicitly disabled (atencion_automatica=false).
                # Treats False, "false", "False", 0 as disabled; true/absent/None → skip.
                stats["skipped_no_attr"] += 1
                continue

            if dry_run:
                logger.info("[DRY RUN] Would seed paused_at for conversation_id=%s", conv_id)
                stats["seeded"] += 1
                continue

            now = datetime.now(tz=UTC)
            async with session_factory() as session:
                result = await session.execute(
                    sa.text(
                        "UPDATE conversation_history"
                        " SET paused_at = :now"
                        " WHERE conversation_id = :cid"
                        "   AND paused_at IS NULL"
                        "   AND resumed_at IS NULL"
                    ),
                    {"now": now, "cid": str(conv_id)},
                )
                await session.commit()

            if result.rowcount > 0:
                logger.info("Seeded paused_at for conversation_id=%s", conv_id)
                stats["seeded"] += 1
            else:
                logger.debug(
                    "Skipped conversation_id=%s — paused_at already set (idempotent).", conv_id
                )
                stats["skipped_already_set"] += 1

        stats["pages_processed"] += 1
        if not dry_run:
            save_checkpoint("seed", page, checkpoint_path)
        page += 1

    if not dry_run:
        clear_checkpoint(checkpoint_path)

    logger.info("Seed complete: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Phase B — CLEAR
# ---------------------------------------------------------------------------


async def run_clear(
    *,
    http_client: httpx.AsyncClient,
    account_id: str,
    base_url: str,
    api_headers: dict[str, str],
    dry_run: bool,
    max_pages: int | None,
    inbox_id: str | None,
    no_resume: bool = False,
    checkpoint_path: str = CHECKPOINT_FILE,
) -> dict[str, int]:
    """Phase B: remove atencion_automatica from all Chatwoot conversations.

    GET current custom_attributes → drop only the atencion_automatica key → POST
    the merged remainder.  Never POSTs {atencion_automatica: null} — that would
    blindly replace the entire custom_attributes object and wipe sibling attributes
    (ADR-4 F2 / shared/chatwoot_client.py:359-361).

    If no_resume=True, any existing checkpoint is cleared and the scan starts from
    page 1 (full rescan).

    Returns stats with keys: pages_processed, cleared, skipped_no_attr.
    """
    stats: dict[str, int] = {
        "pages_processed": 0,
        "cleared": 0,
        "skipped_no_attr": 0,
    }

    if no_resume:
        clear_checkpoint(checkpoint_path)
        start_page = 1
    else:
        start_page = load_checkpoint("clear", checkpoint_path) + 1
    conversations_url = f"{base_url}/api/v1/accounts/{account_id}/conversations"

    page = start_page
    while True:
        if max_pages is not None and page > max_pages:
            logger.info(
                "Reached --max-pages=%d guard; stopping after page %d.",
                max_pages,
                page - 1,
            )
            break

        params: dict[str, Any] = {"page": page}
        if inbox_id:
            params["inbox_id"] = inbox_id

        data = await _fetch_page(http_client, conversations_url, api_headers, params)
        payload: list[dict[str, Any]] = (data.get("data") or {}).get("payload") or []

        if not payload:
            logger.info("Empty page %d — finished paginating.", page)
            break

        for conv in payload:
            conv_id = conv.get("id")
            conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conv_id}"

            # GET fresh custom_attributes — not from page payload (may be stale)
            conv_data = await _get_conversation(http_client, conv_url, api_headers)
            current_attrs: dict[str, Any] = conv_data.get("custom_attributes") or {}

            if "atencion_automatica" not in current_attrs:
                stats["skipped_no_attr"] += 1
                continue

            # Key-removal: preserve all other attrs, drop atencion_automatica entirely
            merged: dict[str, Any] = {
                k: v for k, v in current_attrs.items() if k != "atencion_automatica"
            }

            if dry_run:
                logger.info(
                    "[DRY RUN] Would clear atencion_automatica from conversation_id=%s"
                    " (remaining attrs=%s)",
                    conv_id,
                    merged,
                )
                stats["cleared"] += 1
                continue

            custom_attrs_url = f"{conv_url}/custom_attributes"
            await _post_custom_attrs(
                http_client,
                custom_attrs_url,
                api_headers,
                {"custom_attributes": merged},
            )
            logger.info("Cleared atencion_automatica from conversation_id=%s", conv_id)
            stats["cleared"] += 1

        stats["pages_processed"] += 1
        if not dry_run:
            save_checkpoint("clear", page, checkpoint_path)
        page += 1

    if not dry_run:
        clear_checkpoint(checkpoint_path)

    logger.info("Clear complete: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Parse arguments and run the chosen backfill phase."""
    parser = argparse.ArgumentParser(
        description=(
            "Two-phase backfill for pause-state-internal-ssot migration.\n"
            "  Phase A (seed)  — run BEFORE deploying new images.\n"
            "  Phase B (clear) — run AFTER deploying new images."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--phase",
        choices=["seed", "clear"],
        required=True,
        help="Phase A: seed  |  Phase B: clear",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log intended actions without writing to DB or Chatwoot.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N pages (safety guard against runaway loops). Default: unlimited.",
    )
    parser.add_argument(
        "--account-id",
        default=None,
        help="Override CHATWOOT_ACCOUNT_ID from settings.",
    )
    parser.add_argument(
        "--inbox-id",
        default=None,
        help="Override CHATWOOT_INBOX_ID from settings.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=False,
        help=(
            "Ignore any existing checkpoint and scan from page 1 (full rescan).\n"
            "Always use this for the final pre-flip seed: the page-offset checkpoint\n"
            "is mutable-list-ordered and can skip newly-active drift rows on a resumed run."
        ),
    )

    args = parser.parse_args()

    settings = get_settings()
    account_id: str = args.account_id or settings.CHATWOOT_ACCOUNT_ID
    inbox_id: str = args.inbox_id or settings.CHATWOOT_INBOX_ID
    base_url: str = settings.CHATWOOT_API_URL.rstrip("/")
    api_headers: dict[str, str] = {
        "api_access_token": settings.CHATWOOT_API_TOKEN,
        "Content-Type": "application/json",
    }

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    async with httpx.AsyncClient() as http_client:
        if args.phase == "seed":
            engine = create_async_engine(settings.DATABASE_URL, echo=False)
            factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
                engine, expire_on_commit=False
            )
            try:
                stats = await run_seed(
                    session_factory=factory,
                    http_client=http_client,
                    account_id=account_id,
                    base_url=base_url,
                    api_headers=api_headers,
                    dry_run=args.dry_run,
                    max_pages=args.max_pages,
                    inbox_id=inbox_id,
                    no_resume=args.no_resume,
                )
            finally:
                await engine.dispose()
        else:
            stats = await run_clear(
                http_client=http_client,
                account_id=account_id,
                base_url=base_url,
                api_headers=api_headers,
                dry_run=args.dry_run,
                max_pages=args.max_pages,
                inbox_id=inbox_id,
                no_resume=args.no_resume,
            )

    logger.info("Phase '%s' complete. Stats: %s", args.phase, stats)


if __name__ == "__main__":
    asyncio.run(main())
