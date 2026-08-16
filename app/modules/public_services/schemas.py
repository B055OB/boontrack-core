from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.modules.public_services.schemas import PublicServiceContext, StandardMessagePayload


class KnowledgeProvider(ABC):
    """Interface untuk retrieval data layanan/persyaratan (dummy/local/vector DB)."""

    @abstractmethod
    async def get_service_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def search_relevant_services(self, query: str) -> List[Dict[str, Any]]:
        pass


class EscalationProvider(ABC):
    """Interface penanganan eskalasi tiket ke petugas/admin kelurahan."""

    @abstractmethod
    async def trigger_escalation(
        self, conversation_id: int, reason: str, context: PublicServiceContext
    ) -> int:
        pass


class PublicServiceProvider(ABC):
    """Interface orchestrator alur percakapan publik."""

    @abstractmethod
    async def process_user_query(
        self, payload: StandardMessagePayload, conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Any:
        pass