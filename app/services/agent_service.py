"""app/services/agent_service.py
Agent Service Layer for Multi-Tenant Commerce AI & Prompt Execution.
"""

from typing import Dict, Any, Optional
from app.services.ai_engine import commerce_ai_engine, CommerceAIEngine

__all__ = ["commerce_ai_engine", "CommerceAIEngine"]
