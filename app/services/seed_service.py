from sqlalchemy.orm import Session
from app.services.asset_seed_service import seed_batch_1_assets
from app.repositories.domain_repository import GoalRepository, IntentRepository
from app.models.domain import Goal, Intent, GoalCode, IntentCode

INITIAL_INTENTS = [
    {"code": IntentCode.CREATE_CV, "description": "Membuat CV ATS-friendly"},
    {"code": IntentCode.WRITE_COVER_LETTER, "description": "Membuat surat lamaran kerja"},
    {"code": IntentCode.PREPARE_INTERVIEW, "description": "Latihan pertanyaan interview"},
    {"code": IntentCode.BUILD_LINKEDIN, "description": "Memperbaiki profil LinkedIn"},
    {"code": IntentCode.NEGOTIATE_SALARY, "description": "Panduan negosiasi offering letter"},
    {"code": IntentCode.FIND_JOB, "description": "Mencari platform lowongan kerja"}
]

def seed_initial_domain_data(db: Session):
    goal_repo = GoalRepository(db)
    intent_repo = IntentRepository(db)

    # 1. Seed Goal
    goal = goal_repo.get_by_code(GoalCode.GET_JOB)
    if not goal:
        goal = Goal(
            code=GoalCode.GET_JOB, 
            name="Mendapatkan Pekerjaan", 
            description="Membantu pengguna meraih pekerjaan impian"
        )
        goal = goal_repo.create(goal)

    # 2. Seed Intents
    for intent_data in INITIAL_INTENTS:
        existing = intent_repo.get_by_code(intent_data["code"])
        if not existing:
            new_intent = Intent(
                goal_uuid=goal.uuid,
                code=intent_data["code"],
                description=intent_data["description"]
            )
            intent_repo.create(new_intent)

    # 3. Seed Batch 1 Assets
    seed_batch_1_assets(db)
