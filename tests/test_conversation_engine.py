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


if __name__ == "__main__":
    unittest.main()
