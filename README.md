# Sovereign Aussie Multi-Agent Workflow

> Automated end-to-end ebook business powered by a three-agent MCP (Model Context Protocol) architecture.

---

## Overview

This system automates the full lifecycle of an ebook business:

1. **Customer places an order** → Stripe payment intent is created and logged to Google Sheets.
2. **Payment succeeds** → Manager confirms the order; Writer creates an ebook Google Doc and emails the access link to the customer.
3. **Notifications** → Writer posts status updates to Google Chat and Slack.
4. **Analysis** → Analyst agent pulls Sheets data, queries Vertex AI (Gemini), and posts revenue reports, churn analysis, and forecasts.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         Agent Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ @Manager     │  │ @Writer      │  │ @Analyst             │  │
│  │ Orchestration│  │ Docs / Gmail │  │ Vertex AI / Sheets   │  │
│  │ Stripe       │  │ Comms        │  │ Reports & Forecasts  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────┼─────────────────┼────────────────────┼───────────────┘
          │                 │                    │
┌─────────▼─────────────────▼────────────────────▼───────────────┐
│                        MCP Client Layer                         │
│  GoogleWorkspaceMCP  CommunicationMCP  StripeMCP  VertexAIMCP   │
└─────────────────────────────────────────────────────────────────┘
          │                 │                    │           │
    Drive/Gmail       Chat/Slack             Stripe      Vertex AI
    Docs/Sheets                                           (Gemini)
```

See `diagrams/wire_scaffold.mmd` for the full Mermaid flowchart and
`diagrams/agent_mindmap.mmd` for the agent relationship mindmap.

---

## Project Structure

```
workspace/
├── agents/
│   ├── manager_agent.py      # @Manager: Orchestration, Stripe, Google Sheets
│   ├── writer_agent.py       # @Writer: Docs/Gmail, Comms
│   └── analyst_agent.py      # @Analyst: Vertex AI, Drive/Sheets data analyst
│
├── mcp_clients/
│   ├── google_workspace.py   # Google Workspace (Drive, Gmail, Docs, Sheets)
│   ├── communication_mcp.py  # Google Chat / Slack
│   ├── stripe_mcp.py         # Stripe API (payments, subs, customers)
│   └── vertex_ai.py          # Advanced reasoning via Vertex AI
│
├── config/
│   ├── build.json            # Deployment config, endpoints, API keys
│   └── mcp_endpoints.json    # Service discovery for MCP endpoints
│
├── diagrams/
│   ├── wire_scaffold.mmd     # Mermaid wireframe/system interface diagram
│   └── agent_mindmap.mmd     # Mermaid agent relationship mindmap
│
├── tests/
│   └── test_workflow.py      # End-to-end workforce chain test with mocks
│
├── dependency_lock.txt       # Python/Node.js dependency versions
├── README.md                 # This file
└── main.py                   # Entrypoint — initialises all MCPs and agents
```

---

## Agents

### @Manager (`agents/manager_agent.py`)

Orchestrates the full order lifecycle.

| Method | Description |
|---|---|
| `process_new_order()` | Create Stripe customer + PaymentIntent, log to Sheets |
| `confirm_payment()` | Confirm PI, update Sheets status |
| `create_subscription()` | Attach recurring Stripe subscription |
| `cancel_subscription()` | Cancel subscription (at period end by default) |
| `get_revenue_summary()` | Aggregate totals from the Orders sheet |

### @Writer (`agents/writer_agent.py`)

Creates documents and handles communications.

| Method | Description |
|---|---|
| `create_ebook_doc()` | Create a Google Doc for the product |
| `append_section()` | Append a section to an existing doc |
| `deliver_ebook()` | Email the Doc link to the customer via Gmail |
| `notify_order_received()` | Post order alert to Chat/Slack |
| `notify_delivery_sent()` | Post delivery confirmation to Chat/Slack |
| `post_report()` | Post an arbitrary report to Chat/Slack |

### @Analyst (`agents/analyst_agent.py`)

Vertex AI–powered data analysis over Google Sheets.

| Method | Description |
|---|---|
| `fetch_orders()` | Read Orders sheet → list of row dicts |
| `fetch_subscriptions()` | Read Subscriptions sheet → list of row dicts |
| `ask()` | Natural-language question over sheet data |
| `revenue_report()` | AI-generated revenue summary |
| `churn_analysis()` | Subscription churn risk analysis |
| `forecast_revenue()` | N-month revenue forecast |
| `embed_and_cluster()` | Compute text embeddings |
| `save_report_to_doc()` | Persist a report to a Google Doc |

---

## Setup

### Prerequisites

- Python 3.11+
- A Google Cloud project with the following APIs enabled:
  - Drive, Gmail, Docs, Sheets, Chat, Vertex AI
- A Stripe account
- A Slack workspace (optional)

### 1. Clone and install dependencies

```bash
git clone https://github.com/brettapps789/sovereign_aussie_multi_agent_workflow.git
cd sovereign_aussie_multi_agent_workflow
pip install -r dependency_lock.txt   # or use the listed versions as a requirements.txt
```

### 2. Configure environment variables

Copy the template and fill in your real values:

```bash
cp .env.example .env   # create a .env file (not committed)
```

Required variables:

| Variable | Description |
|---|---|
| `GCP_PROJECT_ID` | Google Cloud project ID |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Service account for Workspace/Vertex API calls |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key |
| `ORDERS_SPREADSHEET_ID` | Google Sheets ID for the orders tracker |
| `SUBS_SPREADSHEET_ID` | Google Sheets ID for subscriptions (can be same sheet) |
| `STRIPE_SECRET_KEY` | Stripe secret API key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `SENDER_EMAIL` | Gmail address used to send delivery emails |
| `NOTIFICATION_EMAIL` | Admin email for internal alerts |
| `GOOGLE_CHAT_SPACE_ID` | Google Chat space name (`spaces/XXXX`) |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token |
| `SLACK_CHANNEL` | Slack channel name (e.g. `#orders`) |
| `GOOGLE_WORKSPACE_MCP_ENDPOINT` | MCP server URL for Workspace |
| `COMMUNICATION_MCP_ENDPOINT` | MCP server URL for Chat/Slack |
| `STRIPE_MCP_ENDPOINT` | MCP server URL for Stripe |
| `VERTEX_AI_MCP_ENDPOINT` | MCP server URL for Vertex AI |

### 3. Run

```bash
python main.py
```

---

## Testing

```bash
pytest tests/ -v
```

Tests use `unittest.mock` only — no real API calls are made.

---

## Logic Flow

```
Stripe Webhook (payment_intent.succeeded)
         │
         ▼
  ManagerAgent.confirm_payment()
         │
         ▼
  WriterAgent.create_ebook_doc()
         │
         ▼
  WriterAgent.deliver_ebook()   ──►  Customer receives email with Doc link
         │
         ▼
  WriterAgent.notify_delivery_sent()  ──►  Chat + Slack notification
         │
         ▼  (scheduled)
  AnalystAgent.revenue_report()
         │
         ▼
  WriterAgent.post_report()  ──►  Daily report to Chat + Slack
```

---

## Diagrams

Render the Mermaid diagrams at [mermaid.live](https://mermaid.live) or with any Mermaid-compatible renderer:

- **System interface**: `diagrams/wire_scaffold.mmd`
- **Agent mindmap**: `diagrams/agent_mindmap.mmd`
