from pathlib import Path
from typing import Dict, List, Any
from app.services.brain_engine import BrainEngine
from app.services.lead_service import LeadService

class WebChatService:
    def __init__(self, brain_engine: BrainEngine, lead_service: LeadService):
        self.brain = brain_engine
        self.lead_service = lead_service
        self._session_memory: Dict[str, List[Dict[str, str]]] = {}
        
        # Load business persona prompt
        prompt_path = Path("prompt/business_system.txt")
        if prompt_path.exists():
            self.business_prompt = prompt_path.read_text(encoding="utf-8").strip()
        else:
            self.business_prompt = "Kamu adalah BoonTrack Business Consultant B2B. Bantu klien mengenai otomatisasi bisnis dan software AI."

    def _get_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self._session_memory:
            self._session_memory[session_id] = []
        return self._session_memory[session_id]

    async def process_business_chat(self, session_id: str, message: str) -> Dict[str, Any]:
        history = self._get_history(session_id)
        history.append({"role": "user", "content": message})

        # Susun pesan percakapan khusus persona B2B
        messages_payload = [{"role": "system", "content": self.business_prompt}]
        for h in history[-8:]:  # Batasi konteks 8 pesan terakhir
            messages_payload.append({"role": h["role"], "content": h["content"]})

        reply = ""
        # 1. Prioritaskan jalur direct LLM via AIGateway agar tidak tercampur router Telegram/Karir
        if hasattr(self.brain, "ai_gateway") and hasattr(self.brain.ai_gateway, "generate_chat_completion"):
            try:
                reply = await self.brain.ai_gateway.generate_chat_completion(messages_payload)
            except Exception:
                reply = ""

        # 2. Fallback via brain handle_message jika direct gateway belum merespons
        if not reply:
            engine_response = await self.brain.handle_message(
                user_id=session_id,
                channel="webchat",
                text=message,
                context={
                    "persona": "BUSINESS",
                    "system_prompt_override": self.business_prompt,
                    "history": history
                }
            )
            if isinstance(engine_response, dict):
                reply = engine_response.get("text") or engine_response.get("reply") or str(engine_response)
            else:
                reply = str(engine_response)

        # Filter jika engine masih mengembalikan template karir / intent mentah
        if any(bad_word in reply for bad_word in ["Bikin CV", "Latihan Interview", "GENERAL_QUERY", "START"]):
            reply = "Tentu saja bisa! BoonTrack menyediakan solusi AI Sales Agent dan otomatisasi CS langsung di WhatsApp untuk onlineshop Anda, dengan keunggulan 0% komisi transaksi. Boleh tahu saat ini penjualannya lebih banyak via WhatsApp atau marketplace, dan kendala apa yang paling sering dialami tim admin Anda?"

        history.append({"role": "assistant", "content": reply})

        # Kualifikasi Lead
        is_qualified = False
        if len(history) >= 6:
            lead_data = await self.lead_service.extract_lead_from_history(history)
            if lead_data and (lead_data.email or lead_data.phone_number or lead_data.business_type):
                is_qualified = True
                await self.lead_service.handoff_lead(lead_data)

        return {"reply": reply, "is_lead_qualified": is_qualified}