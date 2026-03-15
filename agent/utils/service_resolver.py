"""
Service Name Resolver with Fuzzy Matching + Metadata Disambiguation.

Resolves service names (e.g., "corte", "corte de caballero") to Service UUIDs
using fuzzy matching, then delegates to the shared service_disambiguation
resolver for metadata-backed families.

Used by check_availability() and book() tools to resolve service names before
querying availability or creating bookings.

v3.2 changes
============
- Integrate shared ``resolve_candidates()`` resolver (agent/services/service_disambiguation.py)
  for consistent disambiguation behaviour between search and booking paths.
- When ``resolve_candidates`` returns a ``ResolvedService`` → use its UUID directly.
- When ``resolve_candidates`` returns a ``ClarificationPayload`` → surface as
  structured ambiguity info so booking_tools.py can return AMBIGUOUS_SERVICE.
- Backward compatibility: unambiguous names (single fuzzy match or exact match)
  continue to resolve as before.
"""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


async def resolve_service_names(
    service_names: list[str],
    *,
    audience: str | None = None,
    hair_length: str | None = None,
    hair_density: str | None = None,
) -> tuple[list[UUID], dict[str, Any] | None]:
    """
    Resolve service names to UUIDs using fuzzy matching + metadata disambiguation.

    This function takes a list of service names in natural language and resolves
    them to database UUIDs. It handles ambiguity intelligently:

    1. Single fuzzy match → auto-resolve to UUID.
    2. Multiple fuzzy matches + exact name match → use exact match (fast-path).
    3. Multiple fuzzy matches → pass to ``resolve_candidates()`` resolver:
       a. Metadata available → apply provided axes; if single result → resolve.
       b. Metadata available → axes insufficient → surface ClarificationPayload.
       c. No metadata → keep legacy behaviour (return options list for LLM).

    Args:
        service_names: List of service names to resolve, e.g.
            ``["Corte de Caballero", "Barba"]``.
        audience:     Customer's audience axis, e.g. ``"adult_male"`` (optional).
        hair_length:  Customer's hair_length axis (optional).
        hair_density: Customer's hair_density axis (optional).

    Returns:
        Tuple of (resolved_uuids, ambiguity_info):
            - ``resolved_uuids``: list[UUID] — Successfully resolved service UUIDs.
            - ``ambiguity_info``: dict | None — Ambiguity information if detected.

        Ambiguity info shapes:

        Metadata-backed clarification (ClarificationPayload converted to dict):
            {
                "type": "clarification",
                "query": str,
                "axis": str,               # e.g. "hair_density"
                "question_hint": str,
                "options": [               # concrete service options
                    {"label", "value", "service_name", "service_id", "duration_minutes"}
                ]
            }

        Legacy fuzzy ambiguity (for services without metadata):
            {
                "type": "options",
                "query": str,
                "options": [
                    {"id": str, "name": str, "duration_minutes": int, "category": str}
                ]
            }

    Examples:
        Unambiguous:
        >>> await resolve_service_names(["Corte de Caballero"])
        ([UUID("uuid-1")], None)

        Metadata-disambiguated:
        >>> await resolve_service_names(["mechas"], hair_density="normal")
        ([UUID("mechas-uuid")], None)

        Clarification needed:
        >>> await resolve_service_names(["mechas"])
        ([], {"type": "clarification", "axis": "hair_density", ...})

        No matches:
        >>> await resolve_service_names(["servicio inexistente"])
        ([], None)

    Notes:
        - Uses agent/tools/booking_tools.py::get_service_by_name(fuzzy=True)
        - Stops at first ambiguity (handles one at a time)
        - Returns empty list if no matches found (not an error)
    """
    # Lazy imports to avoid circular dependency through agent.services.__init__
    # (importing at module level triggers availability_service → database.connection → asyncpg)
    from agent.tools.booking_tools import get_service_by_name
    from agent.utils.service_disambiguation import (  # noqa: PLC0415
        ClarificationPayload,
        ResolvedService,
        resolve_candidates,
    )

    if not service_names:
        logger.warning("resolve_service_names called with empty list")
        return ([], None)

    logger.info(
        f"Resolving {len(service_names)} service names to UUIDs",
        extra={"service_names": service_names}
    )

    resolved_uuids: list[UUID] = []
    ambiguity_info: dict[str, Any] | None = None

    for service_name in service_names:
        try:
            # Step 1: Fuzzy match against the catalog
            matching_services = await get_service_by_name(
                service_name,
                fuzzy=True,
                limit=5,
            )

            if len(matching_services) == 0:
                logger.warning(
                    f"Could not resolve service name '{service_name}' to UUID (no matches)"
                )
                continue  # No match — skip, don't abort

            if len(matching_services) == 1:
                # Unambiguous single fuzzy match
                service = matching_services[0]
                resolved_uuids.append(service.id)
                logger.info(
                    f"Resolved '{service_name}' → {service.name} (UUID: {service.id})"
                )
                continue

            # Step 2: Multiple matches — try exact name first (fast-path)
            normalized_query = service_name.strip().lower()
            first_match_name = matching_services[0].name.strip().lower()

            if normalized_query == first_match_name:
                service = matching_services[0]
                resolved_uuids.append(service.id)
                logger.info(
                    f"Exact match (ignoring {len(matching_services) - 1} fuzzy matches): "
                    f"'{service_name}' → {service.name} (UUID: {service.id})"
                )
                continue

            # Step 3: Delegate to shared metadata resolver
            disambiguation = resolve_candidates(
                matching_services,
                audience=audience,
                hair_length=hair_length,
                hair_density=hair_density,
            )

            if isinstance(disambiguation, ResolvedService):
                # Metadata resolved to a single service
                resolved_uuids.append(disambiguation.id)
                logger.info(
                    f"Metadata-resolved '{service_name}' → {disambiguation.name} "
                    f"(UUID: {disambiguation.id})"
                )
                continue

            if isinstance(disambiguation, ClarificationPayload):
                # Metadata ambiguity — surface structured clarification
                logger.warning(
                    f"Ambiguous service '{service_name}' requires clarification: "
                    f"axis='{disambiguation.axis}'"
                )
                ambiguity_info = {
                    "type": "clarification",
                    "query": service_name,
                    "axis": disambiguation.axis,
                    "question_hint": disambiguation.question_hint,
                    "options": disambiguation.options,
                }
                # Stop — handle one ambiguity at a time
                break

            # Step 4: Fallback (list returned — no metadata)
            logger.warning(
                f"Ambiguous service query '{service_name}': "
                f"{len(matching_services)} matches (no metadata)"
            )
            ambiguity_info = {
                "type": "options",
                "query": service_name,
                "options": [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "duration_minutes": s.duration_minutes,
                        "category": s.category.value,
                    }
                    for s in matching_services
                ],
            }
            logger.info(
                f"Flagging '{service_name}' as ambiguous with {len(matching_services)} options: "
                f"{[s.name for s in matching_services]}"
            )
            # Stop — handle one ambiguity at a time
            break

        except Exception as e:
            logger.error(
                f"Error resolving service '{service_name}': {e}",
                exc_info=True,
            )
            # Don't add to resolved list, but continue processing

    logger.info(
        f"Service resolution complete: {len(resolved_uuids)}/{len(service_names)} resolved, "
        f"ambiguous: {ambiguity_info is not None}",
        extra={
            "resolved_uuids": [str(uuid) for uuid in resolved_uuids],
            "has_ambiguity": ambiguity_info is not None,
        },
    )

    return (resolved_uuids, ambiguity_info)


async def resolve_single_service(service_name: str) -> UUID | dict[str, Any]:
    """
    Convenience function to resolve a single service name.

    Args:
        service_name: Service name to resolve

    Returns:
        UUID if unambiguous, dict with ambiguity info if ambiguous

    Raises:
        ValueError: If service not found (0 matches)

    Example:
        >>> uuid = await resolve_single_service("Corte de Caballero")
        >>> # Returns UUID directly

        >>> ambiguity = await resolve_single_service("corte")
        >>> # Returns {"query": "corte", "options": [...]}
    """
    resolved_uuids, ambiguity_info = await resolve_service_names([service_name])

    if ambiguity_info:
        return ambiguity_info

    if not resolved_uuids:
        raise ValueError(f"Service '{service_name}' not found in database")

    return resolved_uuids[0]
