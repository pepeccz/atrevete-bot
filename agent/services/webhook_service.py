"""
Webhook Service - Extensible outbound webhook system.

This module provides the foundation for sending notifications to external
services like Slack, Microsoft Teams, or custom webhooks.

Architecture:
- WebhookProvider: Abstract base class for webhook providers
- Provider Registry: Global registry of available providers
- trigger_webhook: Send to specific provider
- trigger_all_webhooks: Broadcast to all registered providers

Usage:
    # Register a provider (at startup)
    from agent.services.webhook_service import register_provider, SlackWebhookProvider
    register_provider(SlackWebhookProvider(webhook_url="https://hooks.slack.com/..."))

    # Trigger webhooks (from escalation service)
    from agent.services.webhook_service import trigger_all_webhooks
    results = await trigger_all_webhooks({
        "type": "escalation",
        "reason": "manual_request",
        "customer_phone": "+34612345678",
    })

Currently placeholder implementations - to be completed when webhook integrations
are requested.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class WebhookProvider(ABC):
    """
    Abstract base class for webhook providers.

    Subclasses must implement:
    - name: Provider name (e.g., 'slack', 'teams')
    - send: Send webhook payload to provider
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'slack', 'teams')."""
        pass

    @abstractmethod
    async def send(self, payload: dict[str, Any]) -> bool:
        """
        Send webhook payload to provider.

        Args:
            payload: Notification payload (provider-specific format)

        Returns:
            True if sent successfully, False otherwise
        """
        pass


class SlackWebhookProvider(WebhookProvider):
    """
    Slack webhook provider (placeholder for future implementation).

    To implement:
    1. Get SLACK_WEBHOOK_URL from settings
    2. Format payload as Slack Block Kit message
    3. POST to webhook URL

    Slack Block Kit format example:
    {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Escalacion: Solicitud de usuario*\n..."
                }
            }
        ]
    }
    """

    def __init__(self, webhook_url: str | None = None):
        """
        Initialize Slack webhook provider.

        Args:
            webhook_url: Slack incoming webhook URL (optional, can be from settings)
        """
        self.webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "slack"

    async def send(self, payload: dict[str, Any]) -> bool:
        """Send webhook to Slack (placeholder)."""
        # TODO: Implement Slack webhook
        # 1. Get SLACK_WEBHOOK_URL from settings if not provided
        # 2. Format payload as Slack Block Kit message
        # 3. POST to webhook URL using httpx
        logger.info(
            f"Slack webhook placeholder | payload_keys={list(payload.keys())}"
        )
        return False


class TeamsWebhookProvider(WebhookProvider):
    """
    Microsoft Teams webhook provider (placeholder).

    To implement:
    1. Get TEAMS_WEBHOOK_URL from settings
    2. Format payload as Teams Adaptive Card
    3. POST to webhook URL
    """

    def __init__(self, webhook_url: str | None = None):
        """
        Initialize Teams webhook provider.

        Args:
            webhook_url: Teams incoming webhook URL
        """
        self.webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "teams"

    async def send(self, payload: dict[str, Any]) -> bool:
        """Send webhook to Teams (placeholder)."""
        # TODO: Implement Teams webhook
        logger.info(
            f"Teams webhook placeholder | payload_keys={list(payload.keys())}"
        )
        return False


class CustomWebhookProvider(WebhookProvider):
    """
    Generic custom webhook provider.

    Sends JSON payload to a custom URL. Can be used for:
    - Internal ticketing systems
    - Custom notification services
    - Third-party integrations
    """

    def __init__(self, name: str, webhook_url: str, headers: dict[str, str] | None = None):
        """
        Initialize custom webhook provider.

        Args:
            name: Provider name (unique identifier)
            webhook_url: Target webhook URL
            headers: Optional HTTP headers (for auth, content-type, etc.)
        """
        self._name = name
        self.webhook_url = webhook_url
        self.headers = headers or {"Content-Type": "application/json"}

    @property
    def name(self) -> str:
        return self._name

    async def send(self, payload: dict[str, Any]) -> bool:
        """Send webhook to custom URL (placeholder)."""
        # TODO: Implement custom webhook
        # 1. POST to webhook_url with headers
        # 2. Handle response and errors
        logger.info(
            f"Custom webhook placeholder | name={self._name} | "
            f"url={self.webhook_url} | payload_keys={list(payload.keys())}"
        )
        return False


# =============================================================================
# Global Provider Registry
# =============================================================================

# Registry of available webhook providers
WEBHOOK_PROVIDERS: dict[str, WebhookProvider] = {}


def register_provider(provider: WebhookProvider) -> None:
    """
    Register a webhook provider.

    Args:
        provider: WebhookProvider instance to register
    """
    WEBHOOK_PROVIDERS[provider.name] = provider
    logger.info(f"Webhook provider registered | name={provider.name}")


def unregister_provider(name: str) -> bool:
    """
    Unregister a webhook provider.

    Args:
        name: Provider name to unregister

    Returns:
        True if provider was removed, False if not found
    """
    if name in WEBHOOK_PROVIDERS:
        del WEBHOOK_PROVIDERS[name]
        logger.info(f"Webhook provider unregistered | name={name}")
        return True
    return False


def get_provider(name: str) -> WebhookProvider | None:
    """
    Get a registered webhook provider.

    Args:
        name: Provider name

    Returns:
        WebhookProvider instance or None if not found
    """
    return WEBHOOK_PROVIDERS.get(name)


def list_providers() -> list[str]:
    """
    List all registered webhook providers.

    Returns:
        List of provider names
    """
    return list(WEBHOOK_PROVIDERS.keys())


# =============================================================================
# Webhook Trigger Functions
# =============================================================================


async def trigger_webhook(
    provider_name: str,
    payload: dict[str, Any],
) -> bool:
    """
    Trigger webhook for a specific provider.

    Args:
        provider_name: Provider name (e.g., 'slack')
        payload: Notification payload

    Returns:
        True if sent, False if provider not found or failed
    """
    provider = WEBHOOK_PROVIDERS.get(provider_name)
    if not provider:
        logger.warning(f"Webhook provider not found | name={provider_name}")
        return False

    try:
        result = await provider.send(payload)
        logger.info(
            f"Webhook triggered | provider={provider_name} | success={result}"
        )
        return result
    except Exception as e:
        logger.error(
            f"Webhook failed | provider={provider_name} | error={str(e)}",
            exc_info=True,
        )
        return False


async def trigger_all_webhooks(payload: dict[str, Any]) -> dict[str, bool]:
    """
    Trigger all registered webhook providers.

    Sends the payload to all registered providers in parallel (conceptually).
    Failures in one provider don't affect others.

    Args:
        payload: Notification payload

    Returns:
        Dict mapping provider name to success status
    """
    if not WEBHOOK_PROVIDERS:
        logger.debug("No webhook providers registered, skipping")
        return {}

    results: dict[str, bool] = {}

    for name in WEBHOOK_PROVIDERS:
        results[name] = await trigger_webhook(name, payload)

    logger.info(
        f"All webhooks triggered | "
        f"total={len(results)} | "
        f"successful={sum(results.values())}"
    )

    return results
