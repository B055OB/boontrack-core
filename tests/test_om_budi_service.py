import os
import unittest
from app.tenants.om_budi.service import om_budi_service
from app.core.messaging.templates import PENJELASAN_SEDEKAH_OM_BUDI, PENDAFTARAN_KELAS_OM_BUDI


class TestOmBudiService(unittest.IsolatedAsyncioTestCase):

    async def test_menu_utama_navigation(self):
        """Memvalidasi Menu Utama menyajikan Zoom Booster, Sedekah, dan Daftar Kelas Online."""
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
        """Memvalidasi pembaruan teks penjelasan sedekah sesuai copy resmi."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_penjelasan_sedekah"
        )
        reply = res.get("reply", "")
        self.assertEqual(res.get("type"), "buttons")
        self.assertIn("*SEDEKAH BERJAMAAH OM BUDI CHANNEL*", reply)
        self.assertIn("Bapak, Ibu, dan teman-teman, sedekah berjamaah adalah ajakan untuk bersama-sama berbagi", reply)
        self.assertIn("minimal Rp50.000 perbulan bapak ibu sudah masuk dalam Program Mulia ini.", reply)
        self.assertIn("Sedikit dari kita, jika dikumpulkan bersama, insyaAllah menjadi manfaat yang besar", reply)
        self.assertIn("Yang terpenting bukan jumlahnya, tetapi keikhlasan dan niat karena Allah.", reply)
        self.assertIn("Semoga menjadi amal kebaikan dan keberkahan untuk kita semua. Aamiin🙏", reply)

        buttons = res.get("buttons", [])
        btn_ids = [b["id"] for b in buttons]
        self.assertIn("btn_cara_sedekah", btn_ids)
        self.assertIn("btn_menu_utama", btn_ids)

    async def test_daftar_kelas_online_qris_image_and_caption(self):
        """Memvalidasi menu Daftar Kelas Online mengembalikan type image app/assets/qrisombudi.png dan caption persis."""
        test_triggers = [
            {"button_id": "menu_daftar_kelas", "text": ""},
            {"button_id": "btn_daftar_kelas", "text": ""},
            {"button_id": "menu_kelas_online", "text": ""},
            {"button_id": "btn_kelas_online", "text": ""},
            {"button_id": "", "text": "daftar kelas online"},
            {"button_id": "", "text": "kelas online"},
            {"button_id": "", "text": "pendaftaran kelas"}
        ]

        for trigger in test_triggers:
            with self.subTest(trigger=trigger):
                res = await om_budi_service.handle_incoming_message(
                    phone_number="081234567890",
                    message_text=trigger["text"],
                    button_id=trigger["button_id"]
                )
                self.assertEqual(res.get("type"), "image")
                img_path = res.get("image_path", "")
                self.assertTrue(img_path.endswith(("qrisombudi.png", "qrisombudi.jpg")))
                self.assertTrue(os.path.exists(img_path))

                reply = res.get("reply", "")
                self.assertIn("🎓 *PENDAFTARAN KELAS ONLINE OM BUDI*", reply)
                self.assertIn("Silakan scan kode QRIS di atas melalui aplikasi M-Banking atau E-Wallet", reply)
                self.assertIn("📌 *Merchant:* OM BUDI CHANNEL", reply)
                self.assertIn("🔢 *NMID:* ID1024333398336", reply)
                self.assertIn("Setelah proses transfer berhasil, silakan kirimkan foto/screenshot bukti pembayaran ke chat ini", reply)

                buttons = res.get("buttons", [])
                btn_ids = [b["id"] for b in buttons]
                self.assertIn("btn_upload_struk", btn_ids)
                self.assertIn("btn_menu_utama", btn_ids)

    async def test_sedekah_menu_options(self):
        """Memvalidasi menu Sedekah Berjamaah memuat opsi Penjelasan dan Cara Ikut."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="menu_sedekah_berjamaah"
        )
        self.assertEqual(res.get("type"), "buttons")
        buttons = res.get("buttons", [])
        btn_ids = [b["id"] for b in buttons]
        self.assertIn("btn_penjelasan_sedekah", btn_ids)
        self.assertIn("btn_cara_sedekah", btn_ids)
        self.assertIn("btn_menu_utama", btn_ids)

    async def test_cara_ikut_sedekah_rekening(self):
        """Memvalidasi informasi rekening dan opsi kirim bukti transfer."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_cara_sedekah"
        )
        self.assertEqual(res.get("type"), "buttons")
        reply = res.get("reply", "")
        self.assertIn("Bank Syariah Indonesia", reply)
        self.assertIn("Bank Mandiri", reply)
        buttons = res.get("buttons", [])
        btn_ids = [b["id"] for b in buttons]
        self.assertIn("btn_upload_struk", btn_ids)

    async def test_alumni_claim_updated_menu(self):
        """Memvalidasi klaim alumni menyajikan menu baru Daftar Kelas Online."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081299998888",
            message_text="aktifkan alumni om budi",
            user_name="Ibu Wahyu"
        )
        self.assertEqual(res.get("type"), "buttons")
        buttons = res.get("buttons", [])
        btn_ids = [b["id"] for b in buttons]
        self.assertIn("menu_daftar_kelas", btn_ids)
        self.assertIn("menu_zoom_booster", btn_ids)
        self.assertIn("menu_sedekah_berjamaah", btn_ids)


if __name__ == "__main__":
    unittest.main()
