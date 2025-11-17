"""
Service Name Resolver with Fuzzy Matching.

Resolves service names (e.g., "corte", "corte de caballero") to Service UUIDs
using fuzzy matching. Handles ambiguity when multiple services match the query.

Used by check_availability() and book() tools to resolve service names before
querying availability or creating bookings.
"""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


async def resolve_service_names(
    service_names: list[str]
) -> tuple[list[UUID], dict[str, Any] | None]:
    """
    Resolve service names to UUIDs using fuzzy matching.

    This function takes a list of service names in natural language and resolves
    them to database UUIDs. It handles ambiguity intelligently:
    - Single match → auto-resolve to UUID
    - Multiple matches + exact match exists → use exact match
    - Multiple matches + no exact match → return ambiguity info for clarification

    Args:
        service_names: List of service names to resolve (e.g., ["Corte de Caballero", "Barba"])

    Returns:
        Tuple of (resolved_uuids, ambiguity_info):
            - resolved_uuids: list[UUID] - Successfully resolved service UUIDs
            - ambiguity_info: dict | None - Ambiguity information if detected

        Ambiguity info structure:
            {
                "query": str,        # Original query (e.g., "corte")
                "options": [         # List of matching services
                    {
                        "id": str,
                        "name": str,
                        "duration_minutes": int,
                        "category": str
                    }
                ]
            }

    Examples:
        Single match:
        >>> await resolve_service_names(["Corte de Caballero"])
        ([UUID("uuid-1")], None)

        Exact match among fuzzy matches:
        >>> await resolve_service_names(["Tinte"])  # Matches "Tinte" exactly, ignores "Tinte + Corte"
        ([UUID("uuid-2")], None)

        True ambiguity:
        >>> await resolve_service_names(["corte"])
        (
            [],
            {
                "query": "corte",
                "options": [
                    {"id": "uuid-3", "name": "Corte Bebé", "duration_minutes": 30, ...},
                    {"id": "uuid-4", "name": "Corte Niño", "duration_minutes": 30, ...},
                    {"id": "uuid-5", "name": "Corte de Caballero", "duration_minutes": 30, ...}
                ]
            }
        )

        No matches:
        >>> await resolve_service_names(["servicio inexistente"])
        ([], None)  # Empty list, no ambiguity info

    Notes:
        - Reuses logic from agent/nodes/conversational_agent.py:333-462
        - Uses agent/tools/booking_tools.py::get_service_by_name(fuzzy=True)
        - Stops at first ambiguity (handles one at a time)
        - Returns empty list if no matches found (not an error)
    """
    from agent.tools.booking_tools import get_service_by_name

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
            # Use fuzzy matching to find services (returns list)
            matching_services = await get_service_by_name(
                service_name,
                fuzzy=True,
                limit=5
            )

            if len(matching_services) == 0:
                # No matches found - log warning but continue
                logger.warning(
                    f"Could not resolve service name '{service_name}' to UUID (no matches)"
                )
                # Don't add to resolved list, but continue processing other services

            elif len(matching_services) == 1:
                # Unambiguous - single match found
                service = matching_services[0]
                resolved_uuids.append(service.id)
                logger.info(
                    f"Resolved '{service_name}' → {service.name} (UUID: {service.id})"
                )

            else:
                # Multiple matches - check if first is exact match
                normalized_query = service_name.strip().lower()
                first_match_name = matching_services[0].name.strip().lower()

                if normalized_query == first_match_name:
                    # Exact match found - use it directly (ignore other fuzzy matches)
                    service = matching_services[0]
                    resolved_uuids.append(service.id)
                    logger.info(
                        f"Exact match found (ignoring {len(matching_services) - 1} fuzzy matches): "
                        f"'{service_name}' → {service.name} (UUID: {service.id})"
                    )
                else:
                    # True ambiguity - multiple matches without exact match
                    logger.warning(
                        f"Ambiguous service query '{service_name}': {len(matching_services)} matches"
                    )

                    # Store ambiguity info for caller to handle
                    ambiguity_info = {
                        "query": service_name,
                        "options": [
                            {
                                "id": str(s.id),
                                "name": s.name,
                                "duration_minutes": s.duration_minutes,
                                "category": s.category.value,
                            }
                            for s in matching_services
                        ]
                    }

                    logger.info(
                        f"Flagging '{service_name}' as ambiguous with {len(matching_services)} options: "
                        f"{[s.name for s in matching_services]}"
                    )

                    # Stop processing more services - handle one ambiguity at a time

        except Exception as e:
            logger.error(
                f"Error resolving service '{service_name}': {e}",
                exc_info=True
            )
            # Don't add to resolved list, but continue processing

    logger.info(
        f"Service resolution complete: {len(resolved_uuids)}/{len(service_names)} resolved, "
        f"ambiguous: {ambiguity_info is not None}",
        extra={
            "resolved_uuids": [str(uuid) for uuid in resolved_uuids],
            "has_ambiguity": ambiguity_info is not None
        }
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
