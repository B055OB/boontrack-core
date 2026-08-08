import os
import asyncio
import json
import re
import requests
import tempfile
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from google import genai
from aiohttp import web

# Import Handler Flow dari folder core (Aman dipanggil via PYTHONPATH=app)
from core.cv_flow import cv_conv_handler

load_dotenv()

# --- CONFIGURATIONS ---
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ai_client = None
if GEMINI_API_KEY:
    try:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Init Error: {e}")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# --- DATABASE ENGINE ---
def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )

def _init_db_sync():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            language_code VARCHAR(10),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            event VARCHAR(100),
            meta JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cv_documents (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            version INT DEFAULT 1,
            position VARCHAR(255),
            data JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            user_id BIGINT PRIMARY KEY,
            last_step INT,
            data JSONB,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _track_event_sync(user_id, event, meta=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO analytics (user_id, event, meta) VALUES (%s, %s, %s)",
                    (user_id, event, json.dumps(meta or {})))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Analytics DB Error: {e}")

async def track_event(user_id, event, meta=None):
    await asyncio.to_thread(_track_event_sync, user_id, event, meta)

def _save_user_sync(user: types.User):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (telegram_id, username, first_name, last_name, language_code)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name;
        """, (user.id, user.username, user.first_name, user.last_name, user.language_code))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Save User DB Error: {e}")

async def save_user(user: types.User):
    await asyncio.to_thread(_save_user_sync, user)

def _save_cv_version_sync(user_id, position, data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cv_documents WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]
        version = count + 1
        
        cur.execute("""
            INSERT INTO cv_documents (user_id, version, position, data)
            VALUES (%s, %s, %s, %s)
        """, (user_id, version, position, json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Save CV Version Error: {e}")

async def save_cv_version(user_id, position, data):
    await asyncio.to_thread(_save_cv_version_sync, user_id, position, data)

def _count_referrals_sync(referrer_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT user_id) FROM analytics "
            "WHERE event = 'start' AND meta->>'referrer_id' = %s", 
            (str(referrer_id),)
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        print(f"Count Referrals Error: {e}")
        return 0

async def count_referrals(referrer_id):
    return await asyncio.to_thread(_count_referrals_sync, referrer_id)

def clean_val(val):
    if not val:
        return ""
    v = str(val).strip().lower()
    if v in ["-", "skip", "tidak ada", "ga ada", "ngga ada", "belum ada", "hangus", "hilang", "lupa", "kosong"]:
        return ""
    return str(val).strip()

def ai_generate_summary(position, target_lang="en"):
    if target_lang == "id":
        if not position:
            return "Profesional berdedikasi tinggi yang terbiasa bekerja secara terstruktur, adaptif, serta berkomitmen memberikan kontribusi operasional terbaik bagi perusahaan."
        return f"Profesional berpengalaman di bidang {position} dengan rekam jejak yang terbukti dalam mengeksekusi target operasional dan manajemen kerja secara efisien."
    else:
        if not position:
            return "Highly dedicated professional with a proven track record in structured workflows, adaptability, and operational excellence."
        return f"Results-driven professional specializing in {position} with demonstrated expertise in operational management and team execution."

def ai_rewrite_achievement(text, target_lang="en"):
    lang_name = "English" if target_lang == "en" else "Bahasa Indonesia"
    prompt_text = (
        f"TUGAS: Terjemahkan dan perbaiki tata bahasa dari deskripsi pengalaman kerja pengguna berikut "
        f"menjadi poin-poin profesional berstandar ATS dalam {lang_name} (gunakan Action Verbs).\n\n"
        "ATURAN KETAT (STRICT RULES):\n"
        "1. DILARANG KERAS menambah, mengarang, atau memfabrikasi pencapaian, angka, persentase, atau tools yang tidak diberikan oleh pengguna.\n"
        "2. Pertahankan kebenaran data asli 100%.\n"
        "3. Format keluaran harus berupa bullet points menggunakan simbol '•'.\n"
        "4. Jika input singkat/sederhana, rapikan tata bahasanya tanpa membuat klaim palsu.\n\n"
        f"Data Pengalaman Pengguna: {text}"
    )

    if ai_client:
        try:
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_text,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"[Fallback Alert] Gemini API Error: {e}. Beralih ke Groq...")

    if GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt_text}],
                "temperature": 0.3
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Fallback Alert] Groq API Error: {e}.")

    lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
    return "\n".join([f"• {line}" for line in lines])

def create_cv_docx(user_id, data):
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    cv_lang = data.get("cv_lang", "en")
    name = clean_val(data.get("name", "NAMA LENGKAP"))
    email = clean_val(data.get("email", ""))
    phone = clean_val(data.get("phone", ""))
    domicile = clean_val(data.get("domicile", ""))
    linkedin = clean_val(data.get("linkedin", ""))

    p_name = doc.add_paragraph()
    p_name.paragraph_format.space_after = Pt(2)
    r_name = p_name.add_run(name.upper())
    r_name.font.name = 'Calibri'
    r_name.font.size = Pt(16)
    r_name.font.bold = True

    contact_parts = [p for p in [email, phone, domicile, linkedin] if p]
    if contact_parts:
        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(12)
        r_contact = p_contact.add_run(" | ".join(contact_parts))
        r_contact.font.name = 'Calibri'
        r_contact.font.size = Pt(10)

    def add_section_header(title):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)
        run = h.add_run(title.upper())
        run.font.name = 'Calibri'
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x78)

    summary_header = "PROFESSIONAL SUMMARY" if cv_lang == "en" else "RINGKASAN PROFESIONAL"
    add_section_header(summary_header)
    position_text = clean_val(data.get("target_position", ""))
    p_sum = doc.add_paragraph(ai_generate_summary(position_text, cv_lang))
    p_sum.paragraph_format.space_after = Pt(8)

    exp = clean_val(data.get("experience", ""))
    ach_raw = clean_val(data.get("achievement", ""))
    if exp:
        exp_header = "PROFESSIONAL EXPERIENCE" if cv_lang == "en" else "PENGALAMAN KERJA"
        add_section_header(exp_header)
        for job_title in [j.strip() for j in re.split(r'[\n|]', exp) if j.strip()]:
            p_job = doc.add_paragraph()
            r_job = p_job.add_run(job_title)
            r_job.font.bold = True

            if ach_raw:
                for bullet in ai_rewrite_achievement(ach_raw, cv_lang).split("\n"):
                    b_text = bullet.strip().lstrip("-*• ")
                    if b_text:
                        doc.add_paragraph(b_text, style='List Bullet')

    edu = clean_val(data.get("education", ""))
    if edu:
        add_section_header("EDUCATION" if cv_lang == "en" else "PENDIDIKAN")
        doc.add_paragraph(edu)

    skill = clean_val(data.get("skills", ""))
    if skill:
        add_section_header("SKILLS" if cv_lang == "en" else "KEAHLIAN")
        for line in skill.split("\n"):
            if line.strip():
                doc.add_paragraph(line.strip())

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"CV_{user_id}.docx")
    doc.save(file_path)
    return file_path

# --- HEALTH CHECK SERVER ---
async def health_check_handler(request):
    return web.json_response({"status": "healthy"}, status=200)

async def start_web_server():
    app_web = web.Application()
    app_web.router.add_get('/', health_check_handler)
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app_web)
    await runner.setup()
    try:
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
    except OSError:
        pass

async def on_startup(dp_obj):
    asyncio.create_task(start_web_server())

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    
    print("Bot Telegram BoonTrack Berjalan...")
    executor_instance = executor.Executor(dp, skip_updates=True, loop=loop)
    executor_instance.on_startup(on_startup)
    executor_instance.start_polling()