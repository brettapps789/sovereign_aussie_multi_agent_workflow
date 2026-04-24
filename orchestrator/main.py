"""
Fair Dinkum Publishing — Sovereign AI Workforce Orchestrator
Owner  : Brett Sjoberg
ABN    : 63 590 716 023
Address: Hackham, SA 5163, Australia

Entry point for the GitHub Actions job.

Workflow:
    1. Read inputs from environment variables set by the Actions workflow.
    2. Verify x-api-key against workspace_secrets in Supabase (SHA-256 hex).
    3. Load active agent knowledge bases from Supabase.
    4. Route the task to the appropriate agent(s) via OpenAI GPT-4o.
    5. Execute agents (sequentially or in parallel based on dependencies).
    6. Persist results to agent_tasks in Supabase.
    7. Exit 0 on success so the Actions step that triggers the webhook runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from supabase import AsyncClient, acreate_client
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agents import (
    analytics,
    content_creator,
    design_production,
    legal_compliance,
    market_research,
    marketing,
    sales_distribution,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("orchestrator")

# ── Agent registry ────────────────────────────────────────────────────────────
# Maps agent_id → (display name, handler module)
AGENT_REGISTRY: dict[str, tuple[str, Any]] = {
    "mra_001": ("Market Research Bruce",   market_research),
    "cca_001": ("Content Crafting Sheila", content_creator),
    "dpa_001": ("Design Davo",             design_production),
    "lca_001": ("Legal Mick",              legal_compliance),
    "ma_001":  ("Marketing Moz",           marketing),
    "sda_001": ("Sales Shazza",            sales_distribution),
    "apa_001": ("Analytics Baz",           analytics),
}

# Dependency ordering for full-workforce runs (sequential where noted)
SEQUENTIAL_PIPELINE: list[str] = [
    "mra_001",  # 1. Research first
    "cca_001",  # 2. Content depends on research
    "dpa_001",  # 3. Design depends on content
    "lca_001",  # 4. Legal review of content
    "ma_001",   # 5. Marketing once content/design ready
    "sda_001",  # 6. Sales/distribution last
    "apa_001",  # 7. Analytics can run throughout but summarises at end
]


# ── Supabase helpers ──────────────────────────────────────────────────────────

async def get_supabase() -> AsyncClient:
    """Return an authenticated Supabase async client."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return await acreate_client(url, key)


async def verify_api_key(
    db: AsyncClient,
    workspace_id: str,
    raw_api_key: str,
) -> bool:
    """
    Check that SHA-256(raw_api_key) matches workspace_secrets.encrypted_value
    for the given workspace.  Returns True on match, False otherwise.

    Note: the workspace_secrets table stores API-key tokens as SHA-256 hex
    digests (not passwords).  SHA-256 is used here for token-matching per the
    system design; the comparison uses hmac.compare_digest to prevent timing
    side-channel attacks.
    """
    candidate = hashlib.sha256(raw_api_key.encode()).hexdigest()
    result = (
        await db.table("workspace_secrets")
        .select("encrypted_value")
        .eq("workspace_id", workspace_id)
        .eq("key_name", "ORCHESTRATOR_API_KEY")
        .single()
        .execute()
    )
    stored: str | None = result.data.get("encrypted_value") if result.data else None
    if not stored:
        return False
    # Use timing-safe comparison to prevent timing side-channel attacks.
    return hmac.compare_digest(stored, candidate)


async def load_knowledge_bases(
    db: AsyncClient,
    agent_ids: list[str],
) -> dict[str, dict]:
    """
    Fetch the latest active knowledge-base JSON for each requested agent.
    Returns {agent_id: knowledge_base_dict}.
    """
    result = (
        await db.table("agent_knowledge_base")
        .select("agent_id, knowledge_base, version")
        .in_("agent_id", agent_ids)
        .eq("active", True)
        .order("version", desc=True)
        .execute()
    )
    kb: dict[str, dict] = {}
    seen: set[str] = set()
    for row in result.data or []:
        aid = row["agent_id"]
        if aid not in seen:
            seen.add(aid)
            raw = row["knowledge_base"]
            kb[aid] = raw if isinstance(raw, dict) else json.loads(raw)
    log.info("Loaded knowledge bases for agents: %s", list(kb.keys()))
    return kb


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def persist_task_result(
    db: AsyncClient,
    task_id: str,
    workspace_id: str,
    agent_id: str,
    result: dict,
    status: str,
    elapsed_seconds: float,
) -> None:
    """Write/update agent_tasks row with execution result."""
    payload = {
        "task_id":        task_id,
        "workspace_id":   workspace_id,
        "agent_id":       agent_id,
        "status":         status,
        "result":         result,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "completed_at":   "now()",
    }
    await (
        db.table("agent_tasks")
        .upsert(payload, on_conflict="task_id,agent_id")
        .execute()
    )


