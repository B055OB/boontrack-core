async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    save_or_update_cv_field(user_id, skill=clean_input(update.message.text))

    await update.message.reply_text("Sedang meracik & mengisikan file Dokumen Word (.docx) CV kamu... Tunggu sebentar ya! ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")

    try:
        # Fetch Data dari Database PostgreSQL
        data = get_user_cv_data(user_id)

        nama = (data.nama if data.nama and data.nama != '-' else "KANDIDAT").upper()
        posisi = data.posisi if data.posisi and data.posisi != '-' else "Professional"
        email = data.email if data.email and data.email != '-' else "email@example.com"
        phone = data.phone_number if data.phone_number and data.phone_number != '-' else "+62 8xx-xxxx-xxxx"
        domisili = data.domisili if data.domisili and data.domisili != '-' else "Indonesia"
        linkedin = data.linkedin_url if data.linkedin_url and data.linkedin_url != '-' else ""
        pendidikan = data.pendidikan if data.pendidikan and data.pendidikan != '-' else "Tidak dicantumkan"
        pengalaman = data.pengalaman if data.pengalaman and data.pengalaman != '-' else "Belum ada pengalaman formal"
        pencapaian = data.pencapaian if data.pencapaian and data.pencapaian != '-' else ""
        skill = data.skill if data.skill and data.skill != '-' else "Kemampuan komunikasi & kerja tim"

        # Rancang Dokumen Word (.docx) ATS Standard
        doc = Document()
        for section in doc.sections:
            section.top_margin = Inches(0.8)
            section.bottom_margin = Inches(0.8)
            section.left_margin = Inches(0.8)
            section.right_margin = Inches(0.8)

        # --- HEADER NAMA & KONTAK ---
        p_name = doc.add_paragraph()
        r_name = p_name.add_run(nama)
        r_name.bold = True
        r_name.font.size = Pt(18)
        r_name.font.name = 'Calibri'

        p_pos = doc.add_paragraph()
        r_pos = p_pos.add_run(posisi)
        r_pos.bold = True
        r_pos.font.size = Pt(12)
        r_pos.font.color.rgb = RGBColor(80, 80, 80)

        contact_parts = [domisili, email, phone]
        if linkedin:
            contact_parts.append(linkedin)

        p_contact = doc.add_paragraph(" | ".join(contact_parts))
        p_contact.runs[0].font.size = Pt(9.5)
        p_contact.runs[0].font.color.rgb = RGBColor(100, 100, 100)

        def add_section_header(title):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(title.upper())
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0, 51, 102)

        # 1. Ringkasan Profil
        add_section_header("Ringkasan Profil")
        doc.add_paragraph(
            f"Profesional berdedikasi di bidang {posisi} berdomisili di {domisili}. "
            f"Didukung latar belakang pendidikan dari {pendidikan} serta keahlian utama di bidang {skill}. "
            f"Siap memberikan kontribusi positif, cepat beradaptasi, dan berorientasi pada hasil."
        )

        # 2. Pengalaman Kerja
        add_section_header("Pengalaman Kerja")
        p_exp = doc.add_paragraph()
        r_exp = p_exp.add_run(f"{posisi} — Perusahaan / Organisasi\n")
        r_exp.bold = True
        p_exp_detail = doc.add_paragraph(style='List Bullet')
        p_exp_detail.add_run(pengalaman)

        # 3. Pencapaian (Cetak Jika Ada)
        if pencapaian:
            add_section_header("Pencapaian & Proyek Utama")
            p_ach = doc.add_paragraph(style='List Bullet')
            p_ach.add_run(pencapaian)

        # 4. Keahlian & Kompetensi
        add_section_header("Keahlian & Kompetensi")
        p_sk = doc.add_paragraph(style='List Bullet')
        p_sk.add_run(skill)

        # 5. Pendidikan
        add_section_header("Pendidikan")
        p_edu = doc.add_paragraph(style='List Bullet')
        p_edu.add_run(pendidikan)

        # Convert ke Stream & Kirim File
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        filename = f"CV_ATS_{nama.replace(' ', '_')}.docx"

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_stream,
            filename=filename,
            caption=f"📄 **CV ATS-Friendly ({nama}) berhasil dibuat & tersimpan di Database!**\n\nSilakan di-download. Ketik /start untuk membuat baru."
        )
    except Exception as e:
        logger.error(f"Error generating Word CV: {e}")
        await update.message.reply_text("Terjadi kendala saat menyusun dokumen Word. Silakan coba lagi dengan /start.")

    return ConversationHandler.END
