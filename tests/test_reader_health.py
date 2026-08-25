import io
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from pypdf import PdfWriter
from docx import Document

from app.services.document_parser_service import extract_text_from_bytes, parse_cv_document
from app.services.receipt_ocr_service import analyze_receipt_image, parse_receipt_image
from app.reader.router import pair_device_handler, refresh_token_handler, revoke_device_handler
from app.core.server import create_web_app


def create_sample_pdf_bytes(text_content: str = "Curriculum Vitae\nNama: Budi Santoso\nKeahlian: Python, FastAPI, PostgreSQL") -> bytes:
    """Helper untuk membuat file PDF valid di memori menggunakan pypdf."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    # pypdf can create blank page or write stream; we write to stream
    output_stream = io.BytesIO()
    writer.write(output_stream)
    return output_stream.getvalue()


def create_sample_docx_bytes(text_content: str = "Curriculum Vitae\nNama: Budi Santoso\nKeahlian: Python, FastAPI, PostgreSQL") -> bytes:
    """Helper untuk membuat file DOCX valid di memori menggunakan python-docx."""
    doc = Document()
    for line in text_content.split("\n"):
        doc.add_paragraph(line)
    output_stream = io.BytesIO()
    doc.save(output_stream)
    return output_stream.getvalue()


class TestReaderEngineHealth(AioHTTPTestCase):

    async def get_application(self):
        return create_web_app()

    def test_document_parser_docx_extraction(self):
        """Memvalidasi modul parsing dokumen DOCX."""
        sample_text = "Curriculum Vitae\nNama: Siti Aminah\nPengalaman: 5 Tahun Software Engineer"
        docx_bytes = create_sample_docx_bytes(sample_text)
        
        extracted = extract_text_from_bytes(docx_bytes, "cv_siti.docx")
        self.assertIn("Curriculum Vitae", extracted)
        self.assertIn("Siti Aminah", extracted)
        self.assertIn("Software Engineer", extracted)

    def test_document_parser_unsupported_format(self):
        """Memvalidasi handling format tidak didukung tanpa crash."""
        raw_bytes = b"dummy content"
        extracted = extract_text_from_bytes(raw_bytes, "file.exe")
        self.assertEqual(extracted, "")

    @unittest_run_loop
    async def test_receipt_ocr_engine_fallback_and_parsing(self):
        """Memvalidasi pipeline Vision OCR struk QRIS / transfer bank."""
        dummy_img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        res = await analyze_receipt_image(dummy_img_bytes, "image/png")
        
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("is_valid_receipt") or res.get("is_transfer_receipt"))
        self.assertGreater(res.get("amount") or res.get("nominal", 0), 0)

    @unittest_run_loop
    async def test_device_pairing_handler_success(self):
        """Memvalidasi endpoint Device Pairing Reader (/api/v1/devices/pair)."""
        payload = {
            "activation_code": "ACT-READER-2026",
            "device_uuid": "dev-uuid-999-abc",
            "device_name": "BoonTrack POS Terminal",
            "platform": "ANDROID",
            "app_version": "2.1.0"
        }
        resp = await self.client.post("/api/v1/devices/pair", json=payload)
        self.assertEqual(resp.status, 200)
        
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("device_id", data)
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data.get("device_name"), "BoonTrack POS Terminal")

    @unittest_run_loop
    async def test_device_pairing_handler_missing_fields(self):
        """Memvalidasi validasi input pada device pairing handler."""
        payload = {"device_name": "Incomplete Device"}
        resp = await self.client.post("/api/v1/devices/pair", json=payload)
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_device_refresh_token_handler(self):
        """Memvalidasi endpoint Refresh Token Reader (/api/v1/devices/refresh)."""
        resp = await self.client.post("/api/v1/devices/refresh", json={})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertTrue(data.get("access_token", "").startswith("bt_at_"))

    @unittest_run_loop
    async def test_device_revoke_handler(self):
        """Memvalidasi endpoint Revoke Device Reader (/api/v1/devices/revoke)."""
        resp = await self.client.post("/api/v1/devices/revoke", json={})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")


if __name__ == "__main__":
    unittest.main()
