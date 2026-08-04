import os
import asyncio
from aiogram import Bot, Dispatcher, executor, types
import psycopg2
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ==============================================================
# CONFIG & INITIALIZATION
# ==============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DB_HOST = os.getenv("POSTGRES_HOST", "boontrack_postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "boontrack_db")
DB_USER = os.getenv("POSTGRES_USER", "boontrack_user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "boontrack_pass")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

user_sessions = {}

THANK_YOU_WORDS = [
    "terima kasih", "terimakasih", "makasih", "thanks", "thank you",
    "suwun", "matur nuhun", "hatur nuhun", "arigato", "tengkiu", "tq"
]

# ==============================================================
# DATABASE FUNCTIONS
# ==============================================================
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_cv_data (
            telegram_id BIGINT PRIMARY KEY,
            nama TEXT,
            email TEXT,
            phone_number TEXT,
            domisili TEXT,
            linkedin_url TEXT,
            posisi TEXT,
            pendidikan TEXT,
            pengalaman TEXT,
            pencapaian TEXT,
            skill TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_cv_to_db(user_id, data):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_cv_data (
            telegram_id, nama, email, phone_number, domisili,
            linkedin_url, posisi, pendidikan, pengalaman, pencapaian, skill, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (telegram_id) DO UPDATE SET
            nama = EXCLUDED.nama,
            email = EXCLUDED.email,
            phone_number = EXCLUDED.phone_number,
            domisili = EXCLUDED.domisili,
            linkedin_url = EXCLUDED.linkedin_url,
            posisi = EXCLUDED.posisi,
            pendidikan = EXCLUDED.pendidikan,
            pengalaman = EXCLUDED.pengalaman,
            pencapaian = EXCLUDED.pencapaian,
            skill = EXCLUDED.skill,
            updated_at = NOW();
    """, (
        user_id,
        data.get(1, ''),
        data.get(2, ''),
        data.get(3, ''),
        data.get(4, ''),
        data.get(5, ''),
        data.get(6, ''),
        data.get(7, ''),
        data.get(8, ''),
        data.get(9, ''),
        data.get(10, '')
    ))
    conn.commit()
    cur.close()
    conn.close()

# ==============================================================
# WORD DOCUMENT GENERATOR (ATS FRIENDLY)
# ==============================================================
def create_cv_docx(data, file_path):
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    p_name = doc.add_paragraph()
    p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_name = p_name.add_run(data.get(1, 'NAMA LENGKAP').upper())
    run_name.bold = True
    run_name.font.size = Pt(18)
    run_name.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    p_target = doc.add_paragraph()
    p_target.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_target = p_target.add_run(data.get(6, 'Target Posisi').upper())
    run_target.bold = True
    run_target.font.size = Pt(12)

    kontak_parts = [
        data.get(4, ''),
        data.get(3, ''),
        data.get(2, ''),
        data.get(5, '')
    ]
    kontak_str = " | ".join([k for k in kontak_parts if k and k != '-'])
    
    p_contact = doc.add_paragraph()
    p_contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_contact = p_contact.add_run(kontak_str)
    run_contact.font.size = Pt(9.5)

    doc.add_paragraph()

    def add_section_heading(title):
        p = doc.add_paragraph()
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)

    if data.get(7) and data.get(7) != '-':
        add_section_heading("Pendidikan")
        p_edu = doc.add_paragraph(data.get(7))
        p_edu.paragraph_format.space_after = Pt(6)

    if data.get(8) and data.get(8) != '-':
        add_section_heading("Pengalaman Kerja & Organisasi")
        p_exp = doc.add_paragraph(data.get(8))
        p_exp.paragraph_format.space_after = Pt(6)

    if data.get(9) and data.get(9) != '-':
        add_section_heading("Pencapaian Utama & Project")
        p_ach = doc.add_paragraph(data.get(9))
        p_ach.paragraph_format.space_after = Pt(6)

    if data.get(10) and data.get(10) != '-':
        add_section_heading("Keahlian & Sertifikasi")
        p_skill = doc.add_paragraph(data.get(10))
        p_skill.paragraph_format.space_after = Pt(6)

    doc.save(file_path)

# ==============================================================
# TELEGRAM BOT HANDLERS
# ==============================================================
STEP_QUESTIONS = {
    1: "📌 **Step 1/10:** Siapa Nama Lengkap kamu?",
    2: "📌 **Step 2/10:** Masukkan **Alamat Email** kamu:",
    3: "📌 **Step 3/10:** Masukkan **Nomor WhatsApp / HP** kamu:",
    4: "📌 **Step 4/10:** Masukkan **Domisili Kota** tempat tinggal kamu saat ini:",
    5: "📌 **Step 5/10:** Masukkan **URL LinkedIn** kamu *(Ketik `-` jika tidak ada)*:",
    6: "📌 **Step 6/10:** Masukkan **Posisi / Jabatan Pekerjaan** yang ingin kamu lamar:",
    7: "📌 **Step 7/10:** Masukkan **Riwayat Pendidikan** (Jurusan, Universitas/Sekolah, Tahun Lulus):",
    8: "📌 **Step 8/10:** Masukkan **Pengalaman Kerja / Organisasi** (Perusahaan, Posisi, Tahun, & Detail Deskripsi Singkat):",
    9: "📌 **Step 9/10:** Masukkan **Pencapaian Utama / Project** yang pernah dikerjakan *(Ketik `-` jika tidak ada)*:",
    10: "📌 **Step 10/10:** Masukkan **Skill / Software / Sertifikasi** yang kamu kuasai:"
}

@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    text_lower = text.lower()

    if text == "/start":
        user_sessions[user_id] = {"step": 1, "data": {}}
        
        start_text = (
            "🚀 **PEMBUATAN CV ATS FRIENDLY STARTED**\n\n"
            "Halo! Saya akan membantu membuatkan CV ATS-Friendly kamu secara otomatis.\n"
            "Proses ini terdiri dari **4 Kelompok Data Utama**:\n"
            "1️⃣ **Data Pribadi** (Nama, Email, HP, Domisili)\n"
            "2️⃣ **Profil & Posisi** (Posisi Dilamar, LinkedIn)\n"
            "3️⃣ **Riwayat Pendidikan & Pengalaman**\n"
            "4️⃣ **Pencapaian & Skill**\n\n"
            "-----------------------------------\n"
            f"{STEP_QUESTIONS[1]}"
        )
        await message.answer(start_text, parse_mode="Markdown")
        return

    session = user_sessions.get(user_id)

    if not session or session.get("step") is None:
        if any(word in text_lower for word in THANK_YOU_WORDS):
            return
        
        await message.answer("Ketik **/start** jika ingin membuat CV baru lagi ya! 😊", parse_mode="Markdown")
        return

    current_step = session["step"]
    session["data"][current_step] = text

    if current_step < 10:
        next_step = current_step + 1
        session["step"] = next_step
        await message.answer(STEP_QUESTIONS[next_step], parse_mode="Markdown")
    else:
        session["step"] = None
        await message.answer("🔄 **Data tersimpan di DB! Memproses file Word (.docx)...**", parse_mode="Markdown")

        try:
            save_cv_to_db(user_id, session["data"])
            file_name = f"CV_{user_id}.docx"
            create_cv_docx(session["data"], file_name)

            with open(file_name, "rb") as file_doc:
                await message.answer_document(
                    document=file_doc,
                    caption="✅ **CV ATS BERHASIL DIBUAT!** Ketik **/start** jika ingin buat lagi."
                )

            if os.path.exists(file_name):
                os.remove(file_name)

        except Exception as e:
            await message.answer(f"❌ Terjadi kesalahan saat memproses CV: {str(e)}")

# ==============================================================
# MAIN RUNNER
# ==============================================================
if __name__ == '__main__':
    print("Inisialisasi Database...")
    init_db()
    print("Bot Telegram Boontrack Berjalan...")
    executor.start_polling(dp, skip_updates=True)