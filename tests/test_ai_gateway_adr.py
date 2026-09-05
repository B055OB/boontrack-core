"""tests/test_ai_gateway_adr.py
Unit & Integration Tests for BoonTrack AI Gateway ADR Architecture:
1. Multi-Agent Profiles & Dynamic Model Routing (BUYER_ASSISTANT, MERCHANT_COPILOT, PLATFORM_SUPPORT).
2. Provider Abstraction & Fallback Chain (Gemini, Claude, OpenAI, Groq, OpenRouter).
3. Store Sales Agent Security Boundary & Action Catalog Verification.
4. Real Transaction Data vs Store Knowledge Context Separation.
5. Backend Validator Price & Stock Integrity (LLM Price Tampering Override).
6. Strict Tenant-Scoped Session Isolation ('tenant:{tenant_id}:session:{session_id}').
"""

import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

from app.services.ai_gateway import (
    AIGateway,
    AgentProfile,
    ModelProfile,
    AGENT_TO_MODEL_PROFILE,
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    ClaudeProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ai_gateway,
)
from app.services.sales_agent_guard import (
    StoreActionType,
    ALLOWED_STORE_ACTIONS,
    format_tenant_session_key,
    TenantScopedSessionStore,
    StoreContextBoundaryManager,
    BackendSecurityValidator,
    backend_security_validator,
    tenant_session_store,
)
from app.services.platform_support_agent import (
    PlatformSupportAgent,
    platform_support_agent,
)
from app.services.ai_engine import commerce_ai_engine


class TestAIGatewayModelRouter(unittest.IsolatedAsyncioTestCase):
    """1. Test Gateway & Model Routing Abstraction."""

    def test_agent_to_model_profile_mapping(self):
        """Pastikan pemetaan profil agen ke profil model sesuai ADR."""
        self.assertEqual(
            AGENT_TO_MODEL_PROFILE[AgentProfile.BUYER_ASSISTANT],
            ModelProfile.FAST,
            "BUYER_ASSISTANT wajib diarahkan ke model profile FAST untuk latensi rendah (Store Sales Agent)"
        )
        self.assertEqual(
            AGENT_TO_MODEL_PROFILE[AgentProfile.MERCHANT_COPILOT],
            ModelProfile.REASONING,
            "MERCHANT_COPILOT wajib diarahkan ke model profile REASONING untuk analisis mendalam (BoonPilot)"
        )
        self.assertEqual(
            AGENT_TO_MODEL_PROFILE[AgentProfile.PLATFORM_SUPPORT],
            ModelProfile.BALANCED,
            "PLATFORM_SUPPORT wajib diarahkan ke model profile BALANCED/FAST (BoonTrack CS)"
        )

    def test_provider_order_resolution(self):
        """Pastikan urutan failover provider sesuai profil performa."""
        gateway = AIGateway()

        fast_order = gateway.resolve_provider_order(ModelProfile.FAST, only_available=False)
        self.assertEqual(fast_order[0][0].provider_name, "groq")
        self.assertEqual(fast_order[1][0].provider_name, "gemini")

        reasoning_order = gateway.resolve_provider_order(ModelProfile.REASONING, only_available=False)
        self.assertEqual(reasoning_order[0][0].provider_name, "gemini")
        self.assertEqual(reasoning_order[1][0].provider_name, "claude")

        balanced_order = gateway.resolve_provider_order(ModelProfile.BALANCED, only_available=False)
        self.assertEqual(balanced_order[0][0].provider_name, "gemini")
        self.assertEqual(balanced_order[1][0].provider_name, "groq")

    async def test_generate_for_agent_failover(self):
        """Pastikan failover otomatis ke provider kedua jika provider pertama error."""
        gateway = AIGateway()

        # Mock providers
        mock_p1 = MagicMock(spec=BaseLLMProvider)
        mock_p1.name = "MockP1"
        mock_p1.provider_name = "mockp1"
        mock_p1.is_available.return_value = True
        mock_p1.call = AsyncMock(side_effect=Exception("API rate limit exceeded"))

        mock_p2 = MagicMock(spec=BaseLLMProvider)
        mock_p2.name = "MockP2"
        mock_p2.provider_name = "mockp2"
        mock_p2.is_available.return_value = True
        mock_p2.call = AsyncMock(return_value=("Halo! Respon dari provider cadangan.", 10, 20))

        mock_chain = [(mock_p1, "mock-model-1"), (mock_p2, "mock-model-2")]
        with patch.object(gateway, "resolve_provider_order", return_value=mock_chain):
            result = await gateway.generate_for_agent(
                agent_profile=AgentProfile.BUYER_ASSISTANT,
                user_message="Halo, mau beli produk",
                context={"tenant_id": "test_store"},
            )

        self.assertEqual(result, "Halo! Respon dari provider cadangan.")
        mock_p1.call.assert_awaited_once()
        mock_p2.call.assert_awaited_once()


