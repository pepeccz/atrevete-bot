"""
Chatwoot client for sending messages and managing conversations.

This module provides the ChatwootClient class for interacting with the
Chatwoot API, including sending WhatsApp messages and updating conversation
attributes.
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.config import get_settings
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# 4xx status codes where Chatwoot has definitively rejected the conversation
# RESOURCE itself (deleted/invalid conversation_id) — as opposed to a transient
# server/network error where the SAME conversation is still perfectly valid.
# Used by ``send_template_to_conversation_checked`` (sdd/context-coherence FIX 1).
_CONVERSATION_REJECTION_STATUS_CODES = frozenset({400, 404, 422})


class ConversationSendOutcome(Enum):
    """Typed result of sending a template into an existing Chatwoot conversation.

    Lets callers (currently only ``deliver_template``) distinguish a definitive
    rejection of the conversation resource — where falling back to a brand-new
    conversation is warranted — from a transient failure, where the SAME
    conversation is still valid and the caller's own retry/backoff loop should
    handle it instead of fragmenting the customer's conversation history
    (sdd/context-coherence FIX 1).
    """

    SENT = "sent"
    REJECTED = "rejected"
    TRANSIENT = "transient"


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

    async def _acquire_rate_limit(self) -> None:
        """
        Enforce per-minute rate limit on outbound Chatwoot API calls.

        Uses Redis INCR+EXPIRE sliding-window counter with key pattern
        ``chatwoot:rate_limit:{YYYYMMDD_HHMM}``.  When the per-minute
        counter exceeds the configured limit the coroutine sleeps until
        the next minute boundary before returning.

        Fails open: any Redis error is logged as a warning and the call
        proceeds without throttling.
        """
        limit = get_settings().CHATWOOT_RATE_LIMIT_PER_MINUTE
        if limit == 0:
            return

        try:
            redis = get_redis_client()
            now = datetime.now(ZoneInfo("Europe/Madrid"))
            key = f"chatwoot:rate_limit:{now.strftime('%Y%m%d_%H%M')}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 60)
            if count > limit:
                seconds_remaining = 60 - now.second - now.microsecond / 1_000_000
                logger.warning(
                    f"Chatwoot rate limit reached ({count}/{limit}), "
                    f"sleeping {seconds_remaining:.1f}s until next minute"
                )
                await asyncio.sleep(seconds_remaining)
        except Exception as exc:
            logger.warning(
                f"Rate limiter unavailable (Redis error: {exc}), proceeding without limiting"
            )

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
    async def _create_conversation_with_template(
        self,
        contact_id: int,
        phone: str,
        template_name: str,
        body_params: dict[str, str],
        category: str = "UTILITY",
        language: str = "es",
        fallback_content: str | None = None,
    ) -> tuple[int, bool]:
        """
        Create a new conversation with an initial template message.

        This method creates the conversation and sends the template message in a single
        API call, which is required when the contact has no prior conversation.

        Args:
            contact_id: Chatwoot contact ID
            phone: Customer phone number (E.164 format, will be used as source_id)
            template_name: Name of the approved template in Meta Business Suite
            body_params: Dynamic variables for template body
            category: Template category (UTILITY, MARKETING, etc.)
            language: BCP 47 language code (default: "es")
            fallback_content: Fallback text for non-WhatsApp channels

        Returns:
            Tuple of (conversation_id, success)
        """
        async with httpx.AsyncClient() as client:
            try:
                # For WhatsApp, source_id is the phone number without + prefix
                # Chatwoot will automatically create the contact_inbox relationship
                # https://github.com/orgs/chatwoot/discussions/2198
                source_id = phone.lstrip("+")

                payload: dict[str, Any] = {
                    "source_id": source_id,
                    "inbox_id": int(self.inbox_id),
                    "contact_id": contact_id,
                    "status": "open",
                    "message": {
                        "content": fallback_content or f"Template: {template_name}",
                        "template_params": {
                            "name": template_name,
                            "category": category,
                            "language": language,
                            "processed_params": {
                                "body": body_params,
                            },
                        },
                    },
                }

                logger.debug(
                    f"Creating conversation with template for contact {contact_id}: {payload}"
                )

                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations",
                    json=payload,
                    headers=self.headers,
                    timeout=15.0,
                )
                response.raise_for_status()

                result = response.json()
                conversation_id = cast(int, result.get("id"))

                logger.info(
                    f"Created conversation {conversation_id} with template {template_name} "
                    f"for contact {contact_id}"
                )
                return (conversation_id, True)

            except httpx.HTTPError as e:
                logger.error(
                    f"HTTP error creating conversation with template: {e}",
                    extra={
                        "contact_id": contact_id,
                        "template_name": template_name,
                        "response_body": (
                            getattr(e.response, "text", None) if hasattr(e, "response") else None
                        ),
                    },
                    exc_info=True,
                )
                raise

    async def create_conversation_with_template(
        self,
        customer_phone: str,
        template_name: str,
        body_params: dict[str, str],
        category: str = "UTILITY",
        language: str = "es",
        customer_name: str | None = None,
        fallback_content: str | None = None,
    ) -> tuple[int | None, bool]:
        """
        Find/create the contact and create a new Chatwoot conversation with an
        initial template message.

        Public wrapper around the find/create-contact flow and the internal
        ``_create_conversation_with_template`` call, extracted so callers (e.g. the
        worker notification handlers' ``deliver_template`` helper) can create a fresh
        canonical conversation on a resolver-miss or a Chatwoot rejection of a
        previously resolved conversation id (sdd/context-coherence D3).

        Args:
            customer_phone: E.164 formatted phone number
            template_name: Name of the approved template in Meta Business Suite
            body_params: Dynamic variables for template body
            category: Template category (UTILITY, MARKETING, etc.)
            language: BCP 47 language code (default: "es")
            customer_name: Optional customer name (used when creating new contact)
            fallback_content: Fallback text for non-WhatsApp channels

        Returns:
            Tuple of (conversation_id, success). conversation_id is None on failure.
        """
        try:
            contact = await self._find_contact_by_phone(customer_phone)
            if not contact:
                logger.info(f"Creating new contact for {customer_phone}")
                contact = await self._create_contact(customer_phone, customer_name)

            contact_id = contact.get("id")
            if not contact_id:
                logger.error(f"No contact ID found for {customer_phone}")
                return None, False

            logger.info(
                f"Creating conversation with template for contact: "
                f"contact_id={contact_id}, phone={customer_phone}"
            )

            conversation_id, success = await self._create_conversation_with_template(
                contact_id=contact_id,
                phone=customer_phone,
                template_name=template_name,
                body_params=body_params,
                category=category,
                language=language,
                fallback_content=fallback_content,
            )
            return conversation_id, success

        except httpx.HTTPError as e:
            logger.error(
                f"Failed to create conversation with template for {customer_phone}: {e}",
                exc_info=True,
            )
            return None, False

        except Exception as e:
            logger.error(
                f"Unexpected error creating conversation with template for {customer_phone}: {e}",
                exc_info=True,
            )
            return None, False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def update_conversation_attributes(
        self,
        conversation_id: int,
        attributes: dict[str, Any],
    ) -> bool:
        """
        Update custom attributes for a Chatwoot conversation.

        Uses the dedicated endpoint for conversation custom attributes:
        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/custom_attributes

        Args:
            conversation_id: Chatwoot conversation ID
            attributes: Dict of custom attributes to set (e.g., {"atencion_automatica": True})

        Returns:
            True if update successful, False otherwise

        Example:
            >>> await client.update_conversation_attributes(
            ...     conversation_id=123,
            ...     attributes={"atencion_automatica": True}
            ... )
        """
        async with httpx.AsyncClient() as client:
            try:
                logger.info(
                    f"Updating conversation {conversation_id} custom_attributes: {attributes}"
                )

                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/custom_attributes",
                    json={"custom_attributes": attributes},
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()

                logger.info(
                    f"Successfully updated conversation {conversation_id} custom_attributes"
                )
                return True

            except httpx.HTTPError as e:
                logger.error(
                    f"HTTP error updating conversation {conversation_id} attributes: {e}",
                    exc_info=True,
                )
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

            # Log message preview for debugging
            logger.debug(
                f"Message to send: '{message}'",
                extra={
                    "customer_phone": customer_phone,
                    "message_length": len(message) if message else 0,
                    "conversation_id": conversation_id,
                },
            )

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

            # Enforce rate limit before the outbound POST
            await self._acquire_rate_limit()

            # Send message
            async with httpx.AsyncClient() as client:
                api_payload = {
                    "content": message,
                    "message_type": "outgoing",
                    "private": False,
                }

                # Log API payload for debugging
                logger.debug(
                    f"Chatwoot API payload: {api_payload}",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                    },
                )

                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                    json=api_payload,
                    headers=self.headers,
                    timeout=10.0,
                )

                # Handle 429 explicitly: respect Retry-After before re-raising
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        f"Chatwoot API returned 429 for conversation {conversation_id}, "
                        f"sleeping {retry_after}s (Retry-After)"
                    )
                    await asyncio.sleep(retry_after)
                    response.raise_for_status()

                response.raise_for_status()

                # Log API response for debugging
                logger.debug(
                    f"Chatwoot API response: status={response.status_code}, body={response.text[:500]}",
                    extra={
                        "conversation_id": conversation_id,
                        "customer_phone": customer_phone,
                    },
                )

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def send_template_message(
        self,
        customer_phone: str,
        template_name: str,
        body_params: dict[str, str],
        category: str = "UTILITY",
        language: str = "es",
        customer_name: str | None = None,
        conversation_id: int | None = None,
        fallback_content: str | None = None,
    ) -> bool:
        """
        Send WhatsApp template message via Chatwoot API.

        Template messages are required for sending messages outside the 24-hour
        conversation window. Templates must be pre-approved in Meta Business Suite.

        Args:
            customer_phone: E.164 formatted phone number (e.g., +34612345678)
            template_name: Name of the approved template in Meta Business Suite
            body_params: Dynamic variables for template body as key-value pairs.
                        Keys are positional: {"1": "value1", "2": "value2"}
            category: Template category (UTILITY, MARKETING, SHIPPING_UPDATE, etc.)
            language: BCP 47 language code (default: "es" for Spanish)
            customer_name: Optional customer name (used when creating new contact)
            conversation_id: Optional existing conversation ID from webhook
            fallback_content: Fallback text for non-WhatsApp channels

        Returns:
            True if template message sent successfully, False otherwise

        Example:
            >>> await client.send_template_message(
            ...     customer_phone="+34612345678",
            ...     template_name="appointment_confirmation_48h",
            ...     body_params={
            ...         "1": "María",
            ...         "2": "lunes 15 de diciembre",
            ...         "3": "10:00",
            ...         "4": "Ana García",
            ...         "5": "Corte y tinte",
            ...         "6": "domingo 14 a las 10:00"
            ...     }
            ... )
        """
        try:
            logger.info(f"Sending template message to {customer_phone}, template={template_name}")

            # If conversation_id provided, send template to existing conversation
            if conversation_id is not None:
                logger.info(f"Using existing conversation_id={conversation_id}")
                return await self._send_template_to_conversation(
                    conversation_id=conversation_id,
                    customer_phone=customer_phone,
                    template_name=template_name,
                    body_params=body_params,
                    category=category,
                    language=language,
                    fallback_content=fallback_content,
                )

            # No conversation_id - delegate to the public wrapper (find/create contact +
            # create a new conversation with an initial template message).
            _, success = await self.create_conversation_with_template(
                customer_phone=customer_phone,
                template_name=template_name,
                body_params=body_params,
                category=category,
                language=language,
                customer_name=customer_name,
                fallback_content=fallback_content,
            )
            return success

        except httpx.HTTPError as e:
            logger.error(
                f"Failed to send template message to {customer_phone}: {e}",
                extra={
                    "template_name": template_name,
                    "response_body": (
                        getattr(e.response, "text", None) if hasattr(e, "response") else None
                    ),
                },
                exc_info=True,
            )
            return False

        except Exception as e:
            logger.error(
                f"Unexpected error sending template message to {customer_phone}: {e}",
                exc_info=True,
            )
            return False

    async def _send_template_to_conversation(
        self,
        conversation_id: int,
        customer_phone: str,
        template_name: str,
        body_params: dict[str, str],
        category: str = "UTILITY",
        language: str = "es",
        fallback_content: str | None = None,
    ) -> bool:
        """
        Send template message to an existing conversation.

        Args:
            conversation_id: Existing Chatwoot conversation ID
            customer_phone: Customer phone for logging
            template_name: Name of the approved template
            body_params: Dynamic variables for template body
            category: Template category
            language: BCP 47 language code
            fallback_content: Fallback text for non-WhatsApp channels

        Returns:
            True if sent successfully, False otherwise
        """
        # Build template payload per Chatwoot API docs
        api_payload: dict[str, Any] = {
            "content": fallback_content or f"Template: {template_name}",
            "message_type": "outgoing",
            "template_params": {
                "name": template_name,
                "category": category,
                "language": language,
                "processed_params": {
                    "body": body_params,
                },
            },
        }

        logger.debug(
            f"Chatwoot template API payload: {api_payload}",
            extra={
                "conversation_id": conversation_id,
                "customer_phone": customer_phone,
                "template_name": template_name,
            },
        )

        # Enforce rate limit before the outbound POST
        await self._acquire_rate_limit()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                json=api_payload,
                headers=self.headers,
                timeout=15.0,
            )

            # Handle 429 explicitly: respect Retry-After before re-raising
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(
                    f"Chatwoot API returned 429 for conversation {conversation_id} "
                    f"(template={template_name}), sleeping {retry_after}s (Retry-After)"
                )
                await asyncio.sleep(retry_after)
                response.raise_for_status()

            response.raise_for_status()

            logger.info(
                f"Template message sent successfully to {customer_phone}, "
                f"conversation_id={conversation_id}, template={template_name}"
            )
            return True

    async def send_template_to_conversation_checked(
        self,
        conversation_id: int,
        customer_phone: str,
        template_name: str,
        body_params: dict[str, str],
        category: str = "UTILITY",
        language: str = "es",
        fallback_content: str | None = None,
    ) -> ConversationSendOutcome:
        """Send a template into an existing conversation, returning a typed outcome.

        Sibling of ``_send_template_to_conversation`` (does not change that method
        or ``send_template_message``'s existing bool contract — other callers,
        e.g. ``ConversationInboxService`` and the admin booking-notification route,
        are unaffected). Only ``deliver_template`` calls this method, so it can
        distinguish a definitive Chatwoot rejection (400/404/422 on the
        conversation resource — fallback to a new conversation is warranted) from
        a transient failure (network error, timeout, 5xx — the SAME conversation
        is still valid) (sdd/context-coherence FIX 1).

        Deliberately makes a single attempt with no tenacity-level retry:
        transient failures are retried by the notifications worker's own
        backoff loop (``mark_failed_fn`` / ``next_retry_at``) on the next poll
        cycle, against the SAME resolved conversation_id — unlike
        ``send_template_message``'s 3-attempt retry (which also wastes retries
        on a permanent 400; left as-is there since it is not on this path).
        """
        try:
            await self._send_template_to_conversation(
                conversation_id=conversation_id,
                customer_phone=customer_phone,
                template_name=template_name,
                body_params=body_params,
                category=category,
                language=language,
                fallback_content=fallback_content,
            )
            return ConversationSendOutcome.SENT
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            if status in _CONVERSATION_REJECTION_STATUS_CODES:
                logger.warning(
                    f"Chatwoot rejected conversation_id={conversation_id} with "
                    f"status={status} — treating as a definitive rejection "
                    f"(template={template_name})"
                )
                return ConversationSendOutcome.REJECTED
            logger.error(
                f"Transient Chatwoot error sending into conversation_id={conversation_id} "
                f"(status={status}): {e}",
                exc_info=True,
            )
            return ConversationSendOutcome.TRANSIENT
        except httpx.HTTPError as e:
            logger.error(
                f"Transient Chatwoot HTTP error sending into conversation_id={conversation_id}: {e}",
                exc_info=True,
            )
            return ConversationSendOutcome.TRANSIENT

    async def get_conversation_labels(self, conversation_id: int) -> list[str]:
        """Get current labels for a conversation."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/labels",
                headers=self.headers,
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json().get("payload", [])

    async def add_conversation_labels(self, conversation_id: int, labels: list[str]) -> bool:
        """Add labels to a conversation (merges with existing labels)."""
        try:
            existing = await self.get_conversation_labels(conversation_id)
            merged = list(set(existing) | set(labels))
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/labels",
                    headers=self.headers,
                    json={"labels": merged},
                    timeout=10.0,
                )
                response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Failed to add labels to conversation {conversation_id}: {e}")
            return False

    async def add_private_note(self, conversation_id: int, content: str) -> bool:
        """Add a private note to a conversation (not visible to customer)."""
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "content": content,
                    "message_type": "outgoing",
                    "private": True,
                }
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages",
                    headers=self.headers,
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Failed to add private note to conversation {conversation_id}: {e}")
            return False

    async def assign_to_team(self, conversation_id: int, team_id: int) -> bool:
        """Assign a conversation to a team."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/assignments",
                    headers=self.headers,
                    json={"team_id": team_id},
                    timeout=10.0,
                )
                response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(
                f"Failed to assign conversation {conversation_id} to team {team_id}: {e}"
            )
            return False
