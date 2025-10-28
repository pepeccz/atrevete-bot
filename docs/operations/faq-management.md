# FAQ Management Guide

## Overview

This document explains how to manage Frequently Asked Questions (FAQs) for the Maite chatbot. FAQs provide instant answers to common customer questions without requiring human escalation.

## FAQ Storage

FAQs are stored in the `policies` table in PostgreSQL database using JSONB format.

### Storage Structure

- **Table**: `policies`
- **Key Pattern**: `faq:{faq_id}` (e.g., `faq:hours`, `faq:parking`)
- **Value**: JSONB object containing FAQ data
- **Description**: Text description of the FAQ purpose

### JSONB Structure

```json
{
  "faq_id": "hours",
  "question_patterns": [
    "¿qué horario?",
    "¿abrís?",
    "¿cuándo abren?",
    "horarios"
  ],
  "answer": "Estamos abiertos de lunes a viernes de 10:00 a 20:00, y los sábados de 10:00 a 14:00 🌸. Los domingos cerramos para descansar 😊.",
  "category": "general",
  "requires_location_link": false
}
```

### Required Fields

- `faq_id` (string): Unique identifier (e.g., "hours", "parking", "address")
- `question_patterns` (array): List of question variations customers might ask
- `answer` (string): Response text in Maite's tone with emojis
- `category` (string): FAQ category - "general", "policy", or "location"
- `requires_location_link` (boolean): If true, Google Maps link is appended

## Current FAQs

### 1. Business Hours (`faq:hours`)
- **Category**: general
- **Answer**: Operating hours (Mon-Fri 10:00-20:00, Sat 10:00-14:00, Sun closed)
- **Question patterns**: "¿qué horario?", "¿abrís?", "¿cuándo abren?", etc.

### 2. Parking (`faq:parking`)
- **Category**: general
- **Answer**: Parking availability and location information
- **Question patterns**: "¿hay parking?", "¿dónde aparcar?", etc.

### 3. Address/Location (`faq:address`)
- **Category**: location
- **Answer**: Salon location with Google Maps link offer
- **Question patterns**: "¿dónde están?", "¿cuál es la dirección?", etc.
- **Special**: Includes Google Maps link

### 4. Cancellation Policy (`faq:cancellation_policy`)
- **Category**: policy
- **Answer**: 24-hour cancellation policy and refund information
- **Question patterns**: "¿puedo cancelar?", "política de cancelación", etc.

### 5. Payment Information (`faq:payment_info`)
- **Category**: policy
- **Answer**: 20% advance payment and payment methods
- **Question patterns**: "¿cómo se paga?", "anticipo", etc.

## Adding New FAQs

### Step 1: Edit Seed Script

Open `database/seeds/faqs.py` and add a new FAQ entry to the `FAQ_POLICIES` list:

```python
{
    "key": "faq:new_faq_id",
    "value": {
        "faq_id": "new_faq_id",
        "question_patterns": [
            "pattern 1",
            "pattern 2",
            "pattern 3",
        ],
        "answer": "Your answer text here with emojis 😊",
        "category": "general",  # or "policy" or "location"
        "requires_location_link": False,
    },
    "description": "FAQ: Brief description",
}
```

### Step 2: Run Seed Script

```bash
cd /home/pepe/atrevete-bot
DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db" \
./venv/bin/python -m database.seeds.faqs
```

### Step 3: Verify Database

```bash
docker exec atrevete-postgres psql -U atrevete -d atrevete_db \
-c "SELECT key, value->>'faq_id', value->>'category' FROM policies WHERE key LIKE 'faq:%';"
```

### Step 4: Restart Agent Container

```bash
docker compose restart agent
```

The new FAQ will be automatically detected and used by Maite.

## Updating Existing FAQs

### Update Answer Text Only

1. Edit the answer text in `database/seeds/faqs.py`
2. Re-run the seed script (uses UPSERT, no duplicates)
3. Restart agent container

### Update Question Patterns

1. Add or modify patterns in the `question_patterns` array
2. Re-run seed script
3. Restart agent container
4. Test with new question variations

## FAQ Best Practices

### Writing Answers

- **Length**: 2-4 sentences, ≤150 words
- **Tone**: Warm, friendly, conversational (use "tú" form in Spanish)
- **Emojis**: 1-2 per answer (🌸 💕 😊 🚗 💳 📍)
- **Language**: Natural Spanish, no technical jargon
- **Proactive**: System automatically adds follow-up "¿Hay algo más en lo que pueda ayudarte? 😊"

### Question Patterns

- Add 6-10 variations per FAQ
- Include common typos or abbreviations
- Cover different ways customers ask the same thing
- Use lowercase, with Spanish accents and punctuation

### Categories

- **general**: Hours, parking, location, general info
- **policy**: Cancellation, payment, refund policies
- **location**: Address, directions (triggers Google Maps link)

## FAQ Analytics

### Viewing FAQ Usage

FAQs log usage to help track popular questions:

```bash
docker compose logs agent | grep "FAQ detected"
docker compose logs agent | grep "FAQ answered"
```

### Metrics Available

- FAQ detection count by `faq_id`
- FAQ category usage
- Customer ID and conversation ID for traceability

### Finding Gaps

Monitor logs for messages classified as `faq_detected=False` to identify questions that should become FAQs.

## Troubleshooting

### FAQ Not Detected

1. Check Claude classification is working (review logs)
2. Verify FAQ exists in database: `SELECT * FROM policies WHERE key='faq:{id}';`
3. Ensure question patterns cover variations
4. Restart agent container

### Wrong Answer Returned

1. Check FAQ `faq_id` matches classification
2. Verify JSONB structure is valid
3. Review answer text for typos
4. Check database with: `SELECT value FROM policies WHERE key='faq:{id}';`

### Google Maps Link Not Added

1. Verify `requires_location_link: true` in FAQ data
2. Check answer_faq node logic in `agent/nodes/faq.py:136-138`
3. Restart agent container

## Related Documentation

- **Story 2.6**: FAQ knowledge base implementation (docs/stories/2.6.faq-knowledge-base-responses.md)
- **Story 2.4**: Maite system prompt and personality (docs/stories/2.4.maite-system-prompt-personality.md)
- **Database Schema**: Policies table structure (docs/architecture/database-schema.md#8.1)

## Support

For technical issues with FAQs, check:
- Agent logs: `docker compose logs agent --tail=100`
- Database connection: `docker compose ps postgres`
- Redis state: `docker compose logs redis --tail=50`

For questions or support, contact the development team.
