import logging
from app.schemas.career_page import CareerPageProfile

logger = logging.getLogger(__name__)

async def build_initial_profile_from_user(user_id: int, full_name: str, slug: str, raw_cv_data: dict = None) -> dict:
    """
    Menyusun payload awal Career Page berdasarkan data hasil review/ekstrak CV pengguna.
    """
    raw_cv_data = raw_cv_data or {}
    
    posisi = raw_cv_data.get("target_role") or raw_cv_data.get("posisi") or "Operations & Career Specialist"
    email = raw_cv_data.get("email") or ""
    telepon = raw_cv_data.get("phone") or raw_cv_data.get("telepon") or ""
    ringkasan = (
        raw_cv_data.get("summary") 
        or raw_cv_data.get("ringkasan") 
        or "Profesional berorientasi hasil dengan fokus pada optimasi alur kerja, integrasi sistem, dan efisiensi operasional."
    )
    pengalaman = raw_cv_data.get("experience_text") or raw_cv_data.get("pengalaman") or ""
    pendidikan = raw_cv_data.get("education_text") or raw_cv_data.get("pendidikan") or ""
    keahlian = (
        raw_cv_data.get("skills_text") 
        or raw_cv_data.get("keahlian") 
        or "Python, Workflow Automation, Data Analytics, Communication, Problem Solving"
    )
    resume_url = raw_cv_data.get("pdf_url") or "https://cvats.boontrack.com/ebook-interview-boontrack.pdf"

    profile = CareerPageProfile(
        user_id=user_id,
        slug=slug,
        nama=full_name,
        posisi=posisi,
        email=email,
        telepon=telepon,
        ringkasan=ringkasan,
        pengalaman=pengalaman,
        pendidikan=pendidikan,
        keahlian=keahlian,
        foto="",
        resume_url=resume_url,
        theme="modern"
    )

    return profile.to_kv_payload()
