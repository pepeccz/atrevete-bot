"""
Shared prompt components for Maite AI assistant.

This module provides modular, reusable prompt sections that can be
composed into mode-specific system prompts.

Available components:
- glossary: Service catalog and technical terms (77 services)
- identity: Maite's personality and communication style
- critical_rules: Non-negotiable behavioral rules
- recovery: Error recovery and edge case handling
"""

from pathlib import Path


def _load_markdown(filename: str) -> str:
    """Load a markdown file from the shared directory."""
    file_path = Path(__file__).parent / f"{filename}.md"
    return file_path.read_text(encoding="utf-8")


def get_glossary() -> str:
    """Get the glossary component with service definitions."""
    return _load_markdown("glossary")


def get_identity() -> str:
    """Get the identity component with Maite's personality."""
    return _load_markdown("identity")


def get_critical_rules() -> str:
    """Get the critical rules component."""
    return _load_markdown("critical_rules")


def get_recovery() -> str:
    """Get the recovery component for error handling."""
    return _load_markdown("recovery")


__all__ = [
    "get_glossary",
    "get_identity",
    "get_critical_rules",
    "get_recovery",
]
