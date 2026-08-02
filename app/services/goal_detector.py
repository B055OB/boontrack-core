from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseGoalDetector(ABC):
    """CTO Decision #046: Standardized Interface for Goal & Intent Detection"""
    
    @abstractmethod
    async def detect(self, query: str) -> Dict[str, Any]:
        """
        Expected Return:
        {
            "goal": "GET_JOB",
            "intent": "CREATE_CV",
            "confidence": 0.95,
            "provider": "gemini"
        }
        """
        pass

class RuleBasedGoalDetector(BaseGoalDetector):
    """Fallback / Mock Implementation untuk testing tanpa LLM"""
    async def detect(self, query: str) -> Dict[str, Any]:
        return {
            "goal": "GET_JOB",
            "intent": "CREATE_CV",
            "confidence": 0.50,
            "provider": "rule_based"
        }
