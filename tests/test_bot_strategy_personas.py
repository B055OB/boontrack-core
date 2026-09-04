import os
import sys
import asyncio
from unittest.mock import patch

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi.testclient import TestClient
from app.main import app
from app.models.tenant import BotStrategy, Tenant
from app.schemas.merchant_schema import BotStrategyEnum, MerchantRegisterRequest
from app.services.ai_engine import (
    CommerceAIEngine,
    commerce_ai_engine,
    BOT_STRATEGY_DIRECTIVES,
)
from app.services.onboarding_service import onboarding_service

def test_all_personas():
    print("=================================================================")
    print("RUNNING BOT STRATEGY / RESPONSE PERSONA TEST SUITE")
    print("=================================================================")

    # 1. Model & Schema Verification
    print("\n[TEST 1] Verifying Model & Schema bot_strategy enum...")
    assert hasattr(BotStrategy, "TRUST_BUILDER")
    assert hasattr(BotStrategy, "BALANCED")
    assert hasattr(BotStrategy, "HARD_SELLING")
    assert BotStrategy.TRUST_BUILDER.value == "trust_builder"
    assert BotStrategy.BALANCED.value == "balanced"
    assert BotStrategy.HARD_SELLING.value == "hard_selling"

    req = MerchantRegisterRequest(
        store_name="Toko Test",
        slug="toko-test",
        owner_name="Owner",
        owner_whatsapp="08123456789",
        owner_email="owner@test.com",
        bot_strategy=BotStrategyEnum.HARD_SELLING
    )
    assert req.bot_strategy == BotStrategyEnum.HARD_SELLING
    print("  -> Models and Schemas properly support bot_strategy enum!")

    # 2. Engine System Prompt Injection Verification
    print("\n[TEST 2] Verifying System Prompt for each Bot Persona Strategy...")
    engine = CommerceAIEngine()

    # a. Mode trust_builder
    prompt_tb = engine.build_commerce_system_prompt("onlineboost", bot_strategy="trust_builder")
    assert "trust_builder" in prompt_tb
    assert "JANGAN langsung kirim link pembayaran" in prompt_tb
    assert "garansi resmi toko" in prompt_tb or "keamanan transaksi" in prompt_tb
    print("  -> Mode 'trust_builder' prompt includes empathy, warranty, and forbids immediate payment push.")

    # b. Mode balanced
    prompt_bal = engine.build_commerce_system_prompt("onlineboost", bot_strategy="balanced")
    assert "balanced" in prompt_bal
    assert "2-3 kalimat ringkas" in prompt_bal
    assert "manfaat utama" in prompt_bal
    print("  -> Mode 'balanced' prompt enforces 2-3 concise sentences and key value proposition.")

    # c. Mode hard_selling
    prompt_hs = engine.build_commerce_system_prompt("onlineboost", bot_strategy="hard_selling")
    assert "hard_selling" in prompt_hs
    assert "1-2 kalimat" in prompt_hs
    assert "Pangkas drop-off" in prompt_hs
    print("  -> Mode 'hard_selling' prompt enforces punchy 1-2 sentences and instant closing.")

    # 3. Intelligent Fallback / Generation Verification
    print("\n[TEST 3] Verifying Generated Responses across Strategies...")
    msg_general = "Halo, bisa jelaskan materi apa saja yang dipelajari di kelas ini?"

    # Trust builder response on general inquiry
    reply_tb = asyncio.run(engine.generate_commerce_response("onlineboost", msg_general, bot_strategy="trust_builder"))
    print(f"\n  [Trust Builder Output]:\n  \"{reply_tb[:140]}...\"")
    # Must NOT push QRIS payment immediately on casual inquiry
    assert "Mau saya buatkan kode QRIS" not in reply_tb
    assert "garansi" in reply_tb.lower() or "jaminan" in reply_tb.lower()

    # Balanced response
    reply_bal = asyncio.run(engine.generate_commerce_response("onlineboost", msg_general, bot_strategy="balanced"))
    print(f"\n  [Balanced Output]:\n  \"{reply_bal[:140]}...\"")
    assert "amankan slot" in reply_bal.lower() or "amankan stok" in reply_bal.lower()

    # Hard selling response
    reply_hs = asyncio.run(engine.generate_commerce_response("onlineboost", msg_general, bot_strategy="hard_selling"))
    print(f"\n  [Hard Selling Output]:\n  \"{reply_hs[:140]}...\"")
    assert "ready" in reply_hs.lower()
    assert "kode qris" in reply_hs.lower()

    # 4. Tenant Settings Update Endpoint (PUT /api/v1/tenants/{slug}/settings)
    print("\n[TEST 4] Testing Tenant Settings Endpoint with bot_strategy...")
    client = TestClient(app)

    # Update to hard_selling
    update_res = client.put("/api/v1/tenants/onlineboost/settings", json={
        "bot_strategy": "hard_selling"
    })
    assert update_res.status_code == 200
    get_res = client.get("/api/v1/tenants/onlineboost/settings")
    assert get_res.status_code == 200
    assert get_res.json()["tenant"].get("bot_strategy") == "hard_selling"
    print("  -> Successfully updated tenant bot_strategy to 'hard_selling' via API!")

    # 5. WhatsApp Inbound Gateway Endpoint (POST /api/v1/whatsapp/inbound-process)
    print("\n[TEST 5] Testing Inbound WhatsApp Processing with bot_strategy...")
    # Inbound call with trust_builder override
    inbound_tb = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": "onlineboost",
        "sender_phone": "081234567890",
        "message_body": "Halo, materi apa saja yang ada?",
        "bot_strategy": "trust_builder"
    })
    assert inbound_tb.status_code == 200
    data_tb = inbound_tb.json()
    assert data_tb["bot_strategy"] == "trust_builder"
    assert "Mau saya buatkan kode QRIS" not in data_tb["reply_text"]
    print("  -> Inbound process in 'trust_builder' mode answered consultation without pushing payment link.")

    # Inbound call with hard_selling override
    inbound_hs = client.post("/api/v1/whatsapp/inbound-process", json={
        "tenant_slug": "onlineboost",
        "sender_phone": "081234567890",
        "message_body": "Halo, materi apa saja yang ada?",
        "bot_strategy": "hard_selling"
    })
    assert inbound_hs.status_code == 200
    data_hs = inbound_hs.json()
    assert data_hs["bot_strategy"] == "hard_selling"
    assert "kode qris" in data_hs["reply_text"].lower()
    print("  -> Inbound process in 'hard_selling' mode answered promptly with instant checkout closing.")

    # Revert tenant settings to default trust_builder
    client.put("/api/v1/tenants/onlineboost/settings", json={
        "bot_strategy": "trust_builder"
    })
    print("\n=================================================================")
    print("ALL 5 BOT STRATEGY / RESPONSE PERSONA TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")

if __name__ == "__main__":
    test_all_personas()
