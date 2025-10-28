"""
Prompt loading utilities for the Maite agent.

This module provides functions to load system prompts from disk.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_maite_system_prompt() -> str:
    """
    Load the Maite system prompt from disk.

    Returns:
        str: The complete system prompt text.

    Raises:
        No exceptions raised - returns fallback prompt on errors.
    """
    prompt_path = Path(__file__).parent / "maite_system_prompt.md"
    fallback_prompt = (
        "Eres Maite, asistenta virtual de Atrevete Peluqueria. "
        "Se amable, usa herramientas, y escala cuando sea necesario."
    )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        if len(prompt) < 100:
            logger.error(
                f"System prompt too short ({len(prompt)} characters), using fallback"
            )
            return fallback_prompt

        logger.info(f"Loaded Maite system prompt ({len(prompt)} characters)")
        return prompt

    except FileNotFoundError:
        logger.error(
            f"System prompt file not found at {prompt_path}, using fallback"
        )
        return fallback_prompt

    except IOError as e:
        logger.error(
            f"Error reading system prompt file: {e}, using fallback"
        )
        return fallback_prompt

    except Exception as e:
        logger.error(
            f"Unexpected error loading system prompt: {e}, using fallback"
        )
        return fallback_prompt


__all__ = ["load_maite_system_prompt"]
