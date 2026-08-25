import unittest
import asyncio
from app.tenants.om_budi.service import om_budi_service

class TestOmBudiAudioAndRiyadhoh(unittest.IsolatedAsyncioTestCase):

    async def test_audio_brainwave_direct_keywords(self):
        test_queries = [
            "minta link audio brainwave",
            "link audio",
            "download audio riyadhoh",
            "kirim file audio om budi",
            "suara brainwave",
            "audio meditasi syukur",
            "audio terapi rezeki",
            "file mp3 brainwave",
            "putar audio quantum ikhlas"
        ]
        
        for q in test_queries:
            with self.subTest(query=q):
                res = await om_budi_service.handle_incoming_message(
                    phone_number="081234567890",
                    message_text=q,
                    user_name="Bapak Ahmad"
                )
                reply = res.get("reply", "")
                self.assertNotIn("belum bisa menjawab", reply.lower(), f"Failed for query '{q}'")
                self.assertIn("drive.google.com", reply, f"Google Drive link missing for query '{q}'")
                self.assertIn("18GjQd8SMymV8kxfvOPodvIXNxlVLbhW9", reply)

    async def test_audio_brainwave_buttons(self):
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_audio_brainwave"
        )
        reply = res.get("reply", "")
        self.assertIn("drive.google.com", reply)
        self.assertIn("PANTANGAN PENTING", reply)

    async def test_materi_riyadhoh_keywords(self):
        test_queries = [
            "materi riyadhoh",
            "panduan riyadhoh",
            "modul riyadhoh",
            "download riyadhoh",
            "jadwal riyadhoh"
        ]

        for q in test_queries:
            with self.subTest(query=q):
                res = await om_budi_service.handle_incoming_message(
                    phone_number="081234567890",
                    message_text=q,
                    user_name="Ibu Siti"
                )
                reply = res.get("reply", "")
                self.assertNotIn("belum bisa menjawab", reply.lower(), f"Failed for query '{q}'")
                self.assertIn("Sholawat Jibril", reply)
                self.assertIn("drive.google.com", reply)

if __name__ == "__main__":
    unittest.main()
