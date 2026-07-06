"""
Integration test for PR-2: global search matches Customer.last_name.

Exercises the REAL `search_conversations` function directly against a live
Postgres connection — no mocking — so the added `last_name.ilike()` OR-branch
is pinned by real query execution, per the mandatory lesson from #7523 (do
NOT merely mock the function under test).

Covers spec requirement: "Search matches customer last name"
(test_search_matches_last_name in the spec artifact).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from api.services.global_search_service import search_conversations
from database.connection import get_async_session
from database.models import ConversationHistory, Customer

pytestmark = pytest.mark.asyncio

# Namespace all test conversation_ids under this prefix so cleanup is scoped
# and never touches unrelated rows created by other test modules.
TEST_PREFIX = "999777"


@pytest.fixture(autouse=True)
async def _cleanup_test_data():
    async def _wipe():
        async with get_async_session() as session:
            await session.execute(
                delete(ConversationHistory).where(
                    ConversationHistory.conversation_id.like(f"{TEST_PREFIX}%")
                )
            )
            await session.execute(delete(Customer).where(Customer.phone.like("+34999777%")))
            await session.commit()

    await _wipe()
    yield
    await _wipe()


async def _make_customer_conversation(
    *, phone: str, first_name: str, last_name: str | None, conversation_id: str
) -> None:
    async with get_async_session() as session:
        customer = Customer(
            id=uuid4(),
            phone=phone,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(customer)
        await session.flush()
        conv = ConversationHistory(
            id=uuid4(),
            conversation_id=conversation_id,
            customer_id=customer.id,
            message_count=0,
            metadata_={},
        )
        session.add(conv)
        await session.commit()


async def test_search_matches_last_name():
    """Scenario: searching by surname ('Test') returns the matching conversation."""
    await _make_customer_conversation(
        phone="+34999777001",
        first_name="Eva",
        last_name="Test",
        conversation_id=f"{TEST_PREFIX}001",
    )

    async with get_async_session() as session:
        results = await search_conversations("Test", session)

    matched = [r for r in results if r["conversation_id"] == f"{TEST_PREFIX}001"]
    assert len(matched) == 1
    assert matched[0]["customer_name"] == "Eva Test"


async def test_search_by_first_name_still_works():
    """Regression guard: first_name matching must keep working alongside last_name."""
    await _make_customer_conversation(
        phone="+34999777002",
        first_name="Zurriaga",
        last_name="Nomatch",
        conversation_id=f"{TEST_PREFIX}002",
    )

    async with get_async_session() as session:
        results = await search_conversations("Zurriaga", session)

    matched = [r for r in results if r["conversation_id"] == f"{TEST_PREFIX}002"]
    assert len(matched) == 1
