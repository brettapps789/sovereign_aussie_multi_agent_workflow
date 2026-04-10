"""
Writer Agent
Creates ebook documents via Google Docs, delivers them via Gmail,
and posts workflow notifications to Google Chat / Slack.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.manager_agent import WorkflowContext
    from mcp_clients.communication_mcp import CommunicationMCP
    from mcp_clients.google_workspace import GoogleWorkspaceMCP

logger = logging.getLogger(__name__)

# Default ebook delivery email template
_DELIVERY_SUBJECT = "Your ebook is ready: {title}"
_DELIVERY_BODY = """\
Hi {name},

Thank you for your purchase of **{title}**!

Your ebook is now available in Google Drive:
{doc_link}

If you have any questions, just reply to this email.

Warm regards,
Sovereign Aussie Team
"""


class WriterAgent:
    """
    @Writer — Google Docs/Gmail, Comms.

    Responsibilities:
    - Generate or populate ebook Google Docs from templates/prompts
    - Deliver ebook access links to customers via Gmail
    - Post status notifications to Google Chat and/or Slack
    - Manage document sharing/permissions for customers
    """

    DRIVE_EBOOK_FOLDER: str = ""  # Set at runtime from config

    def __init__(
        self,
        workspace: "GoogleWorkspaceMCP",
        comms: "CommunicationMCP",
        sender_email: str = "",
        chat_space_id: str = "",
        slack_channel: str = "",
    ) -> None:
        self._workspace = workspace
        self._comms = comms
        self.sender_email = sender_email
        self.chat_space_id = chat_space_id
        self.slack_channel = slack_channel

    # ------------------------------------------------------------------
    # Document creation
    # ------------------------------------------------------------------

    def create_ebook_doc(
        self,
        ctx: "WorkflowContext",
        body_markdown: str = "",
    ) -> "WorkflowContext":
        """
        Create a Google Doc for the ebook and store its ID in *ctx*.

        If *body_markdown* is provided it is inserted as the document body;
        otherwise a placeholder skeleton is used.
        """
        title = f"Ebook — {ctx.product_title}"
        content = body_markdown or self._default_ebook_skeleton(ctx)
        doc = self._workspace.docs_create(title=title, body=content)
        ctx.doc_id = doc.get("documentId", "")
        logger.info(
            "Writer: created ebook doc %r title=%r", ctx.doc_id, title
        )
        return ctx

    def append_section(
        self,
        ctx: "WorkflowContext",
        section_text: str,
    ) -> "WorkflowContext":
        """Append a new section to the ebook document in *ctx*."""
        if not ctx.doc_id:
            raise ValueError("No doc_id in WorkflowContext; create the doc first.")
        self._workspace.docs_append_text(ctx.doc_id, "\n\n" + section_text)
        logger.debug("Writer: appended section to doc %r", ctx.doc_id)
        return ctx

    # ------------------------------------------------------------------
    # Email delivery
    # ------------------------------------------------------------------

    def deliver_ebook(self, ctx: "WorkflowContext") -> "WorkflowContext":
        """
        Email the ebook Google Doc link to the customer.

        Marks *ctx.delivery_sent* as ``True`` on success.
        """
        if not ctx.doc_id:
            raise ValueError("No doc_id in WorkflowContext; create the doc first.")

        doc_link = f"https://docs.google.com/document/d/{ctx.doc_id}/edit"
        subject = _DELIVERY_SUBJECT.format(title=ctx.product_title)
        body = _DELIVERY_BODY.format(
            name=ctx.customer_name or ctx.customer_email,
            title=ctx.product_title,
            doc_link=doc_link,
        )
        self._workspace.gmail_send(
            to=ctx.customer_email,
            subject=subject,
            body=body,
            html=False,
        )
        ctx.delivery_sent = True
        logger.info(
            "Writer: delivery email sent to %r for doc %r",
            ctx.customer_email,
            ctx.doc_id,
        )
        return ctx

    def send_custom_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] | None = None,
    ) -> dict:
        """Send an ad-hoc email via Gmail."""
        result = self._workspace.gmail_send(
            to=to,
            subject=subject,
            body=body,
            html=html,
            attachments=attachments,
        )
        logger.info("Writer: custom email sent to %r subject=%r", to, subject)
        return result

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def notify_order_received(self, ctx: "WorkflowContext") -> None:
        """
        Post an order-received notification to Google Chat and/or Slack.
        """
        message = (
            f"🛒 New order received!\n"
            f"Customer: {ctx.customer_name} <{ctx.customer_email}>\n"
            f"Product: {ctx.product_title}\n"
            f"Amount: {ctx.product_price_cents / 100:.2f} AUD"
        )
        self._post_notification(message)

    def notify_delivery_sent(self, ctx: "WorkflowContext") -> None:
        """Post a delivery-confirmation notification."""
        message = (
            f"✅ Ebook delivered!\n"
            f"Customer: {ctx.customer_email}\n"
            f"Product: {ctx.product_title}\n"
            f"Doc: https://docs.google.com/document/d/{ctx.doc_id}/edit"
        )
        self._post_notification(message)

    def notify_payment_failed(self, ctx: "WorkflowContext") -> None:
        """Post a payment-failure alert."""
        message = (
            f"⚠️ Payment failed!\n"
            f"Customer: {ctx.customer_email}\n"
            f"PI: {ctx.stripe_payment_intent_id}"
        )
        self._post_notification(message)

    def post_report(self, report_text: str, title: str = "Report") -> None:
        """Post an arbitrary report string to all configured channels."""
        message = f"📊 {title}\n\n{report_text}"
        self._post_notification(message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post_notification(self, text: str) -> None:
        if self.chat_space_id:
            try:
                self._comms.chat_send_message(self.chat_space_id, text)
            except Exception:
                logger.exception("Writer: failed to post to Google Chat")
        if self.slack_channel:
            try:
                self._comms.slack_post_message(self.slack_channel, text)
            except Exception:
                logger.exception("Writer: failed to post to Slack")

    @staticmethod
    def _default_ebook_skeleton(ctx: "WorkflowContext") -> str:
        return (
            f"# {ctx.product_title}\n\n"
            "## Introduction\n\n"
            "[Content goes here]\n\n"
            "## Chapter 1\n\n"
            "[Content goes here]\n\n"
            "## Conclusion\n\n"
            "[Content goes here]\n"
        )
