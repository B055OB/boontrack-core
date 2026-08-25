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
                self.assertEqual(res.get("type"), "text", f"Expected type 'text' for query '{q}', got '{res.get('type')}'")
                self.assertNotIn("belum bisa menjawab", reply.lower(), f"Failed for query '{q}'")
                self.assertIn("drive.google.com", reply, f"Google Drive link missing for query '{q}'")
                self.assertIn("18GjQd8SMymV8kxfvOPodvIXNxlVLbhW9", reply)

    async def test_audio_brainwave_buttons(self):
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_audio_brainwave"
        )
        self.assertEqual(res.get("type"), "text")
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
                self.assertEqual(res.get("type"), "text", f"Expected type 'text' for query '{q}', got '{res.get('type')}'")
                reply = res.get("reply", "")
                self.assertNotIn("belum bisa menjawab", reply.lower(), f"Failed for query '{q}'")
                self.assertIn("Sholawat Jibril", reply)
                self.assertIn("drive.google.com", reply)

    async def test_menu_utama_navigation(self):
        """Memvalidasi tombol navigasi Menu Utama memuat menu baru Daftar Kelas Online."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_menu_utama",
            user_name="Bapak Rudi"
        )
        self.assertEqual(res.get("type"), "buttons")
        buttons = res.get("buttons", [])
        button_ids = [b["id"] for b in buttons]
        button_titles = [b["title"] for b in buttons]

        self.assertIn("menu_zoom_booster", button_ids)
        self.assertIn("menu_sedekah_berjamaah", button_ids)
        self.assertIn("menu_daftar_kelas", button_ids)
        self.assertIn("Daftar Kelas Online", button_titles)
        self.assertNotIn("menu_belajar_materi", button_ids)

    async def test_penjelasan_sedekah_exact_copy(self):
        """Memvalidasi pembaruan teks penjelasan sedekah sesuai spesifikasi persis."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_penjelasan_sedekah"
        )
        reply = res.get("reply", "")
        self.assertIn("*SEDEKAH BERJAMAAH OM BUDI CHANNEL*", reply)
        self.assertIn("minimal Rp50.000 perbulan bapak ibu sudah masuk dalam Program Mulia ini.", reply)
        self.assertIn("Sedikit dari kita, jika dikumpulkan bersama, insyaAllah menjadi manfaat yang besar", reply)
        self.assertIn("Yang terpenting bukan jumlahnya, tetapi keikhlasan dan niat karena Allah.", reply)
        self.assertIn("Semoga menjadi amal kebaikan dan keberkahan untuk kita semua. Aamiin🙏", reply)

    async def test_daftar_kelas_online_qris_image(self):
        """Memvalidasi menu Daftar Kelas Online mengembalikan gambar QRIS dan caption resmi."""
        test_triggers = [
            {"button_id": "menu_daftar_kelas", "text": ""},
            {"button_id": "btn_daftar_kelas", "text": ""},
            {"button_id": "", "text": "daftar kelas online"},
            {"button_id": "", "text": "kelas online"}
        ]

        for trigger in test_triggers:
            with self.subTest(trigger=trigger):
                res = await om_budi_service.handle_incoming_message(
                    phone_number="081234567890",
                    message_text=trigger["text"],
                    button_id=trigger["button_id"]
                )
                self.assertEqual(res.get("type"), "image")
                self.assertTrue(res.get("image_path").endswith(("qrisombudi.png", "qrisombudi.jpg")))
                reply = res.get("reply", "")
                self.assertIn("🎓 *PENDAFTARAN KELAS ONLINE OM BUDI*", reply)
                self.assertIn("📌 *Merchant:* OM BUDI CHANNEL", reply)
                self.assertIn("🔢 *NMID:* ID1024333398336", reply)
                self.assertIn("Setelah proses transfer berhasil, silakan kirimkan foto/screenshot bukti pembayaran", reply)

if __name__ == "__main__":
    unittest.main()

