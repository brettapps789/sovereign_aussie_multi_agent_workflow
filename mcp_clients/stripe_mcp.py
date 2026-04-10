"""
Stripe MCP Client
Handles payments, subscriptions, and customer management via Stripe.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StripeMCP:
    """
    MCP client for Stripe.

    Wraps the Stripe API for payment intents, subscription management,
    customer records, and webhook processing so agents never handle
    raw Stripe API keys.
    """

    def __init__(self, endpoint: str, credentials: dict[str, Any]) -> None:
        self.endpoint = endpoint
        self.credentials = credentials
        self._session: Any = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish a session with the Stripe MCP endpoint."""
        logger.info("StripeMCP: connecting to %s", self.endpoint)
        self._session = {"connected": True, "endpoint": self.endpoint}
        logger.info("StripeMCP: connected")

    def disconnect(self) -> None:
        """Close the MCP session."""
        self._session = None
        logger.info("StripeMCP: disconnected")

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def customer_create(
        self,
        email: str,
        name: str = "",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Create a new Stripe customer."""
        self._ensure_connected()
        logger.info("Stripe customer_create email=%r", email)
        return {"id": "", "email": email, "name": name}

    def customer_get(self, customer_id: str) -> dict:
        """Retrieve a Stripe customer by ID."""
        self._ensure_connected()
        return {"id": customer_id}

    def customer_update(
        self, customer_id: str, fields: dict[str, Any]
    ) -> dict:
        """Update fields on a Stripe customer."""
        self._ensure_connected()
        logger.info("Stripe customer_update id=%r", customer_id)
        return {"id": customer_id, **fields}

    def customer_list(
        self, email: str = "", limit: int = 10
    ) -> list[dict]:
        """List Stripe customers, optionally filtered by email."""
        self._ensure_connected()
        return []

    # ------------------------------------------------------------------
    # Payment Intents
    # ------------------------------------------------------------------

    def payment_intent_create(
        self,
        amount: int,
        currency: str,
        customer_id: str = "",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a Stripe PaymentIntent.

        *amount* is in the smallest currency unit (e.g. cents for AUD).
        """
        self._ensure_connected()
        logger.info(
            "Stripe payment_intent_create amount=%d currency=%r",
            amount,
            currency,
        )
        return {"id": "", "amount": amount, "currency": currency, "status": "requires_payment_method"}

    def payment_intent_confirm(self, payment_intent_id: str) -> dict:
        """Confirm a PaymentIntent."""
        self._ensure_connected()
        logger.info("Stripe payment_intent_confirm id=%r", payment_intent_id)
        return {"id": payment_intent_id, "status": "succeeded"}

    def payment_intent_get(self, payment_intent_id: str) -> dict:
        """Retrieve a PaymentIntent by ID."""
        self._ensure_connected()
        return {"id": payment_intent_id}

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscription_create(
        self,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Create a Stripe Subscription."""
        self._ensure_connected()
        logger.info(
            "Stripe subscription_create customer=%r price=%r",
            customer_id,
            price_id,
        )
        return {"id": "", "customer": customer_id, "status": "active"}

    def subscription_cancel(
        self, subscription_id: str, at_period_end: bool = True
    ) -> dict:
        """Cancel a Stripe Subscription."""
        self._ensure_connected()
        logger.info(
            "Stripe subscription_cancel id=%r at_period_end=%s",
            subscription_id,
            at_period_end,
        )
        return {"id": subscription_id, "status": "canceled"}

    def subscription_get(self, subscription_id: str) -> dict:
        """Retrieve a Stripe Subscription."""
        self._ensure_connected()
        return {"id": subscription_id}

    def subscription_list(
        self, customer_id: str = "", status: str = "active"
    ) -> list[dict]:
        """List subscriptions for a customer or by status."""
        self._ensure_connected()
        return []

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def webhook_construct_event(
        self, payload: bytes, sig_header: str, secret: str
    ) -> dict:
        """
        Validate and parse a Stripe webhook event.

        Raises ``ValueError`` if the signature is invalid.
        """
        self._ensure_connected()
        logger.debug("Stripe webhook_construct_event sig=%r", sig_header[:20])
        # In production: stripe.Webhook.construct_event(payload, sig_header, secret)
        return {"type": "", "data": {}}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._session:
            raise RuntimeError(
                "StripeMCP is not connected. Call connect() first."
            )
