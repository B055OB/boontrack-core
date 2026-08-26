import io
import os
import unittest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

from app.utils.qris_generator import (
    crc16_ccitt,
    generate_dynamic_qris_payload,
    generate_qris_image_bytes
)
from app.routes.payment import (
    payment_router,
    test_dynamic_qris_aiohttp_handler
)

SAMPLE_STATIC_QRIS = (
    "00020101021126630016ID.CO.SHOPEE.WWW01189360091510265640750211102656407510303UME"
    "51440014ID.CO.QRIS.WWW0215ID10265640751030303UME5204549953033605802ID5909BoonTrack"
    "6007BANDUNG61054026362070703A016304CA14"
)


class TestQRISGenerator(unittest.TestCase):

    def setUp(self):
        os.environ["BOONTRACK_STATIC_QRIS"] = SAMPLE_STATIC_QRIS

    def test_crc16_ccitt_known_vectors(self):
        """Validasi perhitungan CRC16-CCITT poly 0x1021 init 0xFFFF."""
        # Test vector 1: Standard string "123456789" -> 0x29B1 in standard CCITT (or 4 hex chars)
        data1 = "123456789"
        crc1 = crc16_ccitt(data1)
        self.assertEqual(len(crc1), 4)
        self.assertEqual(crc1.upper(), crc1)

        # Test vector 2: Official standard QRIS EMVCo LinkAja/ASPI test vector
        emvco_sample = (
            "00020101021126580014ID.LINKAJA.WWW011893600911002230535302150000000000000000303UMI"
            "51440014ID.CO.QRIS.WWW0215ID10200210005030303UMI5204581253033605802ID5911Asep Sutisna"
            "6006Bogor 61051611562070703A016304"
        )
        calculated_crc = crc16_ccitt(emvco_sample)
        self.assertEqual(calculated_crc, "4599")

        # Test vector 3: Self-consistency of generated dynamic QRIS CRC
        dyn_payload = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, 50000)
        self.assertEqual(crc16_ccitt(dyn_payload[:-4]), dyn_payload[-4:])

    def test_generate_dynamic_qris_payload_conversion(self):
        """Validasi penyisipan Tag 54 dan rekalkulasi CRC16 tanpa mengubah Tag 01 (tetap 010211)."""
        amount = 25000
        dynamic_payload = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, amount)

        # 1. Validasi Tag 01 tetap 010211
        self.assertIn("010211", dynamic_payload)
        self.assertNotIn("010212", dynamic_payload)

        # 2. Validasi Tag 54 nominal (540525000)
        expected_tag54 = "540525000"
        self.assertIn(expected_tag54, dynamic_payload)

        # 3. Validasi posisi Tag 54 persis sebelum Tag 58 (5802ID)
        self.assertIn(f"{expected_tag54}5802ID", dynamic_payload)

        # 4. Validasi Header Tag 63 dan Checksum CRC16
        self.assertIn("6304", dynamic_payload)
        payload_body_with_6304 = dynamic_payload[:-4]
        expected_crc = crc16_ccitt(payload_body_with_6304)
        self.assertEqual(dynamic_payload[-4:], expected_crc)

    def test_generate_dynamic_qris_payload_various_amounts(self):
        """Validasi formatting Tag 54 untuk berbagai variasi nominal."""
        # 4 digit (Rp4.900) -> 54044900
        dyn_4900 = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, 4900)
        self.assertIn("540449005802ID", dyn_4900)

        # 5 digit (Rp10.000) -> 540510000
        dyn_10000 = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, 10000)
        self.assertIn("5405100005802ID", dyn_10000)

        # 6 digit (Rp125.000) -> 5406125000
        dyn_125000 = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, 125000)
        self.assertIn("54061250005802ID", dyn_125000)

    def test_generate_qris_image_bytes(self):
        """Validasi render QR code image ke bytes PNG."""
        dynamic_payload = generate_dynamic_qris_payload(SAMPLE_STATIC_QRIS, 25000)
        img_bytes = generate_qris_image_bytes(dynamic_payload)

        self.assertIsInstance(img_bytes, bytes)
        self.assertGreater(len(img_bytes), 200)

        # Validasi PNG signature header
        self.assertTrue(img_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Validasi bisa dibaca kembali oleh PIL
        image = Image.open(io.BytesIO(img_bytes))
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.width, 50)
        self.assertGreater(image.height, 50)

    def test_fastapi_dynamic_qris_endpoint(self):
        """Validasi endpoint FastAPI GET /api/v1/payment/qris/test/{amount}."""
        app = FastAPI()
        app.include_router(payment_router)

        client = TestClient(app)
        response = client.get("/api/v1/payment/qris/test/25000")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

        # Validasi gambar PNG yang dihasilkan
        img = Image.open(io.BytesIO(response.content))
        self.assertEqual(img.format, "PNG")


class TestQRISAioHTTP(AioHTTPTestCase):

    async def get_application(self):
        os.environ["BOONTRACK_STATIC_QRIS"] = SAMPLE_STATIC_QRIS
        app = web.Application()
        app.router.add_get("/api/v1/payment/qris/test/{amount}", test_dynamic_qris_aiohttp_handler)
        return app

    @unittest_run_loop
    async def test_aiohttp_dynamic_qris_endpoint(self):
        """Validasi endpoint aiohttp GET /api/v1/payment/qris/test/{amount}."""
        resp = await self.client.request("GET", "/api/v1/payment/qris/test/15000")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "image/png")
        body = await resp.read()
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
