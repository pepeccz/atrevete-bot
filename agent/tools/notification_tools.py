"""
Notification tools for sending messages via Chatwoot.

This module provides the ChatwootClient class for sending WhatsApp messages
through the Chatwoot API.
"""

import logging
from typing import Any, cast

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.config import get_settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    """
    Client for interacting with Chatwoot API.

    This client handles finding or creating contacts/conversations and
    sending messages via the Chatwoot API.
    """

    def __init__(self):
        """Initialize Chatwoot client with credentials from settings."""
        settings = get_settings()
        # Remove trailing slash to avoid double slashes in URLs
        self.api_url = settings.CHATWOOT_API_URL.rstrip("/")
        self.api_token = settings.CHATWOOT_API_TOKEN
        self.account_id = settings.CHATWOOT_ACCOUNT_ID
        self.inbox_id = settings.CHATWOOT_INBOX_ID

        # Set up HTTP client with authentication headers
        self.headers = {
            "api_access_token": self.api_token,
            "Content-Type": "application/json",
        }

        logger.info(f"ChatwootClient initialized: {self.api_url}, account_id={self.account_id}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _find_contact_by_phone(self, phone: str) -> dict[str, Any] | None:
        """
        Find Chatwoot contact by phone number.

        Args:
            phone: E.164 formatted phone number

        Returns:
            Contact dict if found, None otherwise
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/contacts/search",
                    params={"q": phone},
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                payload = response.json().get("payload", [])
                if payload and len(payload) > 0:
                    logger.debug(f"Contact found for phone {phone}")
                    return cast(dict[str, Any], payload[0])

                logger.debug(f"No contact found for phone {phone}")
                return None

            except httpx.HTTPError as e:
                logger.error(f"HTTP error finding contact: {e}")
                raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _create_contact(self, phone: str, name: str | None = None) -> dict[str, Any]:
        """
        Create new Chatwoot contact.

        Args:
            phone: E.164 formatted phone number
            name: Optional contact name

        Returns:
            Created contact dict
        """
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "inbox_id": self.inbox_id,
                    "phone_number": phone,
                }
                if name:
                    payload["name"] = name

                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/contacts",
                    json=payload,
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                contact = response.json().get("payload", {}).get("contact", {})
                logger.info(f"Created contact for phone {phone}, contact_id={contact.get('id')}")
                return cast(dict[str, Any], contact)

            except httpx.HTTPError as e:
                logger.error(f"HTTP error creating contact: {e}")
                raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _get_or_create_conversation(self, contact_id: int) -> int:
        """
        Get existing conversation or create new one for contact.

        Args:
            contact_id: Chatwoot contact ID

        Returns:
            Conversation ID
        """
        async with httpx.AsyncClient() as client:
            try:
                # Get contact details with conversations
                response = await client.get(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/contacts/{contact_id}",
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                # Extract contact data - Chatwoot returns data directly in payload, not payload.contact
                contact = response.json().get("payload", {})

                # Get source_id from first contact_inbox (required for conversation creation)
                contact_inboxes = contact.get("contact_inboxes", [])
                if not contact_inboxes:
                    logger.error(f"No contact_inboxes found for contact {contact_id}")
                    raise ValueError(f"Contact {contact_id} has no associated inboxes")

                source_id = contact_inboxes[0].get("source_id")
                logger.debug(f"Using source_id={source_id} from contact {contact_id}")

                # Create new conversation with source_id
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations",
                    json={
                        "source_id": source_id,
                        "inbox_id": self.inbox_id,
                        "contact_id": contact_id,
                        "status": "open",
                    },
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                conversation_id = cast(int, response.json().get("id"))
                logger.info(f"Created conversation {conversation_id} for contact {contact_id}")
                return conversation_id

            except httpx.HTTPError as e:
                logger.error(f"HTTP error managing conversation: {e}")
                raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def send_message(
        self,
        customer_phone: str,
        message: str,
        customer_name: str | None = None,
        conversation_id: int | None = None,
    ) -> bool:
        """
        Send message to customer via Chatwoot.

        This method handles the complete flow:
        1. If conversation_id provided, use it directly
        2. Otherwise: Find or create contact by phone
        3. Otherwise: Get or create conversation for contact
        4. Send message to conversation

        Args:
            customer_phone: E.164 formatted phone number
            message: Message text to send
            customer_name: Optional customer name (used when creating new contact)
            conversation_id: Optional existing conversation ID from webhook

        Returns:
            True if message sent successfully, False otherwise
        """
        try:
            logger.info(f"Sending message to {customer_phone}")

            # If conversation_id provided, use it directly
            if conversation_id is not None:
                logger.info(f"Using existing conversation_id={conversation_id}")
            else:
                # Find or create contact
                contact = await self._find_contact_by_phone(customer_phone)
                if not contact:
                    logger.info(f"Creating new contact for {customer_phone}")
                    contact = await self._create_contact(customer_phone, customer_name)

                contact_id = contact.get("id")
                if not contact_id:
                    logger.error(f"No contact ID found for {customer_phone}")
                    return False

                # Get or create conversation
                conversation_id = await self._get_or_create_conversation(contact_id)

            # Send message
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                    json={
                        "content": message,
                        "message_type": "outgoing",
                        "private": False,
                    },
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                logger.info(
                    f"Message sent successfully to {customer_phone}, conversation_id={conversation_id}"
                )
                return True

        except httpx.HTTPError as e:
            logger.error(
                f"Failed to send message to {customer_phone} after retries: {e}",
                exc_info=True,
            )
            return False

        except Exception as e:
            logger.error(
                f"Unexpected error sending message to {customer_phone}: {e}",
                exc_info=True,
            )
            return False
