import os
import asyncio
import json
import re
import random
import requests
import tempfile
from datetime import datetime, timedelta
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

    # TABEL TRANSAKSI PRODUK DIGITAL
    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_orders (
            id SERIAL PRIMARY KEY,
            order_id VARCHAR(50) UNIQUE,
            telegram_id BIGINT,
            product_name VARCHAR(100),
            base_price INT,
            unique_code INT,
            total_amount INT UNIQUE,
            status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
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

# DATABASE HELPERS PRODUK DIGITAL
def _create_order_sync(telegram_id, product_name, base_price, unique_code, total_amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        order_id = f"ORD-{int(datetime.now().timestamp())}"
        expires_at = datetime.now() + timedelta(minutes=15)
        
        cur.execute("""
            INSERT INTO product_orders (order_id, telegram_id, product_name, base_price, unique_code, total_amount, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (total_amount) DO UPDATE SET
                telegram_id = EXCLUDED.telegram_id,
                product_name = EXCLUDED.product_name,
                expires_at = EXCLUDED.expires_at,
                status = 'PENDING';
        """, (order_id, telegram_id, product_name, base_price, unique_code, total_amount, expires_at))
        
        conn.commit()
        cur.close()
        conn.close()
        return order_id
    except Exception as e:
        print(f"Create Order Error: {e}")
        return None

async def create_order(telegram_id, product_name, base_price, unique_code, total_amount):
    return await asyncio.to_thread(_create_order_sync, telegram_id, product_name, base_price, unique_code, total_amount)

def _match_and_complete_order_sync(amount):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT * FROM product_orders 
            WHERE total_amount = %s AND status = 'PENDING' AND expires_at > CURRENT_TIMESTAMP
            LIMIT 1;
        """, (amount,))
        order = cur.fetchone()
        
        if order:
            cur.execute("UPDATE product_orders SET status = 'PAID' WHERE id = %s;", (order["id"],))
            conn.commit()
            
        cur.close()
        conn.close()
        return order
    except Exception as e:
        print(f"Match Order Error: {e}")
        return None

async def match_and_complete_order(amount):
    return await asyncio.to_thread(_match_and_complete_order_sync, amount)

def clean_val(val):
    if not val:
        return ""
    v = str(val).strip().lower()
    if v in ["-", "skip", "lewati", "tidak ada", "ga ada", "ngga ada", "belum ada", "lupa", "kosong"]:
        return ""
    return str(val).strip()

def get_question_text(step, target_lang="ID", status_kerja="Berpengalaman"):
    is_full_en = target_lang == "EN"
    is_fresh = "fresh" in str(status_kerja).lower()
    
    if is_full_en:
        questions = {
            1: "👤 <b>What is your Full Name?</b>\n<i>(Recommended official name for the top of your CV)</i>",
            2: "📧 <b>Your Active Email?</b>\n<i>(Email regularly checked for recruiter replies)</i>",
            3: (
                "💼 <b>Your Work / Organization / Freelance Experience?</b>\n\n"
                "💬 <i>Describe it naturally, e.g.:\n"
                "'Cashier at Toko Makmur 2021-2023, then Sales Admin at PT ABC 2023-2024'\n"
                "I will format it into professional statements!</i>\n\n"
                "<i>(Type '-' or 'Fresh Grad' if none)</i>"
            ),
            4: (
                "🏆 <b>Any projects, organizations, competitions, or key accomplishments?</b>\n<i>(Be honest, I will refine the wording for you!)</i>"
                if is_fresh else
                "🏆 <b>What were your key responsibilities or accomplishments in that role?</b>\n<i>(Be honest, I will refine the wording for you!)</i>"
            ),
            5: "🎓 <b>Your Latest Education?</b>\n<i>(e.g., Bachelor of Management - Universitas Terbuka, 2023)</i>",
            6: "🛠️ <b>Your Top Skills / Expertise?</b>\n<i>(e.g., Ms. Excel, Customer Service, Canvassing, Python)</i>",
            7: "📱 <b>WhatsApp / Phone Number (Optional)</b>\n<i>Recruiters need contact info to reach you if you pass selection. You can enter your number here, or click 'Skip' to add it manually in Word later.</i>",
            8: "📍 <b>Current City of Residence?</b>\n<i>Optional if you prefer not to display your location on your CV right now.</i>",
            9: "🔗 <b>LinkedIn / Portfolio / GitHub Link?</b>\n<i>Optional. If you don't have one yet, feel free to skip!</i>"
        }
    else:
        questions = {
            1: "👤 <b>Siapa nama lengkapmu?</b>\n<i>(Nama resmi yang ingin dicantumkan di paling atas CV)</i>",
            2: "📧 <b>Email aktif yang bisa dihubungi recruiter?</b>\n<i>(contoh: nama@gmail.com)</i>",
            3: (
                "💼 <b>Pengalaman Kerja / Organisasi / Freelance terakhirmu?</b>\n\n"
                "💬 <i>Ceritakan santai saja seperti ke teman, contoh:\n"
                "'Kasir di Toko Makmur 2021-2023, lalu Admin Sales di PT ABC 2023-2024'\n"
                "Nanti saya bantu susun menjadi kalimat profesional!</i>\n\n"
                "<i>(Ketik '-' atau 'Fresh Grad' jika belum ada pengalaman)</i>"
            ),
            4: (
                "🏆 <b>Ada project, organisasi, lomba, magang, atau pencapaian yang pernah kamu lakukan?</b>\n"
                "<i>Ceritakan santai saja. Misalnya: 'Pernah bikin website untuk tugas kuliah' atau 'Aktif panitia kampus'.\n"
                "Kalau belum ada juga tidak masalah, tinggal tekan tombol Lewati 😊</i>"
                if is_fresh else
                "🏆 <b>Apa saja tugas utama atau pencapaianmu di pekerjaan tersebut?</b>\n"
                "<i>(Tulis apa adanya, tidak perlu dibuat-buat. Nanti saya rapikan!)</i>"
            ),
            5: "🎓 <b>Pendidikan terakhirmu?</b>\n<i>(contoh: S1 Manajemen - Universitas Terbuka, 2023)</i>",
            6: "🛠️ <b>Skill / Keahlian utama kamu?</b>\n<i>(contoh: Ms. Excel, Customer Service, Canvassing, Python)</i>",
            7: "📱 <b>Nomor WhatsApp / HP (Opsional)</b>\n<i>Rekruter butuh nomor kontak untuk menghubungi kamu jika lolos seleksi. Kamu bisa masukkan nomor HP di sini, atau tekan tombol [ ⏩ Lewati ] jika ingin mengisinya sendiri nanti di Word.</i>",
            8: "📍 <b>Kota Domisili saat ini?</b>\n<i>Tidak wajib diisi kalau kamu belum ingin mencantumkan lokasi di CV.</i>",
            9: "🔗 <b>Link LinkedIn / Portfolio / GitHub?</b>\n<i>Kalau belum punya, tidak masalah. Kamu bisa menyusul menambahkannya nanti.</i>"
        }
    return questions.get(step, "")

def ai_translate_text(text, target_lang="ID"):
    if not text or target_lang not in ["EN", "HYBRID"]:
        return text
    prompt_text = f"Translate the following job title, education, or skill string to professional English concisely. Return ONLY the translation, no explanation:\n\n{text}"
    if ai_client:
        try:
            res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt_text)
            if res and res.text:
                return res.text.strip()
        except Exception:
            pass
    return text

def ai_generate_summary(position, status_kerja, target_lang="ID"):
    is_en = target_lang in ["EN", "HYBRID"]
    is_fresh = "fresh" in str(status_kerja).lower()
    
    if is_en:
        if is_fresh:
            return f"Motivated graduate aspiring for {position or 'entry-level'} roles. Equipped with strong foundational knowledge, high adaptability, and a commitment to contributing effectively to organizational success."
        else:
            return f"Dedicated professional with experience in {position or 'operational roles'}. Proven track record of executing core responsibilities efficiently and delivering quality results."
    else:
        if is_fresh:
            return f"Lulusan yang memiliki ketertarikan kuat pada bidang {position or 'operasional'}. Memiliki landasan akademis yang baik, cepat beradaptasi, serta berkomitmen memberikan kontribusi kerja terbaik bagi perusahaan."
        else:
            return f"Profesional berpengalaman di bidang {position or 'operasional'} yang terbiasa bekerja secara terstruktur, teliti, serta berdedikasi dalam mencapai target operasional tim."

def ai_rewrite_achievement(text, target_lang="ID"):
    is_en = target_lang in ["EN", "HYBRID"]
    
    if is_en:
        prompt_text = (
            f"Translate and convert the following work/organization experience into 2-4 professional, "
            f"ATS-friendly action bullet points in Full English (using '•' symbol).\n"
            f"STRICT RULE: Do NOT leave any Indonesian words. Translate everything to English.\n"
            f"DO NOT invent facts, numbers, or achievements not present in the input.\n\n"
            f"Input Text: {text}"
        )
    else:
        prompt_text = (
            f"Ubah deskripsi tugas/pengalaman kerja/organisasi berikut menjadi 2-4 poin bullet point (menggunakan simbol •) "
            f"dalam Bahasa Indonesia profesional standar HR yang mudah dibaca sistem rekrutmen modern.\n"
            f"ATURAN MUTLAK: DILARANG MENGARANG FAKTA, ANGKA, ATAU PENGETAHUAN YANG TIDAK ADA DALAM INPUT USER.\n\n"
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
            print(f"[Fallback Alert] Gemini Error: {e}. Beralih ke Groq...")

    if GROQ_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt_text}], "temperature": 0.3}
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=4)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Fallback Alert] Groq Error: {e}")

    lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
    return "\n".join([f"• {line}" for line in lines])

def ai_career_chat_response(user_query, user_context=None):
    pos = user_context.get("target_position", "dunia kerja") if user_context else "dunia kerja"
    status = user_context.get("status_kerja", "Pencari Kerja") if user_context else "Pencari Kerja"
    
    prompt = f"""
    Kamu adalah BoonTrack Career Assistant, teman diskusi karier yang suportif, ramah, dan solutif.
    
    Konteks Pengguna:
    - Target Posisi: {pos}
    - Status: {status}
    
    Pertanyaan/Pesan Pengguna:
    "{user_query}"
    
    Tugasmu:
    Jawab pertanyaan pengguna secara spesifik sesuai apa yang ditanyakan (misal jika menanyakan naik gaji, jawab strategi negosiasi/prestasi kerja secara kontekstual).
    Jawab ringkas, praktis, dan memotivasi (Maksimal 60 kata).
    Gunakan Bahasa Indonesia yang santai dan ramah. Jangan gunakan jawaban kaku/statis.
    """
    
    # 1. COBA GEMINI (Primary Provider)
    if ai_client:
        try:
            res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            if res and res.text:
                return res.text.strip()
        except Exception as e:
            print(f"[Career AI Error] Gemini failed: {e}")

    # 2. COBA GROQ (Secondary Provider - Model Aktif Llama 3.1)
    if GROQ_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.1-8b-instant", 
                "messages": [{"role": "user", "content": prompt}], 
                "temperature": 0.4
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=4)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Career AI Error] Groq failed: {e}")

    # 3. COBA OPENROUTER (Open-Source LLM Fallback)
    if OPENROUTER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "meta-llama/llama-3.1-8b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4
            }
            res = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Career AI Error] OpenRouter failed: {e}")
            
    # 4. DYNAMIC FALLBACK (Jika seluruh API Key/Provider luar tidak merespons)
    return f"Untuk pertanyaan seputar '{user_query}' pada posisi {pos}, kunci utamanya adalah menyajikan bukti pencapaian konkret dan mendiskusikannya saat evaluasi kinerja. Ada hal spesifik lain yang mau kamu bedah? 😊"

def create_cv_docx(user_id, data):
    doc = Document()
    target_lang = data.get("target_lang", "ID")
    status_kerja = data.get("status_kerja", "Berpengalaman")
    is_en = target_lang in ["EN", "HYBRID"]
    
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    name = clean_val(data.get("1", "NAMA LENGKAP"))
    email = clean_val(data.get("2", ""))
    phone = clean_val(data.get("7", ""))
    domicile = clean_val(data.get("8", ""))
    linkedin = clean_val(data.get("9", ""))

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

    # Summary
    add_section_header("PROFESSIONAL SUMMARY" if is_en else "RINGKASAN PROFESIONAL")
    position_text = clean_val(data.get("target_position", ""))
    summary_text = ai_generate_summary(position_text, status_kerja, target_lang)
    p_sum = doc.add_paragraph(summary_text)
    p_sum.paragraph_format.space_after = Pt(8)
    for r in p_sum.runs:
        r.font.name = 'Calibri'
        r.font.size = Pt(10.5)

    # Experience / Projects
    exp = clean_val(data.get("3", ""))
    ach_raw = clean_val(data.get("4", ""))

    if exp:
        section_title = "ORGANIZATION & PROJECTS" if (is_en and "fresh" in str(status_kerja).lower()) else ("PROFESSIONAL EXPERIENCE" if is_en else "PENGALAMAN KERJA / ORGANISASI")
        add_section_header(section_title)
        raw_jobs = [j.strip() for j in re.split(r'[\n|]', exp) if j.strip()]
        
        for job_title in raw_jobs:
            if not job_title:
                continue
            
            translated_title = ai_translate_text(job_title, target_lang) if is_en else job_title
            
            p_job = doc.add_paragraph()
            p_job.paragraph_format.space_before = Pt(6)
            p_job.paragraph_format.space_after = Pt(2)
            r_job = p_job.add_run(translated_title)
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
    edu = clean_val(data.get("5", ""))
    if edu:
        add_section_header("EDUCATION" if is_en else "PENDIDIKAN")
        translated_edu = ai_translate_text(edu, target_lang) if is_en else edu
        p_edu = doc.add_paragraph(translated_edu)
        p_edu.paragraph_format.space_after = Pt(8)
        for r in p_edu.runs:
            r.font.name = 'Calibri'
            r.font.size = Pt(10.5)

    # Skills
    skill = clean_val(data.get("6", ""))
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

# MENU UTAMA CAREER HOME (4 PILIHAN)
def get_career_home_keyboard():
    kbd = InlineKeyboardMarkup(row_width=1)
    kbd.add(
        InlineKeyboardButton("📝 Buat / Edit CV Baru", callback_data="home_create_cv"),
        InlineKeyboardButton("📚 Ebook & Program Digital", callback_data="home_digital_products"),
        InlineKeyboardButton("🎁 Cek Referral Saya", callback_data="home_check_ref"),
        InlineKeyboardButton("💼 Tanya Seputar Dunia Kerja", callback_data="home_career_qa")
    )
    return kbd

async def process_and_send_cv(message: types.Message, user_id: int, user_data: dict):
    user_state[user_id]["step"] = 0
    await save_dropoff(user_id, TOTAL_STEPS, user_data)
    
    processing_msg = await message.reply(
        "⏳ <b>Merapikan & menyusun CV kamu agar mudah dibaca sistem rekrutmen...</b>\n"
        "Mohon tunggu sekitar 15-20 detik ya!",
        parse_mode="HTML"
    )

    try:
        file_path = await asyncio.to_thread(create_cv_docx, user_id, user_data)
        position = clean_val(user_data.get("target_position", "General"))
        await save_cv_version(user_id, position, user_data)
        await track_event(user_id, "resume_generated", meta={"position": position})

        document = InputFile(file_path)
        user_name = user_data.get("nama_panggilan", message.from_user.first_name or "Teman")

        await bot.send_document(
            chat_id=user_id,
            document=document,
            caption=f"🎉 <b>CV kamu sudah selesai, {user_name}!</b>\n\n"
                    "File dalam format Word (.docx) sudah saya kirim di atas. Bisa kamu edit kapan saja!",
            parse_mode="HTML"
        )
        
        try:
            await bot.delete_message(chat_id=user_id, message_id=processing_msg.message_id)
        except Exception:
            pass

        value_text = (
            f"💡 <b>Tips Penting Sebelum Melamar ({position}):</b>\n\n"
            "1. Gunakan subjek email jernih: <code>[Posisi] - [Nama Kamu]</code>\n"
            "2. Jangan biarkan body email kosong (tuliskan Surat Lamaran Singkat)\n"
            "3. Cantumkan bukti angka/pencapaian kecil jika ada saat interview nanti.\n\n"
            "CV ini sudah bisa kamu edit kapan saja di Word jika ada bagian yang ingin kamu sesuaikan kembali. 🚀"
        )
        await bot.send_message(user_id, value_text, parse_mode="HTML")

        monetize_text = (
            "❤️ <b>Dukung BoonTrack Supaya Tetap Gratis</b>\n\n"
            "BoonTrack dikembangkan mandiri agar tetap gratis bagi pencari kerja. "
            "Kalau BoonTrack membantu kamu hari ini, kamu boleh traktir kami kopi seikhlasnya via QRIS di bawah. (Tidak Wajib)"
        )
        await bot.send_message(user_id, monetize_text, parse_mode="HTML")

        possible_qris_paths = [QRIS_IMAGE_PATH, "/app/qris.jpg", "qris.jpg"]
        found_qris = next((p for p in possible_qris_paths if os.path.exists(p)), None)
        if found_qris:
            await bot.send_photo(chat_id=user_id, photo=InputFile(found_qris), caption="Dukungan donasi seikhlasnya via QRIS. Terima kasih! 🙏")

        home_text = (
            f"Semoga CV ini jadi langkah awal yang bagus buat kariermu, {user_name}! 🚀\n\n"
            "Kalau kamu mau bikin versi baru, cek referral, atau sekadar tanya-tanya soal dunia kerja, saya tetap di sini ya. 😊\n\n"
            "👇 <b>Pilih menu di bawah atau langsung ketik pertanyaanmu:</b>"
        )
        await bot.send_message(user_id, home_text, reply_markup=get_career_home_keyboard(), parse_mode="HTML")

        if os.path.exists(file_path):
            os.remove(file_path)

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

# COMMAND HANDLERS
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

    if progress and progress.get("last_step") == TOTAL_STEPS:
        user_state[user_id] = {"step": 0, "data": progress.get("data", {}), "meta": meta_data}
        home_msg = (
            f"Halo lagi, {first_name}! 👋\n\n"
            "Ada yang bisa saya bantu untuk persiapan kariermu hari ini?\n\n"
            "👇 <b>Pilih menu di bawah atau langsung ketik pertanyaanmu:</b>"
        )
        await message.reply(home_msg, reply_markup=get_career_home_keyboard(), parse_mode="HTML")
        return

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
    
    msg_1 = (
        "<b>Saya BoonTrack Career Assistant.</b>\n"
        "Saya akan membantu meningkatkan peluang kamu dipanggil interview.\n\n"
        "Sebelum mulai...\n"
        "Boleh kenalan dulu?\n"
        "Ini dengan siapa?"
    )
    await message.reply(msg_1, parse_mode="HTML")

@dp.callback_query_handler(lambda c: c.data in [
    "status_fresh", "status_exp", "lang_id", "lang_en", "lang_hybrid", 
    "skip_optional", "resume_flow", "restart_flow",
    "home_create_cv", "home_check_ref", "home_career_qa",
    "home_digital_products", "buy_test_cv_template", "buy_ebook_interview", "home_back_main"
])
async def handle_callback_navigation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    code = callback_query.data
    
    await bot.edit_message_reply_markup(user_id, callback_query.message.message_id, reply_markup=None)
    if user_id not in user_state:
        user_state[user_id] = {"step": 0, "data": {}}
        
    user_data = user_state[user_id].get("data", {})
    user_name = user_data.get("nama_panggilan", callback_query.from_user.first_name or "Teman")

    # KATALOG PRODUK DIGITAL
    if code == "home_digital_products":
        kbd_products = InlineKeyboardMarkup(row_width=1)
        kbd_products.add(
            InlineKeyboardButton("📄 Template CV ATS-Friendly (Rp1.000 - Tes Live)", callback_data="buy_test_cv_template"),
            InlineKeyboardButton("📘 Ebook Panduan Lolos Interview & Gaji (Rp49.000)", callback_data="buy_ebook_interview"),
            InlineKeyboardButton("🔙 Kembali ke Menu Utama", callback_data="home_back_main")
        )
        msg_catalog = (
            "🚀 <b>PROGRAM & PRODUK DIGITAL KARIR</b>\n\n"
            "Tingkatkan peluang dipanggil dan lolos kerja dengan panduan eksklusif dari BoonTrack:\n\n"
            "📄 <b>Template CV Profesional ATS-Friendly (Mode Tes Live)</b>\n"
            "• Template Word (.docx) siap pakai yang lolos scan HRIS\n"
            "• <i>Produk khusus pengujian live transfer Rp1.000!</i>\n\n"
            "📖 <b>Ebook Panduan Lolos Interview & Negosiasi Gaji</b>\n"
            "• Rangkuman pertanyaan jebakan HR + cara jawabnya\n"
            "• Template surat lamaran & email melamar kerja\n"
            "• Strategi negosiasi gaji untuk Fresh Graduate & Exp\n\n"
            "👇 <i>Pilih produk di bawah untuk membeli secara otomatis:</i>"
        )
        await bot.send_message(user_id, msg_catalog, reply_markup=kbd_products, parse_mode="HTML")

    # PRODUK 1: TEMPLATE CV (PRODUK TES RP1.000)
    elif code == "buy_test_cv_template":
        base_price = 1000
        unique_code = random.randint(100, 500)
        total_amount = base_price + unique_code
        
        await create_order(user_id, "Template CV ATS (Tes)", base_price, unique_code, total_amount)
        
        msg_checkout = (
            f"🛒 <b>CHECKOUT TEST: Template CV ATS-Friendly</b>\n\n"
            f"💵 Harga Normal: <s>Rp25.000</s>\n"
            f"🎉 <b>Total Transfer (Mode Tes Live Rp1.xxx):</b>\n"
            f"<code>{total_amount}</code> 👈 <i>(Tekan/salin angka ini)</i>\n\n"
            f"👇 <b>Cara Pembayaran Tes:</b>\n"
            f"1. Scan QRIS di atas atau transfer via DANA Bisnis.\n"
            f"2. Masukkan nominal <b>PRESISI <code>{total_amount}</code></b> (sampai 3 digit terakhir).\n"
            f"3. Dalam 1-3 detik setelah transfer, file Template CV otomatis terkirim di sini! 🚀\n\n"
            f"⏳ <i>Berlaku selama 15 menit.</i>"
        )
        
        possible_qris_paths = [QRIS_IMAGE_PATH, "/app/qris.jpg", "qris.jpg"]
        found_qris = next((p for p in possible_qris_paths if os.path.exists(p)), None)
        if found_qris:
            await bot.send_photo(chat_id=user_id, photo=InputFile(found_qris), caption=msg_checkout, parse_mode="HTML")
        else:
            await bot.send_message(user_id, msg_checkout, parse_mode="HTML")

    # PRODUK 2: EBOOK INTERVIEW (PRODUK UTAMA RP49.000)
    elif code == "buy_ebook_interview":
        base_price = 50000
        unique_code = random.randint(100, 999)
        total_amount = base_price - unique_code
        
        await create_order(user_id, "Ebook Interview", base_price, unique_code, total_amount)
        
        msg_checkout = (
            f"🛒 <b>CHECKOUT: Ebook Panduan Lolos Interview</b>\n\n"
            f"💵 Harga Normal: <s>Rp{base_price:,}</s>\n"
            f"🎉 <b>Total Transfer (Dapat Potongan):</b>\n"
            f"<code>{total_amount}</code> 👈 <i>(Tekan/salin angka ini)</i>\n\n"
            f"👇 <b>Cara Pembayaran:</b>\n"
            f"1. Scan QRIS di atas atau transfer via DANA Bisnis.\n"
            f"2. Masukkan nominal <b>PRESISI <code>{total_amount}</code></b> (sampai 3 digit terakhir).\n"
            f"3. Dalam 1-3 detik setelah transfer, Ebook otomatis terkirim di sini! 🚀\n\n"
            f"⏳ <i>Nominal unik ini berlaku selama 15 menit.</i>"
        )
        
        possible_qris_paths = [QRIS_IMAGE_PATH, "/app/qris.jpg", "qris.jpg"]
        found_qris = next((p for p in possible_qris_paths if os.path.exists(p)), None)
        if found_qris:
            await bot.send_photo(chat_id=user_id, photo=InputFile(found_qris), caption=msg_checkout, parse_mode="HTML")
        else:
            await bot.send_message(user_id, msg_checkout, parse_mode="HTML")

    elif code in ["home_back_main", "restart_flow"]:
        user_state[user_id] = {"step": 0, "data": {}}
        await bot.send_message(user_id, "👋 <b>Kembali ke Menu Utama:</b>", reply_markup=get_career_home_keyboard(), parse_mode="HTML")

    elif code == "home_create_cv":
        user_state[user_id] = {"step": "ONBOARDING_NAMA", "data": {}}
        await save_dropoff(user_id, 0, {})
        msg_restart = (
            "Sip! Kita susun versi CV baru ya. 👍\n\n"
            "Boleh kenalan lagi atau mau pakai nama panggilan sebelumnya?\n"
            "<b>Ini dengan siapa?</b>"
        )
        await bot.send_message(user_id, msg_restart, parse_mode="HTML")

    elif code == "home_check_ref":
        total_refs = await count_referrals(user_id)
        bot_info = await bot.get_me()
        user_ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        
        ref_msg = (
            "🎁 <b>REFERRAL & BONUS PORTFOLIO WEBSITE</b>\n\n"
            f"📊 <b>Progress Referral Kamu: {total_refs} / 3</b>\n\n"
            "Ajak 3 temanmu membuat CV di BoonTrack, dan kami akan buatkan **Website Portfolio Pribadi Gratis**!\n"
            "<i>Contoh: https://rayigemilang.cv.boontrack.com</i>\n\n"
            f"👇 Bagikan link referral-mu ke teman:\n"
            f"<code>{user_ref_link}</code>"
        )
        await bot.send_message(user_id, ref_msg, reply_markup=get_career_home_keyboard(), parse_mode="HTML")

    elif code == "home_career_qa":
        qa_msg = (
            "💬 <b>Tanya Seputar Dunia Kerja</b>\n\n"
            "Kamu bisa tanyakan apa saja tentang persiapan kerja, tips interview, negosiasi gaji, atau kualifikasi posisi impianmu.\n\n"
            "<i>Ketik saja pertanyaanmu langsung di obrolan ini ya!</i> 👇"
        )
        await bot.send_message(user_id, qa_msg, parse_mode="HTML")

    elif code in ["status_fresh", "status_exp"]:
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

    elif code in ["lang_id", "lang_en", "lang_hybrid"]:
        target_lang = "ID" if code == "lang_id" else ("EN" if code == "lang_en" else "HYBRID")
        user_data["target_lang"] = target_lang
        
        if code == "lang_hybrid":
            msg_lang = (
                "Sip! Pilihan cerdas 🌐\n"
                "CV kamu akan dibuat dalam <b>English profesional</b>, tapi selama pengisian kamu <b>bebas cerita dalam Bahasa Indonesia</b>.\n"
                "Nanti saya bantu terjemahkan dan rapikan menjadi bahasa CV yang profesional! 😊"
            )
        elif code == "lang_en":
            msg_lang = (
                "Great! We will conduct our conversation and build your CV in <b>English</b> 🇬🇧\n"
                "Take your time, I am here to help you refine your details into professional CV statements! 😊"
            )
        else:
            msg_lang = (
                "Siap! Percakapan dan CV kamu akan dibuat dalam <b>Bahasa Indonesia</b> 🇮🇩"
            )
        
        await bot.send_message(user_id, msg_lang, parse_mode="HTML")
        
        user_state[user_id]["step"] = 1
        await save_dropoff(user_id, 1, user_data)
        
        reassurance_msg = (
            "Sip, kita mulai pelan-pelan ya 😊\n"
            "🔒 <i>Data kamu digunakan untuk membantu membuat dan menyimpan progres CV-mu. Kami tidak meminta data yang tidak diperlukan untuk proses ini.</i>\n\n"
            "Kalau ada informasi yang belum kamu punya, beberapa bagian nanti bisa dilewati. "
            "Cerita saja seperti ngobrol biasa. Nanti saya yang bantu merapikannya."
        )
        await bot.send_message(user_id, reassurance_msg, parse_mode="HTML")
        
        status_kerja = user_data.get("status_kerja", "Berpengalaman")
        first_q = f"{get_progress_bar(1)}\n{get_question_text(1, target_lang, status_kerja)}"
        await bot.send_message(user_id, first_q, parse_mode="HTML")

    elif code == "skip_optional":
        current_step = user_state[user_id].get("step", 1)
        if isinstance(current_step, int):
            user_data[str(current_step)] = ""
            
            if current_step >= TOTAL_STEPS:
                await process_and_send_cv(callback_query.message, user_id, user_data)
            else:
                next_step = current_step + 1
                user_state[user_id]["step"] = next_step
                await save_dropoff(user_id, next_step, user_data)
                
                target_lang = user_data.get("target_lang", "ID")
                status_kerja = user_data.get("status_kerja", "Berpengalaman")
                kbd = None
                if next_step in [7, 8, 9]:
                    kbd = InlineKeyboardMarkup().add(InlineKeyboardButton("⏩ Lewati Langkah Ini", callback_data="skip_optional"))
                    
                await bot.send_message(
                    user_id,
                    f"{get_progress_bar(next_step)}\n{get_question_text(next_step, target_lang, status_kerja)}",
                    reply_markup=kbd,
                    parse_mode="HTML"
                )

    elif code == "resume_flow":
        state = user_state.get(user_id, {"step": 1, "data": {}})
        step = state["step"]
        target_lang = state.get("data", {}).get("target_lang", "ID")
        status_kerja = state.get("data", {}).get("status_kerja", "Berpengalaman")
        await bot.send_message(
            user_id,
            f"Sip, mari kita lanjutkan! 👍\n\n{get_progress_bar(step)}\n{get_question_text(step, target_lang, status_kerja)}",
            parse_mode="HTML"
        )

@dp.message_handler(commands=['cancel'])
async def cancel_handler(message: types.Message):
    user_id = message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    await save_dropoff(user_id, 0, {})
    await message.reply("❌ <b>Proses pembuatan CV dibatalkan.</b>\n\nKetik /start kapan saja untuk kembali ke Menu Utama!", parse_mode="HTML")

@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id not in user_state:
        progress, _ = await get_user_history(user_id)
        if progress and progress.get("last_step", 0) > 0:
            user_state[user_id] = {"step": progress["last_step"], "data": progress.get("data", {})}
        else:
            user_state[user_id] = {"step": 0, "data": {}}

    current_step = user_state[user_id].get("step", 0)
    user_data = user_state[user_id].get("data", {})

    if current_step == 0:
        await track_event(user_id, "career_ai_query", meta={"query": text})
        ai_reply = await asyncio.to_thread(ai_career_chat_response, text, user_data)
        
        await message.reply(
            f"{ai_reply}\n\n<i>Mau lanjut bikin CV baru atau cek referral? Pilih tombol di bawah ya!</i> 👇",
            reply_markup=get_career_home_keyboard(),
            parse_mode="HTML"
        )
        return

    if current_step == "ONBOARDING_NAMA":
        user_data["nama_panggilan"] = text
        user_state[user_id]["step"] = "ONBOARDING_STATUS"
        
        kbd_status = InlineKeyboardMarkup(row_width=1)
        kbd_status.add(
            InlineKeyboardButton("🔹 Fresh Graduate / Belum berpengalaman", callback_data="status_fresh"),
            InlineKeyboardButton("🔹 Sudah berpengalaman (Cari kerja baru)", callback_data="status_exp")
        )
        msg_2 = f"Halo {text} 😊\n\nBoleh saya tahu status kamu saat ini?"
        await message.reply(msg_2, parse_mode="HTML")
        return

    if current_step == "ONBOARDING_POSISI":
        user_data["target_position"] = text
        user_state[user_id]["step"] = "SELECT_LANGUAGE"
        
        prompt_insight = f"""
        Pengguna melamar posisi: "{text}".
        
        Tugasmu:
        1. Jelaskan secara singkat peran/tugas utama dari posisi "{text}".
        2. Tuliskan 2-3 kualifikasi, karakter, atau kemampuan spesifik yang PALING DISUKAI dan dinilai oleh recruiter untuk posisi ini (misal: ketelitian, kerapian, komunikasi, kejujuran, atau keahlian teknis tertentu).
        
        Aturan Penulisan:
        - Tulis dalam 1-2 kalimat yang ringkas dan menyatu.
        - Maksimal 30 kata.
        - Gunakan Bahasa Indonesia ramah dan profesional.
        - DILARANG menggunakan bullet point atau tanda bintang (*).
        - DILARANG membahas posisi selain "{text}".
        """

        insight_text = ""

        if ai_client:
            try:
                res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt_insight)
                if res and res.text:
                    insight_text = res.text.strip()
            except Exception as e:
                print(f"[Fallback Alert] Gemini Error on Insight: {e}")

        if not insight_text and GROQ_API_KEY:
            try:
                headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
                payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt_insight}], "temperature": 0.3}
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=3)
                if res.status_code == 200:
                    insight_text = res.json()['choices'][0]['message']['content'].strip()
            except Exception as e:
                print(f"[Fallback Alert] Groq Error on Insight: {e}")

        if not insight_text:
            insight_text = f"Untuk posisi {text}, recruiter biasanya sangat menghargai kedisiplinan, kerapian, serta tanggung jawab kerja yang baik."

        kbd_lang = InlineKeyboardMarkup(row_width=1)
        kbd_lang.add(
            InlineKeyboardButton("🌐 CV English (Ngobrol B. Indonesia)", callback_data="lang_hybrid"),
            InlineKeyboardButton("🇮🇩 CV Bahasa Indonesia", callback_data="lang_id"),
            InlineKeyboardButton("🇬🇧 Full English", callback_data="lang_en")
        )
        
        msg_insight = (
            f"Oke, <b>{text}</b> 👍\n\n"
            f"💡 <b>Sedikit insight untuk kamu:</b>\n{insight_text}\n\n"
            "Nah, berdasarkan itu saya bisa bantu susun CV yang menonjolkan keahlian tersebut.\n\n"
            "Sebelum kita lanjut, CV kamu ingin dibuat dalam bahasa apa?"
        )
        await message.reply(msg_insight, reply_markup=kbd_lang, parse_mode="HTML")
        return

    if current_step == "SELECT_LANGUAGE":
        await message.reply("Silakan <b>pilih salah satu bahasa di atas</b> ya 👆", parse_mode="HTML")
        return

    if isinstance(current_step, int) and current_step > 0:
        target_lang = user_data.get("target_lang", "ID")
        status_kerja = user_data.get("status_kerja", "Berpengalaman")

        if current_step == 2:
            email_clean = text.strip().lower()
            if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email_clean):
                await message.reply(
                    "⚠️ <b>Format email belum sesuai.</b>\n"
                    "Mohon masukkan email yang valid (contoh: <code>nama@gmail.com</code>).",
                    parse_mode="HTML"
                )
                return

        if current_step == 7:
            phone_digits = re.sub(r"\D", "", text)
            if len(phone_digits) < 10 or len(phone_digits) > 14:
                kbd_skip = InlineKeyboardMarkup().add(InlineKeyboardButton("⏩ Lewati Langkah Ini", callback_data="skip_optional"))
                await message.reply(
                    "⚠️ <b>Nomor HP/WhatsApp tidak valid.</b>\n"
                    "Nomor HP harus terdiri dari <b>10 sampai 14 digit</b> (contoh: <code>081234567890</code>).\n\n"
                    "Silakan ketik ulang atau klik tombol di bawah untuk melewati:",
                    reply_markup=kbd_skip,
                    parse_mode="HTML"
                )
                return
            text = phone_digits

        user_data[str(current_step)] = text
        await track_event(user_id, f"step_{current_step}_completed")

        if current_step < TOTAL_STEPS:
            next_step = current_step + 1
            user_state[user_id]["step"] = next_step
            await save_dropoff(user_id, next_step, user_data)
            
            kbd = None
            if next_step in [7, 8, 9]:
                kbd = InlineKeyboardMarkup().add(InlineKeyboardButton("⏩ Lewati Langkah Ini", callback_data="skip_optional"))

            await message.reply(
                f"{get_progress_bar(next_step)}\n{get_question_text(next_step, target_lang, status_kerja)}",
                reply_markup=kbd,
                parse_mode="HTML"
            )
        else:
            await process_and_send_cv(message, user_id, user_data)

# WEBHOOK PENERIMA NOTIFIKASI DANA
async def dana_webhook_handler(request):
    try:
        data = await request.json()
        source = data.get("source", "")
        message = data.get("message", "")
        
        if "dana" not in source.lower():
            return web.json_response({"status": "ignored"}, status=400)
            
        clean_text = message.replace(".", "").replace(",", "")
        match = re.search(r"Rp\s*(\d+)", clean_text, re.IGNORECASE)
        
        if match:
            incoming_amount = int(match.group(1))
            order = await match_and_complete_order(incoming_amount)
            
            if order:
                buyer_id = order["telegram_id"]
                product = order["product_name"]
                
                success_msg = (
                    f"🎉 <b>PEMBAYARAN DITERIMA!</b>\n\n"
                    f"Terima kasih! Pembayaran sebesar <b>Rp{incoming_amount:,}</b> untuk <b>{product}</b> telah terkonfirmasi otomatis.\n\n"
                    f"📥 <b>Akses Produk Kamu:</b>\n"
                    f"https://cvats.boontrack.com/ebook-interview-boontrack.pdf\n\n"
                    f"Semoga bermanfaat dan sukses kariernya! 🚀"
                )
                await bot.send_message(chat_id=buyer_id, text=success_msg, parse_mode="HTML")
                return web.json_response({"status": "success", "order_id": order["order_id"]}, status=200)

        return web.json_response({"status": "no_matching_order"}, status=200)
    except Exception as e:
        print(f"Webhook Exception: {e}")
        return web.json_response({"status": "error"}, status=500)

async def health_check_handler(request):
    return web.json_response({"status": "healthy", "message": "Render is awake!"}, status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check_handler)
    app.router.add_get('/health', health_check_handler)
    app.router.add_post('/webhook/dana', dana_webhook_handler)
    
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