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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://boontrack_user:boontrack_password@postgres:5432/boontrack_db")
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

def save_field(telegram_id: int, **fields):
    db = SessionLocal()
    try:
        user = db.query(UserCVData).filter(UserCVData.telegram_id == telegram_id).first()
        if not user:
            user = UserCVData(telegram_id=telegram_id)
            db.add(user)
        for k, v in fields.items():
            setattr(user, k, v.strip() if v else "-")
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"DB Error: {e}")
    finally:
        db.close()

# DEFINISI STATE (100% UNIK DAN TERPISAH)
ST_NAMA, ST_EMAIL, ST_PHONE, ST_DOMISILI, ST_LINKEDIN, ST_POSISI, ST_PENDIDIKAN, ST_PENGALAMAN, ST_PENCAPAIAN, ST_SKILL = range(201, 211)

app = FastAPI()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🚀 **PEMBUATAN CV ATS STARTED**\n\n1️⃣ **Siapa Nama Lengkap kamu?**", parse_mode="Markdown")
    return ST_NAMA

async def step_nama(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, nama=update.message.text)
    await update.message.reply_text("2️⃣ **Masukkan Email kamu:**")
    return ST_EMAIL

async def step_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, email=update.message.text)
    await update.message.reply_text("3️⃣ **Masukkan No WhatsApp / HP:**")
    return ST_PHONE

async def step_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, phone_number=update.message.text)
    await update.message.reply_text("4️⃣ **Kota Domisili saat ini:**")
    return ST_DOMISILI

async def step_domisili(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, domisili=update.message.text)
    await update.message.reply_text("5️⃣ **Link LinkedIn / Portfolio:** (Ketik '-' jika tidak ada)")
    return ST_LINKEDIN

async def step_linkedin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, linkedin_url=update.message.text)
    await update.message.reply_text("6️⃣ **Posisi / Jabatan yang dilamar:**")
    return ST_POSISI

async def step_posisi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, posisi=update.message.text)
    await update.message.reply_text("7️⃣ **Pendidikan Terakhir (Sekolah/Kampus & Jurusan):**")
    return ST_PENDIDIKAN

async def step_pendidikan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, pendidikan=update.message.text)
    await update.message.reply_text("8️⃣ **Pengalaman Kerja / Organisasi:**")
    return ST_PENGALAMAN

async def step_pengalaman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, pengalaman=update.message.text)
    await update.message.reply_text("9️⃣ **Pencapaian Utama / Project:** (Ketik '-' jika tidak ada)")
    return ST_PENCAPAIAN

async def step_pencapaian(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    save_field(update.effective_user.id, pencapaian=update.message.text)
    await update.message.reply_text("🔟 **Skill / Software / Sertifikasi yang dikuasai:**")
    return ST_SKILL

async def step_skill_and_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    save_field(user_id, skill=update.message.text)
    
    await update.message.reply_text("⏳ Data tersimpan di DB! Memproses file Word (.docx)...")
    
    db = SessionLocal()
    data = db.query(UserCVData).filter(UserCVData.telegram_id == user_id).first()
    db.close()

    doc = Document()
    doc.add_heading(data.nama.upper() if data and data.nama else "CURRICULUM VITAE", level=0)
    doc.add_paragraph(f"Posisi: {data.posisi} | Domisili: {data.domisili}")
    doc.add_paragraph(f"Email: {data.email} | HP: {data.phone_number} | LinkedIn: {data.linkedin_url}")
    doc.add_heading("Pendidikan", level=1)
    doc.add_paragraph(data.pendidikan)
    doc.add_heading("Pengalaman Kerja", level=1)
    doc.add_paragraph(data.pengalaman)
    doc.add_heading("Pencapaian", level=1)
    doc.add_paragraph(data.pencapaian)
    doc.add_heading("Keahlian & Skill", level=1)
    doc.add_paragraph(data.skill)

    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=file_stream,
        filename=f"CV_{user_id}.docx",
        caption="✅ **CV ATS BERHASIL DIBUAT!** Ketik /start jika ingin buat lagi."
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Batal. Ketik /start untuk mulai lagi.")
    return ConversationHandler.END

@app.on_event("startup")
async def startup_event():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        bot_app = ApplicationBuilder().token(token).build()
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                ST_NAMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_nama)],
                ST_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_email)],
                ST_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_phone)],
                ST_DOMISILI: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_domisili)],
                ST_LINKEDIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_linkedin)],
                ST_POSISI: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_posisi)],
                ST_PENDIDIKAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_pendidikan)],
                ST_PENGALAMAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_pengalaman)],
                ST_PENCAPAIAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_pencapaian)],
                ST_SKILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_skill_and_finish)],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CommandHandler("start", start)
            ],
            allow_reentry=True
        )
        bot_app.add_handler(conv_handler)
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
