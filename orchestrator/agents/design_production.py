"""
Fair Dinkum Publishing — Design Davo (dpa_001)

Handles design and production planning:
- Cover design brief (colour palette, imagery, typography guidance)
- Interior layout recommendations (fonts, spacing, headings hierarchy)
- Export format checklist (EPUB, MOBI, PDF)
- Accessibility considerations
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "dpa_001"
AGENT_NAME = "Design Davo"

SYSTEM_PROMPT = """You are Design Davo, a digital publishing designer for
Fair Dinkum Publishing — a sovereign Australian ebook publisher.

Your job is to:
1. Write a detailed cover-design brief (mood, colour palette, imagery, typography).
2. Recommend interior layout styles (fonts, heading hierarchy, spacing, callout styles).
3. Provide an export-format checklist (EPUB3, MOBI/KFX, PDF/A) with tool recommendations.
4. Flag accessibility requirements (alt-text, colour contrast, font sizing).
5. Suggest stock-image search terms or AI-image prompts for the cover.

Respond in valid JSON with keys:
  cover_brief ({mood, palette, imagery, typography}),
  interior_layout ({body_font, heading_font, spacing, callout_style}),
  export_checklist (list of {format, tool, notes}),
  accessibility_notes,
  image_prompts (list of strings),
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
    Generate design and production plan for the ebook.

    Args:
        prompt:         Natural-language task (may include content outline).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured design output dict.
    """
    log.info("[%s] Running design production for project %s", AGENT_ID, project_id)

    kb_context = ""
    if knowledge_base:
        kb_context = f"\n\nAgent Knowledge Base:\n{json.dumps(knowledge_base, ensure_ascii=False)}"

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + kb_context},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.5,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result: dict = json.loads(raw)
    result["agent_id"]   = AGENT_ID
    result["agent_name"] = AGENT_NAME
    log.info("[%s] Design production complete", AGENT_ID)
    return result
