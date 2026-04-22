"""Structured-output Pydantic schemas for booking LLM leaves — Phase 5.2.

Each schema has a required `message: str` field (text to send to user)
plus typed extraction fields. `model_config = ConfigDict(extra="forbid")`.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agent.state import AudienceTag


class ServiceSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    selected_service_ids: list[UUID] | None = None
    suggested_audience: AudienceTag | None = None
    needs_clarification: bool = False


class AudienceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    inferred_audience: AudienceTag | None = None


class StylistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    inferred_stylist_id: UUID | None = None
    no_preference: bool = False


class DateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    inferred_date: date | None = None


class SlotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    selected_slot_index: int | None = None


class NameResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    first_name: str | None = None
    first_surname: str | None = None


class NotesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    notes: str | None = None
    user_declined: bool = False


class ConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    confirmed: bool | None = None
