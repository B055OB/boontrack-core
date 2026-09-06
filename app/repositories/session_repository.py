from typing import Dict, Any, Optional

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
        if key not in _SESSION_CACHE:
            _SESSION_CACHE[key] = SessionState(user_id=user_id, channel=channel)
        return _SESSION_CACHE[key]

    async def save(self, session: Any) -> None:
        key = f"{session.channel}:{session.user_id}"
        _SESSION_CACHE[key] = session

