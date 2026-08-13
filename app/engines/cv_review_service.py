import json
from typing import Dict, Any, Optional
from app.data.database import fetch_one, execute_query  # Sesuaikan dengan helper DB Postgres kamu

class CVReviewService:
    
    @staticmethod
    async def get_latest_cv_version(user_id: int) -> int:
        """Mengambil versi CV terakhir milik user untuk tracking incremental"""
        query = "SELECT MAX(cv_version) as max_version FROM cv_reviews WHERE user_id = $1"
        row = await fetch_one(query, user_id)
        if row and row.get('max_version'):
            return row['max_version'] + 1
        return 1

    @classmethod
    async def save_review(
        cls,
        user_id: int,
        target_position: str,
        overall_score: int,
        quality_score: int,
        job_match_score: int,
        evidence_score: int,
        review_json: Dict[str, Any],
        confidence_level: str
    ) -> int:
        """Menyimpan hasil review ke tabel cv_reviews"""
        cv_version = await cls.get_latest_cv_version(user_id)
        
        query = """
        INSERT INTO cv_reviews (
            user_id, target_position, cv_version, overall_score,
            quality_score, job_match_score, evidence_score,
            review_json, confidence_level
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id;
        """
        
        review_id = await execute_query(
            query,
            user_id, target_position, cv_version, overall_score,
            quality_score, job_match_score, evidence_score,
            json.dumps(review_json), confidence_level
        )
        return review_id

cv_review_service = CVReviewService()