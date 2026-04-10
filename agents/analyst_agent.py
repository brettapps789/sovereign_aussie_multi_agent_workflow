"""
Analyst Agent
Data analysis powered by Vertex AI over Google Drive/Sheets data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_clients.google_workspace import GoogleWorkspaceMCP
    from mcp_clients.vertex_ai import VertexAIMCP

logger = logging.getLogger(__name__)


class AnalystAgent:
    """
    @Analyst — Vertex AI, Drive/Sheets data analyst.

    Responsibilities:
    - Pull raw data from Google Sheets (orders, subscriptions, etc.)
    - Use Vertex AI to answer natural-language questions about the data
    - Generate periodic revenue and engagement reports
    - Surface forecasts and recommendations for the Manager agent
    - Store analysis artefacts back to Drive/Docs as needed
    """

    def __init__(
        self,
        workspace: "GoogleWorkspaceMCP",
        vertex: "VertexAIMCP",
        orders_spreadsheet_id: str,
        subs_spreadsheet_id: str = "",
    ) -> None:
        self._workspace = workspace
        self._vertex = vertex
        self.orders_spreadsheet_id = orders_spreadsheet_id
        self.subs_spreadsheet_id = subs_spreadsheet_id or orders_spreadsheet_id

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def fetch_orders(
        self,
        spreadsheet_id: str = "",
        range_: str = "Orders!A:H",
    ) -> list[dict[str, Any]]:
        """
        Read the Orders sheet and return a list of row dicts.

        The first row is assumed to be the header.
        """
        sid = spreadsheet_id or self.orders_spreadsheet_id
        rows = self._workspace.sheets_read_range(sid, range_)
        return self._rows_to_dicts(rows)

    def fetch_subscriptions(
        self,
        spreadsheet_id: str = "",
        range_: str = "Subscriptions!A:D",
    ) -> list[dict[str, Any]]:
        """Read the Subscriptions sheet and return a list of row dicts."""
        sid = spreadsheet_id or self.subs_spreadsheet_id
        rows = self._workspace.sheets_read_range(sid, range_)
        return self._rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # AI-powered analysis
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        spreadsheet_id: str = "",
        range_: str = "Orders!A:H",
        model: str = "gemini-1.5-pro",
    ) -> str:
        """
        Answer a natural-language *question* about a sheet using Vertex AI.

        Example::

            analyst.ask("What was total revenue last month?")
        """
        data = self.fetch_orders(spreadsheet_id=spreadsheet_id, range_=range_)
        if not data:
            return "No data available in the specified sheet range."
        answer = self._vertex.analyse_tabular(data, question, model=model)
        logger.info("Analyst: answered question=%r", question[:80])
        return answer

    def revenue_report(
        self,
        spreadsheet_id: str = "",
        model: str = "gemini-1.5-pro",
    ) -> str:
        """
        Generate a natural-language revenue summary using Vertex AI.

        Returns a prose report string suitable for posting to Slack/Chat.
        """
        data = self.fetch_orders(spreadsheet_id=spreadsheet_id)
        if not data:
            return "No order data found."

        question = (
            "Summarise total revenue, number of orders, average order value, "
            "top-selling products, and any notable trends. Format as a concise "
            "business report with bullet points."
        )
        report = self._vertex.analyse_tabular(data, question, model=model)
        logger.info(
            "Analyst: revenue_report generated (%d chars)", len(report)
        )
        return report

    def churn_analysis(
        self,
        model: str = "gemini-1.5-pro",
    ) -> str:
        """
        Analyse subscription data to identify churn risk segments.

        Returns a prose analysis string.
        """
        data = self.fetch_subscriptions()
        if not data:
            return "No subscription data found."

        question = (
            "Identify customer segments at risk of churning. Highlight any "
            "patterns in cancellation dates, subscription durations, or product "
            "types. Provide actionable retention recommendations."
        )
        analysis = self._vertex.analyse_tabular(data, question, model=model)
        logger.info("Analyst: churn_analysis generated")
        return analysis

    def forecast_revenue(
        self,
        months_ahead: int = 3,
        model: str = "gemini-1.5-pro",
    ) -> str:
        """
        Forecast revenue for the next *months_ahead* months.

        Returns a prose forecast string with a numeric estimate.
        """
        data = self.fetch_orders()
        if not data:
            return "Insufficient data for forecast."

        question = (
            f"Based on the historical order data, forecast total revenue for "
            f"the next {months_ahead} months. Show your reasoning, state "
            f"assumptions, and provide a numeric estimate in AUD."
        )
        forecast = self._vertex.analyse_tabular(data, question, model=model)
        logger.info(
            "Analyst: forecast_revenue months_ahead=%d generated", months_ahead
        )
        return forecast

    def embed_and_cluster(
        self,
        texts: list[str],
        model: str = "text-embedding-004",
    ) -> list[list[float]]:
        """
        Compute embeddings for a list of text strings.

        Useful for semantic clustering of customer feedback or product
        descriptions.
        """
        return self._vertex.embed_text(texts, model=model)

    def save_report_to_doc(
        self,
        report_text: str,
        title: str = "Analysis Report",
        folder_id: str = "",
    ) -> dict:
        """
        Create a Google Doc containing *report_text* and upload to Drive.

        Returns the created document metadata dict.
        """
        doc = self._workspace.docs_create(title=title, body=report_text)
        logger.info(
            "Analyst: saved report to Doc %r", doc.get("documentId")
        )
        return doc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rows_to_dicts(rows: list[list[Any]]) -> list[dict[str, Any]]:
        """Convert a list of rows (first row = header) to list of dicts."""
        if not rows:
            return []
        header, *data = rows
        return [
            {str(header[i]): row[i] if i < len(row) else "" for i in range(len(header))}
            for row in data
        ]
