from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.core.database import save_user, track_event, get_user_history, save_dropoff
from app.handlers.admin_handler import admin_handler

TOTAL_STEPS = 10

CV_QUESTIONS = {
    1: "👤 Siapa nama lengkapmu?",
    2: "📧 Email aktif yang bisa dihubungi recruiter?",
    3: "📱 Nomor WhatsApp / HP aktif? <i>(contoh: 081234567890)</i>",
    4: "📍 Di kota mana kamu berdomisili saat ini?",
    5: "🔗 Link akun LinkedIn kamu? <i>(Ketik '-' jika tidak ada)</i>",
    6: "🎯 Posisi/pekerjaan apa yang ingin kamu lamar?",
    7: (
        "💼 <b>Pengalaman kerja terakhirmu?</b>\n\n"
        "Tuliskan nama posisi, tempat kerja, dan tahunnya.\n"
        "Jika ada lebih dari 1 pekerjaan, pisahkan dengan <b>pindah baris (Enter)</b>, tanda <b>garis tegak ('|')</b>, atau <b>koma (',')</b>.\n\n"
        "<i>Contoh:</i>\n"
        "Kasir — Toko Makmur (2020 - 2022)\n"
        "Staff Admin — PT ABC (2022 - 2024)\n\n"
        "<i>(Ketik '-' jika fresh graduate)</i>"
    ),
    8: "🏆 Ceritakan tugas atau pencapaian utamamu di pekerjaan tersebut. <i>(Tulis santai saja, nanti saya bantu rapikan menjadi poin-poin profesional)</i>",
    9: "🎓 Pendidikan terakhirmu? <i>(contoh: S1 Manajemen, Universitas Terbuka, 2023)</i>",
    10: "🛠️ Apa saja skill atau keahlian utamamu? <i>(contoh: Microsoft Excel, Pelayanan Pelanggan, Kasir)</i>"
}

def get_progress_bar(step: int) -> str:
    return f"📍 <b>Langkah {step} dari {TOTAL_STEPS}</b>\n━━━━━━━━━━"

