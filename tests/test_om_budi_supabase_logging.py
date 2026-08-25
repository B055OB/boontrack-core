import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.whatsapp_service import (
    log_to_supabase_messages, 
    get_supabase,
    extract_meta_whatsapp_event,
    safe_log_to_supabase_messages
)

class TestOmBudiSupabaseLogging(unittest.IsolatedAsyncioTestCase):

    @patch("app.services.whatsapp_service.get_supabase")
    async def test_log_to_supabase_messages_user_and_bot(self, mock_get_supabase):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_upsert = MagicMock()

        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_insert
        mock_table.upsert.return_value = mock_upsert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "msg-123"}])
        mock_upsert.execute.return_value = MagicMock(data=[{"id": "conv-123"}])

        # Test User Message with metadata
        await log_to_supabase_messages(
            sender="Customer / +628123456789",
            text="Halo Om Budi, minta link audio",
            tenant_id="om_budi",
            channel="whatsapp",
            user_phone="628123456789",
            user_name="Bapak Rudi",
            user_id="628123456789",
            metadata={"button_id": "btn_audio", "msg_type": "interactive"}
        )

        # Verify messages table was called
        mock_client.table.assert_any_call("messages")
        mock_client.table.assert_any_call("conversations")
        
        # Verify inserted payload normalization
        user_call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(user_call_args["sender"], "user")
        self.assertEqual(user_call_args["tenant_id"], "om-budi")
        self.assertEqual(user_call_args["channel"], "whatsapp")
        self.assertEqual(user_call_args["text"], "Halo Om Budi, minta link audio")
        self.assertEqual(user_call_args["user_phone"], "628123456789")
        self.assertEqual(user_call_args["user_name"], "Bapak Rudi")
        self.assertNotIn("payload", user_call_args)
        self.assertIsNotNone(user_call_args["conversation_id"])

        # Verify conversations upsert
        conv_call_args = mock_table.upsert.call_args[0][0]
        self.assertEqual(conv_call_args["tenant_id"], "om-budi")
        self.assertEqual(conv_call_args["phone_number"], "628123456789")

        # Test Bot Message
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            message_text="Bismillah, berikut link download audio...",
            tenant_id="boontrack_career",
            channel="whatsapp",
            user_phone="628123456789",
            user_name="Bapak Rudi",
            user_id="628123456789"
        )

        bot_call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(bot_call_args["sender"], "bot")
        self.assertEqual(bot_call_args["tenant_id"], "boontrack-career")
        self.assertEqual(bot_call_args["channel"], "whatsapp")
        self.assertEqual(bot_call_args["text"], "Bismillah, berikut link download audio...")

    def test_extract_meta_whatsapp_event_text(self):
        sample_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1268977686299719"},
                        "contacts": [{"profile": {"name": "Ahmad Dani"}, "wa_id": "62811112222"}],
                        "messages": [{
                            "from": "62811112222",
                            "type": "text",
                            "text": {"body": "Assalamualaikum"}
                        }]
                    }
                }]
            }]
        }
        res = extract_meta_whatsapp_event(sample_payload)
        self.assertTrue(res["is_message"])
        self.assertFalse(res["is_status"])
        self.assertEqual(res["from_phone"], "62811112222")
        self.assertEqual(res["contact_name"], "Ahmad Dani")
        self.assertEqual(res["phone_id"], "1268977686299719")
        self.assertEqual(res["msg_type"], "text")
        self.assertEqual(res["text"], "Assalamualaikum")

    def test_extract_meta_whatsapp_event_interactive_button(self):
        sample_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "1340866379104241"},
                        "contacts": [{"profile": {"name": "Siti Nurhaliza"}, "wa_id": "62833334444"}],
                        "messages": [{
                            "from": "62833334444",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {
                                    "id": "btn_rewrite",
                                    "title": "🚀 Ambil Rewrite"
                                }
                            }
                        }]
                    }
                }]
            }]
        }
        res = extract_meta_whatsapp_event(sample_payload)
        self.assertTrue(res["is_message"])
        self.assertEqual(res["button_id"], "btn_rewrite")
        self.assertEqual(res["text"], "🚀 Ambil Rewrite")

    def test_extract_meta_whatsapp_event_status(self):
        sample_status = {
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{"id": "wamid.123", "status": "delivered"}]
                    }
                }]
            }]
        }
        res = extract_meta_whatsapp_event(sample_status)
    def test_normalize_phone_number(self):
        from app.services.whatsapp_service import normalize_phone_number
        self.assertEqual(normalize_phone_number("+6281237450222"), "6281237450222")
        self.assertEqual(normalize_phone_number("6281237450222"), "6281237450222")
        self.assertEqual(normalize_phone_number("081237450222"), "6281237450222")
        self.assertEqual(normalize_phone_number("0081237450222"), "6281237450222")
        self.assertEqual(normalize_phone_number("+62 812-3745-0222"), "6281237450222")
        self.assertEqual(normalize_phone_number(""), "")
        self.assertEqual(normalize_phone_number(None), "")

    @patch("app.services.whatsapp_service.get_supabase")
    async def test_log_to_supabase_career(self, mock_get_supabase):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_upsert = MagicMock()

        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_insert
        mock_table.upsert.return_value = mock_upsert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "msg-career-123"}])
        mock_upsert.execute.return_value = MagicMock(data=[{"id": "conv-career-123"}])

        success = await log_to_supabase_messages(
            sender="user",
            text="Halo Career Assistant",
            tenant_id="boontrack-career",
            channel="whatsapp",
            user_phone="+6281237450222",
            user_name="Alldy Career",
            user_id="+6281237450222"
        )
        self.assertTrue(success)

        # Check payload
        call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(call_args["tenant_id"], "boontrack-career")
        self.assertEqual(call_args["tenant_slug"], "boontrack-career")
        self.assertEqual(call_args["user_phone"], "6281237450222")
        self.assertEqual(call_args["user_id"], "6281237450222")
        self.assertEqual(call_args["user_name"], "Alldy Career")
        self.assertEqual(call_args["sender"], "user")


if __name__ == "__main__":
    unittest.main()


