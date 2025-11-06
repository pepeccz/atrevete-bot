"""
Audio transcription service using Groq Whisper API.

This module provides audio-to-text transcription capabilities for WhatsApp
voice messages using Groq's ultra-fast Whisper implementation.

Key Features:
- 9x cheaper than OpenAI ($0.04/hour vs $0.36/hour)
- 216x faster than real-time (instant transcription)
- Spanish language optimization
- Context-aware prompts for better accuracy
"""

import logging
from pathlib import Path

from groq import AsyncGroq
from groq import RateLimitError, APIError

from shared.config import get_settings

logger = logging.getLogger(__name__)


class AudioTranscriptionService:
    """
    Service for transcribing audio files to text using Groq Whisper API.

    This service handles audio transcription with:
    - Groq Whisper large-v3-turbo model (fastest, most cost-effective)
    - Spanish language support
    - Context-aware prompts for hair salon domain
    - Error handling with graceful degradation
    """

    def __init__(self):
        """Initialize Groq client with API key from settings."""
        settings = get_settings()
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        logger.info("AudioTranscriptionService initialized with Groq Whisper API")

    def _calculate_confidence(self, text: str) -> float:
        """
        Calculate confidence score for Spanish transcription.

        Checks for:
        - Non-Spanish characters (Icelandic, Arabic, Chinese, etc.)
        - Valid Spanish characters including accents
        - Text length

        Returns:
            float: Confidence score from 0.0 to 1.0
        """
        if not text or len(text) < 3:
            return 0.0

        # Valid Spanish characters: letters, numbers, punctuation, Spanish accents
        valid_spanish_chars = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "áéíóúÁÉÍÓÚñÑüÜ"
            "0123456789 .,;:!?¿¡-_'\"\n\t"
        )

        total_chars = len(text)
        valid_chars = sum(1 for char in text if char in valid_spanish_chars)

        # Calculate ratio of valid characters
        confidence = valid_chars / total_chars

        return confidence

    async def transcribe_audio(
        self,
        audio_path: str | Path,
        language: str = "es",
        prompt: str | None = None,
    ) -> tuple[str, float]:
        """
        Transcribe audio file to text using Groq Whisper API with confidence scoring.

        Args:
            audio_path: Path to audio file (wav, ogg, mp3, etc.)
            language: ISO-639-1 language code (default: "es" for Spanish)
            prompt: Optional context to improve transcription accuracy.
                    Example: "El audio es de un cliente de peluquería..."

        Returns:
            tuple[str, float]: (transcribed_text, confidence_score)
                - transcribed_text: Transcribed text in Spanish
                - confidence_score: 0.0 to 1.0 based on Spanish character validity
                  (< 0.7 indicates potential transcription error)

        Raises:
            RateLimitError: If Groq API rate limit is exceeded
            APIError: If Groq API returns an error
            FileNotFoundError: If audio file doesn't exist

        Example:
            >>> service = AudioTranscriptionService()
            >>> text, confidence = await service.transcribe_audio("audio.wav")
            >>> if confidence < 0.7:
            ...     print("Low confidence, may need re-recording")
            >>> print(f"Text: {text}, Confidence: {confidence:.2f}")
            Text: Hola, quiero reservar un corte de pelo para mañana, Confidence: 0.98
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Default domain-specific prompt for hair salon context
        if prompt is None:
            prompt = (
                "El audio es de un cliente de una peluquería en español. "
                "Puede mencionar servicios como corte, tinte, mechas, tratamientos, "
                "peinado, manicura, depilación, masajes, nombres de estilistas como "
                "Marta, Pilar, Ana, Victor, Carmen, o consultas sobre citas y horarios."
            )

        logger.info(
            f"Transcribing audio: {audio_path.name}",
            extra={
                "audio_file": str(audio_path),
                "file_size_mb": audio_path.stat().st_size / (1024 * 1024),
                "language": language,
            },
        )

        try:
            # Read audio file
            with open(audio_path, "rb") as audio_file:
                audio_data = audio_file.read()

            # Call Groq Whisper API
            transcription = await self.client.audio.transcriptions.create(
                file=(audio_path.name, audio_data),
                model="whisper-large-v3-turbo",  # Fastest and most cost-effective
                language=language,
                prompt=prompt,
                response_format="text",  # Return plain text (not JSON)
                temperature=0.0,  # Deterministic for consistent transcriptions
            )

            # Calculate confidence based on Spanish character validity
            confidence = self._calculate_confidence(transcription)

            logger.info(
                f"Transcription successful: {len(transcription)} characters, confidence: {confidence:.2f}",
                extra={
                    "audio_file": str(audio_path),
                    "transcription_length": len(transcription),
                    "transcription_preview": transcription[:100],
                    "confidence_score": confidence,
                },
            )

            return transcription, confidence

        except RateLimitError as e:
            logger.error(
                f"Groq rate limit exceeded: {e}",
                extra={"audio_file": str(audio_path)},
                exc_info=True,
            )
            raise

        except APIError as e:
            logger.error(
                f"Groq API error during transcription: {e}",
                extra={"audio_file": str(audio_path)},
                exc_info=True,
            )
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error during transcription: {e}",
                extra={"audio_file": str(audio_path)},
                exc_info=True,
            )
            raise


# Singleton instance for reuse across requests
_transcription_service: AudioTranscriptionService | None = None


def get_transcription_service() -> AudioTranscriptionService:
    """
    Get singleton instance of AudioTranscriptionService.

    This ensures the Groq client is reused across requests for better performance.

    Returns:
        AudioTranscriptionService: Singleton service instance
    """
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = AudioTranscriptionService()
    return _transcription_service
