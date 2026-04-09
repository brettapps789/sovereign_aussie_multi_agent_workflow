"""
Fair Dinkum Publishing — Marketing Moz (ma_001)

Handles marketing strategy and copy:
- Launch email sequence (3–5 emails)
- Social media post schedule (LinkedIn, Facebook, Instagram, X/Twitter)
- Amazon/Gumroad product description and keyword tags
- Paid ad creative briefs (Google, Meta)
- Affiliate / partnership outreach template
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "ma_001"
AGENT_NAME = "Marketing Moz"

SYSTEM_PROMPT = """You are Marketing Moz, a digital marketing strategist for
Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Write a 3-email launch sequence (tease → launch day → follow-up).
2. Create a 2-week social media post schedule with platform-specific copy.
3. Draft a product description and keyword tag list for ebook storefronts.
4. Produce ad creative briefs for Google and Meta campaigns.
5. Write an affiliate/partnership outreach email template.

Tone: friendly, direct, results-oriented. Australian English spelling.

Respond in valid JSON with keys:
  email_sequence (list of {subject, preview_text, body}),
  social_schedule (list of {day, platform, copy, hashtags}),
  product_description (string),
  keyword_tags (list of strings),
  ad_briefs ({google: {headline, description, cta}, meta: {headline, body, cta, image_prompt}}),
  affiliate_template (string),
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
    Generate marketing strategy and copy assets.

    Args:
        prompt:         Natural-language task (may include research + content outputs).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured marketing output dict.
    """
    log.info("[%s] Running marketing strategy for project %s", AGENT_ID, project_id)

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
    log.info("[%s] Marketing strategy complete", AGENT_ID)
    return result
