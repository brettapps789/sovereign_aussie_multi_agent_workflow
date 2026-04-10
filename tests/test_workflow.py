"""
End-to-end workflow chain test with mocks.

Tests cover:
- ManagerAgent: new order, payment confirmation, subscription, revenue summary
- WriterAgent: doc creation, ebook delivery, notifications
- AnalystAgent: data fetch, AI Q&A, revenue report, churn analysis, forecast
- Full workflow chain integration
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, call
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace_mock() -> MagicMock:
    """Return a pre-configured GoogleWorkspaceMCP mock."""
    m = MagicMock()
    m.sheets_read_range.return_value = [
        ["timestamp", "email", "name", "product_title", "amount_cents",
         "stripe_customer_id", "payment_intent_id", "status"],
        ["2024-01-01T00:00:00", "alice@example.com", "Alice", "Ebook A",
         "2999", "cus_1", "pi_1", "succeeded"],
        ["2024-02-01T00:00:00", "bob@example.com", "Bob", "Ebook B",
         "1999", "cus_2", "pi_2", "succeeded"],
    ]
    m.sheets_append_rows.return_value = {"updates": {"updatedRows": 1}}
    m.docs_create.return_value = {"documentId": "doc_abc", "title": "Test"}
    m.docs_append_text.return_value = {"documentId": "doc_abc"}
    m.gmail_send.return_value = {"messageId": "msg_1"}
    m.drive_upload_file.return_value = {"id": "file_1", "name": "test.pdf"}
    return m


def _make_stripe_mock() -> MagicMock:
    m = MagicMock()
    m.customer_list.return_value = []
    m.customer_create.return_value = {"id": "cus_new", "email": "test@example.com"}
    m.payment_intent_create.return_value = {
        "id": "pi_new", "amount": 2999, "currency": "aud",
        "status": "requires_payment_method"
    }
    m.payment_intent_confirm.return_value = {"id": "pi_new", "status": "succeeded"}
    m.subscription_create.return_value = {
        "id": "sub_new", "customer": "cus_new", "status": "active"
    }
    m.subscription_cancel.return_value = {"id": "sub_new", "status": "canceled"}
    return m


def _make_comms_mock() -> MagicMock:
    m = MagicMock()
    m.chat_send_message.return_value = {"name": "spaces/x/messages/1", "text": ""}
    m.slack_post_message.return_value = {"ok": True, "ts": "1234.5678"}
    return m


def _make_vertex_mock() -> MagicMock:
    m = MagicMock()
    m.generate_text.return_value = "AI-generated answer"
    m.chat.return_value = "AI chat response"
    m.embed_text.return_value = [[0.1, 0.2, 0.3]]
    m.analyse_tabular.return_value = "Revenue was $100 AUD."
    m.function_call.return_value = {"name": "tool_name", "args": {}}
    return m


# ---------------------------------------------------------------------------
# ManagerAgent tests
# ---------------------------------------------------------------------------

class TestManagerAgent(unittest.TestCase):

    def setUp(self) -> None:
        from agents.manager_agent import ManagerAgent
        self.workspace = _make_workspace_mock()
        self.stripe = _make_stripe_mock()
        self.manager = ManagerAgent(
            workspace=self.workspace,
            stripe=self.stripe,
            orders_spreadsheet_id="sheet_123",
            notification_email="admin@example.com",
        )

    def test_process_new_order_creates_customer(self) -> None:
        ctx = self.manager.process_new_order(
            email="new@example.com",
            name="New User",
            product_title="Test Ebook",
            price_cents=2999,
        )
        self.stripe.customer_create.assert_called_once_with(
            email="new@example.com", name="New User"
        )
        self.assertEqual(ctx.stripe_customer_id, "cus_new")

    def test_process_new_order_reuses_existing_customer(self) -> None:
        self.stripe.customer_list.return_value = [{"id": "cus_existing"}]
        ctx = self.manager.process_new_order(
            email="existing@example.com",
            name="Existing",
            product_title="Another Ebook",
            price_cents=1999,
        )
        self.stripe.customer_create.assert_not_called()
        self.assertEqual(ctx.stripe_customer_id, "cus_existing")

    def test_process_new_order_creates_payment_intent(self) -> None:
        ctx = self.manager.process_new_order(
            email="test@example.com",
            name="Tester",
            product_title="Ebook X",
            price_cents=4999,
        )
        self.stripe.payment_intent_create.assert_called_once()
        call_kwargs = self.stripe.payment_intent_create.call_args
        self.assertEqual(call_kwargs.kwargs.get("amount") or call_kwargs[1].get("amount") or call_kwargs[0][0], 4999)
        self.assertEqual(ctx.stripe_payment_intent_id, "pi_new")

    def test_process_new_order_logs_to_sheet(self) -> None:
        self.manager.process_new_order(
            email="log@example.com",
            name="Logger",
            product_title="Log Ebook",
            price_cents=999,
        )
        self.workspace.sheets_append_rows.assert_called_once()

    def test_confirm_payment_updates_status(self) -> None:
        from agents.manager_agent import WorkflowContext
        ctx = WorkflowContext(
            customer_email="pay@example.com",
            stripe_payment_intent_id="pi_test",
        )
        result = self.manager.confirm_payment(ctx)
        self.stripe.payment_intent_confirm.assert_called_once_with("pi_test")
        self.workspace.sheets_append_rows.assert_called_once()

    def test_create_subscription(self) -> None:
        from agents.manager_agent import WorkflowContext
        ctx = WorkflowContext(
            customer_email="sub@example.com",
            stripe_customer_id="cus_sub",
        )
        result = self.manager.create_subscription(ctx, price_id="price_123")
        self.stripe.subscription_create.assert_called_once_with(
            customer_id="cus_sub",
            price_id="price_123",
            metadata={"product": ""},
        )
        self.assertEqual(result.stripe_subscription_id, "sub_new")

    def test_cancel_subscription(self) -> None:
        from agents.manager_agent import WorkflowContext
        ctx = WorkflowContext(stripe_subscription_id="sub_cancel")
        self.manager.cancel_subscription(ctx)
        self.stripe.subscription_cancel.assert_called_once_with(
            "sub_cancel", at_period_end=True
        )

    def test_get_revenue_summary(self) -> None:
        summary = self.manager.get_revenue_summary()
        self.assertEqual(summary["total_orders"], 2)
        self.assertEqual(summary["total_revenue_cents"], 2999 + 1999)

    def test_get_revenue_summary_empty_sheet(self) -> None:
        self.workspace.sheets_read_range.return_value = []
        summary = self.manager.get_revenue_summary()
        self.assertEqual(summary["total_orders"], 0)
        self.assertEqual(summary["total_revenue_cents"], 0)


# ---------------------------------------------------------------------------
# WriterAgent tests
# ---------------------------------------------------------------------------

class TestWriterAgent(unittest.TestCase):

    def setUp(self) -> None:
        from agents.writer_agent import WriterAgent
        self.workspace = _make_workspace_mock()
        self.comms = _make_comms_mock()
        self.writer = WriterAgent(
            workspace=self.workspace,
            comms=self.comms,
            sender_email="sender@example.com",
            chat_space_id="spaces/ABC",
            slack_channel="#ebooks",
        )

    def _make_ctx(self, **kwargs: Any):
        from agents.manager_agent import WorkflowContext
        return WorkflowContext(
            customer_email="customer@example.com",
            customer_name="Test Customer",
            product_title="My Ebook",
            **kwargs,
        )

    def test_create_ebook_doc_no_body(self) -> None:
        ctx = self._make_ctx()
        result = self.writer.create_ebook_doc(ctx)
        self.workspace.docs_create.assert_called_once()
        self.assertEqual(result.doc_id, "doc_abc")

    def test_create_ebook_doc_with_body(self) -> None:
        ctx = self._make_ctx()
        result = self.writer.create_ebook_doc(ctx, body_markdown="# Hello\n\nWorld")
        args = self.workspace.docs_create.call_args
        body_arg = args.kwargs.get("body") or args[1].get("body") or args[0][1]
        self.assertEqual(body_arg, "# Hello\n\nWorld")

    def test_append_section(self) -> None:
        ctx = self._make_ctx(doc_id="doc_xyz")
        self.writer.append_section(ctx, "## New Section\n\nContent here.")
        self.workspace.docs_append_text.assert_called_once_with(
            "doc_xyz", "\n\n## New Section\n\nContent here."
        )

    def test_append_section_no_doc_id_raises(self) -> None:
        ctx = self._make_ctx()
        with self.assertRaises(ValueError):
            self.writer.append_section(ctx, "text")

    def test_deliver_ebook(self) -> None:
        ctx = self._make_ctx(doc_id="doc_deliver")
        result = self.writer.deliver_ebook(ctx)
        self.workspace.gmail_send.assert_called_once()
        send_args = self.workspace.gmail_send.call_args
        self.assertIn("doc_deliver", str(send_args))
        self.assertTrue(result.delivery_sent)

    def test_deliver_ebook_no_doc_id_raises(self) -> None:
        ctx = self._make_ctx()
        with self.assertRaises(ValueError):
            self.writer.deliver_ebook(ctx)

    def test_notify_order_received_posts_to_both(self) -> None:
        ctx = self._make_ctx()
        self.writer.notify_order_received(ctx)
        self.comms.chat_send_message.assert_called_once()
        self.comms.slack_post_message.assert_called_once()

    def test_notify_delivery_sent(self) -> None:
        ctx = self._make_ctx(doc_id="doc_notify")
        self.writer.notify_delivery_sent(ctx)
        self.comms.chat_send_message.assert_called_once()
        self.comms.slack_post_message.assert_called_once()

    def test_notify_skips_missing_channels(self) -> None:
        from agents.writer_agent import WriterAgent
        writer = WriterAgent(
            workspace=self.workspace,
            comms=self.comms,
            # no chat_space_id or slack_channel
        )
        ctx = self._make_ctx()
        writer.notify_order_received(ctx)
        self.comms.chat_send_message.assert_not_called()
        self.comms.slack_post_message.assert_not_called()

    def test_send_custom_email(self) -> None:
        result = self.writer.send_custom_email(
            to="target@example.com",
            subject="Hello",
            body="Body text",
        )
        self.workspace.gmail_send.assert_called_once_with(
            to="target@example.com",
            subject="Hello",
            body="Body text",
            html=False,
            attachments=None,
        )


# ---------------------------------------------------------------------------
# AnalystAgent tests
# ---------------------------------------------------------------------------

class TestAnalystAgent(unittest.TestCase):

    def setUp(self) -> None:
        from agents.analyst_agent import AnalystAgent
        self.workspace = _make_workspace_mock()
        self.vertex = _make_vertex_mock()
        self.analyst = AnalystAgent(
            workspace=self.workspace,
            vertex=self.vertex,
            orders_spreadsheet_id="sheet_orders",
            subs_spreadsheet_id="sheet_subs",
        )

    def test_fetch_orders_returns_dicts(self) -> None:
        orders = self.analyst.fetch_orders()
        self.assertEqual(len(orders), 2)
        self.assertIn("email", orders[0])
        self.assertEqual(orders[0]["email"], "alice@example.com")

    def test_fetch_orders_empty_sheet(self) -> None:
        self.workspace.sheets_read_range.return_value = []
        orders = self.analyst.fetch_orders()
        self.assertEqual(orders, [])

    def test_fetch_subscriptions(self) -> None:
        self.workspace.sheets_read_range.return_value = [
            ["timestamp", "email", "subscription_id", "status"],
            ["2024-01-01", "alice@example.com", "sub_1", "active"],
        ]
        subs = self.analyst.fetch_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["email"], "alice@example.com")

    def test_ask_calls_vertex(self) -> None:
        answer = self.analyst.ask("What is total revenue?")
        self.vertex.analyse_tabular.assert_called_once()
        self.assertEqual(answer, "Revenue was $100 AUD.")

    def test_ask_empty_data_returns_message(self) -> None:
        self.workspace.sheets_read_range.return_value = []
        answer = self.analyst.ask("Any question")
        self.assertIn("No data", answer)
        self.vertex.analyse_tabular.assert_not_called()

    def test_revenue_report(self) -> None:
        report = self.analyst.revenue_report()
        self.vertex.analyse_tabular.assert_called_once()
        self.assertEqual(report, "Revenue was $100 AUD.")

    def test_revenue_report_empty(self) -> None:
        self.workspace.sheets_read_range.return_value = []
        report = self.analyst.revenue_report()
        self.assertIn("No order data", report)

    def test_churn_analysis(self) -> None:
        self.workspace.sheets_read_range.return_value = [
            ["timestamp", "email", "subscription_id", "status"],
            ["2024-01-01", "x@e.com", "sub_x", "canceled"],
        ]
        analysis = self.analyst.churn_analysis()
        self.vertex.analyse_tabular.assert_called_once()

    def test_forecast_revenue(self) -> None:
        forecast = self.analyst.forecast_revenue(months_ahead=6)
        self.vertex.analyse_tabular.assert_called_once()
        args = self.vertex.analyse_tabular.call_args
        self.assertIn("6", str(args))

    def test_embed_and_cluster(self) -> None:
        result = self.analyst.embed_and_cluster(["text a", "text b"])
        self.vertex.embed_text.assert_called_once_with(
            ["text a", "text b"], model="text-embedding-004"
        )

    def test_save_report_to_doc(self) -> None:
        result = self.analyst.save_report_to_doc("Big report", title="Q1 Report")
        self.workspace.docs_create.assert_called_once_with(
            title="Q1 Report", body="Big report"
        )

    def test_rows_to_dicts_handles_short_rows(self) -> None:
        from agents.analyst_agent import AnalystAgent
        rows = [
            ["a", "b", "c"],
            ["1", "2"],       # shorter than header
            ["x", "y", "z"],
        ]
        result = AnalystAgent._rows_to_dicts(rows)
        self.assertEqual(result[0]["c"], "")   # missing cell becomes ""
        self.assertEqual(result[1]["a"], "x")


# ---------------------------------------------------------------------------
# Full workflow integration test
# ---------------------------------------------------------------------------

class TestFullWorkflow(unittest.TestCase):
    """
    Integration test that chains Manager → Writer → Analyst together
    using mocked MCP clients to verify the end-to-end call sequence.
    """

    def setUp(self) -> None:
        from agents.manager_agent import ManagerAgent
        from agents.writer_agent import WriterAgent
        from agents.analyst_agent import AnalystAgent

        self.workspace = _make_workspace_mock()
        self.stripe = _make_stripe_mock()
        self.comms = _make_comms_mock()
        self.vertex = _make_vertex_mock()

        self.manager = ManagerAgent(
            workspace=self.workspace,
            stripe=self.stripe,
            orders_spreadsheet_id="sheet_main",
        )
        self.writer = WriterAgent(
            workspace=self.workspace,
            comms=self.comms,
            sender_email="noreply@example.com",
            chat_space_id="spaces/MAIN",
            slack_channel="#orders",
        )
        self.analyst = AnalystAgent(
            workspace=self.workspace,
            vertex=self.vertex,
            orders_spreadsheet_id="sheet_main",
        )

    def test_new_order_to_delivery_chain(self) -> None:
        # 1. Manager processes order
        ctx = self.manager.process_new_order(
            email="end2end@example.com",
            name="E2E User",
            product_title="Full Ebook",
            price_cents=3500,
        )
        self.assertEqual(ctx.stripe_customer_id, "cus_new")
        self.assertEqual(ctx.stripe_payment_intent_id, "pi_new")

        # 2. Confirm payment
        ctx = self.manager.confirm_payment(ctx)
        self.stripe.payment_intent_confirm.assert_called_once_with("pi_new")

        # 3. Writer creates doc
        ctx = self.writer.create_ebook_doc(ctx)
        self.assertEqual(ctx.doc_id, "doc_abc")
        self.workspace.docs_create.assert_called_once()

        # 4. Writer notifies team
        self.writer.notify_order_received(ctx)
        self.comms.chat_send_message.assert_called()
        self.comms.slack_post_message.assert_called()

        # 5. Writer delivers ebook
        ctx = self.writer.deliver_ebook(ctx)
        self.assertTrue(ctx.delivery_sent)
        self.workspace.gmail_send.assert_called_once()

        # 6. Analyst generates revenue report
        report = self.analyst.revenue_report()
        self.vertex.analyse_tabular.assert_called_once()
        self.assertIsInstance(report, str)

        # 7. Writer posts report
        self.writer.post_report(report, title="Revenue Report")
        self.assertEqual(self.comms.chat_send_message.call_count, 2)

    def test_subscription_lifecycle(self) -> None:
        ctx = self.manager.process_new_order(
            email="sub@example.com",
            name="Sub User",
            product_title="Monthly Plan",
            price_cents=999,
        )
        ctx = self.manager.create_subscription(ctx, price_id="price_monthly")
        self.assertEqual(ctx.stripe_subscription_id, "sub_new")
        ctx = self.manager.cancel_subscription(ctx)
        self.stripe.subscription_cancel.assert_called_once_with(
            "sub_new", at_period_end=True
        )


if __name__ == "__main__":
    unittest.main()