async def send_welcome(message: types.Message, user_state: dict):
    user_id = message.from_user.id
    text = message.text.strip()

    # ----------------------------------------------------
    # 🚨 ADMIN COMMAND INTERCEPT (Sprint C)
    # ----------------------------------------------------
    if text.startswith("/analytics") or text.startswith("/admin"):
        response_text = await admin_handler.handle_admin_command(user_id, text)
        await message.reply(response_text, parse_mode="Markdown")
        return

    # ----------------------------------------------------
    # ALUR UTAMA /START & PARSING UTM
    # ----------------------------------------------------
    text_parts = text.split()
    args = text_parts[1] if len(text_parts) > 1 else "direct"

    # 1. PARSING FULL UTM & REFERRAL FIRST
    if args.startswith("ref_"):
        meta_data = {
            "first_source": "referral",
            "latest_source": "referral",
            "utm_source": "referral", 
            "utm_medium": "word_of_mouth",
            "utm_campaign": "user_referral",
            "utm_content": "none",
            "referrer_id": args.replace("ref_", "")
        }
    else:
        payload = args.split("__")
        source_val = payload[0] if len(payload) > 0 else "direct"
        meta_data = {
            "first_source": source_val,
            "latest_source": source_val,
            "utm_source": source_val,
            "utm_medium": payload[1] if len(payload) > 1 else "none",
            "utm_campaign": payload[2] if len(payload) > 2 else "none",
            "utm_content": payload[3] if len(payload) > 3 else "none"
        }

    # 2. SAVE USER & TRACK EVENT SETELAH META_DATA TERDEFINISI
    await save_user(message.from_user, meta=meta_data)
    await track_event(user_id, "start", meta=meta_data)
    
    progress, last_cv = await get_user_history(user_id)
    first_name = message.from_user.first_name or "Teman"

    if progress and 1 < progress.get("last_step", 0) < TOTAL_STEPS:
        last_step = progress["last_step"]
        saved_data = progress.get("data", {})
        user_state[user_id] = {"step": last_step, "data": saved_data}
        
        kbd = InlineKeyboardMarkup(row_width=2)
        kbd.add(
            InlineKeyboardButton("▶️ Lanjutkan CV", callback_data="resume_flow"),
            InlineKeyboardButton("🔄 Mulai Baru", callback_data="restart_flow")
        )
        
        await message.reply(
            f"Halo lagi, {first_name}! 👋\n\n"
            f"Kemarin kita sempat membuat CV sampai di <b>Langkah {last_step} dari {TOTAL_STEPS}</b>.\n\n"
            "Mau kita tuntaskan sekarang agar CV kamu siap dipakai melamar kerja?\n\n"
            "💡 <i>Tips: Ketik /cancel kapan saja jika ingin membatalkan atau mengulang dari awal.</i>",
            reply_markup=kbd,
            parse_mode="HTML"
        )
        return

    if last_cv:
        last_pos = last_cv.get("position", "pekerjaan kamu")
        kbd = InlineKeyboardMarkup(row_width=2)
        kbd.add(
            InlineKeyboardButton("📄 Buat CV Posisi Lain", callback_data="restart_flow"),
            InlineKeyboardButton("💡 FAQ & Tips ATS", callback_data="show_faq")
        )
        
        await message.reply(
            f"Halo kembali, {first_name}! 👋\n\n"
            f"Terakhir kali kita membuat CV untuk posisi <b>{last_pos}</b>.\n"
            "Ada yang bisa saya bantu hari ini?\n\n"
            "💡 <i>Tips: Ketik /cancel kapan saja untuk membatalkan proses.</i>",
            reply_markup=kbd,
            parse_mode="HTML"
        )
        return

    user_state[user_id] = {"step": 1, "data": {}}
    await save_dropoff(user_id, 1, {})
    
    greeting = (
        "<b>👋 Halo! Saya BoonTrack Assistant.</b>\n\n"
        "Saya akan membantumu membuat CV yang bersih, profesional, dan mudah dibaca oleh HR serta sistem rekrutmen perusahaan modern (seperti JobStreet, LinkedIn, Glints, dll).\n\n"
        "<b>📌 Catatan Penting:</b>\n"
        "CV ini sengaja dibuat <b>tanpa foto & desain berlebihan</b> agar fokus utama HR langsung ke pengalaman kerjamu, dan peluang lolos seleksi awal jauh lebih besar.\n\n"
        "Cukup jawab beberapa pertanyaan singkat (~5 menit) dan hasilnya siap di-download dalam format Word (.docx).\n\n"
        "💡 <i>Tips: Ketik /cancel kapan saja jika ingin membatalkan atau mengulang dari awal.</i>\n\n"
        "Kalau sudah siap, kita mulai ya 😃\n\n"
        f"{get_progress_bar(1)}\n"
        f"{CV_QUESTIONS[1]}"
    )
    await message.reply(greeting, parse_mode="HTML")

async def cancel_handler(message: types.Message, user_state: dict):
    user_id = message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    await save_dropoff(user_id, 0, {})
    await message.reply("❌ <b>Proses pembuatan CV dibatalkan.</b>\n\nKetik /start kapan saja jika ingin memulai kembali dari awal!", parse_mode="HTML")

async def handle_callback_navigation(callback_query: types.CallbackQuery, user_state: dict, bot):
    user_id = callback_query.from_user.id
    code = callback_query.data
    
    await bot.edit_message_reply_markup(user_id, callback_query.message.message_id, reply_markup=None)
    
    if code == "resume_flow":
        state = user_state.get(user_id, {"step": 1, "data": {}})
        step = state["step"]
        await bot.send_message(
            user_id,
            f"Sip, mari kita lanjutkan! 👍\n\n{get_progress_bar(step)}\n{CV_QUESTIONS[step]}",
            parse_mode="HTML"
        )
    elif code == "restart_flow":
        user_state[user_id] = {"step": 1, "data": {}}
        await save_dropoff(user_id, 1, {})
        await bot.send_message(
            user_id,
            f"Sip, kita mulai dari awal ya! 😊\n\n{get_progress_bar(1)}\n{CV_QUESTIONS[1]}",
            parse_mode="HTML"
        )
    elif code == "show_faq":
        faq_text = (
            "❓ <b>Kenapa CV BoonTrack Tanpa Foto?</b>\n"
            "Banyak perusahaan saat ini lebih berfokus pada skill & pengalaman. Format bersih tanpa foto juga memastikan CV mudah dibaca sistem ATS tanpa error.\n\n"
            "❓ <b>Apakah File .docx Bisa Di-edit?</b>\n"
            "Bisa banget! Kamu bebas mengedit kembali tulisan atau menambah foto secara manual di Microsoft Word jika melamar ke perusahaan yang mewajibkannya."
        )
        await bot.send_message(user_id, faq_text, parse_mode="HTML")