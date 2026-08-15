from pathlib import Path
from typing import Dict, List, Any
from app.services.brain_engine import BrainEngine
from app.services.lead_service import LeadService
from app.services.ai_gateway import AIGateway

class WebChatService:
    def __init__(self, brain_engine: BrainEngine, lead_service: LeadService):
        self.brain = brain_engine
        self.lead_service = lead_service
        self.ai_gateway = AIGateway()
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

        # Susun riwayat percakapan singkat untuk konteks LLM
        formatted_history = "\n".join([f"{h['role'].upper()}: {h['content']}" for h in history[-6:]])
        user_prompt_with_history = f"Riwayat Chat:\n{formatted_history}\n\nJawab pesan terakhir user di atas sesuai persona bisnismu."

        # Panggil langsung AIGateway dengan System Prompt B2B murni
        reply = await self.ai_gateway.generate(
            user_message=user_prompt_with_history,
            context={"user_id": session_id, "feature": "b2b_webchat"},
            system_prompt=self.business_prompt
        )

        if not reply:
            reply = "Terima kasih atas pertanyaannya! BoonTrack Group siap membantu kebutuhan otomatisasi AI dan software kustom untuk bisnis Anda. Ada spesifikasi atau alur kerja khusus yang ingin kita diskusikan?"

        history.append({"role": "assistant", "content": reply})

        # Kualifikasi Lead
        is_qualified = False
        if len(history) >= 6:
            lead_data = await self.lead_service.extract_lead_from_history(history)
            if lead_data and (lead_data.email or lead_data.phone_number or lead_data.business_type):
                is_qualified = True
                await self.lead_service.handoff_lead(lead_data)

        return {"reply": reply, "is_lead_qualified": is_qualified}