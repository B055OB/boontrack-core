"""Template pesan dan button structures untuk tenant BoonTrack Career."""

# --- 1. FREEMIUM MENU ---
WELCOME_CAREER_TEMPLATE = (
    "Halo{greeting}! Selamat datang di *BoonTrack Career*. 💼\n\n"
    "Layanan kami dikembangkan dengan standar ATS dan kurasi HR Senior.\n\n"
    "Silakan pilih menu gratis Anda di bawah ini:"
)

CAREER_MENU_BUTTONS = [
    {"id": "btn_review", "title": "🔍 Review CV"},
    {"id": "btn_builder", "title": "📝 Bikin CV Dasar"}
]

# --- 2. PREMIUM UNLOCKED DECISION ENGINE MENU ---
WELCOME_PREMIUM_CAREER_TEMPLATE = (
    "Halo{greeting}! 🎖️ *AKSES BOONTRACK CAREER PRO AKTIF*\n\n"
    "AI Decision Engine & Career Companion siap mendampingi Anda memenangkan karir impian:\n\n"
    "🎯 *1. Job Matcher AI* (`job match`)\n"
    "Analisis keselarasan CV vs kualifikasi loker target & missing skills.\n\n"
    "🎙️ *2. Simulasi Interview HR* (`interview`)\n"
    "Latihan wawancara interaktif 3 ronde metode STAR dengan evaluasi instan.\n\n"
    "💰 *3. Salary & Negotiation Coach* (`gaji`)\n"
    "Benchmark gaji industri & template naskah skrip negosiasi penawaran.\n\n"
    "🚀 *4. Optimasi / Bedah CV Lagi* (`review`)\n"
    "Review atau regenerasi naskah CV standar HR Senior.\n\n"
    "👇 *Pilih menu pendamping karir di bawah ini:*"
)

PREMIUM_CAREER_BUTTONS = [
    {"id": "btn_job_match", "title": "🎯 Job Matcher AI"},
    {"id": "btn_mock_interview", "title": "🎙️ Simulasi HR"},
    {"id": "btn_salary_coach", "title": "💰 Negosiasi Gaji"}
]

PREMIUM_ACTION_BUTTONS = [
    {"id": "btn_mock_interview", "title": "🎙️ Latihan Interview"},
    {"id": "btn_salary_coach", "title": "💰 Cek Gaji"},
    {"id": "btn_menu", "title": "🏠 Menu Utama"}
]

# --- 3. UPSELL & PAYMENT ---
UPSELL_REWRITE_MSG = (
    "Ingin melihat versi terbaik dari potensi profesional Anda? 🚀\n\n"
    "Gunakan layanan: *Premium CV Rewrite (Standar HR Senior)*.\n\n"
    "Sistem akan merombak total struktur, diksi pencapaian, dan dampak kerja CV Anda.\n\n"
    "🏷️ *Investasi:* Rp25.000"
)

UPSELL_BUTTONS = [
    {"id": "btn_rewrite", "title": "🚀 Ambil Rewrite"},
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
    "Silakan kirimkan dokumen CV Anda (*format PDF/DOCX*) atau *salin-tempel (copy-paste) teks riwayat CV* "
    "Anda langsung di chat ini untuk kami bedah secara gratis."
)

DOC_READING_TEMPLATE = "📥 Menerima dokumen *{filename}*. Sedang menganalisis struktur & skor ATS CV kamu... ⏳"

DOC_UNREADABLE_MSG = (
    "⚠️ Teks di dalam dokumen tidak dapat diekstrak. "
    "Pastikan file PDF/DOCX berisi teks asli, bukan hasil scan gambar."
)

DOC_ERROR_MSG = "⚠️ Terjadi kendala saat membaca dokumen. Silakan kirim ulang atau tempel teks CV kamu."

TEXT_TOO_SHORT_MSG = (
    "⚠️ Teks CV terlalu singkat. "
    "Silakan tempel teks CV lengkap atau kirim file dokumen (.pdf / .docx)."
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
        f"Analisis CV Anda selesai! 📊\n\n"
        f"🎯 *Skor Keterbacaan ATS:* {overall_score}/100\n\n"
        f"📌 *Breakdown Evaluasi:*\n"
        f"• ⚙️ ATS Compatibility: *{ats_comp}/100*\n"
        f"• 🎯 Relevansi Kata Kunci: *{keyword_score}/100*\n"
        f"• 📈 Kualitas Pengalaman: *{exp_score}/100*\n\n"
        f"💡 *Catatan Praktisi HR:*\n"
        f"{findings_list}\n\n"
        f"_Anda dapat menggunakan catatan di atas sebagai panduan revisi._"
    )


def format_invoice_caption(invoice_id: str, exact_amount: int, unique_code: int) -> str:
    return (
        "📱 *INVOICE PEMBAYARAN PREMIUM CV REWRITE*\n"
        f"🧾 *No. Invoice:* `{invoice_id}`\n\n"
        f"🏷️ *TOTAL TRANSFER:* `{exact_amount}`\n"
        f"*(Rp{exact_amount:,} - Termasuk kode unik: {unique_code})*\n\n"
        "📌 *Panduan Pembayaran QRIS:*\n"
        "1. *Simpan / Screenshot* gambar QRIS di atas ke galeri HP kamu.\n"
        "2. Buka aplikasi m-Banking (*BCA, Mandiri, BRI, BNI*) atau e-Wallet (*GoPay, OVO, DANA, ShopeePay*).\n"
        "3. Pilih menu *Scan QRIS* ➔ ketuk *ikon Galeri / Unggah Gambar* ➔ pilih gambar QRIS tadi.\n"
        f"4. Masukkan nominal persis: `{exact_amount}`\n\n"
        f"⚠️ *PENTING:* Silakan *salin (copy)* angka `{exact_amount}` di atas agar tepat. "
        "Sistem verifikasi otomatis mendeteksi transaksi Anda secara instan!"
    )

