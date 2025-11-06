"""
Audio conversion utilities for WhatsApp voice messages.

This module provides audio format conversion to optimize compatibility
and transcription performance with Groq Whisper API.

Key conversions:
- OGG Opus (WhatsApp format) → WAV 16kHz mono (optimal for speech recognition)
"""

import logging
from pathlib import Path

from pydub import AudioSegment

logger = logging.getLogger(__name__)


async def convert_ogg_to_wav(ogg_path: str | Path) -> Path:
    """
    Convert OGG Opus audio (WhatsApp format) to WAV format optimized for speech recognition.

    This conversion provides:
    - Maximum compatibility with Whisper API
    - Optimal latency (Groq recommendation)
    - Standardized format: 16kHz sample rate, mono channel

    Args:
        ogg_path: Path to input OGG file

    Returns:
        Path: Path to output WAV file (same location, .wav extension)

    Raises:
        FileNotFoundError: If input OGG file doesn't exist
        Exception: If conversion fails (codec issues, corrupted file, etc.)

    Example:
        >>> ogg_path = "/tmp/audio.ogg"
        >>> wav_path = await convert_ogg_to_wav(ogg_path)
        >>> print(wav_path)
        Path('/tmp/audio.wav')
    """
    ogg_path = Path(ogg_path)

    if not ogg_path.exists():
        raise FileNotFoundError(f"OGG file not found: {ogg_path}")

    # Generate WAV path (same directory, .wav extension)
    wav_path = ogg_path.with_suffix(".wav")

    logger.info(
        f"Converting audio: {ogg_path.name} → {wav_path.name}",
        extra={
            "input_file": str(ogg_path),
            "input_size_mb": ogg_path.stat().st_size / (1024 * 1024),
            "output_file": str(wav_path),
        },
    )

    try:
        # Load OGG Opus audio
        # pydub uses ffmpeg backend to decode OGG Opus
        audio = AudioSegment.from_file(ogg_path, format="ogg")

        # Convert to optimal format for speech recognition:
        # - 16kHz sample rate (Whisper standard, reduces file size)
        # - Mono channel (speech is mono, reduces file size 50%)
        audio = audio.set_frame_rate(16000).set_channels(1)

        # Export as WAV (uncompressed, best compatibility)
        audio.export(wav_path, format="wav")

        logger.info(
            f"Audio conversion successful: {wav_path.name}",
            extra={
                "input_file": str(ogg_path),
                "output_file": str(wav_path),
                "output_size_mb": wav_path.stat().st_size / (1024 * 1024),
                "duration_seconds": len(audio) / 1000,
            },
        )

        return wav_path

    except Exception as e:
        logger.error(
            f"Audio conversion failed: {e}",
            extra={"input_file": str(ogg_path), "error": str(e)},
            exc_info=True,
        )
        raise
