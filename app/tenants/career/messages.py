"""Template pesan dan button structures untuk tenant BoonTrack Career & Document Services.
Disetujui oleh CEO & CFO BoonTrack.
"""

from app.services.pricing_engine import COMPLIANCE_DISCLAIMER, OFFICIAL_PRODUCT_NAME

# --- 1. FREEMIUM ENTRY MENU (3 BUTTONS) ---
WELCOME_CAREER_TEMPLATE = (
    "Halo{greeting}! Selamat datang di *BoonTrack*. 💼✨\n\n"
    "Layanan cerdas kami siap membantu pembuatan CV standar HR, audit ATS, serta penyempurnaan dokumen profesional.\n\n"
    "👇 *Silakan pilih layanan yang Anda butuhkan di bawah ini:*\n\n"
    f"_{COMPLIANCE_DISCLAIMER}_"
)

# 3 Interactive Buttons for Pre-Payment / Entry Menu
CAREER_ENTRY_BUTTONS = [
    {"id": "btn_create_cv", "title": "📝 Buat CV Baru"},
    {"id": "btn_review_cv", "title": "🔍 Review Bedah CV"},
    {"id": "btn_paraphrase", "title": "✍️ Polish & Rephrase"}
]

# Legacy alias for backward compatibility
CAREER_MENU_BUTTONS = CAREER_ENTRY_BUTTONS


# --- 2. POST-PAYMENT / PREMIUM DASHBOARD (2 CLUSTER BUTTONS) ---
WELCOME_PREMIUM_CAREER_TEMPLATE = (
    "Halo{greeting}! 🎖️ *AKSES BOONTRACK PRO DASHBOARD AKTIF*\n\n"
    "Silakan pilih kluster layanan terpadu Anda:\n\n"
    "📄 *1. Layanan Dokumen* (`layanan dokumen`)\n"
    "Buat CV Baru, Bedah CV Ulang, dan Document Polish & Rephrase.\n\n"
    "🎯 *2. Career Companion* (`career companion`)\n"
    "Job Matcher AI, Simulasi Interview HR STAR, dan Negosiasi Gaji.\n\n"
    f"_{COMPLIANCE_DISCLAIMER}_"
)

# 2 Cluster Buttons for Post-Payment
PREMIUM_CLUSTER_BUTTONS = [
    {"id": "btn_cluster_docs", "title": "📄 Layanan Dokumen"},
    {"id": "btn_cluster_companion", "title": "🎯 Career Companion"}
]

PREMIUM_CAREER_BUTTONS = PREMIUM_CLUSTER_BUTTONS

# Submenu Layanan Dokumen (Post-payment)
DOCS_CLUSTER_BUTTONS = [
    {"id": "btn_create_cv", "title": "📝 Buat CV Baru"},
    {"id": "btn_review_cv", "title": "🔍 Bedah CV Ulang"},
    {"id": "btn_paraphrase", "title": "✍️ Polish & Rephrase"}
]

# Submenu Career Companion (Post-payment)
COMPANION_CLUSTER_BUTTONS = [
    {"id": "btn_job_match", "title": "🎯 Job Matcher AI"},
    {"id": "btn_mock_interview", "title": "🎙️ Simulasi HR STAR"},
    {"id": "btn_salary_coach", "title": "💰 Negosiasi Gaji"}
]

PREMIUM_ACTION_BUTTONS = [
    {"id": "btn_cluster_docs", "title": "📄 Layanan Dokumen"},
    {"id": "btn_cluster_companion", "title": "🎯 Career Companion"},
    {"id": "btn_menu", "title": "🏠 Menu Utama"}
]


# --- 3. UPSELL & PAYMENT TEMPLATES ---
UPSELL_REWRITE_MSG = (
    "Ingin melihat versi terbaik dari potensi profesional Anda? 🚀\n\n"
    "Pilihan Paket Layanan Unggulan:\n"
    "1. *Single CV Polish & ATS Rewrite*: Rp10.000\n"
    "2. *Career Pro Bundle (CV Rewrite + 3x Interview HR STAR)*: Rp25.000\n\n"
    "Sistem akan merombak total struktur, diksi pencapaian, dan dampak kerja CV Anda berstandar HR Senior."
)

UPSELL_BUTTONS = [
    {"id": "btn_rewrite_single", "title": "📄 CV Rewrite (10k)"},
    {"id": "btn_bundle_pro", "title": "🌟 Pro Bundle (25k)"},
    {"id": "btn_menu", "title": "🏠 Menu Utama"}
]

LANG_SELECTION_BUTTONS = [
    {"id": "lang_en_id", "title": "EN (B. Indo)"},
    {"id": "lang_id", "title": "B. Indonesia"},
    {"id": "lang_en", "title": "Full English"}
]

RECEIPT_UPLOAD_INFO_MSG = (
    "📸 *Silakan kirimkan foto / screenshot struk bukti pembayaran Anda* langsung ke chat ini.\n\n"
    "AI Vision kami akan membaca nominal dan memproses pesanan Anda secara otomatis."
)

RECEIPT_INVALID_MSG = (
    "⚠️ Gambar yang dikirim tidak terdeteksi sebagai bukti transfer yang valid. "
    "Pastikan foto memperlihatkan nominal dan status pembayaran."
)

