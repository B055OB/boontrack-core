from app.services.qris_injector import generate_dynamic_qris

def build_whatsapp_invoice_message(
    tenant_name: str,
    customer_name: str,
    service_name: str,
    amount: int,
    bank_name: str | None,
    bank_account_number: str | None,
    bank_account_holder: str | None,
    static_qris: str | None
) -> tuple[str, str | None]:
    """
    Returns:
        tuple(text_message, dynamic_qris_string)
    """
    dynamic_qris = None
    if static_qris:
        dynamic_qris = generate_dynamic_qris(static_qris, amount)

    msg = f"Halo Kak *{customer_name}*, terima kasih sudah memesan layanan di *{tenant_name}*! 🙏\n\n"
    msg += f"📋 *Rincian Pesanan:*\n"
    msg += f"• Layanan: {service_name}\n"
    msg += f"• Total Tagihan: *Rp {amount:,}*\n\n"
    msg += f"💳 *Metode Pembayaran:*\n"

    if dynamic_qris:
        msg += f"1️⃣ *QRIS Otomatis:*\n"
        msg += f"Scan gambar QRIS di bawah ini melalui m-Banking / e-Wallet (BCA, Mandiri, GoPay, DANA, dll). Nominal sudah otomatis terkunci Rp {amount:,}.\n\n"

    if bank_name and bank_account_number:
        msg += f"2️⃣ *Transfer Bank Manual:*\n"
        msg += f"• Bank: *{bank_name}*\n"
        msg += f"• No. Rekening: *{bank_account_number}*\n"
        msg += f"• Atas Nama: *{bank_account_holder or tenant_name}*\n\n"

    msg += "Pembayaran Anda akan terverifikasi secara otomatis begitu transaksi berhasil. Terima kasih!"
    return msg, dynamic_qris