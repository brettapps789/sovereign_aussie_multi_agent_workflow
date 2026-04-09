"""
Fair Dinkum Publishing — Agents package
Exports all agent modules for the orchestrator.
"""

from . import (
    analytics,
    content_creator,
    design_production,
    legal_compliance,
    market_research,
    marketing,
    sales_distribution,
)

__all__ = [
    "analytics",
    "content_creator",
    "design_production",
    "legal_compliance",
    "market_research",
    "marketing",
    "sales_distribution",
]
