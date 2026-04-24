"""
Fair Dinkum Publishing — Analytics Baz (apa_001)

Handles analytics and performance tracking:
- KPI framework for the ebook launch
- Tracking plan (events, tools, dashboards)
- Post-launch review template
- A/B test suggestions for title, price, and cover
- 90-day growth roadmap
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "apa_001"
AGENT_NAME = "Analytics Baz"

SYSTEM_PROMPT = """You are Analytics Baz, a data and performance analyst for
Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Define a KPI framework for measuring launch success (sales, reviews, email open rates).
2. Produce a tracking plan: what to measure, with which tools, and how often.
3. Create a post-launch review template (Week 1, Month 1, Month 3).
4. Suggest A/B tests for title, cover, price, and ad copy.
5. Outline a 90-day growth roadmap with specific, measurable actions.

Respond in valid JSON with keys:
  kpi_framework (list of {kpi, target, measurement_method}),
  tracking_plan (list of {metric, tool, frequency, owner}),
  review_template ({week_1, month_1, month_3}),
  ab_tests (list of {element, variant_a, variant_b, success_metric}),
  growth_roadmap (list of {week_range, focus_area, actions}),
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
    Generate analytics and performance-tracking plan.

    Args:
        prompt:         Natural-language task (may include all prior agent outputs).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured analytics output dict.
    """
    log.info("[%s] Running analytics for project %s", AGENT_ID, project_id)

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
    log.info("[%s] Analytics complete", AGENT_ID)
    return result
