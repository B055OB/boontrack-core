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

load_dotenv()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QRIS_IMAGE_PATH = "assets/qris.jpg"

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

user_state = {}

TOTAL_STEPS = 9

def get_progress_bar(step):
    return f"📍 <b>Langkah {step} dari {TOTAL_STEPS}</b>\n━━━━━━━━━━"

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

def _save_dropoff_sync(user_id, step, data):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_progress (user_id, last_step, data, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                last_step = EXCLUDED.last_step,
                data = EXCLUDED.data,
                updated_at = CURRENT_TIMESTAMP;
        """, (user_id, step, json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Dropoff DB Error: {e}")

async def save_dropoff(user_id, step, data):
    await asyncio.to_thread(_save_dropoff_sync, user_id, step, data)

def _get_user_history_sync(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT last_step, data FROM user_progress WHERE user_id = %s", (user_id,))
        progress = cur.fetchone()
        
        cur.execute("SELECT version, position, data, created_at FROM cv_documents WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
        last_cv = cur.fetchone()
        
        cur.close()
        conn.close()
        return progress, last_cv
    except Exception as e:
        print(f"Get User History Error: {e}")
        return None, None

async def get_user_history(user_id):
    return await asyncio.to_thread(_get_user_history_sync, user_id)

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

# --- REVISED REFERRAL COUNT (COUNT DISTINCT) ---
def _count_referrals_sync(referrer_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM analytics 
            WHERE event = 'start' AND meta->>'referrer_id' = %s
        """, (str(referrer_id),))
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
    if v in ["-", "skip", "lewati", "tidak ada", "ga ada", "ngga ada", "belum ada", "lupa", "kosong"]:
        return ""
    return str(val).strip()

def get_question_text(step, target_lang="ID"):
    is_en = target_lang in ["EN", "HYBRID"]
    
    questions = {
        1: "👤 <b>Nama Lengkapmu?</b>\n<i>(Disarankan nama resmi untuk di bagian atas CV)</i>",
        2: "📧 <b>Email aktif kamu?</b>\n<i>(Email yang rutin kamu cek untuk balasan recruiter)</i>",
        3: "📱 <b>Nomor WhatsApp / HP Aktif?</b>\n<i>(Klik 'Lewati' jika belum mau mencantumkannya di CV)</i>",
        4: "📍 <b>Kota Domisili saat ini?</b> <i>(contoh: Bandung, Jakarta Selatan)</i>",
        5: "🔗 <b>Link LinkedIn / Portfolio / GitHub?</b>\n<i>(Klik 'Lewati' jika tidak ada)</i>",
        6: (
            "💼 <b>Pengalaman Kerja / Organisasi / Freelance?</b>\n\n"
            "💬 <i>Ceritakan santai saja seperti ke teman, misalnya:\n"
            "'Kasir di Toko Makmur 2021-2023, lalu Admin Sales di PT ABC 2023-2024'\n"
            "Nanti saya yang bantu susun menjadi kalimat profesional ATS!</i>\n\n"
            "<i>(Ketik '-' atau 'Fresh Grad' jika belum ada)</i>"
        ),
        7: "🏆 <b>Apa tugas utama atau pencapaianmu di pekerjaan tersebut?</b>\n<i>(Tulis apa adanya, tidak perlu dibuat-buat. Nanti saya rapikan!)</i>",
        8: "🎓 <b>Pendidikan Terakhirmu?</b>\n<i>(contoh: S1 Manajemen - Universitas Terbuka, 2023)</i>",
        9: "🛠️ <b>Skill / Keahlian Utama?</b>\n<i>(contoh: Ms. Excel, Customer Service, Canvassing, Python)</i>"
    }
    return questions.get(step, "")

