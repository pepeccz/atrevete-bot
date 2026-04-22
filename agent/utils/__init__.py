"""
Utility functions for v3.0 architecture.

This module contains shared utilities used by tools and transaction handlers:
- date_parser: Natural language date parsing for Spanish
- fuzzy_resolver: Deterministic strategy-chain fuzzy option resolution
"""

from agent.utils.date_parser import (
    MADRID_TZ,
    DateParseError,
    format_date_es,
    format_date_spanish,
    get_weekday_name,
    parse_natural_date,
)
from agent.utils.fuzzy_resolver import (
    Match,
    normalize_spanish,
    resolve_from_options,
    resolve_ordinal,
    resolve_time_slot,
)

__all__ = [
    # Date parsing
    "parse_natural_date",
    "get_weekday_name",
    "format_date_spanish",
    "format_date_es",
    "DateParseError",
    "MADRID_TZ",
    # Fuzzy resolution
    "Match",
    "normalize_spanish",
    "resolve_from_options",
    "resolve_time_slot",
    "resolve_ordinal",
]
