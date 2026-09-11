"""tests/test_boonpilot_schemas.py
Test suite for BoonPilot Configuration Proposal schemas and enums.
Validates imports across app.modules, modules, and app.schemas.
"""

import pytest
from pydantic import ValidationError

from app.modules.boonpilot.schemas import (
    VerticalTemplateCode,
    ProposalStatus,
    KnowledgeSemanticCategory,
    KnowledgeProposalItem,
    BusinessConfigurationProposal,
)
import modules.boonpilot.schemas as root_schemas
import app.schemas.boonpilot as app_schemas_boonpilot
import app.schemas as global_schemas


def test_import_parity():
    """Verify schemas can be imported via all architectural paths."""
    assert root_schemas.VerticalTemplateCode is VerticalTemplateCode
    assert root_schemas.BusinessConfigurationProposal is BusinessConfigurationProposal
    assert app_schemas_boonpilot.BusinessConfigurationProposal is BusinessConfigurationProposal
    assert global_schemas.BusinessConfigurationProposal is BusinessConfigurationProposal


def test_enums_members():
    """Verify all required enum members exist."""
    expected_verticals = {
        "PHYSICAL",
        "DIGITAL",
        "FOOD",
        "FIELD_SERVICE",
        "PROFESSIONAL_SERVICE",
        "CREATOR_AGENCY",
    }
    assert {e.value for e in VerticalTemplateCode} == expected_verticals

    expected_statuses = {"DRAFT", "VALIDATED", "PUBLISHED", "REJECTED"}
    assert {e.value for e in ProposalStatus} == expected_statuses

    expected_categories = {
        "FACT",
        "RULE",
        "POLICY",
        "FAQ",
        "OBJECTION",
        "PERSONA",
        "CONVERSION",
    }
    assert {e.value for e in KnowledgeSemanticCategory} == expected_categories


def test_knowledge_proposal_item_valid():
    """Verify KnowledgeProposalItem creates and serializes properly."""
    item = KnowledgeProposalItem(
        category=KnowledgeSemanticCategory.POLICY,
        key="refund_policy",
        content="Barang rusak dapat diklaim garansi dalam waktu 1x24 jam.",
    )
    assert item.category == "POLICY"
    assert item.key == "refund_policy"
    assert "1x24 jam" in item.content

    # String coercion check
    item2 = KnowledgeProposalItem(
        category="FACT",
        key="address",
        content="Jl. Sudirman No 10, Jakarta",
    )
    assert item2.category == KnowledgeSemanticCategory.FACT


def test_knowledge_proposal_item_invalid_category():
    """Verify invalid category raises ValidationError."""
    with pytest.raises(ValidationError):
        KnowledgeProposalItem(
            category="INVALID_CAT",
            key="test",
            content="test",
        )


def test_business_configuration_proposal_defaults():
    """Verify BusinessConfigurationProposal minimal instantiation and default values."""
    proposal = BusinessConfigurationProposal(
        template_code=VerticalTemplateCode.PHYSICAL,
    )
    assert proposal.template_code == "PHYSICAL"
    assert proposal.status == ProposalStatus.DRAFT
    assert proposal.business_profile == {}
    assert proposal.persona == {}
    assert proposal.knowledge == []
    assert proposal.booking_schema is None
    assert proposal.conversion_rules is None
    assert proposal.payment_rules is None
    assert proposal.fulfillment_rules is None


def test_business_configuration_proposal_full():
    """Verify complete BusinessConfigurationProposal payload."""
    payload = {
        "template_code": "FIELD_SERVICE",
        "status": "VALIDATED",
        "business_profile": {
            "name": "Boon Service AC",
            "phone": "081234567890",
            "city": "Jakarta Selatan",
        },
        "persona": {
            "tone": "ramah, sopan, teknis solutif",
            "greeting": "Halo kak! Teknisi kami siap melayani.",
        },
        "knowledge": [
            {
                "category": "FACT",
                "key": "garansi_servis",
                "content": "Garansi cuci AC 14 hari.",
            },
            {
                "category": "RULE",
                "key": "minimal_unit",
                "content": "Minimal order cuci AC adalah 2 unit untuk luar area.",
            },
        ],
        "booking_schema": {
            "slot_duration_minutes": 60,
            "operating_hours": "08:00 - 17:00",
        },
        "conversion_rules": {
            "bundling": "Diskon 10% untuk pemesanan 3 AC sekaligus.",
        },
        "payment_rules": {
            "methods": ["QRIS_STATIS"],
            "allow_dp": True,
        },
        "fulfillment_rules": {
            "type": "ON_SITE",
            "service_radius_km": 15,
        },
    }

    proposal = BusinessConfigurationProposal.model_validate(payload)
    assert proposal.template_code == VerticalTemplateCode.FIELD_SERVICE
    assert proposal.status == ProposalStatus.VALIDATED
    assert len(proposal.knowledge) == 2
    assert proposal.knowledge[0].category == KnowledgeSemanticCategory.FACT
    assert proposal.booking_schema["slot_duration_minutes"] == 60
    assert proposal.fulfillment_rules["service_radius_km"] == 15

    dumped = proposal.model_dump()
    assert dumped["status"] == "VALIDATED"
    assert dumped["template_code"] == "FIELD_SERVICE"
    assert dumped["knowledge"][0]["category"] == "FACT"
