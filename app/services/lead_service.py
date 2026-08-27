import json
from typing import List, Dict, Optional
from app.schemas.webchat import QualifiedB2BLead
from app.services.ai_gateway import AIGateway

class LeadService:
    def __init__(self, ai_gateway: AIGateway = None):
        # Gunakan gateway yang dioperasikan atau fallback instance baru
        self.gateway = ai_gateway or AIGateway()

    async def extract_lead_from_history(self, chat_history: List[Dict[str, str]]) -> Optional[QualifiedB2BLead]:
        """Ekstraksi terstruktur dari percakapan menggunakan JSON schema enforcement"""
        system_instruction = (
            "Ekstrak data prospek B2B dari riwayat percakapan berikut ke dalam format JSON yang valid. "
            "Pastikan sesuai schema: client_name, company_name, email, phone_number, business_type, "
            "core_problem, target_channels, estimated_chat_volume, needs_summary, qualification_score."
        )
        
        try:
            raw_response = await self.gateway.generate_json(
                prompt=f"Riwayat Chat:\n{json.dumps(chat_history, ensure_ascii=False)}",
                system_prompt=system_instruction,
                schema=QualifiedB2BLead.model_json_schema()
            )
            
            if isinstance(raw_response, str):
                raw_response = json.loads(raw_response)
                
            return QualifiedB2BLead.model_validate(raw_response)
        except Exception:
            return None

    async def handoff_lead(self, lead: QualifiedB2BLead) -> bool:
        """Mengirimkan ringkasan lead ke email internal bisnis"""
        # Hook notifikasi internal email/webhook
        print(f"[LEAD HANDOFF] New Qualified Lead: {lead.company_name or lead.client_name} - {lead.phone_number}")
        return True
