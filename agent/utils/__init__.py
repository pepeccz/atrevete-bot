"""
Utility functions for v3.0 architecture.

This module contains shared utilities used by tools and transaction handlers:
- date_parser: Natural language date parsing for Spanish
- service_resolver: Service name → UUID resolution with fuzzy matching
- service_disambiguation: Metadata-driven service disambiguation resolver
"""

from agent.utils.date_parser import (
    parse_natural_date,
    get_weekday_name,
    format_date_spanish,
    MADRID_TZ,
)
from agent.utils.service_resolver import (
    resolve_service_names,
    resolve_single_service,
)
from agent.utils.service_disambiguation import (
    ClarificationPayload,
    ResolvedService,
    resolve_candidates,
)

__all__ = [
    # Date parsing
    "parse_natural_date",
    "get_weekday_name",
    "format_date_spanish",
    "MADRID_TZ",
    # Service resolution
    "resolve_service_names",
    "resolve_single_service",
    # Service disambiguation
    "ClarificationPayload",
    "ResolvedService",
    "resolve_candidates",
]
