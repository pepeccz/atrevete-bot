"""
FAQ tools for conversational agent.

Provides access to FAQ/policy information from database.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from database.connection import get_async_session
from database.models import Policy

logger = logging.getLogger(__name__)


class GetFAQsSchema(BaseModel):
    """Schema for get_faqs tool parameters."""

    keywords: list[str] | None = Field(
        default=None,
        description="Optional list of FAQ category keywords to filter (e.g., ['hours', 'parking', 'address'])"
    )


@tool(args_schema=GetFAQsSchema)
async def get_faqs(keywords: list[str] | None = None) -> dict[str, Any]:
    """
    Get FAQ/policy information from database.

    Queries the policies table for FAQ answers. Can filter by keywords
    or return all active policies.

    Args:
        keywords: Optional list of category keywords to filter FAQs

    Returns:
        Dict with:
        - faqs: List of FAQ dicts with 'category', 'question', 'answer'
        - count: Number of FAQs returned

    Example:
        >>> result = await get_faqs(["hours", "address"])
        >>> result["faqs"]
        [{"category": "hours", "question": "¿A qué hora abrís?", "answer": "..."}]
    """
    try:
        async for session in get_async_session():
            # Filter only FAQ policies (keys starting with 'faq_')
            query = select(Policy).where(Policy.key.like('faq_%'))

            result = await session.execute(query)
            policies = list(result.scalars().all())
            break

        # Parse JSONB value field to extract FAQ data
        faqs = []
        for policy in policies:
            faq_data = policy.value  # JSONB dict with 'question', 'answer', 'keywords'

            # Filter by keywords if provided (match against FAQ keywords)
            if keywords:
                faq_keywords = faq_data.get("keywords", [])
                # Check if any requested keyword matches FAQ keywords
                if not any(kw in faq_keywords for kw in keywords):
                    continue

            faqs.append({
                "category": policy.key.replace("faq_", ""),  # Extract category from key
                "question": faq_data.get("question", ""),
                "answer": faq_data.get("answer", ""),
            })

        logger.info(f"Retrieved {len(faqs)} FAQs" + (f" for keywords: {keywords}" if keywords else ""))

        return {
            "faqs": faqs,
            "count": len(faqs),
        }

    except Exception as e:
        logger.error(f"Error in get_faqs: {e}", exc_info=True)
        return {
            "faqs": [],
            "count": 0,
            "error": "Error consultando FAQs",
        }
