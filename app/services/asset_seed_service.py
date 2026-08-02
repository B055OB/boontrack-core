from sqlalchemy.orm import Session
from app.models.digital_asset import DigitalAsset, Delivery, KnowledgeMapping, ARSStatus, AssetType, DeliveryType
from app.utils.text_normalizer import normalize_keyword

BATCH_1_ASSETS = [
    {
        "slug": "template-cv-ats-fresh-graduate",
        "title": "Template CV ATS Fresh Graduate",
        "description": "Format CV standar ATS untuk lulusan baru.",
        "goal_code": "GET_JOB",
        "intent_code": "CREATE_CV",
        "asset_type": AssetType.TEMPLATE,
        "estimated_time_minutes": 10,
        "expected_outcome": "CV rapi standar ATS.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-cv-ats",
        "keywords": [
            {"raw": "CV ATS!!!", "synonym": "resume", "weight": 1.0},
            {"raw": "Curriculum    Vitae", "synonym": "cv kerja", "weight": 1.0}
        ]
    },
    {
        "slug": "template-cv-ats-experienced",
        "title": "Template CV ATS Professional / Experienced",
        "description": "Format CV ATS berfokus pada achievement dan metrics kerja.",
        "goal_code": "GET_JOB",
        "intent_code": "CREATE_CV",
        "asset_type": AssetType.TEMPLATE,
        "estimated_time_minutes": 15,
        "expected_outcome": "CV profesional siap kirim.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-cv-exp",
        "keywords": [{"raw": "cv profesional", "synonym": "cv senior", "weight": 0.9}]
    },
    {
        "slug": "checklist-review-cv-ats",
        "title": "Checklist Mandiri Audit CV ATS",
        "description": "20 poin pemeriksaan sebelum submit CV.",
        "goal_code": "GET_JOB",
        "intent_code": "CREATE_CV",
        "asset_type": AssetType.CHECKLIST,
        "estimated_time_minutes": 5,
        "expected_outcome": "Mengetahui kelayakan CV.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-chk-cv",
        "keywords": [{"raw": "cek cv", "synonym": "audit cv", "weight": 0.8}]
    },
    {
        "slug": "template-cover-letter-bahasa-indonesia",
        "title": "Template Surat Lamaran Kerja (Bahasa Indonesia)",
        "description": "Format surat lamaran profesional dan persuasif.",
        "goal_code": "GET_JOB",
        "intent_code": "WRITE_COVER_LETTER",
        "asset_type": AssetType.TEMPLATE,
        "estimated_time_minutes": 10,
        "expected_outcome": "Cover letter Indonesia siap pakai.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-cl-id",
        "keywords": [{"raw": "surat lamaran kerja", "synonym": "cover letter id", "weight": 1.0}]
    },
    {
        "slug": "template-cover-letter-english",
        "title": "English Cover Letter Template for MNC / Remote Work",
        "description": "Professional English cover letter format.",
        "goal_code": "GET_JOB",
        "intent_code": "WRITE_COVER_LETTER",
        "asset_type": AssetType.TEMPLATE,
        "estimated_time_minutes": 10,
        "expected_outcome": "English cover letter ready.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-cl-en",
        "keywords": [{"raw": "english cover letter", "synonym": "lamaran bahasa inggris", "weight": 1.0}]
    },
    {
        "slug": "cheatsheet-50-pertanyaan-interview-hrd-user",
        "title": "Cheatsheet 50 Pertanyaan Interview HRD & User",
        "description": "Daftar pertanyaan dan panduan struktur jawaban STAR.",
        "goal_code": "GET_JOB",
        "intent_code": "PREPARE_INTERVIEW",
        "asset_type": AssetType.CHEATSHEET,
        "estimated_time_minutes": 20,
        "expected_outcome": "Kesiapan menghadapi interview.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-int-cheat",
        "keywords": [{"raw": "pertanyaan interview", "synonym": "tanya jawab wawancara", "weight": 1.0}]
    },
    {
        "slug": "script-jawaban-ceritakan-diri-anda",
        "title": "Script Jawaban: Ceritakan Tentang Diri Anda",
        "description": "Formula Elevator Pitch 60 detik untuk awal interview.",
        "goal_code": "GET_JOB",
        "intent_code": "PREPARE_INTERVIEW",
        "asset_type": AssetType.SCRIPT,
        "estimated_time_minutes": 5,
        "expected_outcome": "Jawaban perkenalan yang percaya diri.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-script-intro",
        "keywords": [{"raw": "tell me about yourself", "synonym": "ceritakan diri anda", "weight": 1.0}]
    },
    {
        "slug": "checklist-optimasi-profil-linkedin",
        "title": "Checklist Optimasi Profil LinkedIn All-Star",
        "description": "Langkah optimasi headline, about, dan experience.",
        "goal_code": "GET_JOB",
        "intent_code": "BUILD_LINKEDIN",
        "asset_type": AssetType.CHECKLIST,
        "estimated_time_minutes": 15,
        "expected_outcome": "Profil LinkedIn dilirik recruiter.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-chk-linkedin",
        "keywords": [{"raw": "optimasi linkedin", "synonym": "linkedin all star", "weight": 0.9}]
    },
    {
        "slug": "script-negosiasi-gaji-via-email",
        "title": "Script & Template Email Negosiasi Gaji (Offering Letter)",
        "description": "Template mengajukan counter-offer secara sopan dan profesional.",
        "goal_code": "GET_JOB",
        "intent_code": "NEGOTIATE_SALARY",
        "asset_type": AssetType.SCRIPT,
        "estimated_time_minutes": 10,
        "expected_outcome": "Email counter-offer terkirim rapi.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-script-salary",
        "keywords": [{"raw": "negosiasi gaji", "synonym": "counter offer email", "weight": 1.0}]
    },
    {
        "slug": "guide-job-search-tracker-spreadsheet",
        "title": "Panduan & Spreadsheet Job Search Tracker",
        "description": "Sheet pelacak status lamaran, follow-up, dan interview.",
        "goal_code": "GET_JOB",
        "intent_code": "FIND_JOB",
        "asset_type": AssetType.SPREADSHEET,
        "estimated_time_minutes": 10,
        "expected_outcome": "Manajemen lamaran kerja terorganisir.",
        "status": ARSStatus.READY,
        "delivery_url": "https://drive.google.com/file/d/sample-sheet-tracker",
        "keywords": [{"raw": "job tracker", "synonym": "pelacak lamaran kerja", "weight": 0.8}]
    }
]

