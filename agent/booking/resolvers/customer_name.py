"""
customer_name resolver — verbatim name capture.

R1.6: fires only when _last_leaf == "ask_name"; captures verbatim text
if no other resolver already matched customer_name.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.booking.resolvers import ResolverResult

logger = logging.getLogger(__name__)


def resolve(user_text: str, bc: dict[str, Any], state: dict[str, Any]) -> ResolverResult | None:
    """Capture customer name verbatim at ask_name step.

    Returns:
        patch: {"customer_name": user_text.strip()}
        user_action: "PROVIDE_FIELD"
    or None if guard conditions fail.
    """
    # Context guard
    if bc.get("_last_leaf") != "ask_name":
        return None

    # Already set — idempotent
    if bc.get("customer_name"):
        return None

    name = user_text.strip()
    if not name:
        return None

    logger.info("resolver.customer_name.applied")
    return {
        "patch": {"customer_name": name},
        "matched": True,
        "user_action": "PROVIDE_FIELD",
    }