class TestSalesAgentSecurityBoundary(unittest.IsolatedAsyncioTestCase):
    """2. Test Keamanan & Data Boundary Store Sales Agent."""

    def test_action_catalog_strict_membership(self):
        """Pastikan Action Catalog terikat hanya memuat 6 aksi resmi."""
        expected_actions = {
            "SHOW_PRODUCT",
            "SHOW_PRODUCT_LIST",
            "SHOW_VARIANT",
            "SHOW_CHECKOUT",
            "CREATE_PAYMENT",
            "TRANSFER_TO_HUMAN",
        }
        self.assertEqual(
            ALLOWED_STORE_ACTIONS,
            expected_actions,
            "Action Catalog harus tepat 6 aksi terikat sesuai ADR"
        )

    async def test_backend_validator_rejects_unauthorized_actions(self):
        """Pastikan aksi di luar katalog (misal manipulasi DB atau diskon liar) ditolak langsung."""
        validator = BackendSecurityValidator()

        unauthorized_actions = [
            {"action_type": "SET_PRODUCT_PRICE", "price": 0},
            {"action_type": "DROP_DATABASE"},
            {"action_type": "DIRECT_REFUND", "amount": 1000000},
            {"action_type": "APPLY_ARBITRARY_DISCOUNT", "discount_pct": 99},
        ]

        for action in unauthorized_actions:
            res = await validator.validate_and_sanitize_action(
                tenant_id="onlineboost",
                proposed_action=action,
            )
            self.assertFalse(res["is_valid"])
            self.assertEqual(res["error_code"], "ACTION_NOT_ALLOWED")
            self.assertIn("tidak diizinkan", res["message"])

    async def test_backend_validator_overrides_llm_price_tampering(self):
        """
        PENTING: LLM Dilarang menentukan harga.
        Jika LLM mencoba memanipulasi harga (misal Rp 10.000 untuk barang Rp 149.000),
        Backend Validator WAJIB menimpa (override) ke harga resmi database.
        """
        validator = BackendSecurityValidator()

        # Mock database transaction data
        fake_db_catalog = [
            {
                "product_id": "prod_123",
                "title": "Produk Asli Database",
                "slug": "produk-asli",
                "price": 149000.0,
                "stock": 10,
                "is_available": True,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_db_catalog):
            # LLM berhalusinasi atau diserang prompt injection menawarkan harga Rp 1.000
            tampered_action = {
                "action_type": StoreActionType.SHOW_CHECKOUT.value,
                "product_id": "prod_123",
                "price": 1000.0,  # Price tampering!
                "quantity": 1,
            }

            validation = await validator.validate_and_sanitize_action(
                tenant_id="growth",
                proposed_action=tampered_action,
            )

        self.assertTrue(validation["is_valid"])
        payload = validation["sanitized_payload"]
        self.assertIsNotNone(payload)
        # Harga harus dipaksa kembali ke Rp 149.000 dari database
        self.assertEqual(payload["verified_price"], 149000.0)
        self.assertEqual(payload["price_formatted"], "Rp 149,000")
        self.assertTrue(payload["price_tampered_corrected"], "Validator harus menandai koreksi harga")

    async def test_backend_validator_rejects_out_of_stock(self):
        """Backend Validator wajib menolak checkout jika stok riil di database 0."""
        validator = BackendSecurityValidator()

        fake_out_of_stock_catalog = [
            {
                "product_id": "prod_habis",
                "title": "Barang Langka",
                "slug": "barang-langka",
                "price": 250000.0,
                "stock": 0,  # Habis!
                "is_available": False,
            }
        ]

        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_out_of_stock_catalog):
            action = {
                "action_type": StoreActionType.CREATE_PAYMENT.value,
                "product_id": "prod_habis",
                "quantity": 1,
            }

            validation = await validator.validate_and_sanitize_action(
                tenant_id="growth",
                proposed_action=action,
            )

        self.assertFalse(validation["is_valid"])
        self.assertEqual(validation["error_code"], "OUT_OF_STOCK")
        self.assertIn("habis", validation["message"].lower())

    async def test_backend_validator_action_transfer_to_human(self):
        """Validasi aksi TRANSFER_TO_HUMAN menyertakan kontak support resmi toko."""
        validator = BackendSecurityValidator()

        action = {
            "action_type": StoreActionType.TRANSFER_TO_HUMAN.value,
            "reason": "Pembeli butuh negosiasi custom B2B",
        }

        res = await validator.validate_and_sanitize_action(
            tenant_id="onlineboost",
            proposed_action=action,
        )
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["sanitized_payload"]["action_type"], "TRANSFER_TO_HUMAN")
        self.assertIn("cs_contact", res["sanitized_payload"])


