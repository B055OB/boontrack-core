from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.domain import Goal, Intent, GoalCode, IntentCode

class GoalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_code(self, code: GoalCode) -> Optional[Goal]:
        return self.db.query(Goal).filter(Goal.code == code).first()

    def create(self, goal: Goal) -> Goal:
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

class IntentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_code(self, code: IntentCode) -> Optional[Intent]:
        return self.db.query(Intent).filter(Intent.code == code).first()

    def create(self, intent: Intent) -> Intent:
        self.db.add(intent)
        self.db.commit()
        self.db.refresh(intent)
        return intent
