"""
Seed data script for FAQ policies.

Populates 5 core FAQs for the Atrévete salon chatbot (Maite).
Can be run standalone: python -m database.seeds.faqs
"""

import asyncio

from sqlalchemy.dialects.postgresql import insert

from database.connection import get_async_session
from database.models import Policy

# 5 Core FAQs for Story 2.6
FAQ_POLICIES = [
    {
        "key": "faq:hours",
        "value": {
            "faq_id": "hours",
            "question_patterns": [
                "¿qué horario?",
                "¿abrís?",
                "¿cuándo abren?",
                "horarios",
                "¿hasta qué hora?",
                "¿abren domingos?",
                "¿abrís sábados?",
                "¿a qué hora cierran?",
            ],
            "answer": "Estamos abiertos de lunes a viernes de 10:00 a 20:00, y los sábados de 10:00 a 14:00 🌸. Los domingos cerramos para descansar 😊.",
            "category": "general",
            "requires_location_link": False,
        },
        "description": "FAQ: Business hours",
    },
    {
        "key": "faq:parking",
        "value": {
            "faq_id": "parking",
            "question_patterns": [
                "¿hay parking?",
                "¿dónde aparcar?",
                "¿hay aparcamiento?",
                "parking",
                "zona azul",
                "estacionamiento",
            ],
            "answer": "Sí 😊, hay parking público muy cerca y también zona azul en la calle. Es fácil encontrar sitio 🚗.",
            "category": "general",
            "requires_location_link": False,
        },
        "description": "FAQ: Parking information",
    },
    {
        "key": "faq:address",
        "value": {
            "faq_id": "address",
            "question_patterns": [
                "¿dónde están?",
                "¿cuál es la dirección?",
                "¿cómo llego?",
                "ubicación",
                "dirección",
                "¿dónde es?",
            ],
            "answer": "Estamos en Alcobendas 📍. ¿Te gustaría que te envíe el enlace de Google Maps para llegar fácilmente?",
            "category": "location",
            "requires_location_link": True,
        },
        "description": "FAQ: Address and location",
    },
    {
        "key": "faq:cancellation_policy",
        "value": {
            "faq_id": "cancellation_policy",
            "question_patterns": [
                "¿puedo cancelar?",
                "política de cancelación",
                "¿y si cancelo?",
                "cancelación",
                "¿me devuelven el dinero?",
                "reembolso",
            ],
            "answer": "Si cancelas con más de 24 horas de antelación, te devolvemos el anticipo completo 💕. Si es con menos de 24h, no hay reembolso, pero te ofrecemos reprogramar tu cita sin perder el anticipo 😊.",
            "category": "policy",
            "requires_location_link": False,
        },
        "description": "FAQ: Cancellation policy",
    },
    {
        "key": "faq:payment_info",
        "value": {
            "faq_id": "payment_info",
            "question_patterns": [
                "¿cómo se paga?",
                "¿hay que pagar por adelantado?",
                "anticipo",
                "¿cuánto hay que pagar?",
                "forma de pago",
                "¿aceptan tarjeta?",
            ],
            "answer": "Para confirmar tu cita, pedimos un anticipo del 20% que se paga online con tarjeta de forma segura 💳. El resto lo pagas en el salón después del servicio 🌸.",
            "category": "policy",
            "requires_location_link": False,
        },
        "description": "FAQ: Payment and advance payment information",
    },
]


async def seed_faqs() -> None:
    """
    Seed policies table with 5 core FAQs for Maite chatbot.

    Uses UPSERT logic (INSERT ON CONFLICT UPDATE) to avoid duplicates.
    Each FAQ is stored with key pattern: faq:{faq_id}
    """
    async for session in get_async_session():
        for faq_data in FAQ_POLICIES:
            # Use PostgreSQL UPSERT: INSERT ... ON CONFLICT (key) DO UPDATE
            stmt = insert(Policy).values(
                key=faq_data["key"],
                value=faq_data["value"],
                description=faq_data.get("description"),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": stmt.excluded.value,
                    "description": stmt.excluded.description,
                },
            )
            await session.execute(stmt)

            faq_id = faq_data["value"]["faq_id"]
            print(f"✓ Seeded FAQ: {faq_id} (key: {faq_data['key']})")

        await session.commit()

    print(f"\n✓ Successfully seeded {len(FAQ_POLICIES)} FAQs")


if __name__ == "__main__":
    asyncio.run(seed_faqs())