def ai_generate_summary(position, target_lang="ID"):
    is_en = target_lang in ["EN", "HYBRID"]
    if is_en:
        if not position:
            return "Dedicated and adaptable professional committed to driving operational excellence and contributing effectively to team goals."
        return f"Results-driven professional aspiring for {position} roles, with a proven track record of executing operational objectives and managing tasks efficiently."
    else:
        if not position:
            return "Profesional berdedikasi tinggi yang terbiasa bekerja secara terstruktur, adaptif, serta berkomitmen memberikan kontribusi operasional terbaik bagi perusahaan."
        return f"Profesional berpengalaman di bidang {position} dengan rekam jejak yang terbukti dalam mengeksekusi target operasional dan manajemen kerja secara efisien."

def ai_rewrite_achievement(text, target_lang="ID"):
    is_en = target_lang in ["EN", "HYBRID"]
    lang_instruction = "in Professional English" if is_en else "dalam Bahasa Indonesia profesional"

    prompt_text = (
        f"Ubah deskripsi tugas/pengalaman kerja berikut menjadi 2-4 poin bullet point (menggunakan simbol •) "
        f"{lang_instruction} standar HR yang ATS-friendly.\n"
        f"ATURAN MUTLAK: DILARANG MENGARANG FAKTA, ANGKA, TOOLS, ATAU PENGETAHUAN YANG TIDAK ADA DALAM INPUT USER.\n\n"
        f"Input Pengalaman: {text}"
    )

    if ai_client:
        try:
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_text
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"[Fallback Alert] Gemini API Error: {e}. Beralih ke Groq...")

    if GROQ_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "llama3-8b-8192", "messages": [{"role": "user", "content": prompt_text}], "temperature": 0.3}
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=3)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Fallback Alert] Groq API Error: {e}")

    lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
    return "\n".join([f"• {line}" for line in lines])

def create_cv_docx(user_id, data):
    doc = Document()
    target_lang = data.get("target_lang", "ID")
    
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    name = clean_val(data.get("1", "NAMA LENGKAP"))
    email = clean_val(data.get("2", ""))
    phone = clean_val(data.get("3", ""))
    domicile = clean_val(data.get("4", ""))
    linkedin = clean_val(data.get("5", ""))

    p_name = doc.add_paragraph()
    p_name.paragraph_format.space_after = Pt(2)
    r_name = p_name.add_run(name.upper())
    r_name.font.name = 'Calibri'
    r_name.font.size = Pt(16)
    r_name.font.bold = True
    r_name.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    contact_parts = [p for p in [email, phone, domicile, linkedin] if p]
    if contact_parts:
        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(12)
        r_contact = p_contact.add_run(" | ".join(contact_parts))
        r_contact.font.name = 'Calibri'
        r_contact.font.size = Pt(10)
        r_contact.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    def add_section_header(title):
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)
        run = h.add_run(title.upper())
        run.font.name = 'Calibri'
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x78)
        
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '6')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '1F4E78')
        pBdr.append(bottom)
        h._p.get_or_add_pPr().append(pBdr)

    is_en = target_lang in ["EN", "HYBRID"]
    
    # Summary
    add_section_header("PROFESSIONAL SUMMARY" if is_en else "RINGKASAN PROFESIONAL")
    position_text = clean_val(data.get("target_position", ""))
    summary_text = ai_generate_summary(position_text, target_lang)
    p_sum = doc.add_paragraph(summary_text)
    p_sum.paragraph_format.space_after = Pt(8)
    for r in p_sum.runs:
        r.font.name = 'Calibri'
        r.font.size = Pt(10.5)

    # Experience
    exp = clean_val(data.get("6", ""))
    ach_raw = clean_val(data.get("7", ""))

    if exp:
        add_section_header("PROFESSIONAL EXPERIENCE" if is_en else "PENGALAMAN KERJA")
        raw_jobs = [j.strip() for j in re.split(r'[\n|]', exp) if j.strip()]
        
        for job_title in raw_jobs:
            if not job_title:
                continue
            
            p_job = doc.add_paragraph()
            p_job.paragraph_format.space_before = Pt(6)
            p_job.paragraph_format.space_after = Pt(2)
            r_job = p_job.add_run(job_title)
            r_job.font.name = 'Calibri'
            r_job.font.size = Pt(10.5)
            r_job.font.bold = True

            if ach_raw:
                ach_formatted = ai_rewrite_achievement(ach_raw, target_lang)
                for bullet in ach_formatted.split("\n"):
                    b_text = bullet.strip().lstrip("-*• ")
                    if b_text:
                        p_b = doc.add_paragraph(style='List Bullet')
                        p_b.paragraph_format.space_after = Pt(2)
                        r_b = p_b.add_run(b_text)
                        r_b.font.name = 'Calibri'
                        r_b.font.size = Pt(10)

    # Education
    edu = clean_val(data.get("8", ""))
    if edu:
        add_section_header("EDUCATION" if is_en else "PENDIDIKAN")
        p_edu = doc.add_paragraph(edu)
        p_edu.paragraph_format.space_after = Pt(8)
        for r in p_edu.runs:
            r.font.name = 'Calibri'
            r.font.size = Pt(10.5)

    # Skills
    skill = clean_val(data.get("9", ""))
    if skill:
        add_section_header("SKILLS & EXPERTISE" if is_en else "KEAHLIAN")
        for line in skill.split("\n"):
            line_str = line.strip()
            if line_str:
                p_skill = doc.add_paragraph(line_str)
                p_skill.paragraph_format.space_after = Pt(3)
                for r in p_skill.runs:
                    r.font.name = 'Calibri'
                    r.font.size = Pt(10)

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"CV_{user_id}.docx")
    doc.save(file_path)
    return file_path

