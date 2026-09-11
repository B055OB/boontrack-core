"""app/schemas/boonpilot.py
BoonPilot configuration and knowledge schemas re-export.
"""

from app.modules.boonpilot.schemas import (
    VerticalTemplateCode,
    ProposalStatus,
    KnowledgeSemanticCategory,
    KnowledgeProposalItem,
    BusinessConfigurationProposal,
)

__all__ = [
    "VerticalTemplateCode",
    "ProposalStatus",
    "KnowledgeSemanticCategory",
    "KnowledgeProposalItem",
    "BusinessConfigurationProposal",
]
