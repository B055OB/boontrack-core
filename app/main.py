import io
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['skill'] = update.message.text.strip()

    await update.message.reply_text("Sedang meracik & membuatkan file Dokumen Word (.docx) CV kamu... Tunggu sebentar ya! ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")

    nama = str(context.user_data.get('nama', 'Pengguna')).strip()
    posisi = str(context.user_data.get('posisi', 'Professional')).strip()
    pendidikan = str(context.user_data.get('pendidikan', '-')).strip()
    pengalaman = str(context.user_data.get('pengalaman', '-')).strip()
    skill = str(context.user_data.get('skill', '-')).strip()

    # 1. Minta AI menyusun poin-poin ringkasan & pencapaian kerja profesional
    prompt_ai = (
        f"Buatkan ringkasan profil profesional (3 kalimat) dan 3 poin pencapaian kerja utama dengan kata kerja aksi "
        f"berdasarkan data berikut:\n"
        f"- Nama: {nama}\n"
        f"- Posisi Dilamar: {posisi}\n"
        f"- Pendidikan: {pendidikan}\n"
        f"- Pengalaman: {pengalaman}\n"
        f"- Skill: {skill}\n\n"
        f"Berikan jawaban singkat dan padat."
    )

    try:
        res = await ai_gateway.generate(prompt=prompt_ai)
        ai_summary = res.text if hasattr(res, 'text') else str(res)
    except Exception:
        ai_summary = f"Spesialis {posisi} berdedikasi dengan latar belakang {pendidikan} yang siap memberikan kontribusi maksimal."

    # 2. Buat File Word (.docx) menggunakan python-docx
    doc = Document()

    # Set Margin Halaman
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # --- HEADER NAMA & POSISI ---
    p_name = doc.add_paragraph()
    run_name = p_name.add_run(nama.upper())
    run_name.bold = True
    run_name.font.size = Pt(18)
    run_name.font.name = 'Calibri'
    p_name.alignment = WD_ALIGN_PARAGRAPH.LEFT

    p_pos = doc.add_paragraph()
    run_pos = p_pos.add_run(posisi)
    run_pos.bold = True
    run_pos.font.size = Pt(12)
    run_pos.font.color.rgb = RGBColor(80, 80, 80)
    run_pos.font.name = 'Calibri'

    # Kontak Info
    p_contact = doc.add_paragraph("Indonesia | email@example.com | +62 8xx-xxxx-xxxx")
    p_contact.runs[0].font.size = Pt(9.5)
    p_contact.runs[0].font.color.rgb = RGBColor(100, 100, 100)

    # Helper Function untuk Judul Seksi
    def add_section_header(title):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0, 51, 102)

    # --- RINGKASAN PROFIL ---
    add_section_header("Ringkasan Profil")
    p_prof = doc.add_paragraph(ai_summary)
    p_prof.runs[0].font.size = Pt(10.5)

    # --- PENGALAMAN KERJA ---
    add_section_header("Pengalaman Kerja")
    p_exp_head = doc.add_paragraph()
    r_exp1 = p_exp_head.add_run(f"{posisi} — Perusahaan / Organisasi\n")
    r_exp1.bold = True
    r_exp1.font.size = Pt(10.5)
    r_exp2 = p_exp_head.add_run("2022 – Sekarang | Indonesia")
    r_exp2.font.size = Pt(9.5)
    r_exp2.font.italic = True

    p_exp_detail = doc.add_paragraph(style='List Bullet')
    p_exp_detail.add_run(pengalaman).font.size = Pt(10)

    # --- KEAHLIAN & KOMPETENSI ---
    add_section_header("Keahlian & Kompetensi")
    p_skill = doc.add_paragraph(style='List Bullet')
    p_skill.add_run(skill).font.size = Pt(10)

    # --- PENDIDIKAN ---
    add_section_header("Pendidikan")
    p_edu = doc.add_paragraph()
    r_edu = p_edu.add_run(pendidikan)
    r_edu.bold = True
    r_edu.font.size = Pt(10.5)

    # 3. Simpan Dokumen ke Memory Stream (BytesIO)
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    filename = f"CV_ATS_{nama.replace(' ', '_')}.docx"

    # 4. Kirim Dokumen ke Chat Telegram
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=file_stream,
        filename=filename,
        caption=f"📄 **CV ATS-Friendly ({nama}) siap di-download dan diedit!**\n\nKetik /start jika ingin membuat CV lainnya."
    )

    return ConversationHandler.END
