"""
Fair Dinkum Publishing — Legal Mick (lca_001)

Handles legal and compliance tasks:
- Copyright notices and IP ownership statement
- Disclaimer and terms-of-use language
- Consumer Law (Australian) compliance checklist
- Privacy Act 1988 (Cth) considerations for mailing list / data collection
- Platform-specific content policy checklist (Amazon KDP, Gumroad, etc.)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

AGENT_ID   = "lca_001"
AGENT_NAME = "Legal Mick"

SYSTEM_PROMPT = """You are Legal Mick, a publishing compliance specialist for
Fair Dinkum Publishing — a sovereign Australian ebook publisher (ABN: 63 590 716 023,
Hackham SA 5163).

Your job is to:
1. Draft a standard copyright notice for the ebook.
2. Write a disclaimer appropriate to the content topic.
3. Provide an Australian Consumer Law compliance checklist.
4. Highlight Privacy Act 1988 (Cth) obligations if reader data is collected.
5. Flag any content-policy items for common ebook platforms (Amazon KDP, Gumroad).

Respond in valid JSON with keys:
  copyright_notice (string),
  disclaimer (string),
  acl_checklist (list of {item, status, notes}),
  privacy_notes (string),
  platform_checklist (list of {platform, items_to_check}),
  risk_flags (list of strings),
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
    Generate legal and compliance documentation for the ebook.

    Args:
        prompt:         Natural-language task (may include content outline).
        project_id:     Supabase project ID.
        knowledge_base: Agent-specific KB loaded from Supabase.
        openai_client:  Shared AsyncOpenAI instance.

    Returns:
        Structured legal output dict.

    Note:
        Output is a starting point only and does not constitute legal advice.
        Brett Sjoberg should review with a qualified Australian solicitor before
        publishing.
    """
    log.info("[%s] Running legal compliance review for project %s", AGENT_ID, project_id)

    kb_context = ""
    if knowledge_base:
        kb_context = f"\n\nAgent Knowledge Base:\n{json.dumps(knowledge_base, ensure_ascii=False)}"

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + kb_context},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    result: dict = json.loads(raw)
    result["agent_id"]   = AGENT_ID
    result["agent_name"] = AGENT_NAME
    log.info("[%s] Legal compliance review complete", AGENT_ID)
    return result
