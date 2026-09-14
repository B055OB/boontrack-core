"""app/schemas/tenant_prospect_schema.py
Pydantic schemas for tenant prospect intake, feature flags mapping, and superadmin responses.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ChannelsInput(BaseModel):
    whatsapp: bool = Field(default=False, description="WhatsApp Business / WABA official channel")
    telegram: bool = Field(default=False, description="Telegram Operations channel")
    discord: bool = Field(default=False, description="Discord CRM channel")
    other: Optional[str] = Field(default=None, description="Other custom messaging channel")


class HardwareInput(BaseModel):
    none: bool = Field(default=False, description="No hardware peripherals needed")
    printer: bool = Field(default=False, description="Thermal ESC/POS Receipt Printer")
    doorlock: bool = Field(default=False, description="Smart IoT Doorlock / Turnstile")
    nfc: bool = Field(default=False, description="NFC Access Card / Reader")
    other: Optional[str] = Field(default=None, description="Other custom hardware device")


class TenantOnboardIntakeRequest(BaseModel):
    brand_name: str = Field(..., min_length=2, max_length=150, description="Nama brand / bisnis merchant")
    industry: str = Field(..., min_length=2, max_length=50, description="Kategori industri (e.g. Retail, F&B, Gym, Services)")
    pic_name: str = Field(..., min_length=2, max_length=100, description="Nama lengkap PIC / penanggung jawab")
    whatsapp: str = Field(..., min_length=6, max_length=50, description="Nomor WhatsApp aktif PIC")
    pain_points: str = Field(..., min_length=3, description="Permasalahan atau hambatan operasional saat ini")
    desired_outcome: str = Field(..., min_length=3, description="Target atau hasil yang ingin dicapai dengan BoonTrack")
    channels: ChannelsInput = Field(default_factory=ChannelsInput, description="Konfigurasi channel komunikasi yang diinginkan")
    hardware: HardwareInput = Field(default_factory=HardwareInput, description="Kebutuhan perangkat keras / IoT peripherals")

    def build_feature_flags(self) -> Dict[str, Any]:
        """Maps user choices to standard platform feature flags."""
        has_hardware = not self.hardware.none
        flags: Dict[str, Any] = {
            "channel.waba_official": bool(self.channels.whatsapp),
            "channel.telegram_ops": bool(self.channels.telegram),
            "channel.discord_crm": bool(self.channels.discord),
            "peripheral.escpos_printer": bool(self.hardware.printer if has_hardware else False),
            "peripheral.smart_doorlock": bool(self.hardware.doorlock if has_hardware else False),
            "peripheral.nfc_access": bool(self.hardware.nfc if has_hardware else False),
        }
        if self.channels.other:
            flags["channel.other"] = self.channels.other
        if self.hardware.other and has_hardware:
            flags["peripheral.other"] = self.hardware.other
        return flags


class TenantProspectItem(BaseModel):
    id: str
    brand_name: str
    industry: str
    pic_name: str
    whatsapp: str
    pain_points: str
    desired_outcome: str
    channels_config: Dict[str, Any]
    hardware_config: Dict[str, Any]
    feature_flags: Dict[str, Any]
    status: str
    created_at: Optional[datetime] = None


class TenantOnboardIntakeResponse(BaseModel):
    status: str = "success"
    message: str = "Pendaftaran pilot onboarding berhasil dicatat"
    prospect: TenantProspectItem


class SuperadminLeadsResponse(BaseModel):
    status: str = "success"
    count: int
    data: List[TenantProspectItem]
