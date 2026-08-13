import requests
import google.generativeai as genai
from app.core.config import settings

if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

def ai_generate_summary(position: str) -> str:
    """Menghasilkan ringkasan profil profesional berdasarkan posisi yang dilamar."""
    if not position:
        return "Profesional berdedikasi tinggi yang terbiasa bekerja secara terstruktur, adaptif, serta berkomitmen memberikan kontribusi operasional terbaik bagi perusahaan."
    return f"Profesional berpengalaman di bidang {position} dengan rekam jejak yang terbukti dalam mengeksekusi target operasional dan manajemen kerja secara efisien."

def ai_rewrite_achievement(text: str) -> str:
    """Mengubah deskripsi pekerjaan menjadi poin-poin profesional ATS-friendly."""
    prompt_text = (
        "Ubah deskripsi tugas/pengalaman kerja berikut menjadi 2-4 poin bullet point (menggunakan simbol •) "
        "berbahasa Indonesia profesional standar HR yang ATS-friendly. Buat lugas, aksi-orientasi, dan profesional:\n\n"
        f"Input Pengalaman: {text}"
    )

    # 1. Coba Gemini API
    if settings.GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt_text)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"[Fallback Alert] Gemini API Error/Limit: {e}. Beralih ke Groq...")

    # 2. Fallback ke Groq API
    if settings.GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama3-8b-8192",
                "messages": [{"role": "user", "content": prompt_text}],
                "temperature": 0.5
            }
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Fallback Alert] Groq API Error: {e}. Beralih ke OpenRouter...")

    # 3. Fallback ke OpenRouter API
    if settings.OPENROUTER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "meta-llama/llama-3-8b-instruct:free",
                "messages": [{"role": "user", "content": prompt_text}]
            }
            res = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"[Fallback Alert] OpenRouter Error: {e}. Gunakan aturan lokal.")

    # 4. Fallback ke Aturan Lokal (Regex & Keyword Match)
    clean = text.lower()
    if any(w in clean for w in ["galon", "antar", "kurir", "ojek", "driver"]):
        return "• Mengantarkan produk atau barang kepada pelanggan secara tepat waktu dan aman.\n• Menjaga komunikasi yang baik dengan pelanggan guna memastikan kepuasan pelayanan.\n• Mencatat dan melaporkan setiap transaksi pengiriman harian secara akurat."
    elif any(w in clean for w in ["jaga", "warung", "toko", "kasir"]):
        return "• Melayani pelanggan dengan ramah dan profesional guna meningkatkan kepuasan transaksi.\n• Mengelola transaksi serta pencatatan inventaris harian secara akurat.\n• Memastikan kebersihan dan keteraturan area kerja."
    else:
        lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
        formatted = "\n".join([f"• {line}" for line in lines])
        if len(lines) == 1:
            formatted += "\n• Berkomitmen melaksanakan seluruh tanggung jawab kerja dengan kedisiplinan dan ketelitian tinggi.\n• Berkontribusi aktif dalam mendukung tercapainya efisiensi target operasional tim."
        return formatted