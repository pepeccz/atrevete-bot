"""
Atrévete Bot — Token Usage Pydantic schemas.

Schemas for LLM token consumption tracking and cost calculation.
"""

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from shared.config import Settings, get_settings


@lru_cache(maxsize=1)
def _get_cached_settings() -> Settings:
    """Cache settings to avoid repeated calls in computed fields."""
    return get_settings()


# =============================================================================
# Token Usage Schemas
# =============================================================================


class TokenUsageResponse(BaseModel):
    """Schema for token usage response with computed costs."""

    id: UUID
    year: int = Field(..., description="Year (e.g., 2026)")
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    input_tokens: int = Field(..., description="Total input/prompt tokens")
    output_tokens: int = Field(..., description="Total output/completion tokens")
    total_requests: int = Field(..., description="Number of LLM requests")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens

    @computed_field
    @property
    def cost_input_eur(self) -> Decimal:
        """Cost of input tokens in EUR."""
        settings = _get_cached_settings()
        return (Decimal(self.input_tokens) / Decimal(1_000_000)) * settings.TOKEN_PRICE_INPUT

    @computed_field
    @property
    def cost_output_eur(self) -> Decimal:
        """Cost of output tokens in EUR."""
        settings = _get_cached_settings()
        return (Decimal(self.output_tokens) / Decimal(1_000_000)) * settings.TOKEN_PRICE_OUTPUT

    @computed_field
    @property
    def cost_total_eur(self) -> Decimal:
        """Total cost in EUR."""
        return self.cost_input_eur + self.cost_output_eur


class TokenUsageListResponse(BaseModel):
    """Schema for paginated token usage list."""

    items: list[TokenUsageResponse]
    total: int


class CurrentMonthUsageResponse(BaseModel):
    """Schema for current month usage (simplified, without ID/timestamps)."""

    year: int
    month: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_requests: int
    cost_input_eur: Decimal
    cost_output_eur: Decimal
    cost_total_eur: Decimal


class TokenPricingResponse(BaseModel):
    """Schema for current pricing configuration."""

    input_price_per_million: Decimal = Field(
        ..., description="Price per million input tokens in EUR"
    )
    output_price_per_million: Decimal = Field(
        ..., description="Price per million output tokens in EUR"
    )
