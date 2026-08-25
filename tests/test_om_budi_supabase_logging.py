import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.whatsapp_service import log_to_supabase_messages, get_supabase

class TestOmBudiSupabaseLogging(unittest.IsolatedAsyncioTestCase):

    @patch("app.services.whatsapp_service.get_supabase")
    async def test_log_to_supabase_messages_user_and_bot(self, mock_get_supabase):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_upsert = MagicMock()
        mock_execute = MagicMock()

        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_insert
        mock_table.upsert.return_value = mock_upsert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "msg-123"}])
        mock_upsert.execute.return_value = MagicMock(data=[{"id": "conv-123"}])

        # Test User Message
        await log_to_supabase_messages(
            sender="user",
            text="Halo Om Budi, minta link audio",
            tenant_id="om-budi",
            channel="whatsapp",
            user_phone="628123456789",
            user_name="Bapak Rudi",
            user_id="628123456789"
        )

        # Verify messages table was called
        mock_client.table.assert_any_call("messages")
        mock_client.table.assert_any_call("conversations")
        
        # Verify inserted payload
        user_call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(user_call_args["sender"], "user")
        self.assertEqual(user_call_args["tenant_id"], "om-budi")
        self.assertEqual(user_call_args["channel"], "whatsapp")
        self.assertEqual(user_call_args["text"], "Halo Om Budi, minta link audio")
        self.assertEqual(user_call_args["user_phone"], "628123456789")
        self.assertEqual(user_call_args["user_name"], "Bapak Rudi")
        self.assertIsNotNone(user_call_args["conversation_id"])

        # Test Bot Message
        await log_to_supabase_messages(
            sender="bot",
            text="Bismillah, berikut link download audio...",
            tenant_id="om-budi",
            channel="whatsapp",
            user_phone="628123456789",
            user_name="Bapak Rudi",
            user_id="628123456789"
        )

        bot_call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(bot_call_args["sender"], "bot")
        self.assertEqual(bot_call_args["tenant_id"], "om-budi")
        self.assertEqual(bot_call_args["channel"], "whatsapp")
        self.assertEqual(bot_call_args["text"], "Bismillah, berikut link download audio...")

if __name__ == "__main__":
    unittest.main()
