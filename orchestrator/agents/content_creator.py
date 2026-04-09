"""
Fair Dinkum Publishing — Content Crafting Sheila (cca_001)

Handles all content-creation tasks:
- Full chapter outlines
- Engaging, culturally resonant prose (Australian tone where appropriate)
- SEO-optimised title and subtitle suggestions
- Front/back matter (intro, conclusion, call-to-action)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "cca_001"
AGENT_NAME = "Content Crafting Sheila"

SYSTEM_PROMPT = """You are Content Crafting Sheila, a professional ebook author and content
strategist for Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Generate a detailed chapter outline (chapters with titles and key points).
2. Write an engaging introduction and conclusion.
3. Suggest 3 SEO-friendly title + subtitle combinations.
4. Draft the opening section (first ~300 words) of the ebook.
5. Recommend calls-to-action for the back matter.

The tone should be clear, authoritative, and approachable — Australian English spelling.

Respond in valid JSON with keys:
  chapter_outline (list of {title, key_points}), introduction_draft, conclusion_draft,
  title_suggestions (list of {title, subtitle}), opening_draft, cta_suggestions,
  word_count_estimate, notes
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
    Generate ebook content structure and draft sections.

    Args:
        prompt:         Natural-language task description (may include market research output).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured content output dict.
    """
    log.info("[%s] Running content creation for project %s", AGENT_ID, project_id)

    kb_context = ""
    if knowledge_base:
        kb_context = f"\n\nAgent Knowledge Base:\n{json.dumps(knowledge_base, ensure_ascii=False)}"

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + kb_context},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.6,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result: dict = json.loads(raw)
    result["agent_id"]   = AGENT_ID
    result["agent_name"] = AGENT_NAME
    log.info("[%s] Content creation complete", AGENT_ID)
    return result