# ── Agent execution ───────────────────────────────────────────────────────────

async def run_single_agent(
    *,
    db: AsyncClient,
    openai_client: AsyncOpenAI,
    agent_id: str,
    prompt: str,
    project_id: str,
    workspace_id: str,
    task_id: str,
    knowledge_base: dict,
) -> dict:
    """
    Dispatch a single agent, persist the result, and return the output dict.
    """
    name, module = AGENT_REGISTRY[agent_id]
    log.info("▶ Starting agent %s (%s)", agent_id, name)
    start = time.monotonic()

    try:
        output: dict = await module.run(
            prompt=prompt,
            project_id=project_id,
            knowledge_base=knowledge_base,
            openai_client=openai_client,
        )
        status = "completed"
        log.info("✔ Agent %s completed in %.2fs", agent_id, time.monotonic() - start)
    except Exception as exc:  # noqa: BLE001
        output = {"error": str(exc)}
        status = "failed"
        log.error("✘ Agent %s failed: %s", agent_id, exc)

    elapsed = time.monotonic() - start
    await persist_task_result(
        db=db,
        task_id=task_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        result=output,
        status=status,
        elapsed_seconds=elapsed,
    )
    return output


async def run_agents_parallel(
    *,
    db: AsyncClient,
    openai_client: AsyncOpenAI,
    agent_ids: list[str],
    prompt: str,
    project_id: str,
    workspace_id: str,
    task_id: str,
    knowledge_bases: dict[str, dict],
) -> dict[str, dict]:
    """Run independent agents concurrently and collect results."""
    tasks = [
        run_single_agent(
            db=db,
            openai_client=openai_client,
            agent_id=aid,
            prompt=prompt,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
            knowledge_base=knowledge_bases.get(aid, {}),
        )
        for aid in agent_ids
    ]
    results_list = await asyncio.gather(*tasks, return_exceptions=False)
    return dict(zip(agent_ids, results_list))


# ── Routing ───────────────────────────────────────────────────────────────────

