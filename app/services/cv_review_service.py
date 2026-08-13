import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Optional
import os

class CVReviewService:
    
    @staticmethod
    def _get_db_conn():
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )

    @classmethod
    async def get_latest_cv_version(cls, user_id: int) -> int:
        """Mengambil versi CV terakhir milik user untuk tracking incremental"""
        try:
            conn = cls._get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT MAX(cv_version) as max_version FROM cv_reviews WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0]:
                return row[0] + 1
            return 1
        except Exception as e:
            print(f"[CVReviewService Error] get_latest_cv_version: {e}")
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
    ) -> Optional[int]:
        """Menyimpan hasil review ke tabel cv_reviews"""
        try:
            cv_version = await cls.get_latest_cv_version(user_id)
            conn = cls._get_db_conn()
            cur = conn.cursor()
            
            query = """
            INSERT INTO cv_reviews (
                user_id, target_position, cv_version, overall_score,
                quality_score, job_match_score, evidence_score,
                review_json, confidence_level
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """
            
            cur.execute(
                query,
                (
                    user_id, target_position, cv_version, overall_score,
                    quality_score, job_match_score, evidence_score,
                    json.dumps(review_json), confidence_level
                )
            )
            review_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return review_id
        except Exception as e:
            print(f"[CVReviewService Error] save_review: {e}")
            return None

cv_review_service = CVReviewService()