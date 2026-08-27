from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any

# Payload chat dari frontend WebChat
class WebChatRequest(BaseModel):
    session_id: str = Field(..., description="ID Sesi unik per visitor/prospek")
    message: str = Field(..., min_length=1, max_length=2000)
    client_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class WebChatResponse(BaseModel):
    session_id: str
    reply: str
    is_lead_qualified: bool = False

# Skema Ekstraksi Data Terstruktur Lead B2B
class QualifiedB2BLead(BaseModel):
    client_name: Optional[str] = Field(None, description="Nama PIC atau calon klien")
    company_name: Optional[str] = Field(None, description="Nama perusahaan/brand")
    email: Optional[EmailStr] = Field(None, description="Email kontak")
    phone_number: Optional[str] = Field(None, description="Nomor WhatsApp/telepon")
    business_type: Optional[str] = Field(None, description="Tipe Bisnis / Industri (misal: PJTKI, Retail, Edukasi, FMCG)")
    core_problem: str = Field(..., description="Masalah utama operasional yang ingin diselesaikan")
    target_channels: List[str] = Field(default_factory=list, description="Saluran target (WhatsApp, Webchat, IG, dll)")
    estimated_chat_volume: Optional[str] = Field(None, description="Estimasi volume pesan harian/bulanan")
    needs_summary: str = Field(..., description="Ringkasan kebutuhan integrasi AI Engine")
    qualification_score: int = Field(..., ge=1, le=5, description="Skor kesiapan lead (1-5)")
