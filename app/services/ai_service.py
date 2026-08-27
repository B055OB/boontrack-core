import logging
from typing import Dict, Any
from app.services.ai_gateway import AIGateway

logger = logging.getLogger("ai_service")

# Single Instance AI Gateway (Terpusat & Tanpa Hardcode Model)
ai_gateway = AIGateway()


async def ai_generate_summary(position: str) -> str:
    """Menghasilkan ringkasan profil profesional berdasarkan posisi yang dilamar."""
    if not position:
        return (
            "Profesional berdedikasi tinggi yang terbiasa bekerja secara terstruktur, "
            "adaptif, serta berkomitmen memberikan kontribusi operasional terbaik bagi perusahaan."
        )

    prompt = (
        f"Buatkan ringkasan profil profesional singkat (1 kalimat padat) "
        f"untuk posisi {position} dalam Bahasa Indonesia yang lugas dan ATS-friendly."
    )

    response = await ai_gateway.generate(prompt)
    if response:
        return response

    return (
        f"Profesional berpengalaman di bidang {position} dengan rekam jejak yang terbukti "
        "dalam mengeksekusi target operasional dan manajemen kerja secara efisien."
    )


async def ai_rewrite_achievement(text: str) -> str:
    """
    Mengubah deskripsi pekerjaan menjadi poin-poin profesional ATS-friendly.
    Diproses penuh oleh AIGateway (Gemini -> Groq -> OpenRouter) dengan Fallback Lokal.
    """
    if not text:
        return ""

    prompt_text = (
        "Ubah deskripsi tugas/pengalaman kerja berikut menjadi 2-4 poin bullet point (menggunakan simbol •) "
        "berbahasa Indonesia profesional standar HR yang ATS-friendly. Buat lugas, aksi-orientasi, dan profesional:\n\n"
        f"Input Pengalaman: {text}"
    )

    response = await ai_gateway.generate(prompt_text)
    if response:
        return response

    logger.warning("Seluruh provider AI di AIGateway gagal. Menggunakan Fallback Aturan Lokal.")
    clean = text.lower()
    
    if any(w in clean for w in ["galon", "antar", "kurir", "ojek", "driver"]):
        return (
            "• Mengantarkan produk atau barang kepada pelanggan secara tepat waktu dan aman.\n"
            "• Menjaga komunikasi yang baik dengan pelanggan guna memastikan kepuasan pelayanan.\n"
            "• Mencatat dan melaporkan setiap transaksi pengiriman harian secara akurat."
        )
    elif any(w in clean for w in ["jaga", "warung", "toko", "kasir"]):
        return (
            "• Melayani pelanggan dengan ramah dan profesional guna meningkatkan kepuasan transaksi.\n"
            "• Mengelola transaksi serta pencatatan inventaris harian secara akurat.\n"
            "• Memastikan kebersihan dan keteraturan area kerja."
        )
    else:
        lines = [line.strip().lstrip("-*• ") for line in text.split("\n") if line.strip()]
        formatted = "\n".join([f"• {line}" for line in lines])
        if len(lines) == 1:
            formatted += (
                "\n• Berkomitmen melaksanakan seluruh tanggung jawab kerja dengan kedisiplinan dan ketelitian tinggi.\n"
                "• Berkontribusi aktif dalam mendukung tercapainya efisiensi target operasional tim."
            )
        return formatted


async def enhance_resume_data(user_data: Dict[Any, Any]) -> Dict[str, Any]:
    """Meningkatkan dan memformat ringkasan serta pengalaman kerja mentah menggunakan AI."""
    enhanced = dict(user_data)
    
    # 1. Target Posisi
    pos = str(user_data.get(5) or user_data.get("position") or "General Professional").strip()
    enhanced["position"] = pos

    # 2. Polish Summary
    raw_summary = str(user_data.get(10) or user_data.get("summary") or "").strip()
    if not raw_summary or raw_summary in ["-", "skip", "belum ada"]:
        enhanced[10] = await ai_generate_summary(pos)
        enhanced["summary"] = enhanced[10]
    else:
        enhanced["summary"] = raw_summary

    # 3. Polish Pengalaman Kerja
    raw_exp = str(user_data.get(6) or user_data.get("experience") or "").strip()
    if raw_exp and raw_exp not in ["-", "skip", "belum ada"]:
        enhanced["achievements"] = await ai_rewrite_achievement(raw_exp)
    else:
        enhanced["achievements"] = ""

    return enhanced