# --- BOT COMMAND HANDLERS ---
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    await save_user(message.from_user)
    
    text_parts = message.text.split()
    args = text_parts[1] if len(text_parts) > 1 else "direct"

    meta_data = {}
    if args.startswith("ref_"):
        meta_data = {"utm_source": "referral", "referrer_id": args.replace("ref_", "")}
    else:
        meta_data = {"utm_source": args}

    await track_event(user_id, "start", meta=meta_data)
    
    progress, last_cv = await get_user_history(user_id)
    first_name = message.from_user.first_name or "Teman"

    if progress and isinstance(progress.get("last_step"), int) and progress.get("last_step", 0) > 1 and progress.get("last_step", 0) < TOTAL_STEPS:
        last_step = progress["last_step"]
        saved_data = progress.get("data", {})
        user_state[user_id] = {"step": last_step, "data": saved_data, "meta": meta_data}
        
        kbd = InlineKeyboardMarkup(row_width=2)
        kbd.add(
            InlineKeyboardButton("▶️ Lanjutkan CV", callback_data="resume_flow"),
            InlineKeyboardButton("🔄 Mulai Baru", callback_data="restart_flow")
        )
        await message.reply(
            f"Halo lagi, {first_name}! 👋\n\n"
            f"Kemarin kita sempat menyusun CV sampai di <b>Langkah {last_step} dari {TOTAL_STEPS}</b>.\n\n"
            "Mau kita tuntaskan sekarang agar CV kamu siap dipakai melamar kerja?",
            reply_markup=kbd,
            parse_mode="HTML"
        )
        return

    user_state[user_id] = {"step": "ONBOARDING_NAMA", "data": {}, "meta": meta_data}
    await save_dropoff(user_id, 0, {})
    
    # PESAN 1: Warm Companion Greeting
    msg_1 = (
        "<b>Saya BoonTrack Career Assistant.</b>\n"
        "Saya akan membantu meningkatkan peluang kamu dipanggil interview.\n\n"
        "Sebelum mulai...\n"
        "Boleh kenalan dulu?\n"
        "Ini dengan siapa?"
    )
    await message.reply(msg_1, parse_mode="HTML")

