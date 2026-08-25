import os
import unittest
from app.tenants.om_budi.service import om_budi_service
from app.core.messaging.templates import (
    PENJELASAN_SEDEKAH_OM_BUDI, 
    PANDUAN_QRIS_OM_BUDI, 
    RINGKASAN_KELAS_ONLINE_OM_BUDI,
    CARA_IKUT_SEDEKAH_OM_BUDI
)


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

    async def test_daftar_kelas_online_flow_summary_and_options(self):
        """Memvalidasi menu Daftar Kelas Online menyajikan nominal Rp100.000 dan 2 pilihan pembayaran (QRIS & Bank)."""
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
                self.assertEqual(res.get("type"), "buttons")
                reply = res.get("reply", "")
                self.assertIn("Rp100.000", reply)
                self.assertIn("Investasi Kelas", reply)

                buttons = res.get("buttons", [])
                btn_ids = [b["id"] for b in buttons]
                btn_titles = [b["title"] for b in buttons]
                self.assertIn("btn_kelas_qris", btn_ids)
                self.assertIn("btn_kelas_bank", btn_ids)
                self.assertIn("QRIS", btn_titles)
                self.assertIn("Transfer Bank", btn_titles)

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

    async def test_cara_ikut_sedekah_payment_options(self):
        """Memvalidasi menu Cara Ikut Sedekah menyediakan opsi pembayaran QRIS dan Transfer Bank."""
        res = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_cara_sedekah"
        )
        self.assertEqual(res.get("type"), "buttons")
        reply = res.get("reply", "")
        self.assertIn("Rp50.000", reply)

        buttons = res.get("buttons", [])
        btn_ids = [b["id"] for b in buttons]
        btn_titles = [b["title"] for b in buttons]
        self.assertIn("btn_sedekah_qris", btn_ids)
        self.assertIn("btn_sedekah_bank", btn_ids)
        self.assertIn("QRIS", btn_titles)
        self.assertIn("Transfer Bank", btn_titles)

    async def test_qris_option_flow_and_gallery_guide(self):
        """Memvalidasi pengiriman QRIS menyertakan Public URL HTTPS dan panduan screenshot / upload galeri HP."""
        test_triggers = [
            {"button_id": "btn_kelas_qris", "text": ""},
            {"button_id": "btn_sedekah_qris", "text": ""},
            {"button_id": "", "text": "qris"},
            {"button_id": "", "text": "bayar qris"}
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

                # Validasi Public HTTPS URL untuk Meta Cloud API
                img_url = res.get("image_url") or res.get("image_link")
                self.assertTrue(img_url.startswith("https://") or img_url.startswith("http://"))
                self.assertTrue(img_url.endswith("qrisombudi.png"))
                self.assertEqual(res.get("image", {}).get("link"), img_url)

                # Validasi Teks Panduan Screenshot / Galeri
                caption = res.get("reply", "") or res.get("caption", "")
                self.assertIn("📌 *PANDUAN PEMBAYARAN QRIS*", caption)
                self.assertIn("Merchant: OM BUDI CHANNEL (NMID: ID1024333398336)", caption)
                self.assertIn("💡 *Jika membayar menggunakan HP yang sama:*", caption)
                self.assertIn("1. Screenshot / Simpan gambar QRIS di atas ke galeri HP Bapak/Ibu.", caption)
                self.assertIn("4. Pilih ikon *Upload Gambar dari Galeri / Ambil dari Foto*.", caption)
                self.assertIn("5. Pilih hasil screenshot QRIS tadi dan selesaikan pembayaran.", caption)
                self.assertIn("📸 Setelah transfer berhasil, silakan kirimkan foto/screenshot bukti pembayaran", caption)

                buttons = res.get("buttons", [])
                btn_ids = [b["id"] for b in buttons]
                self.assertIn("btn_upload_struk", btn_ids)
                self.assertIn("btn_menu_utama", btn_ids)

    async def test_transfer_bank_option_flow(self):
        """Memvalidasi opsi Transfer Bank menyajikan nomor rekening resmi, pemilik, dan nominal transfer."""
        # 1. Transfer Bank untuk Kelas Online
        res_kelas = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_kelas_bank"
        )
        self.assertEqual(res_kelas.get("type"), "buttons")
        reply_kelas = res_kelas.get("reply", "")
        self.assertIn("Rp100.000", reply_kelas)
        self.assertIn("7251759094", reply_kelas)
        self.assertIn("1320022006077", reply_kelas)
        self.assertIn("Budi Yulianto", reply_kelas)

        # 2. Transfer Bank untuk Sedekah
        res_sedekah = await om_budi_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="",
            button_id="btn_sedekah_bank"
        )
        self.assertEqual(res_sedekah.get("type"), "buttons")
        reply_sedekah = res_sedekah.get("reply", "")
        self.assertIn("7251759094", reply_sedekah)
        self.assertIn("1320022006077", reply_sedekah)
        self.assertIn("Budi Yulianto", reply_sedekah)

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

    async def test_send_wa_image_payload_structure_and_fallback(self):
        """Memvalidasi fungsi send_wa_image membentuk payload link HTTPS Meta API dan fallback ke text jika gagal."""
        from unittest.mock import patch, MagicMock, AsyncMock
        from app.routes.whatsapp_central import send_wa_image, send_wa_text

        # 1. Test Success Outbound Image Payload
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text.return_value = '{"messages": [{"id": "wamid.test"}]}'
            mock_post.return_value.__aenter__.return_value = mock_resp

            success = await send_wa_image(
                recipient_phone="628123456789",
                image_url_or_path="https://boontrack-core.up.railway.app/static/qrisombudi.png",
                caption=PANDUAN_QRIS_OM_BUDI,
                phone_id="1268977686299719"
            )
            self.assertTrue(success)

            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs["json"]
            self.assertEqual(payload["type"], "image")
            self.assertEqual(payload["image"]["link"], "https://boontrack-core.up.railway.app/static/qrisombudi.png")
            self.assertEqual(payload["image"]["caption"], PANDUAN_QRIS_OM_BUDI)

        # 2. Test Fallback to Text on Error
        with patch("aiohttp.ClientSession.post") as mock_post, \
             patch("app.routes.whatsapp_central.send_wa_text", new_callable=AsyncMock) as mock_send_text:
            mock_resp = AsyncMock()
            mock_resp.status = 400
            mock_resp.text.return_value = '{"error": {"message": "Invalid link URL"}}'
            mock_post.return_value.__aenter__.return_value = mock_resp

            success = await send_wa_image(
                recipient_phone="628123456789",
                image_url_or_path="app/assets/qrisombudi.png",
                caption=PANDUAN_QRIS_OM_BUDI,
                phone_id="1268977686299719"
            )
            self.assertFalse(success)
            # Pastikan fallback text terpanggil membawa NMID dan panduan
            mock_send_text.assert_called_once()
            called_caption = mock_send_text.call_args[0][1]
            self.assertIn("ID1024333398336", called_caption)


if __name__ == "__main__":
    unittest.main()
