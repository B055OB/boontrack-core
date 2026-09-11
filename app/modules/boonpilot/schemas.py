"""app/modules/boonpilot/schemas.py
Pydantic Schemas for BoonPilot Configuration Proposal and Knowledge Architecture.
Aligned with ARCHITECTURE.md Section 8 and frontend types/boonpilot.ts.
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class VerticalTemplateCode(str, Enum):
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"
    FOOD = "FOOD"
    FIELD_SERVICE = "FIELD_SERVICE"
    PROFESSIONAL_SERVICE = "PROFESSIONAL_SERVICE"
    CREATOR_AGENCY = "CREATOR_AGENCY"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class KnowledgeSemanticCategory(str, Enum):
    FACT = "FACT"
    RULE = "RULE"
    POLICY = "POLICY"
    FAQ = "FAQ"
    OBJECTION = "OBJECTION"
    PERSONA = "PERSONA"
    CONVERSION = "CONVERSION"


class KnowledgeProposalItem(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    category: KnowledgeSemanticCategory = Field(
        ...,
        description="Semantic classification of the knowledge item (FACT, RULE, POLICY, FAQ, OBJECTION, PERSONA, CONVERSION)"
    )
    key: str = Field(
        ...,
        description="Unique semantic key or identifier for this knowledge entry (e.g., 'refund_policy', 'operating_hours')"
    )
    content: str = Field(
        ...,
        description="The substantive text, directive, or knowledge payload"
    )


class BusinessConfigurationProposal(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    template_code: VerticalTemplateCode = Field(
        ...,
        description="Canonical vertical business template code"
    )
    status: ProposalStatus = Field(
        default=ProposalStatus.DRAFT,
        description="Lifecycle status of the configuration proposal (DRAFT, VALIDATED, PUBLISHED, REJECTED)"
    )
    business_profile: Dict[str, Any] = Field(
        default_factory=dict,
        description="High-level merchant business profile (name, industry, description, contact)"
    )
    persona: Dict[str, Any] = Field(
        default_factory=dict,
        description="Presentation policy / persona configuration (tone, greetings, dos and donts)"
    )
    knowledge: List[KnowledgeProposalItem] = Field(
        default_factory=list,
        description="Structured list of semantic knowledge items proposed for the tenant"
    )
    booking_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Service scheduling and booking configuration (for FIELD_SERVICE / PROFESSIONAL_SERVICE)"
    )
    conversion_rules: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Conversion optimization triggers, voucher rules, and bundling prompts"
    )
    payment_rules: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Payment methods, static QRIS 0% MDR settings, and unique code parameters"
    )
    fulfillment_rules: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Fulfillment configuration (PHYSICAL logistics vs DIGITAL instant delivery bypass)"
    )