class TestTenantIsolation(unittest.TestCase):
    """3. Test Strict Tenant Isolation (Session & Cache Scoping)."""

    def test_session_key_format_scoping(self):
        """Pastikan format key isolasi multi-tenant selalu 'tenant:{tenant_id}:session:{session_id}'."""
        key1 = format_tenant_session_key("OnlineBoost", "sess_xyz_123")
        self.assertEqual(key1, "tenant:onlineboost:session:sess_xyz_123")

        key2 = format_tenant_session_key("PROSCALE", "998877", sub_key="cart")
        self.assertEqual(key2, "tenant:proscale:session:998877:cart")

    def test_tenant_session_store_data_separation(self):
        """Pastikan data sesi tenant A tidak bocor ke tenant B meskipun session_id sama."""
        store = TenantScopedSessionStore()
        session_id = "user_phone_0812345678"

        store.set("tenant_alpha", session_id, {"selected_product": "alpha_special"})
        store.set("tenant_beta", session_id, {"selected_product": "beta_standard"})

        data_alpha = store.get("tenant_alpha", session_id)
        data_beta = store.get("tenant_beta", session_id)

        self.assertEqual(data_alpha["selected_product"], "alpha_special")
        self.assertEqual(data_beta["selected_product"], "beta_standard")
        self.assertNotEqual(data_alpha, data_beta)

    def test_store_context_boundary_system_prompt_guardrails(self):
        """Pastikan System Prompt yang dibangun memuat larangan keras manipulasi harga/stok bagi LLM."""
        prompt = StoreContextBoundaryManager.build_bounded_system_prompt("onlineboost")

        self.assertIn("DILARANG MENENTUKAN ATAU MENGUBAH HARGA", prompt)
        self.assertIn("DILARANG MEMODIFIKASI STOK", prompt)
        self.assertIn("KATALOG AKSI TERIKAT", prompt)
        for act in ALLOWED_STORE_ACTIONS:
            self.assertIn(act, prompt)


class TestPlatformSupportAgent(unittest.IsolatedAsyncioTestCase):
    """4. Test Platform Support Agent (BoonTrack CS)."""

    async def test_support_agent_uses_platform_support_profile(self):
        """Pastikan Platform Support Agent memanggil gateway dengan AgentProfile.PLATFORM_SUPPORT."""
        agent = PlatformSupportAgent()

        with patch.object(ai_gateway, "generate_for_agent", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Tim Customer Success BoonTrack siap membantu kendala webhook Anda."

            resp = await agent.handle_support_inquiry(
                tenant_id="onlineboost",
                session_id="cs_session_001",
                inquiry="Bagaimana cara mengatur webhook notifikasi order?",
                user_role="merchant",
            )

        self.assertEqual(resp["agent_profile"], AgentProfile.PLATFORM_SUPPORT.value)
        self.assertEqual(resp["model_profile"], ModelProfile.BALANCED.value)
        self.assertIn("BoonTrack", resp["reply"])
        mock_gen.assert_awaited_once()
        call_kwargs = mock_gen.call_args.kwargs
        self.assertEqual(call_kwargs["agent_profile"], AgentProfile.PLATFORM_SUPPORT)


class TestCommerceAIEngineIntegration(unittest.IsolatedAsyncioTestCase):
    """5. Test CommerceAIEngine Integration with Security Validator & AI Gateway."""

    async def test_validate_store_action_proxy(self):
        """Pastikan CommerceAIEngine.validate_store_action memverifikasi aksi via backend validator."""
        fake_catalog = [
            {
                "product_id": "item_1",
                "title": "Produk Integrasi",
                "slug": "produk-integrasi",
                "price": 50000.0,
                "stock": 5,
                "is_available": True,
            }
        ]
        with patch.object(StoreContextBoundaryManager, "fetch_transaction_data", return_value=fake_catalog):
            action = {
                "action_type": "SHOW_PRODUCT",
                "product_id": "item_1",
            }
            res = await commerce_ai_engine.validate_store_action("growth", action)

        self.assertTrue(res["is_valid"])
        self.assertEqual(res["sanitized_payload"]["product_id"], "item_1")
        self.assertEqual(res["sanitized_payload"]["verified_price"], 50000.0)


if __name__ == "__main__":
    unittest.main()
