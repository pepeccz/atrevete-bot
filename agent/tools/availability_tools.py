"""Admin-compat re-export shim — Phase 7.4.

api/routes/admin.py imports check_availability from this module via a
lazy-import block. The canonical implementation lives in
agent/tools/check_availability.py; this file re-exports it so the admin
route resolves without change.

Do NOT add agent-graph logic here — this module is for api/ compat only.
"""

from agent.tools.check_availability import check_availability  # noqa: F401
from agent.tools.next_available import get_next_available_options  # noqa: F401

__all__ = ["check_availability", "get_next_available_options"]