def seed_batch_1_assets(db: Session):
    for asset_data in BATCH_1_ASSETS:
        # Idempotent Check via Slug (CTO Decision #036)
        existing_asset = db.query(DigitalAsset).filter(DigitalAsset.slug == asset_data["slug"]).first()
        
        if not existing_asset:
            asset = DigitalAsset(
                slug=asset_data["slug"],
                title=asset_data["title"],
                description=asset_data["description"],
                goal_code=asset_data["goal_code"],
                intent_code=asset_data["intent_code"],
                asset_type=asset_data["asset_type"],
                estimated_time_minutes=asset_data["estimated_time_minutes"],
                expected_outcome=asset_data["expected_outcome"],
                status=asset_data["status"]
            )
            db.add(asset)
            db.flush()

            # Delivery Binding
            delivery = Delivery(
                asset_uuid=asset.uuid,
                delivery_type=DeliveryType.GDRIVE,
                url_or_file_id=asset_data["delivery_url"]
            )
            db.add(delivery)

            # Knowledge Mapping dengan Normalizer (CTO Decision #038)
            for kw in asset_data.get("keywords", []):
                normalized_kw = normalize_keyword(kw["raw"])
                km = KnowledgeMapping(
                    asset_uuid=asset.uuid,
                    keyword=normalized_kw,
                    synonym=kw["synonym"],
                    search_weight=kw["weight"],
                    language="id",
                    status="active"
                )
                db.add(km)
                
            db.commit()