@dp.callback_query_handler(lambda c: c.data in ["status_fresh", "status_exp", "lang_id", "lang_en", "lang_hybrid", "skip_optional", "resume_flow", "restart_flow"])
async def handle_callback_navigation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    code = callback_query.data
    
    await bot.edit_message_reply_markup(user_id, callback_query.message.message_id, reply_markup=None)
    if user_id not in user_state:
        user_state[user_id] = {"step": 0, "data": {}}
        
    user_data = user_state[user_id].get("data", {})
    user_name = user_data.get("nama_panggilan", callback_query.from_user.first_name or "Teman")

    # FASE STATUS
    if code in ["status_fresh", "status_exp"]:
        user_data["status_kerja"] = "Fresh Graduate" if code == "status_fresh" else "Berpengalaman"
        user_state[user_id]["step"] = "ONBOARDING_POSISI"
        
        if code == "status_fresh":
            reassurance = (
                f"Oke, {user_name}! Berarti kita punya strategi khusus untuk Fresh Graduate 👍\n"
                "Nanti kita fokus menonjolkan pendidikan, project, organisasi, dan skill utama kamu.\n\n"
                "🎯 <b>Kamu saat ini ingin melamar posisi apa?</b>\n"
                "<i>(Contoh: Admin, Marketing, Software Engineer, Customer Service, Kasir)</i>"
            )
        else:
            reassurance = (
                f"Sip, {user_name} 👍\n"
                "Kita akan fokus menggali pengalaman dan pencapaian terbaikmu agar CV-nya makin menjual di mata HR.\n\n"
                "🎯 <b>Kamu saat ini ingin melamar posisi apa?</b>\n"
                "<i>(Contoh: Marketing Executive, Admin Operational, Barista, Graphic Designer)</i>"
            )
        await bot.send_message(user_id, reassurance, parse_mode="HTML")

    # FASE PILIHAN BAHASA
    elif code in ["lang_id", "lang_en", "lang_hybrid"]:
        target_lang = "ID" if code == "lang_id" else ("EN" if code == "lang_en" else "HYBRID")
        user_data["target_lang"] = target_lang
        
        if code == "lang_hybrid":
            msg_lang = (
                "Sip! Pilihan cerdas 🌐\n"
                "CV kamu dibuat dalam **English profesional**, tapi selama pengisian kamu **bebas cerita dalam Bahasa Indonesia**.\n"
                "Nanti saya yang bantu terjemahkan ke bahasa CV yang profesional! 😊\n\n"
                "🔒 <i>Privasi kamu aman. Data ini hanya digunakan untuk pencetakan CV dokumenmu.</i>"
            )
        elif code == "lang_en":
            msg_lang = (
                "Great! We will create your CV in **English** 🇬🇧\n"
                "Tenang, kamu cukup cerita apa adanya. Nanti saya rapikan tata bahasanya agar ATS-friendly! 😊\n\n"
                "🔒 <i>Privasi kamu aman. Data ini hanya digunakan untuk pencetakan CV dokumenmu.</i>"
            )
        else:
            msg_lang = (
                "Siap! CV dibuat dalam **Bahasa Indonesia** 🇮🇩\n\n"
                "🔒 <i>Privasi kamu aman. Data ini hanya digunakan untuk pencetakan CV dokumenmu.</i>"
            )
        
        await bot.send_message(user_id, msg_lang, parse_mode="Markdown")
        
        # Mulai Step 1
        user_state[user_id]["step"] = 1
        await save_dropoff(user_id, 1, user_data)
        
        await bot.send_message(
            user_id,
            f"Mari kita mulai! 👍\n\n{get_progress_bar(1)}\n{get_question_text(1, target_lang)}",
            parse_mode="HTML"
        )

    # TOMBOL LEWATI (OPTIONAL STEPS)
    elif code == "skip_optional":
        current_step = user_state[user_id].get("step", 1)
        if isinstance(current_step, int):
            user_data[str(current_step)] = ""
            next_step = current_step + 1
            user_state[user_id]["step"] = next_step
            await save_dropoff(user_id, next_step, user_data)
            
            target_lang = user_data.get("target_lang", "ID")
            kbd = None
            if next_step in [3, 4, 5]:
                kbd = InlineKeyboardMarkup().add(InlineKeyboardButton("⏩ Lewati Langkah Ini", callback_data="skip_optional"))
                
            await bot.send_message(
                user_id,
                f"{get_progress_bar(next_step)}\n{get_question_text(next_step, target_lang)}",
                reply_markup=kbd,
                parse_mode="HTML"
            )

    elif code == "resume_flow":
        state = user_state.get(user_id, {"step": 1, "data": {}})
        step = state["step"]
        target_lang = state.get("data", {}).get("target_lang", "ID")
        await bot.send_message(
            user_id,
            f"Sip, mari kita lanjutkan! 👍\n\n{get_progress_bar(step)}\n{get_question_text(step, target_lang)}",
            parse_mode="HTML"
        )

    elif code == "restart_flow":
        user_state[user_id] = {"step": "ONBOARDING_NAMA", "data": {}}
        await save_dropoff(user_id, 0, {})
        msg_1 = (
            "<b>Saya BoonTrack Career Assistant.</b>\n"
            "Saya akan membantu meningkatkan peluang kamu dipanggil interview.\n\n"
            "Sebelum mulai...\n"
            "Boleh kenalan dulu?\n"
            "Ini dengan siapa?"
        )
        await bot.send_message(user_id, msg_1, parse_mode="HTML")

