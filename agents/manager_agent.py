"""
Manager Agent
Orchestrates the multi-agent ebook business workflow.
Coordinates Stripe payments/subscriptions and Google Sheets tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_clients.google_workspace import GoogleWorkspaceMCP
    from mcp_clients.stripe_mcp import StripeMCP

logger = logging.getLogger(__name__)


@dataclass
class WorkflowContext:
    """Shared state passed between agents during a workflow run."""

    customer_email: str = ""
    customer_name: str = ""
    product_title: str = ""
    product_price_cents: int = 0
    stripe_customer_id: str = ""
    stripe_payment_intent_id: str = ""
    stripe_subscription_id: str = ""
    sheet_row: list[Any] = field(default_factory=list)
    doc_id: str = ""
    delivery_sent: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ManagerAgent:
    """
    @Manager — Orchestration, Stripe, Google Sheets.

    Responsibilities:
    - Bootstrap workflow contexts for new customer orders
    - Process Stripe payments and subscriptions
    - Record order/subscription state to Google Sheets
    - Delegate writing tasks to WriterAgent and analysis to AnalystAgent
    - Aggregate results and surface summaries to stakeholders
    """

    ORDERS_SHEET_RANGE = "Orders!A:H"

    def __init__(
        self,
        workspace: "GoogleWorkspaceMCP",
        stripe: "StripeMCP",
        orders_spreadsheet_id: str,
        notification_email: str = "",
    ) -> None:
        self._workspace = workspace
        self._stripe = stripe
        self.orders_spreadsheet_id = orders_spreadsheet_id
        self.notification_email = notification_email

    # ------------------------------------------------------------------
    # High-level orchestration
    # ------------------------------------------------------------------

    def process_new_order(
        self,
        email: str,
        name: str,
        product_title: str,
        price_cents: int,
        currency: str = "aud",
    ) -> WorkflowContext:
        """
        End-to-end handler for a new product purchase.

        1. Creates / retrieves a Stripe customer.
        2. Creates a PaymentIntent.
        3. Logs the pending order in Google Sheets.
        4. Returns a WorkflowContext for downstream agents.
        """
        ctx = WorkflowContext(
            customer_email=email,
            customer_name=name,
            product_title=product_title,
            product_price_cents=price_cents,
        )

        # Step 1 – Stripe customer
        ctx.stripe_customer_id = self._get_or_create_customer(email, name)

        # Step 2 – PaymentIntent
        pi = self._stripe.payment_intent_create(
            amount=price_cents,
            currency=currency,
            customer_id=ctx.stripe_customer_id,
            metadata={"product": product_title},
        )
        ctx.stripe_payment_intent_id = pi.get("id", "")
        logger.info(
            "Manager: created PaymentIntent %r for %r",
            ctx.stripe_payment_intent_id,
            email,
        )

        # Step 3 – Sheet logging
        self._log_order_to_sheet(ctx, status="pending")

        return ctx

    def confirm_payment(self, ctx: WorkflowContext) -> WorkflowContext:
        """
        Confirm a pending PaymentIntent and update the Sheets record.
        """
        result = self._stripe.payment_intent_confirm(ctx.stripe_payment_intent_id)
        status = result.get("status", "unknown")
        logger.info(
            "Manager: payment status=%r for PI %r",
            status,
            ctx.stripe_payment_intent_id,
        )
        self._update_order_status(ctx, status)
        return ctx

    def create_subscription(
        self,
        ctx: WorkflowContext,
        price_id: str,
    ) -> WorkflowContext:
        """
        Attach a recurring Stripe subscription to the customer in *ctx*.
        """
        sub = self._stripe.subscription_create(
            customer_id=ctx.stripe_customer_id,
            price_id=price_id,
            metadata={"product": ctx.product_title},
        )
        ctx.stripe_subscription_id = sub.get("id", "")
        logger.info(
            "Manager: subscription %r created for %r",
            ctx.stripe_subscription_id,
            ctx.customer_email,
        )
        self._log_subscription_to_sheet(ctx)
        return ctx

    def cancel_subscription(
        self,
        ctx: WorkflowContext,
        at_period_end: bool = True,
    ) -> WorkflowContext:
        """Cancel the subscription recorded in *ctx*."""
        self._stripe.subscription_cancel(
            ctx.stripe_subscription_id, at_period_end=at_period_end
        )
        logger.info(
            "Manager: subscription %r cancelled",
            ctx.stripe_subscription_id,
        )
        return ctx

    def get_revenue_summary(self, spreadsheet_id: str = "") -> dict[str, Any]:
        """
        Read all order rows from Sheets and return aggregate revenue stats.
        """
        sid = spreadsheet_id or self.orders_spreadsheet_id
        rows = self._workspace.sheets_read_range(sid, self.ORDERS_SHEET_RANGE)
        if not rows:
            return {"total_orders": 0, "total_revenue_cents": 0, "rows": []}

        header, *data = rows
        total = 0
        for row in data:
            try:
                col = header.index("amount_cents")
                total += int(row[col])
            except (ValueError, IndexError):
                pass

        logger.info(
            "Manager: revenue_summary total_orders=%d total_cents=%d",
            len(data),
            total,
        )
        return {
            "total_orders": len(data),
            "total_revenue_cents": total,
            "rows": data,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create_customer(self, email: str, name: str) -> str:
        existing = self._stripe.customer_list(email=email, limit=1)
        if existing:
            cid = existing[0].get("id", "")
            logger.debug("Manager: found existing customer %r", cid)
            return cid
        customer = self._stripe.customer_create(email=email, name=name)
        cid = customer.get("id", "")
        logger.info("Manager: created Stripe customer %r", cid)
        return cid

    def _log_order_to_sheet(
        self, ctx: WorkflowContext, status: str = "pending"
    ) -> None:
        import datetime

        row = [
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ctx.customer_email,
            ctx.customer_name,
            ctx.product_title,
            ctx.product_price_cents,
            ctx.stripe_customer_id,
            ctx.stripe_payment_intent_id,
            status,
        ]
        ctx.sheet_row = row
        self._workspace.sheets_append_rows(
            self.orders_spreadsheet_id, self.ORDERS_SHEET_RANGE, [row]
        )
        logger.debug("Manager: logged order row to Sheets")

    def _log_subscription_to_sheet(self, ctx: WorkflowContext) -> None:
        import datetime

        row = [
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ctx.customer_email,
            ctx.stripe_subscription_id,
            "active",
        ]
        self._workspace.sheets_append_rows(
            self.orders_spreadsheet_id, "Subscriptions!A:D", [row]
        )

    def _update_order_status(
        self, ctx: WorkflowContext, status: str
    ) -> None:
        """Append a status-update row (idempotent approach for simplicity)."""
        import datetime

        row = [
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ctx.customer_email,
            "",
            "",
            "",
            "",
            ctx.stripe_payment_intent_id,
            status,
        ]
        self._workspace.sheets_append_rows(
            self.orders_spreadsheet_id, self.ORDERS_SHEET_RANGE, [row]
        )
