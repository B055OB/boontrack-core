import os
import logging
import io
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from docx import Document
from docx.shared import Pt, Inches, RGBColor

from sqlalchemy import create_engine, Column, String, Text, BigInteger, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://boontrack_user:boontrack_password@postgres:5432/boontrack_db"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserCVData(Base):
    __tablename__ = "user_cv_data"

    telegram_id = Column(BigInteger, primary_key=True, index=True)
    nama = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    domisili = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    posisi = Column(String, nullable=True)
    pendidikan = Column(Text, nullable=True)
    pengalaman = Column(Text, nullable=True)
    pencapaian = Column(Text, nullable=True)
    skill = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def clean_input(text: str) -> str:
    val = text.strip()
    lowered = val.lower()
    skip_words = ['-', 'belum ada', 'tidak ada', 'ga ada', 'gak ada', 'skip', 'kosong', 'belum', 'none', 'no']
    if lowered in skip_words or not val:
        return "-"
    return val


def save_or_update_cv_field(telegram_id: int, **fields):
    db = SessionLocal()
    try:
        user_data = db.query(UserCVData).filter(UserCVData.telegram_id == telegram_id).first()
        if not user_data:
            user_data = UserCVData(telegram_id=telegram_id)
            db.add(user_data)
        
        for key, value in fields.items():
            setattr(user_data, key, value)
        
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving to DB: {e}")
    finally:
        db.close()


def get_user_cv_data(telegram_id: int):
    db = SessionLocal()
    try:
        return db.query(UserCVData).filter(UserCVData.telegram_id == telegram_id).first()
    finally:
        db.close()


# --- DEFINISI STATE URUT 100% ---
NAMA, EMAIL, PHONE, DOMISILI, LINKEDIN, POSISI, PENDIDIKAN, PENGALAMAN, PENCAPAIAN, SKILL = range(10)

app = FastAPI(title="BoonTrack Core API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def root():
    return {"status": "online", "message": "BoonTrack Core Engine is Running"}


# --- TELEGRAM HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Halo! Saya **BoonTrack Assistant**. 🚀\n\n"
        "Mari kita buat CV ATS-Friendly kamu secara sistematis.\n"
        "*(Catatan: Jika ada pertanyaan yang belum ada jawabannya, cukup ketik: 'belum ada' atau '-')*\n\n"
        "1️⃣ Pertama-tama, **siapa nama lengkap kamu?**",
        parse_mode="Markdown"
    )
    return NAMA


async def get_nama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, nama=clean_input(update.message.text))
    await update.message.reply_text(
        "2️⃣ Masukkan **alamat Email aktif kamu**:\n*(Ketik 'belum ada' jika belum punya)*",
        parse_mode="Markdown"
    )
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, email=clean_input(update.message.text))
    await update.message.reply_text(
        "3️⃣ Masukkan **Nomor WhatsApp / HP aktif**:\n*(Ketik 'belum ada' jika tidak ingin dicantumkan)*",
        parse_mode="Markdown"
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, phone_number=clean_input(update.message.text))
    await update.message.reply_text(
        "4️⃣ Dimana **Kota Domisili tempat tinggal kamu sekarang?** (Contoh: Bandung, Jawa Barat):",
        parse_mode="Markdown"
    )
    return DOMISILI


async def get_domisili(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, domisili=clean_input(update.message.text))
    await update.message.reply_text(
        "5️⃣ Masukkan **Link LinkedIn atau Portofolio kamu**:\n*(Ketik 'belum ada' atau '-' jika tidak ada)*",
        parse_mode="Markdown"
    )
    return LINKEDIN


async def get_linkedin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, linkedin_url=clean_input(update.message.text))
    await update.message.reply_text(
        "6️⃣ **Posisi / Jabatan apa yang ingin kamu lamar?** (Contoh: Operations Lead, Software Engineer, Admin):",
        parse_mode="Markdown"
    )
    return POSISI