@dp.message_handler(commands=['cancel'])
async def cancel_handler(message: types.Message):
    user_id = message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    await save_dropoff(user_id, 0, {})
    await message.reply("❌ <b>Proses pembuatan CV dibatalkan.</b>\n\nKetik /start kapan saja jika ingin memulai kembali!", parse_mode="HTML")

@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_state or user_state[user_id].get("step", 0) == 0:
        progress, _ = await get_user_history(user_id)
        if progress and progress.get("last_step", 0) > 0:
            user_state[user_id] = {"step": progress["last_step"], "data": progress.get("data", {})}
        else:
            await message.reply("Ketik <b>/start</b> untuk mulai membuat CV ya!", parse_mode="HTML")
            return

    current_step = user_state[user_id]["step"]
    user_data = user_state[user_id]["data"]

    # FASE 1: ONBOARDING NAMA
    if current_step == "ONBOARDING_NAMA":
        user_data["nama_panggilan"] = text
        user_state[user_id]["step"] = "ONBOARDING_STATUS"
        
        kbd_status = InlineKeyboardMarkup(row_width=1)
        kbd_status.add(
            InlineKeyboardButton("🔹 Fresh Graduate / Belum berpengalaman", callback_data="status_fresh"),
            InlineKeyboardButton("🔹 Sudah berpengalaman (Cari kerja baru)", callback_data="status_exp")
        )
        msg_2 = f"Halo {text} 😊\n\nBoleh saya tahu status kamu saat ini?"
        await message.reply(msg_2, reply_markup=kbd_status, parse_mode="HTML")
        return

    # FASE 2: ONBOARDING POSISI (VALUE BEFORE DATA)
    if current_step == "ONBOARDING_POSISI":
        user_data["target_position"] = text
        user_state[user_id]["step"] = "SELECT_LANGUAGE"
        
        # CAREER INSIGHT PER POSISI
        pos_clean = text.lower()
        if "marketing" in pos_clean or "sales" in pos_clean:
            insight_text = "Untuk posisi **Marketing/Sales**, recruiter sangat memperhatikan kemampuan komunikasi, campaign, sosial media, serta pencapaian target yang pernah kamu raih."
        elif "admin" in pos_clean or "office" in pos_clean:
            insight_text = "Untuk posisi **Admin**, recruiter menyukai kandidat yang teliti, menguasai pengolahan data (Excel), ketikan rapi, serta rekapitulasi inventaris yang akurat."
        elif "developer" in pos_clean or "engineer" in pos_clean or "it" in pos_clean:
            insight_text = "Untuk posisi **Technical/IT**, recruiter berfokus pada tech-stack, portfolio project, serta kemampuan problem solving yang logis."
        else:
            insight_text = f"Untuk posisi **{text}**, recruiter akan sangat memperhatikan kejelasan tugas harian, kedisiplinan, serta skill praktis yang kamu miliki."

        kbd_lang = InlineKeyboardMarkup(row_width=1)
        kbd_lang.add(
            InlineKeyboardButton("🌐 CV English (Ngobrol B. Indonesia)", callback_data="lang_hybrid"),
            InlineKeyboardButton("🇮🇩 CV Bahasa Indonesia", callback_data="lang_id"),
            InlineKeyboardButton("🇬🇧 Full English", callback_data="lang_en")
        )
        
        msg_insight = (
            f"Oke, **{text}** 👍\n\n"
            f"💡 **Career Insight:**\n{insight_text}\n\n"
            "Nanti ceritakan saja tugas harianmu apa adanya, saya yang bantu ubah menjadi bahasa CV profesional.\n\n"
            "Sebelum kita mulai, CV kamu ingin dibuat dalam bahasa apa?"
        )
        await message.reply(msg_insight, reply_markup=kbd_lang, parse_mode="Markdown")
        return

    if current_step == "SELECT_LANGUAGE":
        await message.reply("Silakan **pilih salah satu bahasa di atas** ya 👆", parse_mode="Markdown")
        return

    # FASE 3: 9 PROGRESSIVE STEPS
    if isinstance(current_step, int) and current_step > 0:
        user_data[str(current_step)] = text
        await track_event(user_id, f"step_{current_step}_completed")

        if current_step < TOTAL_STEPS:
            next_step = current_step + 1
            user_state[user_id]["step"] = next_step
            await save_dropoff(user_id, next_step, user_data)
            
            target_lang = user_data.get("target_lang", "ID")
            kbd = None
            # Tampilkan tombol Lewati untuk No HP (Step 3), Domisili (Step 4), & LinkedIn (Step 5)
            if next_step in [3, 4, 5]:
                kbd = InlineKeyboardMarkup().add(InlineKeyboardButton("⏩ Lewati Langkah Ini", callback_data="skip_optional"))

            await message.reply(
                f"{get_progress_bar(next_step)}\n{get_question_text(next_step, target_lang)}",
                reply_markup=kbd,
                parse_mode="HTML"
            )
        else:
            user_state[user_id]["step"] = 0
            await save_dropoff(user_id, TOTAL_STEPS, user_data)
            
            processing_msg = await message.reply(
                "⏳ <b>Merapikan & menyusun CV ATS-Friendly kamu...</b>\n"
                "Mohon tunggu sekitar 15-20 detik ya!",
                parse_mode="HTML"
            )

            try:
                file_path = await asyncio.to_thread(create_cv_docx, user_id, user_data)
                
                position = clean_val(user_data.get("target_position", "General"))
                await save_cv_version(user_id, position, user_data)
                await track_event(user_id, "resume_generated", meta={"position": position})

                document = InputFile(file_path)
                
                # --- POST-CV 3-PHASE EXPERIENCE ---
                
                # 🥇 FASE 1: CELEBRATION & DELIVER FILE
                user_name = user_data.get("nama_panggilan", message.from_user.first_name or "Teman")
                await bot.send_document(
                    chat_id=user_id,
                    document=document,
                    caption=f"🎉 <b>CV ATS-Friendly kamu sudah selesai, {user_name}!</b>\n\n"
                            "Silakan di-download dan diperiksa kembali. File dalam format Word (.docx) sehingga bisa kamu edit kapan saja!",
                    parse_mode="HTML"
                )
                
                try:
                    await bot.delete_message(chat_id=user_id, message_id=processing_msg.message_id)
                except Exception:
                    pass

                # 🥈 FASE 2: CAREER INSIGHT & TIPS
                value_text = (
                    f"💡 <b>Tips Penting untuk Posisi {position}:</b>\n\n"
                    "Saat mengirim lamaran lewat email atau portal kerja:\n"
                    "1. Gunakan subjek email jernih: <code>[Posisi] - [Nama Kamu]</code>\n"
                    "2. Jangan biarkan body email kosong (tuliskan Surat Lamaran Singkat)\n"
                    "3. Cantumkan bukti angka/pencapaian kecil jika ada saat interview nanti.\n\n"
                    "Semoga peluang dipanggil interview semakin tinggi! 🚀"
                )
                await bot.send_message(user_id, value_text, parse_mode="HTML")

                # 🥉 FASE 3: MONETISASI + GAMIFIED REFERRAL (PROGRESS 0/3)
                total_refs = await count_referrals(user_id)
                bot_info = await bot.get_me()
                user_ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
                
                monetize_and_referral = (
                    "❤️ <b>Dukung BoonTrack & Dapatkan Bonus Portfolio Website</b>\n\n"
                    "BoonTrack dikembangkan mandiri agar tetap gratis bagi pencari kerja. "
                    "Jika merasa terbantu, kamu bisa traktir kami kopi seikhlasnya via QRIS di bawah. (Tidak Wajib)\n\n"
                    "🎁 <b>BONUS PORTOFOLIO WEBSITE</b>\n"
                    f"Ajak 3 temanmu membuat CV di BoonTrack, dan kami akan buatkan **Website Portfolio Pribadi Gratis**!\n\n"
                    f"📊 <b>Progress Referral Kamu: {total_refs} / 3</b>\n"
                    f"👇 Bagikan link referral-mu ke teman:\n"
                    f"<code>{user_ref_link}</code>"
                )
                await bot.send_message(user_id, monetize_and_referral, parse_mode="HTML")

                # Kirim Gambar QRIS
                possible_qris_paths = [QRIS_IMAGE_PATH, "/app/qris.jpg", "qris.jpg"]
                found_qris = next((p for p in possible_qris_paths if os.path.exists(p)), None)
                if found_qris:
                    await bot.send_photo(chat_id=user_id, photo=InputFile(found_qris), caption="Dukungan donasi seikhlasnya via QRIS. Terima kasih! 🙏")

                # HEARTFELT CLOSING
                closing_text = (
                    "🤝 <b>Satu Hal Lagi...</b>\n\n"
                    "Kalau nanti kamu berhasil dapat panggilan interview atau bahkan diterima kerja... "
                    "Boleh balik ke bot ini dan kasih tahu saya?\n\n"
                    "Saya ingin ikut merayakannya. Semoga sukses! ❤️🚀"
                )
                await bot.send_message(user_id, closing_text, parse_mode="HTML")

                if os.path.exists(file_path):
                    os.remove(file_path)

                # TRIGGER REFERRAL REWARD (IF >= 3)
                referrer_id = user_state.get(user_id, {}).get("meta", {}).get("referrer_id")
                if referrer_id:
                    ref_count = await count_referrals(referrer_id)
                    if ref_count >= 3:
                        reward_text = (
                            "🎉 <b>SELAMAT! Target 3 Referral Kamu Tercapai!</b>\n\n"
                            "3 teman yang kamu ajak telah berhasil menyusun CV.\n"
                            "Kamu berhak klaim <b>Website Portfolio Personal Gratis</b>!\n\n"
                            "Ketik /claim_website untuk klaim websitemu! 🌐"
                        )
                        try:
                            await bot.send_message(chat_id=int(referrer_id), text=reward_text, parse_mode="HTML")
                        except Exception as e:
                            print(f"Error send referral reward: {e}")

            except Exception as e:
                print(f"Error Generate CV Flow: {e}")
                await message.reply("❌ Terjadi kendala teknis. Silakan tekan /start untuk coba lagi!", parse_mode="HTML")

async def health_check_handler(request):
    return web.json_response({"status": "healthy", "message": "Render is awake!"}, status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check_handler)
    app.router.add_get('/health', health_check_handler)
    
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    
    try:
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
    except OSError:
        site = web.TCPSite(runner, '0.0.0.0', port + 1)
        await site.start()

async def on_startup(dp):
    asyncio.create_task(start_web_server())

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)