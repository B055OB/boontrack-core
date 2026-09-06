import unittest
from unittest.mock import MagicMock
from app.modules.conversation.schemas import CustomerState
from app.modules.conversation.signals import extract_signals
from app.modules.conversation.strategy import determine_strategy
from app.modules.conversation.validator import validate_action
from app.modules.conversation.state import load_customer_state, dump_customer_state


class TestConversationEngine(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()

    def test_1_tanya_budget(self):
        """Test 1 (Tanya Budget): Query 'Sepatu kerja budget 500k' -> state.stage == 'AWARENESS', validate_action allow_button == False."""
        state = CustomerState(session_id="sess_1", tenant_id="onlineboost")
        query = "Sepatu kerja budget 500k"

        intent = extract_signals(query, state)
        determine_strategy(state, intent)
        result = validate_action(state, self.mock_db)

        self.assertEqual(state.stage, "AWARENESS")
        self.assertFalse(result["allow_button"])
        self.assertFalse(state.show_interactive_button)

    def test_2_tanya_ukuran(self):
        """Test 2 (Tanya Ukuran): Query 'Size 42 hitam ada?' -> state.stage == 'CONSIDERATION', allow_button == False."""
        state = CustomerState(session_id="sess_2", tenant_id="onlineboost")
        query = "Size 42 hitam ada?"

        intent = extract_signals(query, state)
        determine_strategy(state, intent)
        result = validate_action(state, self.mock_db)

        self.assertEqual(state.stage, "CONSIDERATION")
        self.assertTrue(state.signals.asked_variant_or_spec)
        self.assertTrue(state.signals.asked_stock)
        self.assertFalse(result["allow_button"])

    def test_3_tanya_ongkir(self):
        """Test 3 (Tanya Ongkir): Query 'Ongkir ke Bandung berapa?' -> state.signals.asked_shipping == True, target_product_ids tidak hilang."""
        state = CustomerState(session_id="sess_3", tenant_id="onlineboost", target_product_ids=["prod_shoes_99"])
        query = "Ongkir ke Bandung berapa?"

        extract_signals(query, state)

        # Simpan ke context dan load kembali untuk memverifikasi integritas state
        context = dump_customer_state(state, {})
        reloaded_state = load_customer_state("sess_3", "onlineboost", context)

        self.assertTrue(reloaded_state.signals.asked_shipping)
        self.assertEqual(reloaded_state.target_product_ids, ["prod_shoes_99"])

    def test_4_konfirmasi_ambil(self):
        """Test 4 (Konfirmasi Ambil): Query 'Oke saya ambil ini' (mock product stock > 0) -> state.stage == 'DECISION', allow_button == True, button_type == 'CHECKOUT_QRIS'."""
        state = CustomerState(session_id="sess_4", tenant_id="onlineboost", target_product_ids=["prod_shoes_01"])
        query = "Oke saya ambil ini"

        mock_product = MagicMock()
        mock_product.id = "prod_shoes_01"
        mock_product.stock = 15
        self.mock_db.get_product.return_value = mock_product

        intent = extract_signals(query, state)
        self.assertEqual(intent, "PURCHASE_CONFIRMED")

        strategy = determine_strategy(state, intent)
        self.assertEqual(strategy, "PREPARE_CHECKOUT")
        self.assertEqual(state.stage, "DECISION")

        result = validate_action(state, self.mock_db)
        self.assertTrue(result["allow_button"])
        self.assertEqual(result["button_type"], "CHECKOUT_QRIS")
        self.assertEqual(result["payload"]["product_id"], "prod_shoes_01")
        self.assertTrue(state.show_interactive_button)

    def test_5_keberatan(self):
        """Test 5 (Keberatan): Query 'Mahal, pikir-pikir dulu' -> state.stage == 'HESITATION', allow_button == False."""
        state = CustomerState(session_id="sess_5", tenant_id="onlineboost", target_product_ids=["prod_shoes_01"])
        query = "Mahal, pikir-pikir dulu"

        intent = extract_signals(query, state)
        self.assertEqual(intent, "OBJECTION_RAISED")

        strategy = determine_strategy(state, intent)
        self.assertEqual(strategy, "HANDLE_OBJECTION")
        self.assertEqual(state.stage, "HESITATION")

        result = validate_action(state, self.mock_db)
        self.assertFalse(result["allow_button"])
        self.assertFalse(state.show_interactive_button)


class TestConversationWebhookIntegration(unittest.TestCase):
    """End-to-End integration test for 3-layer engine wired to WhatsApp webhook."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.services.whatsapp_service import user_tenant_sessions
        self.client = TestClient(app)
        user_tenant_sessions.clear()

    def test_webhook_3_layer_flow_multi_turn(self):
        from app.services.whatsapp_service import user_tenant_sessions
        from app.repositories.session_repository import SessionRepository
        from app.modules.conversation import load_customer_state

        phone = "6281122334455"
        user_tenant_sessions[phone] = "onlineboost"
        session_repo = SessionRepository()

        # Turn 1: Tanya kebutuhan / budget (AWARENESS)
        payload1 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": phone}],
                        "messages": [{"from": phone, "id": "m1", "type": "text", "text": {"body": "Budget saya 500k"}}],
                    },
                    "field": "messages",
                }]
            }]
        }
        res1 = self.client.post("/api/v1/whatsapp/webhook", json=payload1)
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1.get("stage"), "AWARENESS")
        self.assertFalse(data1.get("allow_button"))

        # Turn 2: Tanya varian / stok (CONSIDERATION)
        payload2 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": phone}],
                        "messages": [{"from": phone, "id": "m2", "type": "text", "text": {"body": "Size 42 ready?"}}],
                    },
                    "field": "messages",
                }]
            }]
        }
        res2 = self.client.post("/api/v1/whatsapp/webhook", json=payload2)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2.get("stage"), "CONSIDERATION")
        self.assertFalse(data2.get("allow_button"))

        # Turn 3: Siap beli (DECISION -> allow_button = True)
        payload3 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": phone}],
                        "messages": [{"from": phone, "id": "m3", "type": "text", "text": {"body": "Oke saya ambil ini"}}],
                    },
                    "field": "messages",
                }]
            }]
        }
        res3 = self.client.post("/api/v1/whatsapp/webhook", json=payload3)
        self.assertEqual(res3.status_code, 200)
        data3 = res3.json()
        self.assertEqual(data3.get("stage"), "DECISION")
        self.assertTrue(data3.get("allow_button"))

        # Turn 4: Beli QRIS (CLOSED)
        payload4 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Budi"}, "wa_id": phone}],
                        "messages": [{
                            "from": phone,
                            "id": "m4",
                            "type": "interactive",
                            "interactive": {"type": "button_reply", "button_reply": {"id": "btn_buy_now", "title": "Beli"}},
                        }],
                    },
                    "field": "messages",
                }]
            }]
        }
        res4 = self.client.post("/api/v1/whatsapp/webhook", json=payload4)
        self.assertEqual(res4.status_code, 200)
        data4 = res4.json()
        self.assertEqual(data4.get("status"), "qris_dispatched")

    def test_onlineboost_locked_session_natural_chat_response(self):
        """Tes user yang terkunci di sesi onlineboost mengirim chat pertanyaan umum dijawab oleh bot."""
        from app.routes.meta_whatsapp import user_tenant_sessions
        phone = "6281122334455"
        user_tenant_sessions[phone] = "onlineboost"

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Pemula"}, "wa_id": phone}],
                        "messages": [{
                            "from": phone,
                            "id": "msg_ob_advice",
                            "type": "text",
                            "text": {"body": "Saya pemula di dunia digital marketing, enaknya ambil yang mana ya min?"},
                        }],
                    },
                    "field": "messages",
                }]
            }]
        }
        res = self.client.post("/api/v1/whatsapp/webhook", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("tenant"), "onlineboost")
        self.assertTrue(len(data.get("reply", "")) > 0)


if __name__ == "__main__":
    unittest.main()


