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

    @classmethod
    def filter_entitlement_response(cls, full_review: Dict[str, Any], is_premium: bool = False) -> Dict[str, Any]:
        """
        Backend-Side Entitlement Filtering (Security P0).
        - Free User: Hanya menerima overall_score, breakdown_scores, dan 3-5 findings.
        - Premium User: Menerima findings + recommendations lengkap + actionable examples.
        """
        # Parsing nested breakdown atau root scores dengan fallback aman
        breakdown = full_review.get("breakdown_scores", {})
        ats_comp = breakdown.get("ats_compatibility", full_review.get("ats_compatibility", full_review.get("quality_score", 0)))
        exp_score = breakdown.get("experience", full_review.get("experience", full_review.get("evidence_score", 0)))
        ach_score = breakdown.get("achievement", full_review.get("achievement", 0))
        kw_score = breakdown.get("keyword", full_review.get("keyword", full_review.get("job_match_score", 0)))
        str_score = breakdown.get("structure", full_review.get("structure", 0))

        raw_findings = full_review.get("findings", [])
        if not raw_findings and "top_problems" in full_review:
            raw_findings = full_review.get("top_problems", [])

        # Filter response dasar
        base_data: Dict[str, Any] = {
            "status": "success",
            "is_premium": is_premium,
            "overall_score": full_review.get("overall_score", 0),
            "breakdown_scores": {
                "ats_compatibility": ats_comp,
                "experience": exp_score,
                "achievement": ach_score,
                "keyword": kw_score,
                "structure": str_score
            },
            "findings": raw_findings[:5]  # Batasi 3-5 temuan masalah untuk Free User
        }

        if is_premium:
            base_data["recommendations"] = full_review.get("recommendations", [])
            base_data["actionable_examples"] = full_review.get("actionable_examples", [])
        else:
            # Data rekomendasi diisolasi di backend dan TIDAK dikirim ke frontend
            all_recs = full_review.get("recommendations", [])
            base_data["locked_preview"] = {
                "total_recommendations_locked": len(all_recs) if all_recs else 3,
                "cta_text": "🚀 PERBAIKI CV SAYA",
                "cta_link": "/career#pricing"
            }

        return base_data

cv_review_service = CVReviewService()