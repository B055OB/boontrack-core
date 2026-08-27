from pydantic import BaseModel
from typing import Optional

class CareerPageProfile(BaseModel):
    user_id: int
    slug: str
    nama: str
    posisi: str = "Operations & Career Specialist"
    email: str = ""
    telepon: str = ""
    ringkasan: str = ""
    pengalaman: str = ""
    pendidikan: str = ""
    keahlian: str = ""
    foto: str = ""
    resume_url: str = ""
    theme: str = "modern"

    def to_kv_payload(self) -> dict:
        """Mengubah instance ke format payload JSON yang siap dikirim ke Cloudflare KV."""
        return {
            "user_id": self.user_id,
            "nama": self.nama,
            "posisi": self.posisi,
            "email": self.email,
            "telepon": self.telepon,
            "ringkasan": self.ringkasan,
            "pengalaman": self.pengalaman,
            "pendidikan": self.pendidikan,
            "keahlian": self.keahlian,
            "foto": self.foto,
            "resume_url": self.resume_url,
            "theme": self.theme
        }
