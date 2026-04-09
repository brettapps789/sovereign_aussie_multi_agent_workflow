"""
Fair Dinkum Publishing — Market Research Bruce (mra_001)

Handles all market research tasks:
- Competitive analysis of existing ebooks on the topic
- Audience segmentation and buyer persona creation
- Keyword/SEO opportunity identification
- Pricing benchmarks for the niche
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "mra_001"
AGENT_NAME = "Market Research Bruce"

SYSTEM_PROMPT = """You are Market Research Bruce, a senior market-research specialist for
Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Identify the target audience and key buyer personas.
2. Analyse the competitive landscape (top 5 competing ebooks/products).
3. Recommend primary and secondary keywords for discoverability.
4. Suggest a viable price range and positioning strategy.
5. Highlight any market gaps the proposed ebook could fill.

Respond in valid JSON with keys:
  target_audience, buyer_personas, competitors, keywords, pricing_recommendation,
  market_gap, confidence_score (0–1), notes
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
    Execute market research for the given prompt.

    Args:
        prompt:         Natural-language task description.
        project_id:     Supabase project ID (for logging/context).
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured research output dict.
    """
    log.info("[%s] Running market research for project %s", AGENT_ID, project_id)

    kb_context = ""
    if knowledge_base:
        kb_context = f"\n\nAgent Knowledge Base:\n{json.dumps(knowledge_base, ensure_ascii=False)}"

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + kb_context},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result: dict = json.loads(raw)
    result["agent_id"]   = AGENT_ID
    result["agent_name"] = AGENT_NAME
    log.info("[%s] Market research complete", AGENT_ID)
    return result
