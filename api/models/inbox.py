"""
Pydantic request/response models for the human-agent inbox endpoints.

These models cover the 7 new admin endpoints added in PR-2:
  - send-message, send-template, pause, resume, escalate (POST)
  - window-status, templates (GET)

All models use Pydantic v2 conventions (model_config, Field validators).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared response
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Response returned after a human-agent message is sent and persisted."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    created_at: datetime
    author_username: str | None = None


# ---------------------------------------------------------------------------
# send-message
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    """Body for POST /{conversation_id}/send-message."""

    text: str = Field(min_length=1, max_length=4096, description="Free-text message body.")


class SendMessageResponse(MessageResponse):
    """Response for send-message — alias kept for symmetry."""


# ---------------------------------------------------------------------------
# send-template
# ---------------------------------------------------------------------------


class SendTemplateRequest(BaseModel):
    """Body for POST /{conversation_id}/send-template."""

    template_name: str = Field(description="Machine-readable template name from the catalog.")
    params: dict[str, str] = Field(
        default_factory=dict,
        description="Parameter dict matching the template's ParamDef list.",
    )


class SendTemplateResponse(MessageResponse):
    """Response for send-template."""


# ---------------------------------------------------------------------------
# pause
# ---------------------------------------------------------------------------


class PauseRequest(BaseModel):
    """Body for POST /{conversation_id}/pause."""

    reason: str | None = Field(default=None, description="Optional reason for pausing.")
    source: Literal["manual", "toggle"] = Field(
        default="toggle",
        description=(
            "'manual' when the takeover modal was confirmed (creates Escalation row), "
            "'toggle' for direct toggle without modal."
        ),
    )


class PauseResponse(BaseModel):
    """Response for pause."""

    paused_at: datetime
    escalation_id: UUID | None = None


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


class ResumeRequest(BaseModel):
    """Body for POST /{conversation_id}/resume — empty body accepted."""


class ResumeResponse(BaseModel):
    """Response for resume."""

    resumed_at: datetime
    pending_injection_ttl_seconds: int = 600


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------


class EscalateRequest(BaseModel):
    """Body for POST /{conversation_id}/escalate."""

    reason: str = Field(description="Short reason for the escalation.")
    note: str | None = Field(default=None, description="Optional longer note.")


class EscalateResponse(BaseModel):
    """Response for escalate."""

    escalation_id: UUID


# ---------------------------------------------------------------------------
# window-status
# ---------------------------------------------------------------------------


class WindowStatusResponse(BaseModel):
    """Response for GET /{conversation_id}/window-status."""

    window_open: bool
    last_user_message_at: datetime | None = None
    hours_until_close: float | None = None


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


class ParamDefResponse(BaseModel):
    """A single parameter slot for a Meta template."""

    name: str
    label: str
    description: str = ""


class TemplateDefResponse(BaseModel):
    """A single template entry returned by GET /templates."""

    name: str
    display_name: str
    status: Literal["approved", "pending"]
    params: list[ParamDefResponse]


class TemplateListResponse(BaseModel):
    """Response for GET /templates."""

    items: list[TemplateDefResponse]


# ---------------------------------------------------------------------------
# mark-read (PR-1)
# ---------------------------------------------------------------------------


class MarkReadRequest(BaseModel):
    """Optional body for POST /{conversation_id}/mark-read.

    When ``up_to_message_id`` is omitted all unread messages in the
    conversation are marked.
    """

    up_to_message_id: UUID | None = Field(
        default=None,
        description="Mark only messages up to and including this message UUID.",
    )


class MarkReadResponse(BaseModel):
    """Response for mark-read."""

    marked: int = Field(description="Number of messages whose read_at was updated.")


# ---------------------------------------------------------------------------
# PR-3a — attachment DTO
# ---------------------------------------------------------------------------


class AttachmentDTO(BaseModel):
    """Single attachment as returned within a MessageDetailDTO.

    Fields mirror the ``message_attachments`` table columns exactly so the
    ORM ``from_attributes=True`` mapping works without a custom serializer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_type: str
    url: str
    thumb_url: str | None = None
    content_type: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    position: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Extended message DTO (PR-1) — additive fields
# ---------------------------------------------------------------------------


class MessageDetailDTO(BaseModel):
    """Per-message fields returned on GET /conversations/{id}.

    Additive over the plain dict used today. Backward-compat: existing
    consumers still get role, content, created_at, chatwoot_message_id.
    PR-3a: ``attachments`` list is populated by the ORM selectin relationship.
    """

    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str | None
    created_at: datetime
    chatwoot_message_id: int | None = None
    author_type: str | None = None
    read_at: datetime | None = None
    delivery_failed: bool = False
    attachments: list[AttachmentDTO] = []


# ---------------------------------------------------------------------------
# conversation notes (PR-2)
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    """Body for POST /{conversation_id}/notes."""

    content: str = Field(min_length=1, max_length=4000, description="Note body.")


class NoteUpdate(BaseModel):
    """Body for PATCH /notes/{note_id}."""

    content: str = Field(min_length=1, max_length=4000, description="Updated note body.")


class ConversationNoteDTO(BaseModel):
    """Single note as returned by GET/POST/PATCH note endpoints."""

    id: str
    content: str
    author_user_id: str | None = None
    author_name: str
    created_at: str
    updated_at: str


class NoteListResponse(BaseModel):
    """Response for GET /{conversation_id}/notes."""

    items: list[ConversationNoteDTO]


# ---------------------------------------------------------------------------
# sidebar aggregate (PR-2)
# ---------------------------------------------------------------------------


class SidebarCustomer(BaseModel):
    """Customer summary within the sidebar response."""

    id: str
    name: str
    phone: str
    customer_notes_count: int


class SidebarEscalation(BaseModel):
    """Active escalation summary within the sidebar response."""

    id: str
    reason: str
    triggered_at: str


class SidebarResponse(BaseModel):
    """Response for GET /{conversation_id}/sidebar."""

    customer: SidebarCustomer | None = None
    notes: list[ConversationNoteDTO] = Field(default_factory=list)
    active_escalation: SidebarEscalation | None = None
