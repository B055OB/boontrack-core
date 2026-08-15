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
        self.business_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    def _get_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self._session_memory:
            self._session_memory[session_id] = []
        return self._session_memory[session_id]

    async def process_business_chat(self, session_id: str, message: str) -> Dict[str, Any]:
        history = self._get_history(session_id)
        history.append({"role": "user", "content": message})

        # Panggil BrainEngine menggunakan handle_message native tanpa merusak flow live
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

        # Handle return value (baik berupa string maupun dict)
        if isinstance(engine_response, dict):
            reply = engine_response.get("text") or engine_response.get("reply") or str(engine_response)
        else:
            reply = str(engine_response)

        history.append({"role": "assistant", "content": reply})

        # Trigger kualifikasi lead jika percakapan mencapai kedalaman tertentu
        is_qualified = False
        if len(history) >= 6:
            lead_data = await self.lead_service.extract_lead_from_history(history)
            if lead_data and (lead_data.email or lead_data.phone_number or lead_data.business_type):
                is_qualified = True
                await self.lead_service.handoff_lead(lead_data)

        return {"reply": reply, "is_lead_qualified": is_qualified}