async def route_agents(
    openai_client: AsyncOpenAI,
    prompt: str,
    requested_ids: list[str],
) -> list[str]:
    """
    If specific agent_ids were requested, return them (validated).
    Otherwise ask GPT-4o which agents are most appropriate for the task.
    """
    valid = set(AGENT_REGISTRY.keys())

    if requested_ids:
        chosen = [aid for aid in requested_ids if aid in valid]
        if not chosen:
            log.warning("No valid agent IDs in request; falling back to auto-routing.")
        else:
            log.info("Using requested agents: %s", chosen)
            return chosen

    # Auto-routing via GPT-4o
    agent_descriptions = "\n".join(
        f"- {aid}: {name}" for aid, (name, _) in AGENT_REGISTRY.items()
    )
    system_msg = (
        "You are the routing engine for Fair Dinkum Publishing's sovereign AI workforce. "
        "Given a task prompt, select the most appropriate agent(s) from the list below. "
        "Return ONLY a JSON array of agent_id strings, e.g. [\"mra_001\",\"cca_001\"]. "
        "Pick the minimum set needed to fulfil the task.\n\n"
        f"Available agents:\n{agent_descriptions}"
    )
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": prompt},
        ],
        temperature=0,
        max_tokens=128,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "[]"
    # The model may return {"agents": [...]} or a bare array wrapped in an object
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        chosen = parsed
    else:
        # Try common keys
        chosen = parsed.get("agents") or parsed.get("agent_ids") or list(parsed.values())[0]

    chosen = [aid for aid in chosen if aid in valid]
    log.info("Auto-routed to agents: %s", chosen)
    return chosen if chosen else list(AGENT_REGISTRY.keys())


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Sovereign workforce orchestrator entry point."""
    load_dotenv()  # no-op in Actions; useful for local dev

    # Read inputs injected as environment variables by the workflow
    prompt       = os.environ["INPUT_PROMPT"]
    project_id   = os.environ["INPUT_PROJECT_ID"]
    workspace_id = os.environ["INPUT_WORKSPACE_ID"]
    task_id      = os.environ["INPUT_TASK_ID"]
    raw_agent_ids = os.environ.get("INPUT_AGENT_IDS", "")
    requested_ids = [a.strip() for a in raw_agent_ids.split(",") if a.strip()]

    api_key = os.environ["ORCHESTRATOR_API_KEY"]

    log.info(
        "Sovereign Workforce Orchestrator — task_id=%s project_id=%s workspace_id=%s",
        task_id, project_id, workspace_id,
    )

    # ── Initialise clients ────────────────────────────────────────────────────
    db = await get_supabase()
    openai_client = AsyncOpenAI(api_key=os.environ["CHATGPT_API_KEY"])

    # ── Verify API key ────────────────────────────────────────────────────────
    log.info("Verifying x-api-key for workspace %s …", workspace_id)
    if not await verify_api_key(db, workspace_id, api_key):
        log.error("API key verification failed — aborting.")
        raise PermissionError("Invalid ORCHESTRATOR_API_KEY for workspace.")
    log.info("API key verified ✔")

    # ── Route to agents ───────────────────────────────────────────────────────
    chosen_ids = await route_agents(openai_client, prompt, requested_ids)

    # ── Load knowledge bases ──────────────────────────────────────────────────
    kb = await load_knowledge_bases(db, chosen_ids)

    # ── Execute agents ────────────────────────────────────────────────────────
    workflow_start = time.monotonic()

    if len(chosen_ids) == 1:
        # Single-agent path
        results = await run_agents_parallel(
            db=db,
            openai_client=openai_client,
            agent_ids=chosen_ids,
            prompt=prompt,
            project_id=project_id,
            workspace_id=workspace_id,
            task_id=task_id,
            knowledge_bases=kb,
        )
    else:
        # Multi-agent: run in dependency order, grouping independent agents in parallel
        ordered = [aid for aid in SEQUENTIAL_PIPELINE if aid in chosen_ids]
        # Any chosen agents not in the pipeline run in parallel at the start
        extra = [aid for aid in chosen_ids if aid not in SEQUENTIAL_PIPELINE]

        results: dict[str, dict] = {}

        if extra:
            extra_results = await run_agents_parallel(
                db=db,
                openai_client=openai_client,
                agent_ids=extra,
                prompt=prompt,
                project_id=project_id,
                workspace_id=workspace_id,
                task_id=task_id,
                knowledge_bases=kb,
            )
            results.update(extra_results)

        # Run pipeline agents sequentially so each has access to prior output
        accumulated_context = prompt
        for aid in ordered:
            # Enrich prompt with prior outputs as context
            if results:
                summary = json.dumps(
                    {k: v for k, v in results.items()}, ensure_ascii=False
                )
                enriched_prompt = (
                    f"{accumulated_context}\n\n"
                    f"--- Prior agent outputs (for context) ---\n{summary}"
                )
            else:
                enriched_prompt = accumulated_context

            out = await run_single_agent(
                db=db,
                openai_client=openai_client,
                agent_id=aid,
                prompt=enriched_prompt,
                project_id=project_id,
                workspace_id=workspace_id,
                task_id=task_id,
                knowledge_base=kb.get(aid, {}),
            )
            results[aid] = out

    total_elapsed = time.monotonic() - workflow_start
    log.info(
        "All agents completed in %.2fs. Results: %s",
        total_elapsed,
        {k: ("ok" if "error" not in v else "failed") for k, v in results.items()},
    )

    # ── Audit log entry ───────────────────────────────────────────────────────
    try:
        await db.table("audit_log").insert({
            "workspace_id":   workspace_id,
            "project_id":     project_id,
            "task_id":        task_id,
            "event":          "orchestrator_completed",
            "payload":        {"agents_run": list(results.keys()), "elapsed_seconds": round(total_elapsed, 3)},
        }).execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("Audit log insert failed (non-fatal): %s", exc)


if __name__ == "__main__":
    asyncio.run(main())
