"""
main.py — Entrypoint for Sovereign Aussie Multi-Agent Workflow.

Initialises all MCP clients and agents, then starts the workflow
dispatcher (HTTP server for Stripe webhooks + scheduled tasks).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent / "config"


def _load_json(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    with path.open() as fh:
        return json.load(fh)


def _resolve_env(value: str) -> str:
    """Expand ``${ENV_VAR}`` placeholders in config strings."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var = value[2:-1]
        resolved = os.environ.get(var, "")
        if not resolved:
            logger.warning("Environment variable %r is not set.", var)
        return resolved
    return value


# ---------------------------------------------------------------------------
# MCP client factory
# ---------------------------------------------------------------------------

def _build_mcp_clients(endpoints: dict) -> dict:
    """Instantiate and connect all MCP clients."""
    from mcp_clients.google_workspace import GoogleWorkspaceMCP
    from mcp_clients.communication_mcp import CommunicationMCP
    from mcp_clients.stripe_mcp import StripeMCP
    from mcp_clients.vertex_ai import VertexAIMCP

    svc = endpoints["services"]

    workspace = GoogleWorkspaceMCP(
        endpoint=_resolve_env(svc["google_workspace"]["endpoint"]),
        credentials={
            "keyfile": _resolve_env(svc["google_workspace"]["credentials_env"]),
            "scopes": svc["google_workspace"]["scopes"],
        },
    )

    comms = CommunicationMCP(
        endpoint=_resolve_env(svc["communication"]["endpoint"]),
        credentials={
            "keyfile": _resolve_env(svc["communication"]["credentials_env"]),
            "slack_token": os.environ.get(
                svc["communication"].get("slack_token_env", ""), ""
            ),
        },
    )

    stripe = StripeMCP(
        endpoint=_resolve_env(svc["stripe"]["endpoint"]),
        credentials={
            "api_key": os.environ.get(
                svc["stripe"].get("api_key_env", "STRIPE_SECRET_KEY"), ""
            ),
        },
    )

    vertex = VertexAIMCP(
        endpoint=_resolve_env(svc["vertex_ai"]["endpoint"]),
        credentials={
            "keyfile": _resolve_env(svc["vertex_ai"]["credentials_env"]),
            "location": svc["vertex_ai"]["location"],
        },
    )

    clients = {
        "workspace": workspace,
        "comms": comms,
        "stripe": stripe,
        "vertex": vertex,
    }

    # Connect all clients
    for name, client in clients.items():
        logger.info("Connecting MCP client: %s", name)
        client.connect()

    return clients


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def _build_agents(clients: dict, build_cfg: dict) -> dict:
    """Instantiate all agents with their MCP clients and config."""
    from agents.manager_agent import ManagerAgent
    from agents.writer_agent import WriterAgent
    from agents.analyst_agent import AnalystAgent

    agent_cfg = build_cfg.get("agents", {})

    manager = ManagerAgent(
        workspace=clients["workspace"],
        stripe=clients["stripe"],
        orders_spreadsheet_id=_resolve_env(
            agent_cfg.get("manager", {}).get("orders_spreadsheet_id", "")
        ),
        notification_email=_resolve_env(
            agent_cfg.get("manager", {}).get("notification_email", "")
        ),
    )

    writer = WriterAgent(
        workspace=clients["workspace"],
        comms=clients["comms"],
        sender_email=_resolve_env(
            agent_cfg.get("writer", {}).get("sender_email", "")
        ),
        chat_space_id=_resolve_env(
            agent_cfg.get("writer", {}).get("chat_space_id", "")
        ),
        slack_channel=_resolve_env(
            agent_cfg.get("writer", {}).get("slack_channel", "")
        ),
    )

    analyst = AnalystAgent(
        workspace=clients["workspace"],
        vertex=clients["vertex"],
        orders_spreadsheet_id=_resolve_env(
            agent_cfg.get("analyst", {}).get("orders_spreadsheet_id", "")
        ),
        subs_spreadsheet_id=_resolve_env(
            agent_cfg.get("analyst", {}).get("subs_spreadsheet_id", "")
        ),
    )

    return {"manager": manager, "writer": writer, "analyst": analyst}


# ---------------------------------------------------------------------------
# Webhook / event dispatcher
# ---------------------------------------------------------------------------

def handle_stripe_webhook(
    payload: bytes,
    sig_header: str,
    clients: dict,
    agents: dict,
    build_cfg: dict,
) -> dict:
    """
    Process an incoming Stripe webhook event.

    Supported event types:
    - ``payment_intent.succeeded``  → confirm order, create doc, deliver ebook
    - ``customer.subscription.deleted`` → log cancellation
    """
    webhook_secret = _resolve_env(
        build_cfg.get("stripe", {}).get("webhook_secret", "")
    )
    event = clients["stripe"].webhook_construct_event(
        payload, sig_header, webhook_secret
    )
    event_type: str = event.get("type", "")
    data: dict = event.get("data", {}).get("object", {})

    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "payment_intent.succeeded":
        from agents.manager_agent import WorkflowContext

        ctx = WorkflowContext(
            customer_email=data.get("receipt_email", ""),
            stripe_customer_id=data.get("customer", ""),
            stripe_payment_intent_id=data.get("id", ""),
            product_title=data.get("metadata", {}).get("product", "Ebook"),
        )
        agents["writer"].notify_order_received(ctx)
        ctx = agents["writer"].create_ebook_doc(ctx)
        ctx = agents["writer"].deliver_ebook(ctx)
        agents["writer"].notify_delivery_sent(ctx)
        return {"handled": True, "event": event_type}

    if event_type == "customer.subscription.deleted":
        logger.info(
            "Subscription %s deleted for customer %s",
            data.get("id"),
            data.get("customer"),
        )
        return {"handled": True, "event": event_type}

    logger.debug("Unhandled webhook event type: %s", event_type)
    return {"handled": False, "event": event_type}


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------

def run_daily_report(agents: dict, writer_agent) -> None:
    """Generate and post the daily revenue report."""
    logger.info("Running daily revenue report…")
    report = agents["analyst"].revenue_report()
    writer_agent.post_report(report, title="Daily Revenue Report")
    logger.info("Daily report posted.")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting Sovereign Aussie Multi-Agent Workflow…")

    build_cfg = _load_json("build.json")
    endpoints_cfg = _load_json("mcp_endpoints.json")

    clients = _build_mcp_clients(endpoints_cfg)
    agents = _build_agents(clients, build_cfg)

    logger.info(
        "All MCP clients and agents initialised. "
        "Agents: %s", list(agents.keys())
    )

    # In a real deployment this would start an HTTP server (e.g. FastAPI/Flask)
    # to receive Stripe webhooks and schedule periodic tasks.
    # For now we log a startup summary.
    summary = agents["manager"].get_revenue_summary()
    logger.info(
        "Startup revenue summary: total_orders=%d total_revenue_cents=%d",
        summary["total_orders"],
        summary["total_revenue_cents"],
    )


if __name__ == "__main__":
    main()
