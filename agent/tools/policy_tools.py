"""
Policy tools for conversational agent.

Provides access to business policies (payment, cancellation) from database.
"""

import logging
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from database.connection import get_async_session
from database.models import Policy

logger = logging.getLogger(__name__)


@tool
async def get_payment_policies() -> dict[str, Any]:
    """
    Get payment and booking policies from database.

    Retrieves policies related to advance payment, provisional booking timeouts,
    and payment retry logic. Essential for explaining payment requirements to customers.

    Returns:
        Dict with:
        - advance_payment_percentage: Percentage of total required as anticipo (typically 20%)
        - provisional_timeout_standard: Minutes to complete payment for standard bookings (typically 30)
        - provisional_timeout_same_day: Minutes to complete payment for same-day bookings (typically 10)
        - formatted: Human-readable Spanish summary of payment policies

    Example:
        >>> result = await get_payment_policies()
        >>> result["advance_payment_percentage"]
        20
        >>> result["formatted"]
        "Anticipo: 20% del total. Tiempo para pagar: 30 minutos (10 minutos para citas del mismo día)."
    """
    try:
        async for session in get_async_session():
            # Query payment-related policies
            query = select(Policy).where(
                Policy.key.in_([
                    "advance_payment_percentage",
                    "provisional_timeout_standard",
                    "provisional_timeout_same_day",
                ])
            )
            result = await session.execute(query)
            policies = list(result.scalars().all())
            break

        if not policies:
            logger.warning("No payment policies found in database")
            return {
                "advance_payment_percentage": 20,  # Fallback default
                "provisional_timeout_standard": 30,
                "provisional_timeout_same_day": 10,
                "formatted": "Políticas de pago no configuradas (usando valores por defecto)",
                "error": "No payment policies configured",
            }

        # Parse policies
        policies_dict = {}
        for policy in policies:
            value_data = policy.value  # JSONB dict

            if policy.key == "advance_payment_percentage":
                policies_dict["advance_payment_percentage"] = value_data.get("payment_percentage", 20)
            elif policy.key == "provisional_timeout_standard":
                policies_dict["provisional_timeout_standard"] = value_data.get("timeout_minutes", 30)
            elif policy.key == "provisional_timeout_same_day":
                policies_dict["provisional_timeout_same_day"] = value_data.get("timeout_minutes", 10)

        # Generate formatted summary
        advance_pct = policies_dict.get("advance_payment_percentage", 20)
        timeout_std = policies_dict.get("provisional_timeout_standard", 30)
        timeout_same_day = policies_dict.get("provisional_timeout_same_day", 10)

        formatted = (
            f"Anticipo requerido: {advance_pct}% del total del servicio. "
            f"Tiempo para completar el pago: {timeout_std} minutos (reservas estándar) "
            f"o {timeout_same_day} minutos (reservas para el mismo día). "
            f"Tras el tiempo límite, la cita provisional se libera automáticamente."
        )

        logger.info("Retrieved payment policies successfully")

        return {
            "advance_payment_percentage": advance_pct,
            "provisional_timeout_standard": timeout_std,
            "provisional_timeout_same_day": timeout_same_day,
            "formatted": formatted,
        }

    except Exception as e:
        logger.error(f"Error in get_payment_policies: {e}", exc_info=True)
        return {
            "advance_payment_percentage": 20,  # Fallback
            "provisional_timeout_standard": 30,
            "provisional_timeout_same_day": 10,
            "formatted": "Error consultando políticas de pago",
            "error": str(e),
        }


@tool
async def get_cancellation_policy() -> dict[str, Any]:
    """
    Get cancellation and refund policy from database.

    Retrieves the threshold hours for penalty-free cancellation and
    refund conditions. Used when customers ask about cancellation terms.

    Returns:
        Dict with:
        - threshold_hours: Hours before appointment for penalty-free cancellation (typically 24)
        - formatted: Human-readable Spanish explanation of cancellation policy

    Example:
        >>> result = await get_cancellation_policy()
        >>> result["threshold_hours"]
        24
        >>> result["formatted"]
        "Cancelación con más de 24 horas: reembolso completo. Menos de 24 horas: sin reembolso."
    """
    try:
        async for session in get_async_session():
            # Query cancellation policy
            query = select(Policy).where(Policy.key == "cancellation_threshold_hours")
            result = await session.execute(query)
            policy = result.scalar_one_or_none()
            break

        if not policy:
            logger.warning("No cancellation policy found in database")
            return {
                "threshold_hours": 24,  # Fallback default
                "formatted": "Política de cancelación no configurada (usando 24 horas por defecto)",
                "error": "No cancellation policy configured",
            }

        # Parse policy value
        value_data = policy.value  # JSONB dict
        threshold_hours = value_data.get("threshold_hours", 24)

        # Generate formatted summary
        formatted = (
            f"Cancelación con más de {threshold_hours} horas de antelación: reembolso completo del anticipo "
            f"(procesado vía Stripe, tarda 5-10 días hábiles). "
            f"Cancelación con {threshold_hours} horas o menos: sin reembolso, pero puedes reprogramar "
            f"la cita manteniendo el anticipo pagado."
        )

        logger.info("Retrieved cancellation policy successfully")

        return {
            "threshold_hours": threshold_hours,
            "formatted": formatted,
        }

    except Exception as e:
        logger.error(f"Error in get_cancellation_policy: {e}", exc_info=True)
        return {
            "threshold_hours": 24,  # Fallback
            "formatted": "Error consultando política de cancelación",
            "error": str(e),
        }
