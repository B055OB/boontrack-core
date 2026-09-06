import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("SESSION_REPOSITORY")
_SESSION_CACHE: Dict[str, Any] = {}


class SessionState:
    def __init__(self, user_id: str, channel: str = "whatsapp", state: str = "START", goal: Optional[str] = None, intent: Optional[str] = None, context_json: Optional[Dict[str, Any]] = None):
        self.user_id = str(user_id)
        self.channel = str(channel)
        self.state = state
        self.goal = goal
        self.intent = intent
        self.context_json = context_json if context_json is not None else {}


class SessionRepository:
    async def get_or_create(self, user_id: str, channel: str = "whatsapp") -> SessionState:
        key = f"{channel}:{user_id}"
        if key in _SESSION_CACHE:
            return _SESSION_CACHE[key]

        state = "START"
        context_json = {}
        try:
            from app.services.session_store import _load_from_db, _load_disk_cache
            clean_phone = user_id.replace("+", "").replace("-", "").strip()
            db_res = _load_from_db(clean_phone)
            if db_res:
                state = db_res.get("state", "START")
                context_json = db_res.get("context_json", {})
            else:
                disk_data = _load_disk_cache()
                if clean_phone in disk_data:
                    state = disk_data[clean_phone].get("state", "START")
                    context_json = disk_data[clean_phone].get("context_json", {})
        except Exception as e:
            logger.debug(f"[SESSION REPO RESTORE ERROR] {e}")

        session = SessionState(user_id=user_id, channel=channel, state=state, context_json=context_json)
        _SESSION_CACHE[key] = session
        return session

    async def save(self, session: Any) -> None:
        key = f"{session.channel}:{session.user_id}"
        _SESSION_CACHE[key] = session
        try:
            from app.services.session_store import set_user_tenant_session, get_user_tenant_session
            clean_phone = str(session.user_id).replace("+", "").replace("-", "").strip()
            current_tenant = get_user_tenant_session(clean_phone) or "onlineboost"
            set_user_tenant_session(
                phone=clean_phone,
                tenant_slug=current_tenant,
                state=getattr(session, "state", "ACTIVE"),
                context=getattr(session, "context_json", {})
            )
        except Exception as e:
            logger.debug(f"[SESSION REPO PERSIST ERROR] {e}")

    @staticmethod
    def get_user_session(phone: str, message_text: str = "") -> Optional[str]:
        from app.services.session_store import get_user_tenant_session
        return get_user_tenant_session(phone, message_text)

    @staticmethod
    def set_user_session(phone: str, tenant_slug: str, state: str = "ACTIVE", context: Optional[dict] = None) -> None:
        from app.services.session_store import set_user_tenant_session
        set_user_tenant_session(phone, tenant_slug, state, context)

    @staticmethod
    def clear_user_session(phone: str) -> None:
        from app.services.session_store import clear_user_tenant_session
        clear_user_tenant_session(phone)


