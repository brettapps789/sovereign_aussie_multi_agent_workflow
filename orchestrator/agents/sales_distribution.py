"""
Fair Dinkum Publishing — Sales Shazza (sda_001)

Handles sales and distribution planning:
- Platform selection and setup checklist (Amazon KDP, Gumroad, Payhip, etc.)
- Pricing strategy (launch price, evergreen price, bundle ideas)
- Distribution timeline
- Upsell / cross-sell recommendations
- Royalty / revenue split summary
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "sda_001"
AGENT_NAME = "Sales Shazza"

SYSTEM_PROMPT = """You are Sales Shazza, a sales and distribution specialist for
Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Recommend the best distribution platforms with pros/cons and setup steps.
2. Propose a pricing strategy: launch price, evergreen price, bundle offers.
3. Draft a distribution timeline (pre-launch → launch → post-launch).
4. Suggest upsell and cross-sell products (courses, templates, coaching).
5. Summarise expected royalty/revenue splits per platform.

Respond in valid JSON with keys:
  platforms (list of {name, pros, cons, royalty_rate, setup_steps}),
  pricing_strategy ({launch_price, evergreen_price, bundle_ideas}),
  distribution_timeline (list of {week, milestone, actions}),
  upsell_suggestions (list of {product, price_point, description}),
  revenue_summary (string),
  notes
"""


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    reraise=True,
)
async def run(
    *,
    prompt: str,
    project_id: str,
    knowledge_base: dict[str, Any],
    openai_client: AsyncOpenAI,
) -> dict[str, Any]:
    """
    Generate sales and distribution plan.

    Args:
        prompt:         Natural-language task (may include earlier agent outputs).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured sales output dict.
    """
    log.info("[%s] Running sales distribution for project %s", AGENT_ID, project_id)

    kb_context = ""
    if knowledge_base:
        kb_context = f"\n\nAgent Knowledge Base:\n{json.dumps(knowledge_base, ensure_ascii=False)}"

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + kb_context},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.4,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result: dict = json.loads(raw)
    result["agent_id"]   = AGENT_ID
    result["agent_name"] = AGENT_NAME
    log.info("[%s] Sales distribution complete", AGENT_ID)
    return result
