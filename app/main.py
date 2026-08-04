async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['skill'] = update.message.text.strip()

    await update.message.reply_text("Sedang meracik dan menyusun draft CV ATS-friendly kamu... Tunggu sebentar ya! ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Prompt instruksi agar AI mencetak format persis sesuai contoh kamu
    prompt_final = (
        f"Tolong format data berikut menjadi CV ATS-Friendly profesional tanpa intro/outro. "
        f"Gunakan struktur persis seperti template berikut:\n\n"
        f"[NAMA LENGKAP DALAM HURUF KAPITAL]\n"
        f"[POSISI DILAMAR]\n"
        f"Kota, Indonesia | email@example.com | +62 8xx-xxxx-xxxx\n\n"
        f"RINGKASAN PROFIL\n"
        f"[Buat ringkasan profil profesional 3-4 kalimat padat yang menonjolkan kualifikasi]\n\n"
        f"PENGALAMAN KERJA\n"
        f"[Posisi] — [Nama Perusahaan/Organisasi]\n"
        f"[Periode] | [Lokasi]\n"
        f"• [Tulis pencapaian/tanggung jawab utama dengan kata kerja aksi]\n"
        f"• [Pencapaian kedua]\n\n"
        f"KEAHLIAN & KOMPETENSI\n"
        f"• [Kelompok Skill / Tools Utama]\n\n"
        f"PENDIDIKAN\n"
        f"[Nama Jurusan/Gelar] — [Nama Institusi/Sekolah]\n\n"
        f"Data Pengguna:\n"
        f"- Nama Lengkap: {context.user_data.get('nama')}\n"
        f"- Posisi Dilamar: {context.user_data.get('posisi')}\n"
        f"- Pendidikan Terakhir: {context.user_data.get('pendidikan')}\n"
        f"- Pengalaman Kerja/Organisasi: {context.user_data.get('pengalaman')}\n"
        f"- Keahlian / Skill: {context.user_data.get('skill')}"
    )

    try:
        res = await ai_gateway.generate(prompt=prompt_final)
        reply = res.text if hasattr(res, 'text') else str(res)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error generating CV: {e}")
        # Fallback format manual persis contoh jika AI Groq mengalami limit/timeout
        fallback_text = (
            f"**{str(context.user_data.get('nama')).upper()}**\n"
            f"**{context.user_data.get('posisi')}**\n"
            f"Bandung, Indonesia | email@example.com | +62 812-3456-7890\n\n"
            f"**RINGKASAN PROFIL**\n"
            f"Spesialis {context.user_data.get('posisi')} profesional dengan pengalaman teruji dalam mengelola operasional harian, "
            f"penerapan efisiensi alur kerja, serta didukung keahlian teknis yang kuat di bidangnya.\n\n"
            f"**PENGALAMAN KERJA**\n"
            f"{context.user_data.get('posisi')} — Perusahaan / Organisasi\n"
            f"2022 – Sekarang | Indonesia\n"
            f"• {context.user_data.get('pengalaman')}\n\n"
            f"**KEAHLIAN & KOMPETENSI**\n"
            f"• {context.user_data.get('skill')}\n\n"
            f"**PENDIDIKAN**\n"
            f"• {context.user_data.get('pendidikan')}\n"
        )
        await update.message.reply_text(fallback_text, parse_mode="Markdown")

    await update.message.reply_text(
        "\n✨ **CV kamu selesai dibuat!** Ketik /start untuk kembali ke menu utama.",
        parse_mode="Markdown"
    )

    return ConversationHandler.END
