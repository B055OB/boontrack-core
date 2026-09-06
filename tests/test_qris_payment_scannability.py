import pytest
import io
import urllib.parse
from PIL import Image
from app.utils.qris_generator import (
    get_dynamic_qris_string,
    render_qris_bytes,
    get_quickchart_qr_url,
    crc16_ccitt,
    STANDARD_MASTER_QRIS,
)
from app.services.whatsapp_service import (
    generate_cart_checkout_response,
    generate_fast_track_checkout_response,
)
from app.services.xendit_service import xendit_service


def parse_emvco_tlv(payload: str):
    """Utility parser to check EMVCo TLV tags."""
    i = 0
    tags = {}
    while i < len(payload):
        tag = payload[i:i+2]
        length = int(payload[i+2:i+4])
        val = payload[i+4:i+4+length]
        tags[tag] = val
        i = i + 4 + length
    return tags


def test_qris_emvco_structure_and_tags():
    amount = 175000
    invoice_id = "INV-TEST-001"
    qris_payload = get_dynamic_qris_string(amount=amount, invoice_id=invoice_id)

    # 1. Must start with 000201
    assert qris_payload.startswith("000201")

    # 2. Parse TLV tags
    tags = parse_emvco_tlv(qris_payload)

    # Tag 00: Format Indicator (01)
    assert tags.get("00") == "01"

    # Tag 01: Point of Initiation Method (12 = Dynamic QRIS)
    assert tags.get("01") == "12"

    # Tag 52: Merchant Category Code (7372)
    assert tags.get("52") == "7372"

    # Tag 53: Currency (360 = IDR ISO 4217)
    assert tags.get("53") == "360"

    # Tag 54: Transaction Amount
    assert tags.get("54") == str(amount)

    # Tag 58: Country Code (ID)
    assert tags.get("58") == "ID"

    # Tag 59: Merchant Name
    assert tags.get("59") == "BoonTrack"

    # Tag 62: Additional Data (Invoice Reference)
    assert "62" in tags
    assert invoice_id in tags["62"]

    # Tag 63: CRC16 Checksum
    assert "63" in tags
    calculated_crc = crc16_ccitt(qris_payload[:-4])
    assert tags["63"] == calculated_crc


def test_qris_image_generator_parameters():
    amount = 99000
    payload = get_dynamic_qris_string(amount=amount)
    png_bytes = render_qris_bytes(payload, box_size=10, border=4)

    assert png_bytes is not None
    assert len(png_bytes) > 500

    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"

    # Verify high resolution (>= 500x500 px) for sharp scanning
    width, height = img.size
    assert width >= 500, f"Width {width} is below 500 px minimum"
    assert height >= 500, f"Height {height} is below 500 px minimum"


@pytest.mark.asyncio
async def test_xendit_service_overrides_sandbox_dummy_string():
    # Even if Xendit API returns 'some-random-qr-string', xendit_service must override it with valid EMVCo
    res = await xendit_service.create_qris_invoice("onlineboost", 150000, "Masterclass FB Ads")
    qr_string = res.get("qr_string", "")

    assert qr_string.startswith("000201")
    assert "5303360" in qr_string
    assert "5406150000" in qr_string
    assert "5802ID" in qr_string
    assert "some-random-qr-string" not in qr_string

    # QR Code URL must use high-res URL with size >= 500
    qr_url = res.get("qr_code_url", "")
    assert ("api.qrserver.com" in qr_url or "quickchart.io/qr" in qr_url)
    assert "size=600" in qr_url or "size=500" in qr_url


@pytest.mark.asyncio
async def test_checkout_responses_include_billing_details_and_web_link():
    phone = "6281234567890"

    # Test fast track checkout response
    caption, invoice, qr_bytes = await generate_fast_track_checkout_response(
        tenant_slug="onlineboost",
        from_phone=phone,
        contact_name="Budi",
    )

    # 1. Non-empty high-res PNG bytes
    assert len(qr_bytes) > 500
    img = Image.open(io.BytesIO(qr_bytes))
    assert img.format == "PNG"
    assert img.size[0] >= 500

    # 2. Caption details
    assert "Total:" in caption
    assert "No. Invoice / Kode Bayar:" in caption
    assert "Link Pembayaran Web Alternatif:" in caption
    assert "String Kode QRIS (Copy Manual):" in caption
    assert invoice.get("external_id") in caption
    assert invoice.get("qr_string") in caption
    assert "pay/" in caption

    # Test cart checkout response
    cart_caption, cart_inv, cart_qr_bytes = await generate_cart_checkout_response(
        tenant_slug="onlineboost",
        from_phone=phone,
        contact_name="Budi",
    )
    assert len(cart_qr_bytes) > 500
    assert "Total:" in cart_caption
    assert "Link Pembayaran Web Alternatif:" in cart_caption
    assert cart_inv.get("qr_string").startswith("000201")