REVIEW_INTRO_MSG = (
    "🔍 *[REVIEW & AUDIT ATS CV]*\n\n"
    "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* "
    "Anda langsung di chat ini untuk kami bedah secara gratis."
)

PARAPHRASE_INTRO_MSG = (
    f"✍️ *[{OFFICIAL_PRODUCT_NAME.upper()}]*\n\n"
    "Silakan kirim dokumen (*format PDF/DOCX*) atau tempel naskah yang ingin Anda perbaiki struktur dan keterbacaannya.\n\n"
    "Sistem akan menghitung jumlah kata secara otomatis dan menampilkan estimasi tarif resmi.\n\n"
    f"_{COMPLIANCE_DISCLAIMER}_"
)

DOC_READING_TEMPLATE = "📥 Menerima dokumen *{filename}*. Sedang menganalisis struktur & menghitung metrik dokumen... ⏳"

DOC_UNREADABLE_MSG = (
    "⚠️ Teks di dalam dokumen tidak dapat diekstrak. "
    "Pastikan file PDF/DOCX berisi teks asli, bukan hasil scan gambar."
)

DOC_ERROR_MSG = "⚠️ Terjadi kendala saat membaca dokumen. Silakan kirim ulang atau tempel teks CV kamu."

TEXT_TOO_SHORT_MSG = (
    "⚠️ Teks terlalu singkat. "
    "Silakan tempel naskah lengkap atau kirim file dokumen (.pdf / .docx)."
)


# --- 4. DECISION ENGINE INVITATION MESSAGES ---
JOB_MATCH_INVITATION_MSG = (
    "🎯 *[JOB MATCHER AI - ANALISIS KECOCOKAN LOKER]*\n\n"
    "Silakan *salin dan tempel (copy-paste) teks deskripsi pekerjaan (Job Description)* dari lowongan yang ingin Anda lamar.\n\n"
    "AI Decision Engine kami akan membedah:\n"
    "📊 *Persentase Keselarasan (Match Score)*\n"
    "✅ *Kualifikasi & Skill CV yang Sudah Cocok*\n"
    "⚠️ *Gap Analysis & Missing Keywords Kritis*\n"
    "📋 *Action Checklist Revisi untuk Lolos ATS*"
)

SALARY_COACH_INVITATION_MSG = (
    "💰 *[SALARY & NEGOTIATION COACH]*\n\n"
    "Ketikkan posisi dan nominal tawaran gaji atau ekspektasi Anda:\n"
    "*(Contoh: Backend Engineer 15 juta di Jakarta / Staff Akuntansi 2 tahun exp tawaran 7 juta)*\n\n"
    "AI Coach akan menyusun panduan instan:\n"
    "📊 *Benchmark Pasar Indonesia (P25 - P75)*\n"
    "⚖️ *Evaluasi Tawaran (Underpaid / Fair / Competitive)*\n"
    "💬 *Naskah Script Negosiasi Siap Pakai (Email/WA)*\n"
    "🎁 *Strategi Negosiasi Benefit Non-Gaji*"
)


def format_diagnosis_message(overall_score: int, breakdown_scores: dict, findings: list) -> str:
    ats_comp = breakdown_scores.get("ats_compatibility", 85)
    keyword_score = breakdown_scores.get("keyword", breakdown_scores.get("structure", 80))
    exp_score = breakdown_scores.get("experience", 85)

    findings_list = "\n".join([f"• {f}" for f in findings]) if findings else "• Format dasar CV sudah terbaca dengan baik."

    return (
        f"📊 *HASIL AUDIT & DIAGNOSTIK ATS CV*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Skor Total:* {overall_score}/100\n\n"
        f"📈 *Rincian Skor Parameter:*\n"
        f"• 🤖 Keterbacaan ATS: {ats_comp}/100\n"
        f"• 🔑 Kepadatan Kata Kunci: {keyword_score}/100\n"
        f"• 💼 Dampak & Kuantifikasi Karir: {exp_score}/100\n\n"
        f"🔍 *Temuan & Area Optimasi:*\n"
        f"{findings_list}\n\n"
        f"_{COMPLIANCE_DISCLAIMER}_"
    )


def format_invoice_caption(invoice_id: str, exact_amount: int, unique_code: int, product_name: str = "Premium CV Rewrite") -> str:
    formatted_amount = f"Rp{exact_amount:,}".replace(",", ".")
    return (
        f"💳 *INVOICE PEMBAYARAN QRIS*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Layanan:* {product_name}\n"
        f"🆔 *Invoice ID:* `{invoice_id}`\n"
        f"💰 *Total Transfer:* *{formatted_amount}*\n"
        f"🔢 *(Termasuk 3 Digit Kode Unik: {unique_code})*\n\n"
        f"⚠️ *PENTING:* Mohon transfer *PERSIS* sampai 3 digit terakhir agar sistem reader mutasi kami dapat memverifikasi pesanan Anda secara otomatis dalam hitungan detik.\n\n"
        f"Scan QRIS di atas melalui GoPay, OVO, DANA, BCA, Mandiri, atau m-Banking Anda."
    )
