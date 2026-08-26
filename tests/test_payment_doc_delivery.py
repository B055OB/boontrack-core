import io
import os
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from docx import Document

from app.core.server import create_web_app
from app.payments.matcher import (
    extract_clean_dana_amount,
    find_matching_unpaid_job,
    match_and_fulfill_payment,
    handle_admin_verify_command,
    handle_admin_retry_doc_command
)
from app.services.whatsapp_service import send_whatsapp_document, send_whatsapp_text
from app.services.document_engine import (
    deliver_completed_document_job,
    process_document_job_async,
    intake_document_job
)
from app.services.reconciliation_service import PAYMENT_INTENTS
from app.services.cv_state_engine import GLOBAL_USER_STATES


class TestPaymentDocDelivery(AioHTTPTestCase):

    async def get_application(self):
        return create_web_app()

    def setUp(self):
        super().setUp()
        GLOBAL_USER_STATES.clear()
        PAYMENT_INTENTS.clear()

    # ==========================================
    # 1. DANA Nominal Extraction Tests
    # ==========================================
    def test_extract_clean_dana_amount_variations(self):
        """Validasi ekstraksi nominal bersih dari berbagai format teks notifikasi DANA Bisnis."""
        # Format standard DANA notification
        self.assertEqual(extract_clean_dana_amount("DANA Masuk Rp5.083 dari Siti"), 5083)
        self.assertEqual(extract_clean_dana_amount("DANA: Berhasil menerima pembayaran QRIS sebesar Rp 5.083"), 5083)
        self.assertEqual(extract_clean_dana_amount("Mutasi Masuk DANA Bisnis Rp5.083,00"), 5083)
        self.assertEqual(extract_clean_dana_amount("Transfer masuk Rp5083"), 5083)
        self.assertEqual(extract_clean_dana_amount("Pembayaran QRIS Rp. 5.083 berhasil"), 5083)
        self.assertEqual(extract_clean_dana_amount("IDR 5,083.00 diterima"), 5083)
        
        # Dict payload
        self.assertEqual(extract_clean_dana_amount({"amount": 5083}), 5083)
        self.assertEqual(extract_clean_dana_amount({"nominal": "5.083"}), 5083)
        self.assertEqual(extract_clean_dana_amount({"raw_text": "DANA QRIS Masuk Rp5.083"}), 5083)

        # Non-matching
        self.assertEqual(extract_clean_dana_amount(""), 0)
        self.assertEqual(extract_clean_dana_amount("Pesan halo biasa tanpa nominal"), 0)

    # ==========================================
    # 2. Payment Matching & Document Delivery Flow
    # ==========================================
    @patch("app.payments.matcher.get_supabase")
    @patch("app.services.document_engine.get_supabase")
    @patch("app.services.document_engine.r2_storage_service.download_file", new_callable=AsyncMock)
    @patch("app.services.document_engine.send_whatsapp_document", new_callable=AsyncMock)
    @patch("app.services.document_engine.send_whatsapp_text", new_callable=AsyncMock)
    async def test_dana_callback_5083_matches_unpaid_job_and_delivers_docx(
        self,
        mock_send_text,
        mock_send_doc,
        mock_r2_download,
        mock_doc_engine_supabase,
        mock_matcher_supabase
    ):
        """Simulasi notifikasi pembayaran DANA Rp5.083 -> status job berubah ke PAID & file DOCX terkirim."""
        job_id = "job-uuid-5083-abc"
        user_phone = "6281299988877"

        # Mock Supabase document_jobs record
        mock_job_record = {
            "id": job_id,
            "tenant_id": "boontrack-career",
            "user_phone": user_phone,
            "price_amount": 5083,
            "payment_status": "UNPAID",
            "status": "COMPLETED",
            "task_type": "POLISH_REPHRASE",
            "result_storage_key": f"output/boontrack-career/{job_id}_result.docx"
        }

        # Mock query return with fluent builder
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        query_builder = MagicMock()
        query_builder.eq.return_value = query_builder
        query_builder.order.return_value = query_builder
        query_builder.limit.return_value = query_builder
        query_builder.execute.return_value = MagicMock(data=[mock_job_record])

        mock_table.select.return_value = query_builder
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[mock_job_record])

        mock_matcher_supabase.return_value = mock_client
        mock_doc_engine_supabase.return_value = mock_client

        # Mock binary docx
        fake_doc = Document()
        fake_doc.add_paragraph("Hasil Polish CV ATS")
        doc_buf = io.BytesIO()
        fake_doc.save(doc_buf)
        mock_r2_download.return_value = doc_buf.getvalue()

        # Mock send_whatsapp_document success
        mock_send_doc.return_value = {"messages": [{"id": "wamid.123"}]}
        mock_send_text.return_value = {"messages": [{"id": "wamid.456"}]}

        # Eksekusi matching pembayaran Rp5.083
        result = await match_and_fulfill_payment(
            amount=5083,
            raw_text="DANA: Masuk Rp5.083 dari User Budi",
            tenant_id="boontrack-career",
            source="dana_reader"
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["action"], "JOB_PAID_AND_DELIVERED")
        self.assertEqual(result["job_id"], job_id)
        self.assertEqual(result["user_phone"], user_phone)
        self.assertTrue(result["delivered"])

        # Verifikasi status di memory
        self.assertTrue(GLOBAL_USER_STATES[user_phone]["is_premium_paid"])
        self.assertEqual(GLOBAL_USER_STATES[user_phone]["tier"], "premium_unlocked")

        # Verifikasi attachment DOCX terkirim dengan parameter yang benar
        mock_send_doc.assert_called_once()
        call_kwargs = mock_send_doc.call_args[1]
        self.assertEqual(call_kwargs["to_phone"], user_phone)
        self.assertEqual(call_kwargs["filename"], "CV_Hasil_Polish.docx")
        self.assertEqual(call_kwargs["mime_type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertIn("CV Hasil Polish", call_kwargs["caption"])

        # Verifikasi teks konfirmasi juga terkirim
        mock_send_text.assert_called_once()
        self.assertIn("Dokumen Anda Selesai Diproses", mock_send_text.call_args[1]["text"])

    # ==========================================
    # 3. Webhook Listener Route Integration Test
    # ==========================================
    @unittest_run_loop
    @patch("app.routes.payment_webhook.match_and_fulfill_payment", new_callable=AsyncMock)
    async def test_webhook_listener_dana_5083(self, mock_fulfill):
        """Memvalidasi route POST /api/webhook/dana mengekstrak Rp5.083 dan memanggil matcher."""
        mock_fulfill.return_value = {
            "status": "SUCCESS",
            "action": "JOB_PAID_AND_DELIVERED",
            "job_id": "job-5083",
            "amount": 5083
        }

        payload = {
            "message": "DANA Bisnis: Masuk pembayaran QRIS Rp5.083",
            "package_name": "id.dana"
        }

        resp = await self.client.post("/api/webhook/dana", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["amount"], 5083)

        mock_fulfill.assert_called_once()
        self.assertEqual(mock_fulfill.call_args[1]["amount"], 5083)

    # ==========================================
    # 4. WhatsApp Service Attachment & Error Logging
    # ==========================================
    @patch("app.services.whatsapp_service.get_wa_credentials")
    @patch("httpx.AsyncClient.post")
    async def test_send_whatsapp_document_error_logging_on_failure(self, mock_http_post, mock_creds):
        """Memvalidasi penanganan dan logging jika WhatsApp Cloud API mengembalikan status non-200."""
        mock_creds.return_value = ("fake_token", "fake_phone_id", "v21.0")

        # Mock API returning 400 Bad Request
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = '{"error":{"message":"Invalid parameter: media_id"}}'
        mock_http_post.return_value = mock_resp

        # Harus mengembalikan None dan mencatat error tanpa raise exception tak tertangani
        res = await send_whatsapp_document(
            to_phone="628123456789",
            file_path_or_bytes=b"dummy docx bytes",
            filename="CV_Hasil_Polish.docx",
            caption="Test Caption"
        )
        self.assertIsNone(res)

    # ==========================================
    # 5. Admin Fallback Commands (/verify & /retry_doc)
    # ==========================================
    @patch("app.payments.matcher.match_and_fulfill_payment", new_callable=AsyncMock)
    async def test_admin_verify_command_success(self, mock_fulfill):
        """Memvalidasi eksekusi perintah admin /verify 5083."""
        mock_fulfill.return_value = {
            "status": "SUCCESS",
            "action": "JOB_PAID_AND_DELIVERED",
            "job_id": "job-5083-xyz",
            "user_phone": "62812345678"
        }

        reply = await handle_admin_verify_command("/verify 5083")
        self.assertIn("Verifikasi Manual Berhasil", reply)
        self.assertIn("5,083", reply)
        self.assertIn("job-5083-xyz", reply)

    @patch("app.services.document_engine.deliver_completed_document_job", new_callable=AsyncMock)
    async def test_admin_retry_doc_command_success(self, mock_deliver):
        """Memvalidasi eksekusi perintah admin /retry_doc <job_id>."""
        mock_deliver.return_value = True

        reply = await handle_admin_retry_doc_command("/retry_doc job-5083-xyz")
        self.assertIn("Pengiriman Ulang Berhasil", reply)
        self.assertIn("job-5083-xyz", reply)


if __name__ == "__main__":
    unittest.main()
