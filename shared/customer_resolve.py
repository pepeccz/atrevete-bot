"""Customer cache resolution — forward shim.

Implementation lives in agent.middleware.customer_resolve.
This module is a thin re-export shim so api/routes/admin.py can import from
shared.* without crossing the api → agent boundary.

Note: _invalidate_cached_customer is a private (_-prefixed) symbol. Re-exporting
it here is a pre-existing API leak — the function was already consumed by admin.py
directly. This PR does not address the hygiene issue; making it a public API on
the middleware module is a follow-up change (out of scope for sdd/agent-tools-shared-extraction).

Do NOT add implementation logic here. All logic stays in agent.middleware.
Test mock paths (agent.middleware.customer_resolve.*) remain unchanged.
"""

from agent.middleware.customer_resolve import _invalidate_cached_customer

__all__ = [
    "_invalidate_cached_customer",
]
