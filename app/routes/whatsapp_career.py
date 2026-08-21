# 3. TRIGGER REWRITE (Uji Coba Terkunci)
    if button_id == "btn_rewrite" or user_text_clean in ["rewrite", "perbaiki", "mau rewrite", "ambil rewrite", "🚀 ambil rewrite"]:
        await track_event(sender_wa_id, "rewrite_clicked")

        exact_amount = 25000
        user_session["mode"] = "awaiting_rewrite_payment"
        user_session["active_payment"] = {"amount": exact_amount, "product": "career-rewrite-25k"}

        caption_text = (
            "📱 *PEMBAYARAN PREMIUM CV REWRITE*\n\n"
            "🏷️ *Nominal:* Rp25.000 *(Uji Coba Terkunci Otomatis)*\n\n"
            "1. Scan *QRIS diatas* pakai BCA Mobile / myBCA / GoPay / DANA / OVO / ShopeePay.\n"
            "2. Cek apakah nominal Rp25.000 langsung terkunci otomatis di layar konfirmasi Anda.\n"
            "3. Setelah berhasil, sistem akan memproses versi CV terbaik Anda!"
        )

        from app.services.qris_engine import inject_dynamic_amount_bca, render_qris_image
        
        # String dasar QRIS BCA Uwinfly
        bca_base_payload = "00020101021126590014ID.CO.BCA.WWW01189360001400147816300208102214735204581253033605802ID5915UWINFLY BANDUNG6007BANDUNG6304"
        locked_payload = inject_dynamic_amount_bca(bca_base_payload, exact_amount)
        qr_bytes = render_qris_image(locked_payload)

        await send_whatsapp_image(sender_wa_id, image_path_or_bytes=qr_bytes.getvalue(), caption=caption_text)
        return web.Response(text="EVENT_RECEIVED", status=200)