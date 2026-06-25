"""
Escalation Service - Handles human escalation workflow.

This service is responsible for:
1. Disabling bot in Chatwoot (atencion_automatica = false) — CRITICAL step
2. Deduplication (5-minute window per conversation)
3. Adding Chatwoot labels and private notes
4. Assigning conversation to a team (if CHATWOOT_TEAM_ID is configured)
5. Recording the escalation in the database

The escalation system ensures conversations that the AI cannot handle are
properly transferred to human agents with full context preserved.

Architecture (N2 — DB-record-first):
- The escalation DB record (S5) is written FIRST and is the source of truth.
  success=True means the escalation IS recorded; success=False means it is NOT.
- All Chatwoot steps (disable bot, labels, note, team assign) are best-effort.
  A Chatwoot outage or non-integer conversation_id never prevents the record.

Entry points:
- perform_escalation(): Central entrypoint (new, recommended)
- trigger_escalation(): Backward-compatible wrapper (deprecated)
"""

import logging
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import get_async_session
from database.models import ConversationHistory, Customer, Notification, NotificationType

logger = logging.getLogger(__name__)

# Map escalation reasons to notification types
REASON_TO_NOTIFICATION_TYPE: dict[str, NotificationType] = {
    "medical_consultation": NotificationType.ESCALATION_MEDICAL,
    "ambiguity": NotificationType.ESCALATION_AMBIGUITY,
    "manual_request": NotificationType.ESCALATION_MANUAL,
    "technical_error": NotificationType.ESCALATION_TECHNICAL,
    "auto_escalation": NotificationType.ESCALATION_AUTO,
    # Default fallback for unknown reasons
    "default": NotificationType.ESCALATION_MANUAL,
}

# Human-readable titles for each escalation type
ESCALATION_TITLES: dict[NotificationType, str] = {
    NotificationType.ESCALATION_MEDICAL: "Escalacion: Consulta medica",
    NotificationType.ESCALATION_AMBIGUITY: "Escalacion: Solicitud ambigua",
    NotificationType.ESCALATION_MANUAL: "Escalacion: Solicitud de usuario",
    NotificationType.ESCALATION_TECHNICAL: "Escalacion: Error tecnico",
    NotificationType.ESCALATION_AUTO: "Escalacion automatica: Errores consecutivos",
}

# Human-readable reason descriptions
REASON_DESCRIPTIONS: dict[str, str] = {
    "medical_consultation": "Consulta relacionada con salud (alergias, embarazo, medicamentos)",
    "ambiguity": "Solicitud ambigua tras multiples intentos de clarificacion",
    "manual_request": "Cliente solicito hablar con persona humana",
    "technical_error": "Error tecnico en el procesamiento",
    "auto_escalation": "Multiples errores consecutivos detectados",
}


# ============================================================================
# EscalationResult dataclass
# ============================================================================


@dataclass
class EscalationResult:
    """Result of a perform_escalation() call."""

    success: bool
    escalation_id: uuid_module.UUID | None = None
    duplicate_prevented: bool = False
    steps_completed: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    user_message: str = ""


# ============================================================================
# Private helpers
# ============================================================================


