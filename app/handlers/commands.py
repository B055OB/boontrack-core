from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.core.database import save_user, track_event, get_user_history, save_dropoff
from app.handlers.admin_handler import admin_handler

TOTAL_STEPS = 10

# INISIALISASI GLOBAL STATE DI SINI AGAR TIDAK LUPA
user_state = {}

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

async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text.startswith("/analytics") or text.startswith("/admin"):
        response_text = await admin_handler.handle_admin_command(user_id, text)
        await message.reply(response_text, parse_mode="Markdown")
        return

    text_parts = text.split()
    args = text_parts[1] if len(text_parts) > 1 else "direct"

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

    await save_user(message.from_user, meta=meta_data)
    await track_event(user_id, "start", meta=meta_data)
    
    progress, last_cv = await get_user_history(user_id)
    first_name = message.from_user.first_name or "Teman"

    # Cek sinkronisasi dari database jika memori runtime kosong
    saved_data = progress.get("data", {}) if progress else {}
    if user_id not in user_state:
        user_state[user_id] = {"step": progress.get("last_step", 1) if progress else 1, "data": saved_data}

    if progress and 1 < progress.get("last_step", 0) < TOTAL_STEPS:
        last_step = progress["last_step"]
        user_state[user_id] = {"step": last_step, "data": saved_data}
        
        kbd = InlineKeyboardMarkup(row_width=2)
        kbd.add(
            InlineKeyboardButton("▶️ Lanjutkan CV", callback_data="resume_flow"),
            InlineKeyboardButton("🔄 Mulai Baru", callback_data="restart_flow")
        )
        
        await message.reply(
            f"Halo lagi, {first_name}! 👋\n\n"
            f"Kemarin kita sempat membuat CV sampai di <b>Langkah {last_step} dari {TOTAL_STEPS}</b>.\n\n"
            "Mau kita tuntaskan sekarang agar CV kamu siap dipakai melamar kerja?",
            reply_markup=kbd,
            parse_mode="HTML"
        )
        return

    user_state[user_id] = {"step": 1, "data": {}}
    await save_dropoff(user_id, 1, {})
    
    greeting = (
        "<b>👋 Halo! Saya BoonTrack Assistant.</b>\n\n"
        "Saya akan membantumu membuat CV yang bersih, profesional, dan mudah dibaca oleh HR serta sistem rekrutmen perusahaan modern.\n\n"
        f"{get_progress_bar(1)}\n"
        f"{CV_QUESTIONS[1]}"
    )
    await message.reply(greeting, parse_mode="HTML")

async def cancel_handler(message: types.Message):
    user_id = message.from_user.id
    user_state[user_id] = {"step": 0, "data": {}}
    await save_dropoff(user_id, 0, {})
    await message.reply("❌ <b>Proses pembuatan CV dibatalkan.</b>", parse_mode="HTML")

async def handle_callback_navigation(callback_query: types.CallbackQuery, bot):
    user_id = callback_query.from_user.id
    code = callback_query.data
    
    await bot.edit_message_reply_markup(user_id, callback_query.message.message_id, reply_markup=None)
    
    if user_id not in user_state:
        progress, _ = await get_user_history(user_id)
        saved_data = progress.get("data", {}) if progress else {}
        user_state[user_id] = {"step": progress.get("last_step", 0) if progress else 0, "data": saved_data}
        
    user_data = user_state[user_id].get("data", {})
    
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
    elif code == "trigger_cv_review":
        # Ambil ringkasan teks dari data step 7, 8, atau 10
        cv_text_summary = f"{user_data.get('7', '')} {user_data.get('8', '')} {user_data.get('10', '')}"
        
        # Fallback cadangan: cek juga ke database jika memori runtime kosong
        if not cv_text_summary.strip():
            progress, _ = await get_user_history(user_id)
            if progress and progress.get("data"):
                user_data = progress.get("data")
                user_state[user_id]["data"] = user_data
                cv_text_summary = f"{user_data.get('7', '')} {user_data.get('8', '')} {user_data.get('10', '')}"

        if not cv_text_summary.strip():
            kbd_empty = InlineKeyboardMarkup(row_width=1)
            kbd_empty.add(
                InlineKeyboardButton("📝 Buat / Edit CV Baru", callback_data="restart_flow"),
                InlineKeyboardButton("🏠 Menu Utama", callback_data="home_back_main")
            )
            await bot.send_message(
                user_id,
                "⚠️ <b>Kamu belum mengisi data CV di BoonTrack.</b>\n\nSilakan klik tombol di bawah untuk mulai membuat CV baru:",
                reply_markup=kbd_empty,
                parse_mode="HTML"
            )
            return
        await bot.send_message(user_id, "🔍 <b>Menganalisis kualitas CV kamu...</b>", parse_mode="HTML")
    elif code == "home_back_main":
        current_data = user_state.get(user_id, {}).get("data", {})
        user_state[user_id] = {"step": 0, "data": current_data}
        kbd = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("📝 Buat / Edit CV Baru", callback_data="restart_flow"),
            InlineKeyboardButton("🔍 Review CV Saya", callback_data="trigger_cv_review")
        )
        await bot.send_message(user_id, "👋 <b>Kembali ke Menu Utama:</b>", reply_markup=kbd, parse_mode="HTML")
    elif code == "show_faq":
        faq_text = (
            "❓ <b>Kenapa CV BoonTrack Tanpa Foto?</b>\n"
            "Banyak perusahaan saat ini lebih berfokus pada skill & pengalaman. Format bersih tanpa foto juga memastikan CV mudah dibaca sistem ATS tanpa error."
        )
        await bot.send_message(user_id, faq_text, parse_mode="HTML")