import os
import json
import logging
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

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
        """Mengambil versi CV terakhir milik user untuk tracking incremental."""
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
            logger.error(f"[CVReviewService Error] get_latest_cv_version: {e}")
            return 1

    @classmethod
    async def record_user_profile(
        cls,
        user_id: int,
        full_name: str,
        target_position: str,
        email: str = "",
        phone: str = "",
        summary: str = "",
        skills: str = "",
        experience_text: str = "",
        education_text: str = ""
    ) -> bool:
        """
        Menyimpan / memperbarui profil kandidat ke database PostgreSQL.
        Data ini menjadi memori persisten agar bot tidak lupa minat/passion user 
        dan langsung menjadi bahan auto-fill saat user mengklaim Career Page.
        """
        try:
            conn = cls._get_db_conn()
            cur = conn.cursor()
            
            # Skema Upsert (Insert jika belum ada, Update jika user kirim CV versi baru)
            query = """
            INSERT INTO user_profiles (
                user_id, full_name, target_position, email, phone, 
                summary, skills, experience_text, education_text, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (user_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                target_position = EXCLUDED.target_position,
                email = CASE WHEN EXCLUDED.email <> '' THEN EXCLUDED.email ELSE user_profiles.email END,
                phone = CASE WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone ELSE user_profiles.phone END,
                summary = EXCLUDED.summary,
                skills = EXCLUDED.skills,
                experience_text = EXCLUDED.experience_text,
                education_text = EXCLUDED.education_text,
                updated_at = NOW();
            """
            cur.execute(
                query,
                (
                    user_id, full_name, target_position, email, phone,
                    summary, skills, experience_text, education_text
                )
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"[CVReviewService Error] record_user_profile: {e}")
            return False

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
        confidence_level: str = "HIGH"
    ) -> Optional[int]:
        """Menyimpan hasil evaluasi scoring CV ke tabel cv_reviews."""
        try:
            cv_version = await cls.get_latest_cv_version(user_id)
            conn = cls._get_db_conn()
            cur = conn.cursor()
            
            query = """
            INSERT INTO cv_reviews (
                user_id, target_position, cv_version, overall_score,
                quality_score, job_match_score, evidence_score,
                review_json, confidence_level, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
            logger.error(f"[CVReviewService Error] save_review: {e}")
            return None

    @classmethod
    async def get_user_profile(cls, user_id: int) -> Optional[Dict[str, Any]]:
        """Mengambil data profil terakhir user dari PostgreSQL."""
        try:
            conn = cls._get_db_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM user_profiles WHERE user_id = %s LIMIT 1;", (user_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"[CVReviewService Error] get_user_profile: {e}")
            return None

    @classmethod
    def filter_entitlement_response(cls, full_review: Dict[str, Any], is_premium: bool = False) -> Dict[str, Any]:
        """
        Backend-Side Entitlement Filtering (Security P0).
        - Free User: Hanya menerima overall_score, breakdown_scores, dan temuan masalah ringkas.
        - Premium User: Menerima findings + recommendations lengkap + actionable examples.
        """
        breakdown = full_review.get("breakdown_scores", {})
        ats_comp = breakdown.get("ats_compatibility", full_review.get("quality_score", 0))
        exp_score = breakdown.get("experience", full_review.get("evidence_score", 0))
        ach_score = breakdown.get("achievement", 0)
        kw_score = breakdown.get("keyword", full_review.get("job_match_score", 0))
        str_score = breakdown.get("structure", 0)

        raw_findings = full_review.get("findings", [])
        if not raw_findings and "top_problems" in full_review:
            raw_findings = full_review.get("top_problems", [])

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
            "findings": raw_findings[:4]
        }

        if is_premium:
            base_data["recommendations"] = full_review.get("recommendations", [])
            base_data["actionable_examples"] = full_review.get("actionable_examples", [])
        else:
            all_recs = full_review.get("recommendations", [])
            base_data["locked_preview"] = {
                "total_recommendations_locked": len(all_recs) if all_recs else 3,
                "cta_text": "🚀 BUKA DETAIL REKOMENDASI & CAREER PAGE",
                "cta_callback": "btn_upgrade_premium"
            }

        return base_data

    @classmethod
    def format_telegram_review_message(cls, filtered_data: Dict[str, Any], target_role: str) -> str:
        """Menghasilkan teks format HTML yang rapi untuk dikirim ke chat bot Telegram."""
        score = filtered_data.get("overall_score", 0)
        breakdown = filtered_data.get("breakdown_scores", {})
        findings = filtered_data.get("findings", [])
        is_premium = filtered_data.get("is_premium", False)

        # Indikator Skor
        badge = "🟢 Sangat Baik" if score >= 80 else ("🟡 Cukup Baik" if score >= 60 else "🔴 Perlu Perbaikan")

        lines = [
            f"📊 <b>HASIL ANALISIS CV & ATS CHECKER</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 <b>Target Role:</b> {target_role}",
            f"📈 <b>Skor Keseluruhan:</b> <code>{score}/100</code> ({badge})\n",
            f"📌 <b>Breakdown Evaluasi:</b>",
            f"• ATS Compatibility: <b>{breakdown.get('ats_compatibility', 0)}%</b>",
            f"• Job Match & Keyword: <b>{breakdown.get('keyword', 0)}%</b>",
            f"• Impact & Evidence: <b>{breakdown.get('experience', 0)}%</b>",
            f"• Formatting & Layout: <b>{breakdown.get('structure', 0)}%</b>\n",
            f"🔍 <b>Catatan Temuan Utama:</b>"
        ]

        if findings:
            for f in findings:
                lines.append(f"• {f}")
        else:
            lines.append("• Format CV sudah terbaca dengan baik oleh sistem ATS dasar.")

        if not is_premium:
            lines.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                "🔒 <b>Rekomendasi Perbaikan & Actionable Points Terkunci</b>",
                "Upgrade akun untuk membuka strategi perbaikan bullet point, rekomendasi keyword industri, dan aktivasi <b>Website Career Page</b> kustom kamu!"
            ])
        else:
            recs = filtered_data.get("recommendations", [])
            if recs:
                lines.append("\n💡 <b>Rekomendasi Strategis AI:</b>")
                for r in recs:
                    lines.append(f"👉 {r}")

        return "\n".join(lines)


cv_review_service = CVReviewService()