async def get_posisi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, posisi=clean_input(update.message.text))
    await update.message.reply_text(
        "7️⃣ Tuliskan **Pendidikan Terakhir** kamu (Nama Sekolah/Kampus & Jurusan):",
        parse_mode="Markdown"
    )
    return PENDIDIKAN


async def get_pendidikan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, pendidikan=clean_input(update.message.text))
    await update.message.reply_text(
        "8️⃣ Tuliskan **Pengalaman Kerja / Organisasi** utama kamu:\n*(Jika belum pernah kerja, ketik: 'belum ada')*",
        parse_mode="Markdown"
    )
    return PENGALAMAN


async def get_pengalaman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, pengalaman=clean_input(update.message.text))
    await update.message.reply_text(
        "9️⃣ Tuliskan **Prestasi / Pencapaian Utama / Project** yang pernah kamu kerjakan:\n*(Ketik 'belum ada' jika tidak ada)*",
        parse_mode="Markdown"
    )
    return PENCAPAIAN


async def get_pencapaian(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_or_update_cv_field(update.effective_user.id, pencapaian=clean_input(update.message.text))
    await update.message.reply_text(
        "🔟 Terakhir, tuliskan **Keahlian (Skill), Software, atau Sertifikasi** yang kamu kuasai:",
        parse_mode="Markdown"
    )
    return SKILL


async def get_skill_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    save_or_update_cv_field(user_id, skill=clean_input(update.message.text))

    await update.message.reply_text("Data tersimpan di Database! Sedang membuatkan file Word (.docx) CV ATS-Friendly kamu... ⏳")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")

    try:
        data = get_user_cv_data(user_id)

        nama = (data.nama if data and data.nama and data.nama != '-' else "KANDIDAT").upper()
        posisi = data.posisi if data and data.posisi and data.posisi != '-' else "Professional"
        email = data.email if data and data.email and data.email != '-' else ""
        phone = data.phone_number if data and data.phone_number and data.phone_number != '-' else ""
        domisili = data.domisili if data and data.domisili and data.domisili != '-' else "Indonesia"
        linkedin = data.linkedin_url if data and data.linkedin_url and data.linkedin_url != '-' else ""
        pendidikan = data.pendidikan if data and data.pendidikan and data.pendidikan != '-' else "Tidak dicantumkan"
        pengalaman = data.pengalaman if data and data.pengalaman and data.pengalaman != '-' else "Belum ada pengalaman formal"
        pencapaian = data.pencapaian if data and data.pencapaian and data.pencapaian != '-' else ""
        skill = data.skill if data and data.skill and data.skill != '-' else "Kemampuan komunikasi & kerja tim"

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

        contact_parts = [domisili]
        if email: contact_parts.append(email)
        if phone: contact_parts.append(phone)
        if linkedin: contact_parts.append(linkedin)

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

        # Export File & Send
        file_stream = io.BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        filename = f"CV_ATS_{nama.replace(' ', '_')}.docx"

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_stream,
            filename=filename,
            caption=f"📄 **Dokumen CV ATS-Friendly ({nama}) berhasil dibuat & tersimpan di Database!**\n\nSilakan di-download. Ketik /start untuk membuat atau memperbarui data kapan saja."
        )
    except Exception as e:
        logger.error(f"Error generating Word CV: {e}")
        await update.message.reply_text("Terjadi kendala teknis saat menyusun dokumen Word. Silakan coba lagi dengan /start.")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proses dibatalkan. Ketik /start untuk mulai lagi ya!")
    return ConversationHandler.END


# --- STARTUP EVENT ---

@app.on_event("startup")
async def startup_event():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        bot_app = ApplicationBuilder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_nama)],
                EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
                DOMISILI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_domisili)],
                LINKEDIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_linkedin)],
                POSISI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_posisi)],
                PENDIDIKAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pendidikan)],
                PENGALAMAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pengalaman)],
                PENCAPAIAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pencapaian)],
                SKILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_skill_and_generate)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        bot_app.add_handler(conv_handler)
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
