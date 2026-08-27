import re
from aiogram import types, Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.services.cloudflare_service import (
    is_slug_available, 
    sync_profile_to_cloudflare_kv, 
    get_profile_from_cloudflare_kv
)

class CareerPageSetup(StatesGroup):
    waiting_for_slug = State()

def sanitize_slug(text: str) -> str:
    clean = text.lower().strip()
    clean = re.sub(r'[^a-z0-9\-]', '-', clean)
    clean = re.sub(r'-+', '-', clean)
    return clean.strip('-')[:30]

def get_theme_selection_keyboard(slug: str):
    kbd = InlineKeyboardMarkup(row_width=2)
    kbd.add(
        InlineKeyboardButton("☀️ Happy (Light)", callback_data=f"cptheme_{slug}_happy"),
        InlineKeyboardButton("🌑 Modern (Dark)", callback_data=f"cptheme_{slug}_modern"),
        InlineKeyboardButton("🏢 Corporate (Navy)", callback_data=f"cptheme_{slug}_corporate"),
        InlineKeyboardButton("👑 Executive (Gold)", callback_data=f"cptheme_{slug}_professional"),
    )
    kbd.add(InlineKeyboardButton("🔙 Batal / Kembali", callback_data=f"cpmanage_{slug}"))
    return kbd

def get_dashboard_keyboard(slug: str):
    kbd = InlineKeyboardMarkup(row_width=2)
    kbd.add(
        InlineKeyboardButton("🎨 Ganti Tema Web", callback_data=f"cpmenutheme_{slug}"),
        InlineKeyboardButton("🌐 Buka Web Live", url=f"https://{slug}.boontrack.com"),
    )
    kbd.add(InlineKeyboardButton("🏠 Menu Utama", callback_data="home_back_main"))
    return kbd

async def start_career_page_claim(message_or_query, user_id: int, state: FSMContext):
    """Pintu masuk pemilihan slug bagi user terbayar."""
    await CareerPageSetup.waiting_for_slug.set()

    prompt_text = (
        "🌐 <b>Tentukan Alamat Website Career Page Kamu</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Website portofoliomu akan aktif di alamat:\n"
        "👉 <code>https://nama-pilihanmu.boontrack.com</code>\n\n"
        "📌 <b>Panduan Nama Subdomain:</b>\n"
        "• Gunakan huruf kecil, angka, atau tanda hubung (-)\n"
        "• <i>Contoh:</i> <code>rayi-gemilang</code> atau <code>marsela-sales</code>\n"
        "• Minimal 3 karakter\n\n"
        "Ketik nama domain yang kamu inginkan di bawah: 👇"
    )

    if hasattr(message_or_query, "edit_message_text"):
        await message_or_query.edit_message_text(prompt_text, parse_mode="HTML")
    else:
        await message_or_query.reply(prompt_text, parse_mode="HTML")

async def process_slug_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    raw_input = message.text or ""
    clean_slug = sanitize_slug(raw_input)

    if len(clean_slug) < 3:
        await message.reply("⚠️ <b>Nama terlalu pendek!</b> Minimal 3 karakter ya kak. Silakan ketik nama lain:", parse_mode="HTML")
        return

    available, reason = await is_slug_available(clean_slug, current_user_id=user_id)
    if not available:
        await message.reply(f"❌ <b>{reason}</b>\n\nNama <code>{clean_slug}</code> tidak bisa digunakan. Ketik nama lain: 👇", parse_mode="HTML")
        return

    await message.reply("⏳ <b>Nama tersedia! Sedang menyiapkan website kamu...</b>", parse_mode="HTML")

    profile_payload = {
        "user_id": user_id,
        "nama": message.from_user.full_name,
        "posisi": "Operations & Career Specialist",
        "email": "",
        "telepon": "",
        "ringkasan": "Siap memberikan dampak nyata dan kontribusi positif bagi pertumbuhan perusahaan.",
        "pengalaman": "",
        "pendidikan": "",
        "keahlian": "Komunikasi, Problem Solving, Manajemen Tugas",
        "foto": "",
        "resume_url": "https://cvats.boontrack.com/ebook-interview-boontrack.pdf",
        "theme": "happy"
    }

    synced = await sync_profile_to_cloudflare_kv(clean_slug, profile_payload)

    if synced:
        await state.finish()
        success_msg = (
            f"🎉 <b>Selamat! Career Page Kamu Sudah Aktif!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>Website Live:</b>\n"
            f"👉 https://{clean_slug}.boontrack.com\n\n"
            "Gunakan tombol di bawah untuk mengatur tema web kamu kapan saja! 🚀"
        )
        await message.reply(success_msg, reply_markup=get_dashboard_keyboard(clean_slug), parse_mode="HTML")
    else:
        await message.reply("❌ Terjadi kendala saat menghubungkan ke Cloudflare. Silakan coba sesaat lagi.")

async def handle_open_theme_menu(callback_query: types.CallbackQuery):
    slug = callback_query.data.replace("cpmenutheme_", "")
    await callback_query.edit_message_text(
        "🎨 <b>PILIH TEMA TAMPILAN CAREER PAGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tampilan web kamu akan langsung berganti detik ini juga:\n\n"
        "• ☀️ <b>Happy:</b> Cerah, hangat & kreatif\n"
        "• 🌑 <b>Modern:</b> Gelap, tech-focused & futuristik\n"
        "• 🏢 <b>Corporate:</b> Putih, navy blue & formal\n"
        "• 👑 <b>Executive:</b> Elegan, charcoal & gold",
        reply_markup=get_theme_selection_keyboard(slug),
        parse_mode="HTML"
    )

async def handle_set_theme(callback_query: types.CallbackQuery):
    parts = callback_query.data.split("_")
    theme = parts[-1]
    slug = "_".join(parts[1:-1])

    profile_data = await get_profile_from_cloudflare_kv(slug)
    if not profile_data:
        profile_data = {"user_id": callback_query.from_user.id, "nama": callback_query.from_user.full_name}

    profile_data["theme"] = theme
    await sync_profile_to_cloudflare_kv(slug, profile_data)

    await callback_query.answer(f"✅ Tema diubah ke {theme.upper()}!", show_alert=True)
    await callback_query.edit_message_text(
        f"⚙️ <b>DASHBOARD KELOLA CAREER PAGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>Website:</b> https://{slug}.boontrack.com\n"
        f"🎨 <b>Tema Aktif:</b> {theme.capitalize()}\n\n"
        "Pilih pengaturan yang ingin kamu sesuaikan:",
        reply_markup=get_dashboard_keyboard(slug),
        parse_mode="HTML"
    )

async def handle_manage_dashboard(callback_query: types.CallbackQuery):
    slug = callback_query.data.replace("cpmanage_", "")
    await callback_query.edit_message_text(
        f"⚙️ <b>DASHBOARD KELOLA CAREER PAGE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>Website Live:</b> https://{slug}.boontrack.com\n\n"
        "Pilih pengaturan yang ingin kamu sesuaikan:",
        reply_markup=get_dashboard_keyboard(slug),
        parse_mode="HTML"
    )

def register_career_page_handlers(dp: Dispatcher):
    dp.register_message_handler(process_slug_input, state=CareerPageSetup.waiting_for_slug)
    dp.register_callback_query_handler(handle_open_theme_menu, lambda c: c.data.startswith("cpmenutheme_"))
    dp.register_callback_query_handler(handle_set_theme, lambda c: c.data.startswith("cptheme_"))
    dp.register_callback_query_handler(handle_manage_dashboard, lambda c: c.data.startswith("cpmanage_"))
