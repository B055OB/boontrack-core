"""app/core/trial_guardrail.py
CFO Hard-Cap Guardrail Engine for BoonTrack Core.

Enforces strict trial boundaries for tenants with `is_trial = True`:
- Hard cap: Max 30 orders
- Hard cap: Max 50 AI / WhatsApp interactions
- Throws / returns structured `TrialLimitExceededException` (error_code: `TRIAL_LIMIT_EXCEEDED`).
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("CFO_TRIAL_GUARDRAIL")

CFO_TRIAL_MAX_ORDERS: int = 30
CFO_TRIAL_MAX_AI_INTERACTIONS: int = 50


class TrialLimitExceededException(Exception):
    """
    Exception terstruktur ketika tenant dalam status trial (is_trial = True)
    mencapai batas keras CFO Guardrail (maks 30 order & 50 interaksi AI/WA).
    """

    def __init__(
        self,
        tenant_id: str,
        quota_type: str,  # "orders" | "ai_interactions" | "whatsapp"
        current_usage: int,
        limit: int,
        message: Optional[str] = None,
    ):
        self.error_code: str = "TRIAL_LIMIT_EXCEEDED"
        self.tenant_id: str = tenant_id
        self.quota_type: str = quota_type
        self.current_usage: int = current_usage
        self.limit: int = limit
        self.message: str = message or (
            f"CFO Guardrail: Batas kuota trial tercapai untuk tenant '{tenant_id}'. "
            f"Kuota {quota_type}: {current_usage}/{limit}. "
            f"Silakan upgrade paket langganan untuk melanjutkan."
        )
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes exception to a clean structured dictionary."""
        return {
            "error": self.error_code,
            "error_code": self.error_code,
            "tenant_id": self.tenant_id,
            "quota_type": self.quota_type,
            "current_usage": self.current_usage,
            "limit": self.limit,
            "detail": self.message,
            "message": self.message,
        }


class TrialGuardrailService:
    """
    Service pengawas batas keras operasional akun trial.
    Mencegah eksploitasi API eksternal (LLM token & WhatsApp WABA) serta pesanan berlebih.
    """

    def __init__(self):
        self._order_counts: Dict[str, int] = {}
        self._ai_counts: Dict[str, int] = {}

    def get_order_count(self, tenant_id: str) -> int:
        """Mengambil jumlah pesanan tenant."""
        return self._order_counts.get(tenant_id, 0)

    def get_ai_count(self, tenant_id: str) -> int:
        """Mengambil jumlah interaksi AI/WA tenant."""
        return self._ai_counts.get(tenant_id, 0)

    def record_order(self, tenant_id: str) -> int:
        """Mencatat pembuatan pesanan baru dan mengembalikan total pemakaian."""
        new_count = self._order_counts.get(tenant_id, 0) + 1
        self._order_counts[tenant_id] = new_count
        return new_count

    def record_ai_interaction(self, tenant_id: str) -> int:
        """Mencatat 1 interaksi AI / WA dan mengembalikan total pemakaian."""
        new_count = self._ai_counts.get(tenant_id, 0) + 1
        self._ai_counts[tenant_id] = new_count
        return new_count

    def check_order_quota(
        self,
        tenant_id: str,
        is_trial: bool = False,
        current_count: Optional[int] = None,
    ) -> None:
        """
        Validasi batas keras pesanan trial.
        Jika is_trial == True dan pemakaian >= 30, raise TrialLimitExceededException.
        """
        if not is_trial:
            return

        used = current_count if current_count is not None else self.get_order_count(tenant_id)
        if used >= CFO_TRIAL_MAX_ORDERS:
            logger.warning(
                f"[CFO Guardrail] Tenant '{tenant_id}' reached trial order limit: {used}/{CFO_TRIAL_MAX_ORDERS}"
            )
            raise TrialLimitExceededException(
                tenant_id=tenant_id,
                quota_type="orders",
                current_usage=used,
                limit=CFO_TRIAL_MAX_ORDERS,
            )

    def check_ai_interaction_quota(
        self,
        tenant_id: str,
        is_trial: bool = False,
        current_count: Optional[int] = None,
    ) -> None:
        """
        Validasi batas keras interaksi AI/WA trial.
        Jika is_trial == True dan pemakaian >= 50, raise TrialLimitExceededException.
        """
        if not is_trial:
            return

        used = current_count if current_count is not None else self.get_ai_count(tenant_id)
        if used >= CFO_TRIAL_MAX_AI_INTERACTIONS:
            logger.warning(
                f"[CFO Guardrail] Tenant '{tenant_id}' reached trial AI interaction limit: {used}/{CFO_TRIAL_MAX_AI_INTERACTIONS}"
            )
            raise TrialLimitExceededException(
                tenant_id=tenant_id,
                quota_type="ai_interactions",
                current_usage=used,
                limit=CFO_TRIAL_MAX_AI_INTERACTIONS,
            )

    def get_usage(self, tenant_id: str) -> Dict[str, Any]:
        """Mengembalikan metrik pemakaian kuota trial."""
        return {
            "tenant_id": tenant_id,
            "orders": {
                "used": self.get_order_count(tenant_id),
                "limit": CFO_TRIAL_MAX_ORDERS,
                "is_exceeded": self.get_order_count(tenant_id) >= CFO_TRIAL_MAX_ORDERS,
            },
            "ai_interactions": {
                "used": self.get_ai_count(tenant_id),
                "limit": CFO_TRIAL_MAX_AI_INTERACTIONS,
                "is_exceeded": self.get_ai_count(tenant_id) >= CFO_TRIAL_MAX_AI_INTERACTIONS,
            },
        }

    def reset(self, tenant_id: Optional[str] = None) -> None:
        """Reset state penghitung (berguna untuk testing)."""
        if tenant_id:
            self._order_counts.pop(tenant_id, None)
            self._ai_counts.pop(tenant_id, None)
        else:
            self._order_counts.clear()
            self._ai_counts.clear()


# Singleton Instance
trial_guardrail = TrialGuardrailService()
