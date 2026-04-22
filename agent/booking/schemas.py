"""Structured-output Pydantic schemas for booking LLM leaves — Phase 5.2.

Each schema has a required `message: str` field (text to send to user)
plus typed extraction fields. `model_config = ConfigDict(extra="forbid")`.
All fields carry Spanish-language `Field(description=...)` for LLM guidance.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AudienceTag


class ServiceSelectionResponse(BaseModel):
    """Respuesta del LLM para el paso de selección de servicio.

    El LLM extrae los IDs de servicio que el usuario mencionó.
    No infiere ni escribe la audiencia — eso lo hace ask_audience.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    selected_service_ids: list[UUID] | None = Field(
        default=None,
        description=(
            "Lista de UUIDs de los servicios seleccionados por el usuario. "
            "Null si aún no se pudo determinar."
        ),
    )
    needs_clarification: bool = Field(
        default=False,
        description=("True si el usuario mencionó un servicio ambiguo y se necesita aclaración."),
    )


class AudienceResponse(BaseModel):
    """Respuesta del LLM para el paso de identificación de audiencia.

    El LLM deduce para quién es el servicio según el mensaje del usuario.
    Valores válidos: adult_female, adult_male, child_female, child_male, unisex, baby.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    inferred_audience: AudienceTag | None = Field(
        default=None,
        description=(
            "Audiencia inferida del mensaje del usuario. "
            "Usar: adult_female (señora/mujer), adult_male (caballero/hombre), "
            "child_female (niña), child_male (niño), unisex, baby (bebé/bebe). "
            "Null si no se pudo determinar."
        ),
    )


class StylistResponse(BaseModel):
    """Respuesta del LLM para el paso de selección de estilista.

    El LLM extrae la preferencia de estilista o registra que no hay preferencia.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    inferred_stylist_id: UUID | None = Field(
        default=None,
        description=(
            "UUID del estilista preferido por el usuario. "
            "Null si no mencionó a ninguno en particular."
        ),
    )
    no_preference: bool = Field(
        default=False,
        description=(
            "True si el usuario indicó explícitamente que no tiene preferencia de estilista."
        ),
    )


class DateResponse(BaseModel):
    """Respuesta del LLM para el paso de selección de fecha.

    El LLM extrae la fecha deseada para el turno a partir del mensaje del usuario.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    inferred_date: date | None = Field(
        default=None,
        description=(
            "Fecha inferida del mensaje del usuario en formato YYYY-MM-DD. "
            "Null si no se pudo determinar una fecha concreta."
        ),
    )


class SlotResponse(BaseModel):
    """Respuesta del LLM para el paso de selección de turno horario.

    El LLM identifica cuál de los turnos ofrecidos eligió el usuario (por índice).
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    selected_slot_index: int | None = Field(
        default=None,
        description=(
            "Índice (0-based) del turno seleccionado por el usuario de la lista ofrecida. "
            "Null si el usuario no eligió un turno válido."
        ),
    )


class NameResponse(BaseModel):
    """Respuesta del LLM para el paso de recopilación del nombre del cliente.

    El LLM extrae nombre y apellido para registrar el turno.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    first_name: str | None = Field(
        default=None,
        description="Nombre de pila del cliente extraído del mensaje. Null si no se mencionó.",
    )
    first_surname: str | None = Field(
        default=None,
        description="Primer apellido del cliente extraído del mensaje. Null si no se mencionó.",
    )


class NotesResponse(BaseModel):
    """Respuesta del LLM para el paso de notas o solicitudes especiales.

    El LLM captura cualquier indicación especial o confirma que no hay.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    notes: str | None = Field(
        default=None,
        description=(
            "Notas o solicitudes especiales del cliente (alergias, preferencias, etc.). "
            "Null si el usuario no indicó nada o declinó."
        ),
    )
    user_declined: bool = Field(
        default=False,
        description="True si el usuario indicó explícitamente que no tiene notas especiales.",
    )


class ConfirmationResponse(BaseModel):
    """Respuesta del LLM para el paso de confirmación final del turno.

    El LLM interpreta si el usuario confirmó o rechazó el resumen del turno.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Mensaje en español para enviar al usuario.")
    confirmed: bool | None = Field(
        default=None,
        description=(
            "True si el usuario confirmó el turno, False si lo rechazó, "
            "Null si la respuesta fue ambigua."
        ),
    )