async def _check_duplicate_escalation(conversation_id: str, db: Any) -> "Any | None":
    """Returns existing Escalation if recent (last 5 min), None otherwise. Fail-open."""
    try:
        from datetime import timedelta

        from database.models import Escalation

        cutoff = datetime.now(tz=UTC) - timedelta(minutes=5)
        result = await db.execute(
            select(Escalation)
            .where(
                Escalation.conversation_id == conversation_id,
                Escalation.triggered_at > cutoff,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"Dedupe check failed (fail-open): {e}")
        return None


# ============================================================================
# Legacy helpers (kept for backward compatibility)
# ============================================================================


async def create_escalation_notification(
    reason: str,
    customer_phone: str,
    conversation_id: str,
    conversation_context: list[dict[str, Any]] | None = None,
) -> UUID | None:
    """
    Create escalation notification in admin panel database.

    Args:
        reason: Escalation reason (maps to NotificationType)
        customer_phone: Customer phone number
        conversation_id: Chatwoot conversation ID
        conversation_context: Last 3-5 messages for context (optional)

    Returns:
        Notification UUID if created, None if failed
    """
    notification_type = REASON_TO_NOTIFICATION_TYPE.get(
        reason, REASON_TO_NOTIFICATION_TYPE["default"]
    )

    title = ESCALATION_TITLES.get(notification_type, "Escalacion")
    reason_description = REASON_DESCRIPTIONS.get(reason, reason)

    try:
        async with get_async_session() as session:
            # Get customer name for message
            customer_name = "Cliente"
            if customer_phone:
                stmt = select(Customer).where(Customer.phone == customer_phone)
                result = await session.execute(stmt)
                customer = result.scalar_one_or_none()
                if customer:
                    customer_name = f"{customer.first_name} {customer.last_name or ''}".strip()

            # Build message with context
            context_preview = ""
            if conversation_context:
                # Get last 3 messages for context
                recent = conversation_context[-3:]
                context_lines = []
                for msg in recent:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    # Truncate long messages
                    if len(content) > 100:
                        content = content[:100] + "..."
                    context_lines.append(f"- {role}: {content}")
                context_preview = "\n\nContexto reciente:\n" + "\n".join(context_lines)

            message = (
                f"{customer_name} ({customer_phone}) necesita atencion humana.\n"
                f"Motivo: {reason_description}\n"
                f"Conversacion ID: {conversation_id}"
                f"{context_preview}"
            )

            notification = Notification(
                type=notification_type,
                title=title,
                message=message,
                entity_type="conversation",
                entity_id=None,  # No entity_id for escalations (could link to customer in future)
            )

            session.add(notification)
            await session.commit()
            await session.refresh(notification)

            logger.info(
                f"Escalation notification created | id={notification.id} | "
                f"type={notification_type.value} | customer_phone={customer_phone}"
            )

            return notification.id

    except Exception as e:
        logger.error(
            f"Failed to create escalation notification | reason={reason} | error={str(e)}",
            exc_info=True,
        )
        return None


# ============================================================================
# Central escalation entrypoint
# ============================================================================


async def perform_escalation(
    conversation_id: str,
    customer_phone: str,
    reason: str,
    source: str,  # "manual" | "auto_error" | "fallback"
    is_technical_error: bool = False,
    issue_summary: str | None = None,
    contact_preference: str | None = None,
    conversation_context: list | None = None,
    customer_id: str | None = None,
) -> EscalationResult:
    """
    Central escalation entrypoint. DB-record-first pipeline (N2).
    The escalation DB record is critical (success reflects it); Chatwoot
    steps and the admin notification are best-effort.

    Args:
        conversation_id: Chatwoot conversation ID (numeric string)
        customer_phone: Customer phone number (E.164)
        reason: Human-readable escalation reason
        source: Source of escalation ("manual" | "auto_error" | "fallback")
        is_technical_error: True if escalation was triggered by a technical error
        issue_summary: Optional user-provided issue description
        contact_preference: Optional preferred contact method ("WhatsApp" | "llamada")
        conversation_context: Optional recent messages for context
        customer_id: Optional customer UUID string

    Returns:
        EscalationResult with step tracking and user-facing message
    """
    from shared.chatwoot_client import ChatwootClient
    from shared.config import get_settings

    settings = get_settings()
    result = EscalationResult(success=True)

    # User-facing message differentiation
    # R3b: set expectation — mention that the team will follow up, reference
    # salon availability, but do NOT promise a specific response time.
    if is_technical_error:
        result.user_message = (
            "Hubo un problema técnico de mi parte. "
            "Te paso con el equipo del salón para que te ayuden. "
            "Te contactaremos en el horario de atención. 🙏"
        )
    else:
        result.user_message = (
            "Con mucho gusto te paso con alguien del equipo del salón. "
            "Te atenderán en el próximo horario disponible. 🙏"
        )

    # Dedupe check — fail-open. Runs first so a duplicate never writes a second row.
    existing = None
    try:
        async with get_async_session() as db:
            existing = await _check_duplicate_escalation(conversation_id, db)
    except Exception as e:
        logger.warning(f"[escalation] Dedupe check error: {e}")

    if existing is not None:
        logger.info(f"[escalation] Duplicate prevented for conversation {conversation_id}")
        result.duplicate_prevented = True
        result.escalation_id = existing.id  # propagate existing escalation ID
        return result

    # S5 — DB record FIRST (N2 / V6 C2): the escalation row is the source of truth.
    # It must be written independently of any Chatwoot client work so a Chatwoot
    # outage (or a non-integer conversation_id) can never produce a phantom
    # escalation where the bot claims a handoff that was never recorded.
    try:
        from database.models import Escalation, EscalationSource

        source_enum = (
            EscalationSource(source)
            if source in EscalationSource._value2member_map_
            else EscalationSource.MANUAL
        )

        escalation_row = Escalation(
            id=uuid_module.uuid4(),
            conversation_id=conversation_id,
            customer_phone=customer_phone,
            reason=reason,
            source=source_enum,
            is_technical_error=is_technical_error,
            issue_summary=issue_summary,
            contact_preference=contact_preference,
            metadata_={"recorded": "before_chatwoot_steps"},
        )
        if customer_id:
            try:
                escalation_row.customer_id = uuid_module.UUID(customer_id)
            except ValueError:
                pass

        async with get_async_session() as db:
            db.add(escalation_row)
            # ON CONFLICT upsert — sets paused_at atomically with the Escalation row (R4/ADR-3).
            # Existing row: updates paused_at=now, resumed_at=NULL (re-pauses cleanly).
            # Absent row (first-contact): inserts a minimal ConversationHistory with paused_at=now.
            # Because this is ON CONFLICT (not a bare INSERT), a concurrent insert from the
            # webhook Step-7 upsert can no longer raise a UNIQUE violation that rolls back and
            # discards the Escalation record.
            now = datetime.now(tz=UTC)
            _pause_stmt = pg_insert(ConversationHistory).values(
                id=uuid_module.uuid4(),
                conversation_id=conversation_id,
                started_at=now,
                ended_at=now,
                message_count=0,
                paused_at=now,
                metadata_={},
            ).on_conflict_do_update(
                index_elements=[ConversationHistory.conversation_id],
                set_={"paused_at": now, "resumed_at": None},
            )
            await db.execute(_pause_stmt)
            await db.commit()
            result.escalation_id = escalation_row.id
            result.steps_completed.append("db_record")

    except Exception as e:
        logger.error(f"[escalation] S5 DB record failed: {e}", exc_info=True)
        result.success = False
        result.steps_failed.append("db_record")

    # Chatwoot phase — best-effort. A non-integer conversation_id (e.g. UUID in
    # the QA harness) or a client init failure skips ALL Chatwoot calls without
    # affecting the recorded escalation.
    client = None
    conv_id_int: int | None = None
    try:
        conv_id_int = int(conversation_id)
        client = ChatwootClient()
    except (ValueError, Exception) as e:  # noqa: B014 — client init can raise anything
        logger.warning(
            f"[escalation] Chatwoot phase skipped for conversation {conversation_id}: {e}"
        )
        result.steps_failed.extend(["labels", "private_note", "team_assign"])

    # W2 / V6: skip the entire Chatwoot notification phase when the DB record
    # failed. Bot state must follow DB truth.
    db_write_ok = "db_record" in result.steps_completed

    if client is not None and conv_id_int is not None and db_write_ok:
        # S2 — best-effort: Add labels
        try:
            labels = ["escalado", "error-tecnico"] if is_technical_error else ["escalado"]
            await client.add_conversation_labels(conv_id_int, labels)
            result.steps_completed.append("labels")
        except Exception as e:
            logger.warning(f"[escalation] S2 labels failed: {e}")
            result.steps_failed.append("labels")

        # S3 — best-effort: Add private note
        try:
            note_parts = [
                "🚨 *Escalación a humano*",
                f"• Razón: {reason}",
                f"• Origen: {source}",
                f"• Teléfono: {customer_phone}",
                f"• Conversación: {conversation_id}",
            ]
            if issue_summary:
                note_parts.append(f"• Problema: {issue_summary}")
            if contact_preference:
                note_parts.append(f"• Contacto preferido: {contact_preference}")
            note_parts.append(f"• Timestamp: {datetime.now(tz=UTC).isoformat()}")
            await client.add_private_note(conv_id_int, "\n".join(note_parts))
            result.steps_completed.append("private_note")
        except Exception as e:
            logger.warning(f"[escalation] S3 private note failed: {e}")
            result.steps_failed.append("private_note")

        # S4 — best-effort: Assign to team
        try:
            if settings.CHATWOOT_TEAM_ID:
                await client.assign_to_team(conv_id_int, settings.CHATWOOT_TEAM_ID)
                result.steps_completed.append("team_assign")
        except Exception as e:
            logger.warning(f"[escalation] S4 team assign failed: {e}")
            result.steps_failed.append("team_assign")

    # ── S6 — Admin notification (best-effort) ────────────────────────────
    try:
        notification_id = await create_escalation_notification(
            reason=reason,
            customer_phone=customer_phone,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
        )
        if notification_id is not None:
            result.steps_completed.append("admin_notification")
        else:
            result.steps_failed.append("admin_notification")
    except Exception as e:
        logger.warning("[escalation] S6 admin notification failed: %s", e)
        result.steps_failed.append("admin_notification")

    logger.info(
        f"[escalation] Completed | conversation_id={conversation_id} | "
        f"success={result.success} | steps_completed={result.steps_completed} | "
        f"steps_failed={result.steps_failed}"
    )

    return result


# ============================================================================
# Backward-compatible aliases
# ============================================================================


async def trigger_escalation(
    reason: str,
    conversation_id: str,
    customer_phone: str,
    conversation_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Execute full escalation workflow.

    Deprecated: use perform_escalation() instead.
    Kept for backward compatibility with existing callers.

    Returns:
        Dict with escalation result keys for legacy consumers.
    """
    result = await perform_escalation(
        conversation_id=conversation_id,
        customer_phone=customer_phone,
        reason=reason,
        source="manual",
        conversation_context=conversation_context,
    )
    return {
        "chatwoot_disabled": "disable_bot" in result.steps_completed,
        "notification_id": result.escalation_id,
        "webhooks_triggered": [],
    }
