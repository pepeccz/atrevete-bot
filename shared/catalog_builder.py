"""Service catalog builder — forward shim.

Implementation lives in agent.prompts.catalog_builder.
This module is a thin re-export shim so api/routes/admin.py can import from
shared.* without crossing the api → agent boundary.

Do NOT add implementation logic here. All logic stays in agent.prompts.
Test mock paths (agent.prompts.catalog_builder.*) remain unchanged.
"""

from agent.prompts.catalog_builder import invalidate_catalog_cache

__all__ = [
    "invalidate_catalog_cache",
]
